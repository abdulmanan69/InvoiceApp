"""Offline-first cloud sync engine.

Local SQLite stays the source of truth. Local inserts/updates on actively-synced tables are queued
into sync_outbox by DB triggers; this engine PUSHES those rows to Supabase and PULLS newer rows back,
resolving conflicts last-write-wins by the server's updated_at. It runs on a background thread and can
also be triggered on demand ("Sync now"). Every network hop is wrapped so a dropped connection just
means "try again next cycle" - the app keeps working offline.
"""
from __future__ import annotations

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
            # wait for the interval, but wake early on trigger()/stop()
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

    def _business_cols(self, table: str) -> list[str]:
        cols = self._cols.get(table)
        if cols is None:
            info = self.db.query(f"PRAGMA table_info({table})")
            cols = [r["name"] for r in info if r["name"] not in _SKIP_COLS]
            self._cols[table] = cols
        return cols

    def _to_remote(self, table: str, row: dict) -> dict:
        data = {c: row.get(c) for c in self._business_cols(table)}
        return {"id": row["uuid"], "shop_id": self.shop, "deleted": bool(row.get("deleted")), "data": data}

    # ------------------------------------------------------------------ push
    def _push(self) -> int:
        pushed = 0
        for t in SYNC_ACTIVE:
            maxid = self.db.scalar("SELECT MAX(id) FROM sync_outbox WHERE table_name = ?", (t,))
            if maxid is None:
                continue
            uuids = [r["row_uuid"] for r in self.db.query(
                "SELECT DISTINCT row_uuid FROM sync_outbox WHERE table_name = ? AND id <= ?", (t, maxid))]
            rows = []
            for u in uuids:
                r = self.db.query_one(f"SELECT * FROM {t} WHERE uuid = ?", (u,))
                if r:
                    rows.append(self._to_remote(t, r))
            for i in range(0, len(rows), _CHUNK):
                chunk = rows[i:i + _CHUNK]
                self._authed(lambda tok, c=chunk: self.sb.upsert(t, tok, c, on_conflict="id"))
                pushed += len(chunk)
            # everything up to maxid is now on the server; edits made during the push have id > maxid
            self.db.execute("DELETE FROM sync_outbox WHERE table_name = ? AND id <= ?", (t, maxid))
        return pushed

    # ------------------------------------------------------------------ pull
    def _pull(self) -> int:
        pulled = 0
        for t in SYNC_ACTIVE:
            cursor = self.db.get_sync_state(f"pull_cursor_{t}", "") or _EPOCH
            params = {"select": "id,shop_id,deleted,updated_at,data", "shop_id": f"eq.{self.shop}",
                      "updated_at": f"gt.{cursor}", "order": "updated_at.asc", "limit": 1000}
            remote = self._authed(lambda tok: self.sb.select(t, tok, params))
            if not remote:
                continue
            pulled += self._apply(t, remote)
            newest = max((r.get("updated_at") for r in remote if r.get("updated_at")), default=cursor)
            self.db.set_sync_state(f"pull_cursor_{t}", newest)
        return pulled

    def _apply(self, t: str, remote: list[dict]) -> int:
        cols = self._business_cols(t)
        applied = 0
        # suppress the outbox triggers while we write pulled data, so it does not echo back out
        with self.db._lock:
            self.db.set_sync_state("sync_suppress", "1")
            try:
                for r in remote:
                    uid = r.get("id")
                    if not uid:
                        continue
                    # a locally pending (dirty) row wins - it will push and overwrite the server next
                    if self.db.scalar("SELECT COUNT(*) FROM sync_outbox WHERE table_name = ? AND row_uuid = ?",
                                      (t, uid), 0):
                        continue
                    data = r.get("data") or {}
                    deleted = 1 if r.get("deleted") else 0
                    updated = r.get("updated_at") or ""
                    vals = [(data.get(c) if data.get(c) is not None else "") for c in cols]
                    local = self.db.query_one(f"SELECT id FROM {t} WHERE uuid = ?", (uid,))
                    if local:
                        sets = ", ".join(f"{c} = ?" for c in cols)
                        self.db.execute(
                            f"UPDATE {t} SET {sets}, shop_id = ?, deleted = ?, row_updated_at = ? WHERE id = ?",
                            (*vals, r.get("shop_id"), deleted, updated, local["id"]))
                    else:
                        allcols = cols + ["uuid", "shop_id", "deleted", "row_updated_at"]
                        ph = ", ".join("?" * len(allcols))
                        self.db.execute(
                            f"INSERT INTO {t}({', '.join(allcols)}) VALUES ({ph})",
                            (*vals, uid, r.get("shop_id"), deleted, updated))
                    applied += 1
            finally:
                self.db.set_sync_state("sync_suppress", "0")
        return applied
