"""Offline-first cloud sync engine (Phase C: every entity).

Local SQLite stays the source of truth. Local inserts/updates on synced tables are queued into
sync_outbox by DB triggers ('upsert'), hard deletes queue a 'delete' tombstone; this engine PUSHES
those to Supabase and PULLS newer rows back, resolving conflicts last-write-wins by the server's
updated_at.

Cross-PC references: local rows use per-machine AUTOINCREMENT ids, so every foreign key crosses the
wire as the target row's UUID (see _FK / _POLY_REF) and is translated back to the local id on
arrival. Tables are processed parents-first; when a child arrives before its parent, the pull for
that table stops at the blocker and retries next cycle (the cursor is only advanced past rows that
were applied).

Every network hop is wrapped so a dropped connection just means "try again next cycle" - the app
keeps working offline.
"""
from __future__ import annotations

import sqlite3
import threading
import time

import models
from cloud import CloudError
from db import SYNC_ACTIVE

# bookkeeping columns that are NOT part of the business payload
_SKIP_COLS = {"id", "uuid", "shop_id", "deleted", "row_updated_at"}
_EPOCH = "1970-01-01 00:00:00"
_INTERVAL = 30           # seconds between automatic sync cycles
_CHUNK = 200             # rows per upsert request

# parents before children, so pulled rows can resolve their references
_ORDER = ["customers", "vendors", "products", "documents", "purchases", "returns",
          "document_items", "purchase_items", "return_items", "payments", "stock_movements"]

# integer-FK columns -> the table they point at
_FK = {
    "documents": {"customer_id": "customers", "source_quotation_id": "documents"},
    "document_items": {"document_id": "documents", "product_id": "products"},
    "payments": {"invoice_id": "documents"},
    "purchases": {"vendor_id": "vendors"},
    "purchase_items": {"purchase_id": "purchases", "product_id": "products"},
    "returns": {"invoice_id": "documents", "purchase_id": "purchases",
                "customer_id": "customers", "vendor_id": "vendors"},
    "return_items": {"return_id": "returns", "product_id": "products"},
    "stock_movements": {"product_id": "products"},
}
# polymorphic reference: stock_movements.ref_id points at the table named by ref_type
_POLY_REF = {"invoice": "documents", "purchase": "purchases", "return": "returns"}


class SyncEngine:
    def __init__(self, app):
        self.app = app
        self.db = app.db
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._op_lock = threading.Lock()     # only one sync cycle at a time
        self._cols: dict[str, list[str]] = {}
        self.sb = None
        self.shop = ""
        self.status = {"running": False, "last_sync": self.db.get_sync_state("last_sync", ""),
                       "last_error": "", "pushed": 0, "pulled": 0}
        self.on_change = None                 # optional callback(status); UI must marshal to its thread

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="cloud-sync", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def trigger(self):
        """Ask the background thread to sync as soon as it can."""
        self._wake.set()

    def _loop(self):
        first = True
        while not self._stop.is_set():
            if models.cloud_ready(self.db) and (first or models.cloud_auto_sync(self.db)):
                self._safe_cycle()
                first = False
            self._wake.wait(timeout=_INTERVAL)
            self._wake.clear()

    def _safe_cycle(self):
        try:
            self.sync_now()
        except Exception:
            pass

    # ------------------------------------------------------------------ public API
    def sync_now(self) -> dict:
        """Push then pull. Blocking (does network I/O) - call from a worker thread for the UI."""
        with self._op_lock:
            self.status["running"] = True
            self._emit()
            pushed = pulled = 0
            err = ""
            try:
                if not models.cloud_ready(self.db):
                    raise CloudError("Cloud is not fully set up yet (enable, sign in and pick a shop).")
                self.sb = models.cloud_client(self.db)
                self.shop = models.cloud_shop_id(self.db)
                self._uuid_cache: dict[tuple, str | None] = {}
                self._id_cache: dict[tuple, int | None] = {}
                pushed = self._push()
                pulled = self._pull()
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                self.db.set_sync_state("last_sync", stamp)
                self.status["last_sync"] = stamp
            except CloudError as e:
                err = str(e)
            except Exception as e:                       # pragma: no cover - defensive
                err = str(e)
            self.status.update(running=False, last_error=err, pushed=pushed, pulled=pulled)
            self.db.set_sync_state("last_error", err)
            self._emit()
            return dict(self.status)

    # ------------------------------------------------------------------ helpers
    def _emit(self):
        cb = self.on_change
        if callable(cb):
            try:
                cb(dict(self.status))
            except Exception:
                pass

    def _authed(self, fn):
        """Run a Supabase call, refreshing the access token once if it has expired."""
        tok = models.cloud_token(self.db)
        try:
            return fn(tok)
        except CloudError as e:
            msg = str(e).lower()
            if "401" in msg or "jwt" in msg or "expired" in msg or "token" in msg:
                new = models.cloud_refresh(self.db)
                if new:
                    return fn(new)
                raise CloudError("Cloud session expired - open Settings > Cloud sync and press Sign in again.")
            raise

    def _tables(self) -> list[str]:
        return [t for t in _ORDER if t in SYNC_ACTIVE]

    def _business_cols(self, table: str) -> list[str]:
        cols = self._cols.get(table)
        if cols is None:
            info = self.db.query(f"PRAGMA table_info({table})")
            cols = [r["name"] for r in info if r["name"] not in _SKIP_COLS]
            self._cols[table] = cols
        return cols

    def _uuid_of(self, table: str, local_id) -> str | None:
        """Local integer id -> that row's uuid (for pushing FK values)."""
        if not table or local_id in (None, "", 0):
            return None
        key = (table, local_id)
        if key not in self._uuid_cache:
            self._uuid_cache[key] = self.db.scalar(f"SELECT uuid FROM {table} WHERE id = ?", (local_id,))
        return self._uuid_cache[key]

    def _id_of(self, table: str, uu) -> int | None:
        """A row's uuid -> the local integer id on THIS machine (for applying pulled FKs)."""
        if not table or not uu:
            return None
        key = (table, uu)
        if key not in self._id_cache:
            self._id_cache[key] = self.db.scalar(f"SELECT id FROM {table} WHERE uuid = ?", (uu,))
        return self._id_cache[key]

    def _to_remote(self, table: str, row: dict) -> dict:
        data = {c: row.get(c) for c in self._business_cols(table)}
        for col, target in _FK.get(table, {}).items():
            data[col] = self._uuid_of(target, row.get(col))
        if table == "stock_movements":
            data["ref_id"] = self._uuid_of(_POLY_REF.get(row.get("ref_type") or ""), row.get("ref_id"))
        return {"id": row["uuid"], "shop_id": self.shop, "deleted": bool(row.get("deleted")), "data": data}

    # ------------------------------------------------------------------ push
    def _push(self) -> int:
        pushed = 0
        for t in self._tables():
            maxid = self.db.scalar("SELECT MAX(id) FROM sync_outbox WHERE table_name = ?", (t,))
            if maxid is None:
                continue
            entries = self.db.query("SELECT row_uuid, op FROM sync_outbox WHERE table_name = ? AND id <= ?"
                                    " ORDER BY id", (t, maxid))
            ops: dict[str, str] = {}
            for e in entries:                 # last op per row wins
                ops[e["row_uuid"]] = e["op"]
            rows = []
            for u, op in ops.items():
                r = self.db.query_one(f"SELECT * FROM {t} WHERE uuid = ?", (u,))
                if r is not None:
                    rows.append(self._to_remote(t, r))
                else:
                    # the row is gone locally (deleted, possibly via cascade) -> tombstone
                    rows.append({"id": u, "shop_id": self.shop, "deleted": True, "data": {}})
            for i in range(0, len(rows), _CHUNK):
                chunk = rows[i:i + _CHUNK]
                self._authed(lambda tok, c=chunk, tt=t: self.sb.upsert(tt, tok, c, on_conflict="id"))
                pushed += len(chunk)
            # everything up to maxid is now on the server; edits made during the push have id > maxid
            self.db.execute("DELETE FROM sync_outbox WHERE table_name = ? AND id <= ?", (t, maxid))
        return pushed

    # ------------------------------------------------------------------ pull
    def _pull(self) -> int:
        pulled = 0
        for t in self._tables():
            cursor = self.db.get_sync_state(f"pull_cursor_{t}", "") or _EPOCH
            params = {"select": "id,shop_id,deleted,updated_at,data", "shop_id": f"eq.{self.shop}",
                      "updated_at": f"gt.{cursor}", "order": "updated_at.asc", "limit": 1000}
            remote = self._authed(lambda tok, tt=t, pp=params: self.sb.select(tt, tok, pp))
            if not remote:
                continue
            last_ts, n = self._apply(t, remote)
            pulled += n
            if last_ts:
                self.db.set_sync_state(f"pull_cursor_{t}", last_ts)
            # if the batch stalled on a missing parent, the cursor stays before the blocker
            # and the next cycle retries (the parent table syncs earlier in _ORDER)
        return pulled

    def _apply(self, t: str, remote: list[dict]) -> tuple[str, int]:
        """Apply pulled rows in order. Returns (last applied updated_at, applied count).
        Stops early (without advancing past the blocker) when a referenced parent row
        has not arrived yet."""
        cols = self._business_cols(t)
        fk = _FK.get(t, {})
        last_ts = ""
        n = 0
        with self.db._lock:
            self.db.set_sync_state("sync_suppress", "1")
            try:
                for r in remote:
                    uid = r.get("id")
                    ts = r.get("updated_at") or ""
                    if not uid:
                        last_ts = ts
                        continue
                    if r.get("deleted"):
                        # tombstone: remove the local row (FK cascades clean children the same
                        # way a local delete would) and forget any pending pushes for it
                        self.db.execute(f"DELETE FROM {t} WHERE uuid = ?", (uid,))
                        self.db.execute("DELETE FROM sync_outbox WHERE table_name = ? AND row_uuid = ?", (t, uid))
                        self._id_cache.pop((t, uid), None)
                        last_ts = ts
                        n += 1
                        continue
                    # a locally pending (dirty) row wins - it will push and overwrite the server next
                    if self.db.scalar("SELECT COUNT(*) FROM sync_outbox WHERE table_name = ? AND row_uuid = ?",
                                      (t, uid), 0):
                        last_ts = ts
                        continue
                    data = dict(r.get("data") or {})
                    blocked = False
                    for col, target in fk.items():
                        uval = data.get(col)
                        if uval:
                            lid = self._id_of(target, uval)
                            if lid is None:
                                blocked = True
                                break
                            data[col] = lid
                        else:
                            data[col] = None
                    if not blocked and t == "stock_movements":
                        target = _POLY_REF.get(data.get("ref_type") or "")
                        uval = data.get("ref_id")
                        if uval and target:
                            lid = self._id_of(target, uval)
                            if lid is None:
                                blocked = True
                            else:
                                data["ref_id"] = lid
                        else:
                            data["ref_id"] = None
                    if blocked:
                        break                  # parent not here yet; retry next cycle from here
                    if self._write_row(t, cols, uid, r, data):
                        n += 1
                    last_ts = ts
            finally:
                self.db.set_sync_state("sync_suppress", "0")
        return last_ts, n

    def _write_row(self, t: str, cols: list[str], uid: str, r: dict, data: dict) -> bool:
        vals = [data.get(c) for c in cols]
        local = self.db.query_one(f"SELECT id FROM {t} WHERE uuid = ?", (uid,))
        try:
            self._exec_row(t, cols, vals, uid, r, local)
            return True
        except sqlite3.IntegrityError as e:
            # two PCs can mint the same invoice/purchase/return number while offline; keep both
            # rows by tagging the later arrival's number
            if "UNIQUE" in str(e).upper() and data.get("number"):
                data["number"] = f"{data['number']}-{uid[:4]}"
                vals = [data.get(c) for c in cols]
                try:
                    self._exec_row(t, cols, vals, uid, r, local)
                    return True
                except Exception:
                    return False
            return False

    def _exec_row(self, t: str, cols: list[str], vals: list, uid: str, r: dict, local) -> None:
        if local:
            sets = ", ".join(f"{c} = ?" for c in cols)
            self.db.execute(f"UPDATE {t} SET {sets}, shop_id = ?, deleted = 0, row_updated_at = ? WHERE id = ?",
                            (*vals, r.get("shop_id"), r.get("updated_at") or "", local["id"]))
        else:
            allcols = cols + ["uuid", "shop_id", "deleted", "row_updated_at"]
            ph = ", ".join("?" * len(allcols))
            self.db.execute(f"INSERT INTO {t}({', '.join(allcols)}) VALUES ({ph})",
                            (*vals, uid, r.get("shop_id"), 0, r.get("updated_at") or ""))
            self._id_cache.pop((t, uid), None)
