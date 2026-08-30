"""SQLite connection, schema, settings store, backup/restore."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading

from utils import default_db_path, now_stamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
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
"""

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
    "invoice_due_days": "14",
    "quotation_valid_days": "30",
    # documents
    "default_template": "Modern",
    "pdf_page_size": "A4",
    "default_notes": "Thank you for your business.",
    "default_terms": "Payment is due within the stated period. Please quote the invoice number when making payment.",
    "bank_details": "",
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
    "date_format": "%d %b %Y",
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
            for key, value in DEFAULT_SETTINGS.items():
                self.conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
            self.conn.commit()

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
