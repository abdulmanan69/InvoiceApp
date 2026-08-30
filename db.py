"""SQLite connection, schema + migrations, settings store, backup/restore."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import uuid as _uuid

from utils import default_db_path, now_stamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name     TEXT DEFAULT '',
    role          TEXT NOT NULL CHECK (role IN ('owner', 'employee')),
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    company          TEXT DEFAULT '',
    billing_address  TEXT DEFAULT '',
    shipping_address TEXT DEFAULT '',
    phone            TEXT DEFAULT '',
    email            TEXT DEFAULT '',
    tax_number       TEXT DEFAULT '',
    notes            TEXT DEFAULT '',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    company    TEXT DEFAULT '',
    address    TEXT DEFAULT '',
    phone      TEXT DEFAULT '',
    email      TEXT DEFAULT '',
    tax_number TEXT DEFAULT '',
    notes      TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT DEFAULT '',
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    unit_price  REAL NOT NULL DEFAULT 0,
    unit        TEXT DEFAULT 'pcs',
    tax_rate    REAL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type            TEXT NOT NULL CHECK (doc_type IN ('invoice', 'quotation')),
    number              TEXT NOT NULL,
    customer_id         INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    date                TEXT NOT NULL,
    due_date            TEXT,
    template            TEXT DEFAULT '',
    currency            TEXT DEFAULT '',
    notes               TEXT DEFAULT '',
    terms               TEXT DEFAULT '',
    discount_type       TEXT NOT NULL DEFAULT 'percent',
    discount_value      REAL NOT NULL DEFAULT 0,
    tax_rate            REAL NOT NULL DEFAULT 0,
    subtotal            REAL NOT NULL DEFAULT 0,
    discount_amount     REAL NOT NULL DEFAULT 0,
    tax_amount          REAL NOT NULL DEFAULT 0,
    total               REAL NOT NULL DEFAULT 0,
    source_quotation_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (doc_type, number)
);

CREATE TABLE IF NOT EXISTS document_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    product_id  INTEGER REFERENCES products(id) ON DELETE SET NULL,
    description TEXT DEFAULT '',
    quantity    REAL NOT NULL DEFAULT 1,
    unit        TEXT DEFAULT '',
    unit_price  REAL NOT NULL DEFAULT 0,
    tax_rate    REAL,
    line_total  REAL NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    amount     REAL NOT NULL,
    date       TEXT NOT NULL,
    method     TEXT DEFAULT '',
    reference  TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    number     TEXT NOT NULL UNIQUE,
    vendor_id  INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    date       TEXT NOT NULL,
    reference  TEXT DEFAULT '',
    notes      TEXT DEFAULT '',
    total      REAL NOT NULL DEFAULT 0,
    created_by TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
    product_id  INTEGER REFERENCES products(id) ON DELETE SET NULL,
    description TEXT DEFAULT '',
    quantity    REAL NOT NULL DEFAULT 0,
    unit_cost   REAL NOT NULL DEFAULT 0,
    line_total  REAL NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS returns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL CHECK (kind IN ('customer', 'vendor')),
    number      TEXT NOT NULL UNIQUE,
    invoice_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    purchase_id INTEGER REFERENCES purchases(id) ON DELETE SET NULL,
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    vendor_id   INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    date        TEXT NOT NULL,
    reason      TEXT DEFAULT '',
    restock     INTEGER NOT NULL DEFAULT 1,
    total       REAL NOT NULL DEFAULT 0,
    created_by  TEXT DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS return_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    return_id   INTEGER NOT NULL REFERENCES returns(id) ON DELETE CASCADE,
    product_id  INTEGER REFERENCES products(id) ON DELETE SET NULL,
    description TEXT DEFAULT '',
    quantity    REAL NOT NULL DEFAULT 0,
    unit_price  REAL NOT NULL DEFAULT 0,
    line_total  REAL NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    qty        REAL NOT NULL,
    kind       TEXT NOT NULL,
    ref_type   TEXT,
    ref_id     INTEGER,
    unit_cost  REAL NOT NULL DEFAULT 0,
    date       TEXT NOT NULL,
    note       TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    kind     TEXT NOT NULL,
    message  TEXT NOT NULL,
    ref_type TEXT,
    ref_id   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_documents_type_date ON documents(doc_type, date);
CREATE INDEX IF NOT EXISTS idx_documents_customer ON documents(customer_id);
CREATE INDEX IF NOT EXISTS idx_items_document ON document_items(document_id);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(date);
CREATE INDEX IF NOT EXISTS idx_movements_product ON stock_movements(product_id);
CREATE INDEX IF NOT EXISTS idx_movements_ref ON stock_movements(ref_type, ref_id);
CREATE INDEX IF NOT EXISTS idx_returns_invoice ON returns(invoice_id);

CREATE TABLE IF NOT EXISTS sync_outbox (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    row_uuid   TEXT NOT NULL,
    op         TEXT NOT NULL,
    payload    TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Tables that sync to the cloud. Each gets uuid / shop_id / deleted / row_updated_at columns.
SYNC_TABLES = ["customers", "vendors", "products", "documents", "document_items", "payments",
               "purchases", "purchase_items", "returns", "return_items", "stock_movements"]

# Columns added after v1.0 (table, column, declaration). Applied idempotently on every start.
MIGRATIONS = [
    ("users", "hidden", "INTEGER NOT NULL DEFAULT 0"),
    ("products", "cost_price", "REAL NOT NULL DEFAULT 0"),
    ("products", "track_stock", "INTEGER NOT NULL DEFAULT 1"),
    ("products", "low_stock_level", "REAL NOT NULL DEFAULT 0"),
    ("documents", "bill_to_label", "TEXT DEFAULT ''"),
    ("documents", "bill_to_text", "TEXT DEFAULT ''"),
    ("documents", "display_options", "TEXT DEFAULT ''"),
    ("documents", "prepared_by", "TEXT DEFAULT ''"),
    ("documents", "received_by", "TEXT DEFAULT ''"),
    ("documents", "created_by", "TEXT DEFAULT ''"),
    ("document_items", "sku", "TEXT DEFAULT ''"),
    ("document_items", "cost_price", "REAL NOT NULL DEFAULT 0"),
    ("payments", "created_by", "TEXT DEFAULT ''"),
]

# Cloud-sync columns added to every synced table (idempotent).
for _t in SYNC_TABLES:
    MIGRATIONS.append((_t, "uuid", "TEXT"))
    MIGRATIONS.append((_t, "shop_id", "TEXT"))
    MIGRATIONS.append((_t, "deleted", "INTEGER NOT NULL DEFAULT 0"))
    MIGRATIONS.append((_t, "row_updated_at", "TEXT DEFAULT ''"))

# Per-document PDF display switches. These are the defaults; Settings can change them and
# every document stores its own copy (display_options JSON) so old PDFs keep their look.
DISPLAY_DEFAULTS = {
    "show_logo": 1,
    "show_company_details": 1,
    "show_status": 1,
    "show_due_date": 1,
    "show_currency": 1,
    "show_customer_contact": 1,
    "show_ship_to": 1,
    "show_line_numbers": 1,
    "show_sku": 0,
    "show_qty": 1,
    "show_unit": 1,
    "show_unit_price": 1,
    "show_tax_col": 1,
    "show_discount": 1,
    "show_tax_total": 1,
    "show_paid_balance": 1,
    "show_notes": 1,
    "show_terms": 1,
    "show_bank_details": 1,
    "show_signatures": 1,
    "show_grid": 1,
}

DISPLAY_LABELS = {
    "show_logo": "Company logo",
    "show_company_details": "Company address / contact lines",
    "show_status": "Status badge (Paid / Unpaid ...)",
    "show_due_date": "Due date / Valid until",
    "show_currency": "Currency line",
    "show_customer_contact": "Customer phone / email / tax no.",
    "show_ship_to": "Ship-to block (when different)",
    "show_line_numbers": "Column: #",
    "show_sku": "Column: SKU / code",
    "show_qty": "Column: Qty",
    "show_unit": "Column: Unit",
    "show_unit_price": "Column: Unit price",
    "show_tax_col": "Column: Tax %",
    "show_discount": "Discount line in totals",
    "show_tax_total": "Tax line in totals",
    "show_paid_balance": "Paid / Balance due lines",
    "show_notes": "Notes",
    "show_terms": "Terms & conditions",
    "show_bank_details": "Bank / payment details",
    "show_signatures": "Signature boxes (prepared by / received by)",
    "show_grid": "Grid borders on the items table",
}

# Every brandable / business-specific value lives here, never in the UI or PDF code.
DEFAULT_SETTINGS = {
    # company profile
    "company_name": "Your Company Name",
    "company_tagline": "",
    "company_address": "",
    "company_phone": "",
    "company_email": "",
    "company_website": "",
    "company_tax_number": "",
    "company_logo": "",  # file name inside data dir, or absolute path
    # currency / tax
    "currency_code": "PKR",
    "currency_symbol": "Rs",
    "default_tax_rate": "0",
    "tax_label": "Tax",
    # numbering
    "invoice_prefix": "INV-",
    "invoice_next_number": "1",
    "invoice_number_padding": "4",
    "quotation_prefix": "QT-",
    "quotation_next_number": "1",
    "quotation_number_padding": "4",
    "purchase_prefix": "PUR-",
    "purchase_next_number": "1",
    "return_prefix": "RET-",
    "return_next_number": "1",
    "invoice_due_days": "14",
    "quotation_valid_days": "30",
    # documents
    "default_template": "Modern",
    "pdf_page_size": "A4",
    "default_notes": "Thank you for your business.",
    "default_terms": "Payment is due within the stated period. Please quote the invoice number when making payment.",
    "bank_details": "",
    "bill_to_label": "Bill To",
    "doc_display_defaults": json.dumps(DISPLAY_DEFAULTS),
    "signature_prepared_label": "Prepared by",
    "signature_received_label": "Received by",
    "signature_prepared_name": "",  # blank = the logged-in user's name
    "signature_received_name": "",
    # inventory
    "allow_negative_stock": "0",
    "low_stock_threshold": "5",
    # access
    "require_login": "1",
    # payments
    "payment_methods": json.dumps(["Cash", "Bank Transfer", "Credit/Debit Card", "Cheque", "Online/Wallet"]),
    # theme
    "theme_accent": "#2563eb",
    "theme_bg": "#f4f6fb",
    "theme_fg": "#0f172a",
    "theme_success": "#16a34a",
    "theme_warning": "#d97706",
    "theme_danger": "#dc2626",
    "theme_muted": "#64748b",
    "ui_font": "Segoe UI",
    "ui_font_size": "10",
    "ui_radius": "10",
    "date_format": "%d %b %Y",
    "pdf_font": "Auto",
    "currency_decimals": "2",
    # dashboard
    "dashboard_period": "month",
    "dashboard_recent": "6",
    "dashboard_show_low_stock": "1",
    "dashboard_show_best": "1",
    "dashboard_show_profit": "1",
    "dashboard_show_activity": "1",
    "dashboard_quick_actions": "1",
    # behaviour
    "enable_quotations": "1",
    "overdue_grace_days": "0",
    # cloud sync (Supabase). URL + anon key + shop are shared per shop and safe to store here.
    # The service_role key and the signed-in session are per-machine secrets kept in a local file, NOT here.
    "cloud_enabled": "0",
    "cloud_url": "",
    "cloud_anon_key": "",
    "cloud_shop_id": "",
    "cloud_shop_name": "",
    "cloud_auto_sync": "1",
}


class Database:
    """Thin wrapper around one sqlite3 connection."""

    def __init__(self, path: str | None = None):
        self.path = path or default_db_path()
        self.conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self.connect()

    # ---------------------------------------------------------------- lifecycle
    def connect(self):
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = DELETE")
        self.init_schema()

    def close(self):
        if self.conn is not None:
            try:
                self.conn.commit()
                self.conn.close()
            finally:
                self.conn = None

    def init_schema(self):
        with self._lock:
            self.conn.executescript(SCHEMA)
            for table, column, decl in MIGRATIONS:
                cols = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                if column not in cols:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            for key, value in DEFAULT_SETTINGS.items():
                self.conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
            self._create_sync_triggers()
            self._backfill_sync_columns()
            self.conn.commit()

    def _create_sync_triggers(self):
        """Every new row in a synced table automatically gets a UUID + timestamp (no model changes needed)."""
        for t in SYNC_TABLES:
            self.conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS trg_{t}_newuuid AFTER INSERT ON {t} "
                f"WHEN NEW.uuid IS NULL OR NEW.uuid = '' BEGIN "
                f"UPDATE {t} SET uuid = lower(hex(randomblob(16))), "
                f"row_updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE rowid = NEW.rowid; END;")

    def _backfill_sync_columns(self):
        """Give every existing row a UUID and a row_updated_at so it is ready to sync later."""
        now = now_stamp()
        for t in SYNC_TABLES:
            for (rid,) in self.conn.execute(f"SELECT rowid FROM {t} WHERE uuid IS NULL OR uuid = ''").fetchall():
                self.conn.execute(f"UPDATE {t} SET uuid = ? WHERE rowid = ?", (_uuid.uuid4().hex, rid))
            self.conn.execute(f"UPDATE {t} SET row_updated_at = ? WHERE row_updated_at IS NULL OR row_updated_at = ''",
                              (now,))

    # ---------------------------------------------------------------- sync helpers
    def get_sync_state(self, key: str, default=None):
        return self.scalar("SELECT value FROM sync_state WHERE key = ?", (key,), default)

    def set_sync_state(self, key: str, value) -> None:
        self.execute("INSERT INTO sync_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, "" if value is None else str(value)))

    def _secrets_path(self) -> str:
        import os as _os
        from utils import data_dir
        return _os.path.join(data_dir(), "cloud_secrets.json")

    def get_secret(self, key: str, default=None):
        """Per-machine secrets (service_role key, saved session). Never stored in the shared DB."""
        try:
            with open(self._secrets_path(), "r", encoding="utf-8") as fh:
                return json.load(fh).get(key, default)
        except Exception:
            return default

    def set_secret(self, key: str, value) -> None:
        path = self._secrets_path()
        try:
            data = {}
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
        except Exception:
            pass

    # ---------------------------------------------------------------- queries
    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def executemany(self, sql: str, seq) -> None:
        with self._lock:
            self.conn.executemany(sql, seq)
            self.conn.commit()

    def query(self, sql: str, params=()) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def query_one(self, sql: str, params=()) -> dict | None:
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def scalar(self, sql: str, params=(), default=None):
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
        if row is None or row[0] is None:
            return default
        return row[0]

    class _Tx:
        def __init__(self, db):
            self.db = db

        def __enter__(self):
            self.db._lock.acquire()
            self.db.conn.execute("BEGIN")
            return self.db.conn

        def __exit__(self, exc_type, exc, tb):
            try:
                if exc_type is None:
                    self.db.conn.commit()
                else:
                    self.db.conn.rollback()
            finally:
                self.db._lock.release()
            return False

    def transaction(self):
        """with db.transaction() as conn: ... commits on success, rolls back on error."""
        return Database._Tx(self)

    # ---------------------------------------------------------------- settings
    def get_setting(self, key: str, default=None):
        v = self.scalar("SELECT value FROM settings WHERE key = ?", (key,), None)
        if v is None:
            return DEFAULT_SETTINGS.get(key, default) if default is None else default
        return v

    def get_settings(self) -> dict:
        data = dict(DEFAULT_SETTINGS)
        for row in self.query("SELECT key, value FROM settings"):
            data[row["key"]] = row["value"]
        return data

    def set_setting(self, key: str, value) -> None:
        if value is None:
            value = ""
        self.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    def set_settings(self, mapping: dict) -> None:
        with self.transaction() as conn:
            for k, v in mapping.items():
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, "" if v is None else str(v)),
                )

    def get_list_setting(self, key: str) -> list:
        raw = self.get_setting(key, "[]")
        try:
            data = json.loads(raw)
            return [str(x) for x in data] if isinstance(data, list) else []
        except Exception:
            return []

    def set_list_setting(self, key: str, values: list) -> None:
        self.set_setting(key, json.dumps([str(v) for v in values]))

    def get_json_setting(self, key: str, default: dict | None = None) -> dict:
        raw = self.get_setting(key, "")
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        out = dict(default or {})
        if isinstance(data, dict):
            out.update(data)
        return out

    def display_defaults(self) -> dict:
        """Default PDF display switches (settings override the built-in defaults)."""
        return {k: int(bool(v)) for k, v in self.get_json_setting("doc_display_defaults", DISPLAY_DEFAULTS).items()
                if k in DISPLAY_DEFAULTS}

    # ---------------------------------------------------------------- backup / restore
    def backup_to(self, target_path: str) -> None:
        """Copy the live database to target_path using the sqlite online-backup API."""
        target_path = os.path.abspath(target_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with self._lock:
            self.conn.commit()
            if os.path.exists(target_path):
                os.remove(target_path)
            dest = sqlite3.connect(target_path)
            try:
                self.conn.backup(dest)
                dest.commit()
            finally:
                dest.close()

    def restore_from(self, source_path: str) -> None:
        """Replace the live database with source_path. Validates the file first."""
        source_path = os.path.abspath(source_path)
        if not os.path.isfile(source_path):
            raise FileNotFoundError(source_path)
        probe = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        try:
            names = {r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError as exc:
            raise ValueError("The selected file is not a valid SQLite database.") from exc
        finally:
            probe.close()
        required = {"settings", "customers", "documents", "payments"}
        if not required.issubset(names):
            raise ValueError("The selected file is not an InvoiceApp database backup.")
        with self._lock:
            self.close()
            safety = self.path + ".before-restore"
            try:
                if os.path.exists(self.path):
                    shutil.copy2(self.path, safety)
                shutil.copy2(source_path, self.path)
            finally:
                self.connect()

    # ---------------------------------------------------------------- activity
    def log(self, kind: str, message: str, ref_type: str | None = None, ref_id: int | None = None) -> None:
        self.execute(
            "INSERT INTO activity_log(ts, kind, message, ref_type, ref_id) VALUES (?, ?, ?, ?, ?)",
            (now_stamp(), kind, message, ref_type, ref_id),
        )
