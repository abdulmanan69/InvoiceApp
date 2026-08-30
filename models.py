"""Domain logic: CRUD repositories, totals, status, numbering, stock, purchases, returns, users, stats.

Everything here works on plain dicts (sqlite rows) and a Database instance.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets

from db import DISPLAY_DEFAULTS, SYNC_TABLES, Database
from utils import add_days, now_stamp, parse_date, parse_float, parse_int, round2, today_iso

INVOICE = "invoice"
QUOTATION = "quotation"

STATUS_UNPAID = "Unpaid"
STATUS_PARTIAL = "Partially Paid"
STATUS_PAID = "Paid"
STATUS_OVERDUE = "Overdue"
STATUS_OPEN = "Open"
STATUS_CONVERTED = "Converted"
STATUS_EXPIRED = "Expired"

INVOICE_STATUSES = [STATUS_UNPAID, STATUS_PARTIAL, STATUS_PAID, STATUS_OVERDUE]
QUOTATION_STATUSES = [STATUS_OPEN, STATUS_CONVERTED, STATUS_EXPIRED]

DOC_LABEL = {INVOICE: "Invoice", QUOTATION: "Quotation"}

ROLE_OWNER = "owner"
ROLE_EMPLOYEE = "employee"

MOVE_PURCHASE = "purchase"
MOVE_SALE = "sale"
MOVE_CUSTOMER_RETURN = "customer_return"
MOVE_VENDOR_RETURN = "vendor_return"
MOVE_ADJUSTMENT = "adjustment"
MOVE_LABELS = {MOVE_PURCHASE: "Purchase", MOVE_SALE: "Sale", MOVE_CUSTOMER_RETURN: "Customer return",
               MOVE_VENDOR_RETURN: "Return to vendor", MOVE_ADJUSTMENT: "Adjustment"}


class ValidationError(Exception):
    """Raised for user-facing validation failures. Message is safe to show."""


class OverpaymentError(ValidationError):
    def __init__(self, amount: float, remaining: float):
        self.amount, self.remaining = amount, remaining
        super().__init__(f"Payment of {amount:,.2f} exceeds the remaining balance of {remaining:,.2f}.")


class StockError(ValidationError):
    """Not enough stock for one or more lines."""


# =========================================================================== helpers
def _clean(text) -> str:
    return (text or "").strip() if isinstance(text, str) else ("" if text is None else str(text))


def _like(term: str) -> str:
    return f"%{_clean(term)}%"


def _user_name(user) -> str:
    if not user:
        return ""
    if isinstance(user, dict):
        return user.get("full_name") or user.get("username") or ""
    return str(user)


# =========================================================================== users / auth
def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000).hex()
    return digest, salt


def count_users(db: Database) -> int:
    return int(db.scalar("SELECT COUNT(*) FROM users WHERE hidden = 0", (), 0) or 0)


def list_users(db: Database) -> list[dict]:
    return db.query("SELECT id, username, full_name, role, active, created_at FROM users WHERE hidden = 0 ORDER BY role, username COLLATE NOCASE")


def get_user(db: Database, user_id) -> dict | None:
    return db.query_one("SELECT id, username, full_name, role, active, created_at FROM users WHERE id = ?", (user_id,))


def create_user(db: Database, username: str, password: str, role: str = ROLE_EMPLOYEE, full_name: str = "") -> int:
    username = _clean(username)
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{2,40}", username):
        raise ValidationError("Username must be 2-40 characters (letters, numbers, . _ - @).")
    if len(password or "") < 4:
        raise ValidationError("Password must be at least 4 characters.")
    if role not in (ROLE_OWNER, ROLE_EMPLOYEE):
        raise ValidationError("Role must be owner or employee.")
    if db.scalar("SELECT COUNT(*) FROM users WHERE username = ? COLLATE NOCASE", (username,), 0):
        raise ValidationError(f"Username '{username}' is already taken.")
    digest, salt = hash_password(password)
    cur = db.execute(
        "INSERT INTO users(username, full_name, role, password_hash, salt, active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
        (username, _clean(full_name), role, digest, salt, now_stamp()),
    )
    db.log("user", f"Added {role} account {username}", "user", cur.lastrowid)
    return int(cur.lastrowid)


def update_user(db: Database, user_id: int, full_name=None, role=None, active=None, password=None) -> None:
    user = get_user(db, user_id)
    if not user:
        raise ValidationError("User not found.")
    if role is not None and role not in (ROLE_OWNER, ROLE_EMPLOYEE):
        raise ValidationError("Role must be owner or employee.")
    owners = db.scalar("SELECT COUNT(*) FROM users WHERE role = 'owner' AND active = 1 AND hidden = 0", (), 0)
    demoting = (role == ROLE_EMPLOYEE or active == 0) and user["role"] == ROLE_OWNER and user["active"]
    if demoting and owners <= 1:
        raise ValidationError("There must always be at least one active owner account.")
    if full_name is not None:
        db.execute("UPDATE users SET full_name = ? WHERE id = ?", (_clean(full_name), user_id))
    if role is not None:
        db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    if active is not None:
        db.execute("UPDATE users SET active = ? WHERE id = ?", (1 if active else 0, user_id))
    if password:
        if len(password) < 4:
            raise ValidationError("Password must be at least 4 characters.")
        digest, salt = hash_password(password)
        db.execute("UPDATE users SET password_hash = ?, salt = ? WHERE id = ?", (digest, salt, user_id))
    db.log("user", f"Updated account {user['username']}", "user", user_id)


def delete_user(db: Database, user_id: int) -> None:
    user = get_user(db, user_id)
    if not user:
        return
    if user["role"] == ROLE_OWNER and db.scalar("SELECT COUNT(*) FROM users WHERE role = 'owner' AND hidden = 0", (), 0) <= 1:
        raise ValidationError("You cannot delete the last owner account.")
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.log("user", f"Deleted account {user['username']}", "user", user_id)


SUPPORT_USERNAME = "manan"  # built-in recovery account (hidden from the Users list)


def ensure_support_user(db: Database) -> None:
    """Seed the always-present recovery account if it is missing. Full access, hidden from the UI."""
    row = db.query_one("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (SUPPORT_USERNAME,))
    if row:
        return
    digest, salt = hash_password("11122006")
    db.execute(
        "INSERT INTO users(username, full_name, role, password_hash, salt, active, created_at, hidden)"
        " VALUES (?, ?, 'owner', ?, ?, 1, ?, 1)",
        (SUPPORT_USERNAME, "Support", digest, salt, now_stamp()),
    )


def authenticate(db: Database, username: str, password: str) -> dict | None:
    row = db.query_one("SELECT * FROM users WHERE username = ? COLLATE NOCASE AND active = 1", (_clean(username),))
    if not row:
        return None
    digest, _ = hash_password(password or "", row["salt"])
    if not secrets.compare_digest(digest, row["password_hash"]):
        return None
    return {k: row[k] for k in ("id", "username", "full_name", "role", "active")}


# =========================================================================== customers
def list_customers(db: Database, search: str = "") -> list[dict]:
    sql = """
        SELECT c.*,
               COALESCE((SELECT SUM(d.total) FROM documents d WHERE d.customer_id = c.id AND d.doc_type = 'invoice'), 0)
               - COALESCE((SELECT SUM(p.amount) FROM payments p JOIN documents d ON d.id = p.invoice_id
                           WHERE d.customer_id = c.id), 0)
               - COALESCE((SELECT SUM(r.total) FROM returns r JOIN documents d ON d.id = r.invoice_id
                           WHERE d.customer_id = c.id AND r.kind = 'customer'), 0) AS balance,
               (SELECT COUNT(*) FROM documents d WHERE d.customer_id = c.id AND d.doc_type = 'invoice') AS invoice_count
        FROM customers c
    """
    params: list = []
    if _clean(search):
        sql += " WHERE c.name LIKE ? OR c.company LIKE ? OR c.email LIKE ? OR c.phone LIKE ?"
        params = [_like(search)] * 4
    sql += " ORDER BY c.name COLLATE NOCASE"
    rows = db.query(sql, params)
    for r in rows:
        r["balance"] = round2(r["balance"])
    return rows


def get_customer(db: Database, customer_id) -> dict | None:
    if not customer_id:
        return None
    row = db.query_one("SELECT * FROM customers WHERE id = ?", (customer_id,))
    if row:
        row["balance"] = customer_balance(db, customer_id)
    return row


def customer_balance(db: Database, customer_id) -> float:
    invoiced = db.scalar("SELECT SUM(total) FROM documents WHERE customer_id = ? AND doc_type = 'invoice'", (customer_id,), 0)
    paid = db.scalar("SELECT SUM(p.amount) FROM payments p JOIN documents d ON d.id = p.invoice_id WHERE d.customer_id = ?",
                     (customer_id,), 0)
    credit = db.scalar("SELECT SUM(r.total) FROM returns r JOIN documents d ON d.id = r.invoice_id"
                       " WHERE d.customer_id = ? AND r.kind = 'customer'", (customer_id,), 0)
    return round2((invoiced or 0) - (paid or 0) - (credit or 0))


def save_customer(db: Database, data: dict) -> int:
    name = _clean(data.get("name"))
    if not name:
        raise ValidationError("Customer name is required.")
    fields = ("name", "company", "billing_address", "shipping_address", "phone", "email", "tax_number", "notes")
    values = [_clean(data.get(f)) for f in fields]
    values[0] = name
    cid = data.get("id")
    if cid:
        db.execute("UPDATE customers SET " + ", ".join(f"{f} = ?" for f in fields) + " WHERE id = ?", (*values, cid))
        db.log("customer", f"Updated customer {name}", "customer", cid)
        return int(cid)
    cur = db.execute(
        f"INSERT INTO customers({', '.join(fields)}, created_at) VALUES ({', '.join('?' * len(fields))}, ?)",
        (*values, now_stamp()),
    )
    db.log("customer", f"Added customer {name}", "customer", cur.lastrowid)
    return int(cur.lastrowid)


def delete_customer(db: Database, customer_id: int) -> None:
    count = db.scalar("SELECT COUNT(*) FROM documents WHERE customer_id = ?", (customer_id,), 0)
    if count:
        raise ValidationError(f"This customer has {count} invoice(s)/quotation(s). Delete or reassign those documents first.")
    row = get_customer(db, customer_id)
    db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    if row:
        db.log("customer", f"Deleted customer {row['name']}", "customer", customer_id)


# =========================================================================== vendors
def list_vendors(db: Database, search: str = "") -> list[dict]:
    sql = """
        SELECT v.*,
               (SELECT COUNT(*) FROM purchases p WHERE p.vendor_id = v.id) AS purchase_count,
               COALESCE((SELECT SUM(p.total) FROM purchases p WHERE p.vendor_id = v.id), 0) AS purchased_total
        FROM vendors v
    """
    params: list = []
    if _clean(search):
        sql += " WHERE v.name LIKE ? OR v.company LIKE ? OR v.email LIKE ? OR v.phone LIKE ?"
        params = [_like(search)] * 4
    sql += " ORDER BY v.name COLLATE NOCASE"
    return db.query(sql, params)


def get_vendor(db: Database, vendor_id) -> dict | None:
    return db.query_one("SELECT * FROM vendors WHERE id = ?", (vendor_id,)) if vendor_id else None


def save_vendor(db: Database, data: dict) -> int:
    name = _clean(data.get("name"))
    if not name:
        raise ValidationError("Vendor name is required.")
    fields = ("name", "company", "address", "phone", "email", "tax_number", "notes")
    values = [_clean(data.get(f)) for f in fields]
    values[0] = name
    vid = data.get("id")
    if vid:
        db.execute("UPDATE vendors SET " + ", ".join(f"{f} = ?" for f in fields) + " WHERE id = ?", (*values, vid))
        db.log("vendor", f"Updated vendor {name}", "vendor", vid)
        return int(vid)
    cur = db.execute(
        f"INSERT INTO vendors({', '.join(fields)}, created_at) VALUES ({', '.join('?' * len(fields))}, ?)",
        (*values, now_stamp()),
    )
    db.log("vendor", f"Added vendor {name}", "vendor", cur.lastrowid)
    return int(cur.lastrowid)


def delete_vendor(db: Database, vendor_id: int) -> None:
    row = get_vendor(db, vendor_id)
    db.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))
    if row:
        db.log("vendor", f"Deleted vendor {row['name']}", "vendor", vendor_id)


# =========================================================================== products & stock
_PRODUCT_SELECT = """
    SELECT p.*, COALESCE((SELECT SUM(m.qty) FROM stock_movements m WHERE m.product_id = p.id), 0) AS stock
    FROM products p
"""


def list_products(db: Database, search: str = "", active_only: bool = False) -> list[dict]:
    sql = _PRODUCT_SELECT
    clauses, params = [], []
    if _clean(search):
        clauses.append("(p.name LIKE ? OR p.sku LIKE ? OR p.description LIKE ?)")
        params += [_like(search)] * 3
    if active_only:
        clauses.append("p.active = 1")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY p.name COLLATE NOCASE"
    rows = db.query(sql, params)
    for r in rows:
        r["stock"] = round2(r["stock"])
    return rows


def get_product(db: Database, product_id) -> dict | None:
    if not product_id:
        return None
    row = db.query_one(_PRODUCT_SELECT + " WHERE p.id = ?", (product_id,))
    if row:
        row["stock"] = round2(row["stock"])
    return row


def save_product(db: Database, data: dict) -> int:
    name = _clean(data.get("name"))
    if not name:
        raise ValidationError("Product/service name is required.")
    price = parse_float(data.get("unit_price"), None)
    if price is None or price < 0:
        raise ValidationError("Sale price must be a number of 0 or more.")
    cost = parse_float(data.get("cost_price"), 0) if _clean(data.get("cost_price")) != "" else 0
    if cost is None or cost < 0:
        raise ValidationError("Cost price must be a number of 0 or more.")
    tax_raw = data.get("tax_rate")
    tax_rate = None
    if tax_raw not in (None, ""):
        tax_rate = parse_float(tax_raw, None)
        if tax_rate is None or tax_rate < 0 or tax_rate > 100:
            raise ValidationError("Tax rate override must be between 0 and 100, or left blank.")
    low = parse_float(data.get("low_stock_level"), 0) if _clean(data.get("low_stock_level")) != "" else 0
    active = 1 if data.get("active", 1) in (1, True, "1", "True", "true") else 0
    track = 1 if data.get("track_stock", 1) in (1, True, "1", "True", "true") else 0
    values = (_clean(data.get("sku")), name, _clean(data.get("description")), round2(price),
              _clean(data.get("unit")) or "pcs", tax_rate, active, round2(cost), track, max(0.0, low or 0))
    pid = data.get("id")
    if pid:
        db.execute(
            "UPDATE products SET sku=?, name=?, description=?, unit_price=?, unit=?, tax_rate=?, active=?,"
            " cost_price=?, track_stock=?, low_stock_level=? WHERE id=?", (*values, pid))
        db.log("product", f"Updated product {name}", "product", pid)
        return int(pid)
    cur = db.execute(
        "INSERT INTO products(sku, name, description, unit_price, unit, tax_rate, active, cost_price, track_stock,"
        " low_stock_level, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (*values, now_stamp()))
    opening = parse_float(data.get("opening_stock"), 0) or 0
    if opening > 0:
        _insert_movement(db, cur.lastrowid, opening, MOVE_ADJUSTMENT, "product", cur.lastrowid, cost or 0,
                         today_iso(), "Opening stock")
    db.log("product", f"Added product {name}", "product", cur.lastrowid)
    return int(cur.lastrowid)


def delete_product(db: Database, product_id: int) -> None:
    row = get_product(db, product_id)
    db.execute("DELETE FROM products WHERE id = ?", (product_id,))  # items keep their text; movements cascade
    if row:
        db.log("product", f"Deleted product {row['name']}", "product", product_id)


def _insert_movement(db_or_conn, product_id, qty, kind, ref_type, ref_id, unit_cost, date, note=""):
    sql = ("INSERT INTO stock_movements(product_id, qty, kind, ref_type, ref_id, unit_cost, date, note, created_at)"
           " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
    params = (product_id, round2(qty), kind, ref_type, ref_id, round2(unit_cost or 0), date, _clean(note), now_stamp())
    if isinstance(db_or_conn, Database):
        db_or_conn.execute(sql, params)
    else:
        db_or_conn.execute(sql, params)


def stock_level(db: Database, product_id, exclude_ref: tuple | None = None) -> float:
    sql = "SELECT SUM(qty) FROM stock_movements WHERE product_id = ?"
    params: list = [product_id]
    if exclude_ref:
        sql += " AND NOT (ref_type = ? AND ref_id = ?)"
        params += list(exclude_ref)
    return round2(db.scalar(sql, params, 0) or 0)


def adjust_stock(db: Database, product_id: int, new_qty, note: str = "", user=None) -> None:
    prod = get_product(db, product_id)
    if not prod:
        raise ValidationError("Product not found.")
    target = parse_float(new_qty, None)
    if target is None or target < 0:
        raise ValidationError("Stock quantity must be a number of 0 or more.")
    delta = round2(target - prod["stock"])
    if abs(delta) < 0.0001:
        return
    _insert_movement(db, product_id, delta, MOVE_ADJUSTMENT, "adjustment", None, prod.get("cost_price") or 0,
                     today_iso(), note or f"Adjusted by {_user_name(user) or 'user'}")
    db.log("stock", f"Stock of {prod['name']} set to {target:g}", "product", product_id)


def stock_history(db: Database, product_id=None, limit: int = 200) -> list[dict]:
    sql = "SELECT m.*, p.name AS product_name, p.unit FROM stock_movements m JOIN products p ON p.id = m.product_id"
    params: list = []
    if product_id:
        sql += " WHERE m.product_id = ?"
        params.append(product_id)
    sql += " ORDER BY m.date DESC, m.id DESC LIMIT ?"
    params.append(limit)
    rows = db.query(sql, params)
    for r in rows:
        r["kind_label"] = MOVE_LABELS.get(r["kind"], r["kind"])
    return rows


def low_stock_products(db: Database, threshold: float | None = None) -> list[dict]:
    if threshold is None:
        threshold = parse_float(db.get_setting("low_stock_threshold", "5"), 5) or 0
    out = []
    for p in list_products(db, active_only=True):
        if not p.get("track_stock"):
            continue
        level = p["low_stock_level"] if (p.get("low_stock_level") or 0) > 0 else threshold
        if p["stock"] <= level:
            out.append(p)
    return out


def stock_value(db: Database) -> float:
    return round2(sum(max(p["stock"], 0) * float(p.get("cost_price") or 0) for p in list_products(db) if p.get("track_stock")))


# =========================================================================== numbering
def _num_keys(doc_type: str) -> tuple[str, str, str]:
    p = "invoice" if doc_type == INVOICE else "quotation"
    return f"{p}_prefix", f"{p}_next_number", f"{p}_number_padding"


def next_number(db: Database, doc_type: str) -> str:
    """Suggest the next document number. Skips numbers that already exist."""
    k_prefix, k_next, k_pad = _num_keys(doc_type)
    prefix = db.get_setting(k_prefix, "")
    counter = max(1, parse_int(db.get_setting(k_next, "1"), 1) or 1)
    pad = max(0, min(10, parse_int(db.get_setting(k_pad, "4"), 4) or 0))
    for _ in range(10000):
        candidate = f"{prefix}{str(counter).zfill(pad)}"
        if not number_exists(db, doc_type, candidate):
            return candidate
        counter += 1
    return f"{prefix}{counter}"


def number_exists(db: Database, doc_type: str, number: str, exclude_id=None) -> bool:
    sql = "SELECT COUNT(*) FROM documents WHERE doc_type = ? AND number = ?"
    params = [doc_type, _clean(number)]
    if exclude_id:
        sql += " AND id != ?"
        params.append(exclude_id)
    return bool(db.scalar(sql, params, 0))


def bump_counter(db: Database, doc_type: str, number: str) -> None:
    k_prefix, k_next, _ = _num_keys(doc_type)
    _bump(db, k_prefix, k_next, number)


def _bump(db: Database, k_prefix: str, k_next: str, number: str) -> None:
    prefix = db.get_setting(k_prefix, "")
    m = re.fullmatch(re.escape(prefix) + r"(\d+)", _clean(number))
    if not m:
        return
    used = int(m.group(1))
    current = parse_int(db.get_setting(k_next, "1"), 1) or 1
    if used >= current:
        db.set_setting(k_next, str(used + 1))


def _next_simple(db: Database, table: str, k_prefix: str, k_next: str) -> str:
    prefix = db.get_setting(k_prefix, "")
    counter = max(1, parse_int(db.get_setting(k_next, "1"), 1) or 1)
    for _ in range(10000):
        cand = f"{prefix}{str(counter).zfill(4)}"
        if not db.scalar(f"SELECT COUNT(*) FROM {table} WHERE number = ?", (cand,), 0):
            return cand
        counter += 1
    return f"{prefix}{counter}"


def next_purchase_number(db: Database) -> str:
    return _next_simple(db, "purchases", "purchase_prefix", "purchase_next_number")


def next_return_number(db: Database) -> str:
    return _next_simple(db, "returns", "return_prefix", "return_next_number")


# =========================================================================== totals
def normalize_items(raw_items: list[dict], default_tax_rate: float) -> list[dict]:
    """Validate and compute per-line totals. Raises ValidationError on bad numbers."""
    items = []
    for idx, raw in enumerate(raw_items or [], start=1):
        desc = _clean(raw.get("description"))
        qty = parse_float(raw.get("quantity"), None)
        price = parse_float(raw.get("unit_price"), None)
        if not desc and qty in (None, 0) and price in (None, 0):
            continue
        if not desc:
            raise ValidationError(f"Line {idx}: description is required.")
        if qty is None:
            raise ValidationError(f"Line {idx}: quantity must be a number.")
        if price is None:
            raise ValidationError(f"Line {idx}: unit price must be a number.")
        tax_raw = raw.get("tax_rate")
        tax_rate = None
        if tax_raw not in (None, ""):
            tax_rate = parse_float(tax_raw, None)
            if tax_rate is None or tax_rate < 0 or tax_rate > 100:
                raise ValidationError(f"Line {idx}: tax % must be between 0 and 100.")
        items.append({
            "product_id": raw.get("product_id") or None,
            "description": desc,
            "quantity": qty,
            "unit": _clean(raw.get("unit")),
            "unit_price": round2(price),
            "tax_rate": tax_rate,
            "effective_tax_rate": default_tax_rate if tax_rate is None else tax_rate,
            "line_total": round2(qty * price),
            "sort_order": idx,
            "sku": _clean(raw.get("sku")),
            "cost_price": parse_float(raw.get("cost_price"), 0) or 0,
        })
    return items


def compute_totals(items: list[dict], discount_type: str, discount_value, default_tax_rate) -> dict:
    """Subtotal -> discount (percent or fixed) -> tax (per line, after discount) -> total. Never raises."""
    default_tax_rate = parse_float(default_tax_rate, 0) or 0
    discount_value = parse_float(discount_value, 0) or 0
    subtotal = round2(sum(float(i.get("line_total") or 0) for i in items))
    if discount_type == "fixed":
        discount = min(max(discount_value, 0), subtotal)
    else:
        discount = subtotal * max(min(discount_value, 100), 0) / 100.0
    discount = round2(discount)
    factor = (1 - discount / subtotal) if subtotal else 0.0
    tax = 0.0
    for i in items:
        rate = i.get("effective_tax_rate")
        if rate is None:
            rate = default_tax_rate if i.get("tax_rate") is None else i.get("tax_rate")
        tax += float(i.get("line_total") or 0) * factor * float(rate or 0) / 100.0
    tax = round2(tax)
    total = round2(subtotal - discount + tax)
    return {"subtotal": subtotal, "discount_amount": discount, "tax_amount": tax, "total": total}


# =========================================================================== status
def compute_status(doc_type: str, total: float, paid: float, due_date, converted: bool = False,
                   today: dt.date | None = None, grace: int = 0) -> str:
    today = today or dt.date.today()
    due = parse_date(due_date)
    grace = max(0, int(grace or 0))
    if doc_type == QUOTATION:
        if converted:
            return STATUS_CONVERTED
        if due and (today - due).days > grace:
            return STATUS_EXPIRED
        return STATUS_OPEN
    total = float(total or 0)
    paid = float(paid or 0)
    if paid >= total - 0.005:
        return STATUS_PAID
    if due and (today - due).days > grace:
        return STATUS_OVERDUE
    if paid > 0.005:
        return STATUS_PARTIAL
    return STATUS_UNPAID


# =========================================================================== display options
def parse_display_options(raw) -> dict:
    """Merge a JSON string / dict of switches with the built-in defaults."""
    opts = dict(DISPLAY_DEFAULTS)
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw) if raw.strip() else {}
        except Exception:
            data = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if k in opts:
                opts[k] = 1 if v in (1, True, "1", "true", "True") else 0
    return opts


def document_display_options(db: Database, doc: dict) -> dict:
    """Effective switches for a document: settings defaults overridden by the document's own JSON."""
    base = db.display_defaults()
    raw = (doc or {}).get("display_options") or ""
    if not raw.strip():
        return base
    try:
        own = json.loads(raw)
    except Exception:
        return base
    out = dict(base)
    if isinstance(own, dict):
        for k, v in own.items():
            if k in out:
                out[k] = 1 if v in (1, True, "1", "true", "True") else 0
    return out


# =========================================================================== documents
_DOC_SELECT = """
    SELECT d.*, c.name AS customer_name, c.company AS customer_company,
           COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = d.id), 0) AS paid,
           COALESCE((SELECT SUM(r.total) FROM returns r WHERE r.invoice_id = d.id AND r.kind = 'customer'), 0) AS credit,
           (SELECT COUNT(*) FROM documents x WHERE x.source_quotation_id = d.id) AS converted_count,
           (SELECT COUNT(*) FROM document_items i WHERE i.document_id = d.id) AS item_count
    FROM documents d LEFT JOIN customers c ON c.id = d.customer_id
"""


def overdue_grace(db: Database) -> int:
    return max(0, parse_int(db.get_setting("overdue_grace_days", "0"), 0) or 0)


def _decorate(row: dict, grace: int = 0) -> dict:
    row["paid"] = round2(row.get("paid") or 0)
    row["credit"] = round2(row.get("credit") or 0)
    row["balance"] = round2(float(row.get("total") or 0) - row["paid"] - row["credit"])
    row["status"] = compute_status(row["doc_type"], row.get("total"), row["paid"] + row["credit"], row.get("due_date"),
                                   bool(row.get("converted_count")), grace=grace)
    row["customer_display"] = row.get("customer_name") or "(no customer)"
    if row.get("customer_company"):
        row["customer_display"] += f" - {row['customer_company']}"
    return row


def list_documents(db: Database, doc_type: str, search: str = "", status: str = "", customer_id=None,
                   date_from=None, date_to=None) -> list[dict]:
    sql = _DOC_SELECT + " WHERE d.doc_type = ?"
    params: list = [doc_type]
    if _clean(search):
        sql += " AND (d.number LIKE ? OR c.name LIKE ? OR c.company LIKE ? OR d.notes LIKE ?)"
        params += [_like(search)] * 4
    if customer_id:
        sql += " AND d.customer_id = ?"
        params.append(customer_id)
    df, dtn = parse_date(date_from), parse_date(date_to)
    if df:
        sql += " AND d.date >= ?"
        params.append(df.isoformat())
    if dtn:
        sql += " AND d.date <= ?"
        params.append(dtn.isoformat())
    sql += " ORDER BY d.date DESC, d.id DESC"
    grace = overdue_grace(db)
    rows = [_decorate(r, grace) for r in db.query(sql, params)]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def get_document(db: Database, doc_id) -> dict | None:
    if not doc_id:
        return None
    row = db.query_one(_DOC_SELECT + " WHERE d.id = ?", (doc_id,))
    if not row:
        return None
    _decorate(row, overdue_grace(db))
    row["items"] = db.query(
        "SELECT i.*, COALESCE(NULLIF(i.sku, ''), p.sku, '') AS sku_display FROM document_items i"
        " LEFT JOIN products p ON p.id = i.product_id WHERE i.document_id = ? ORDER BY i.sort_order, i.id", (doc_id,))
    row["payments"] = db.query("SELECT * FROM payments WHERE invoice_id = ? ORDER BY date, id", (doc_id,))
    row["returns"] = db.query("SELECT * FROM returns WHERE invoice_id = ? ORDER BY date, id", (doc_id,))
    row["customer"] = get_customer(db, row.get("customer_id"))
    if row.get("source_quotation_id"):
        src = db.query_one("SELECT number FROM documents WHERE id = ?", (row["source_quotation_id"],))
        row["source_quotation_number"] = src["number"] if src else ""
    return row


def check_stock_for_items(db: Database, items: list[dict], exclude_doc_id=None) -> list[str]:
    """Return human-readable problems for lines that exceed available stock (empty list = OK)."""
    needed: dict[int, float] = {}
    for i in items:
        if i.get("product_id"):
            needed[i["product_id"]] = needed.get(i["product_id"], 0) + float(i.get("quantity") or 0)
    problems = []
    for pid, qty in needed.items():
        prod = get_product(db, pid)
        if not prod or not prod.get("track_stock"):
            continue
        available = stock_level(db, pid, ("invoice", exclude_doc_id) if exclude_doc_id else None)
        if qty > available + 0.0001:
            problems.append(f"{prod['name']}: only {available:g} {prod.get('unit') or ''} in stock, you entered {qty:g}")
    return problems


def save_document(db: Database, data: dict, raw_items: list[dict], user=None) -> int:
    """Insert or update a document with its items. Validates everything, keeps stock in sync for invoices."""
    doc_type = data.get("doc_type") or INVOICE
    if doc_type not in (INVOICE, QUOTATION):
        raise ValidationError("Unknown document type.")
    number = _clean(data.get("number"))
    if not number:
        raise ValidationError("Document number is required.")
    doc_id = data.get("id")
    if number_exists(db, doc_type, number, exclude_id=doc_id):
        raise ValidationError(f"{DOC_LABEL[doc_type]} number '{number}' already exists. Choose another number.")
    date = parse_date(data.get("date"))
    if not date:
        raise ValidationError("Date is required (YYYY-MM-DD).")
    due_raw = data.get("due_date")
    due = parse_date(due_raw) if _clean(due_raw) else None
    if _clean(due_raw) and not due:
        raise ValidationError("Due date is not a valid date (YYYY-MM-DD).")
    if due and due < date:
        raise ValidationError("Due date cannot be earlier than the document date.")
    customer_id = data.get("customer_id") or None
    if customer_id and not get_customer(db, customer_id):
        raise ValidationError("Selected customer no longer exists.")
    tax_rate = parse_float(data.get("tax_rate"), None)
    if tax_rate is None or tax_rate < 0 or tax_rate > 100:
        raise ValidationError("Default tax rate must be between 0 and 100.")
    discount_type = "fixed" if data.get("discount_type") == "fixed" else "percent"
    discount_value = parse_float(data.get("discount_value"), None)
    if discount_value is None or discount_value < 0:
        raise ValidationError("Discount must be a number of 0 or more.")
    if discount_type == "percent" and discount_value > 100:
        raise ValidationError("Percentage discount cannot exceed 100%.")

    items = normalize_items(raw_items, tax_rate)
    # snapshot SKU + cost from the product so profit and PDFs stay stable later
    for i in items:
        if i["product_id"]:
            prod = get_product(db, i["product_id"])
            if prod:
                i["sku"] = i["sku"] or prod.get("sku") or ""
                i["cost_price"] = float(prod.get("cost_price") or 0)
    if doc_type == INVOICE and db.get_setting("allow_negative_stock", "0") != "1":
        problems = check_stock_for_items(db, items, exclude_doc_id=doc_id)
        if problems:
            raise StockError("Not enough stock:\n- " + "\n- ".join(problems))

    totals = compute_totals(items, discount_type, discount_value, tax_rate)
    display = data.get("display_options")
    if isinstance(display, dict):
        display = json.dumps(display)
    ts = now_stamp()
    cols = {
        "doc_type": doc_type, "number": number, "customer_id": customer_id,
        "date": date.isoformat(), "due_date": due.isoformat() if due else None,
        "template": _clean(data.get("template")), "currency": _clean(data.get("currency")),
        "notes": _clean(data.get("notes")), "terms": _clean(data.get("terms")),
        "discount_type": discount_type, "discount_value": discount_value, "tax_rate": tax_rate,
        **totals, "source_quotation_id": data.get("source_quotation_id") or None, "updated_at": ts,
        "bill_to_label": _clean(data.get("bill_to_label")), "bill_to_text": _clean(data.get("bill_to_text")),
        "display_options": _clean(display), "prepared_by": _clean(data.get("prepared_by")),
        "received_by": _clean(data.get("received_by")),
    }
    with db.transaction() as conn:
        if doc_id:
            sets = ", ".join(f"{k} = ?" for k in cols)
            conn.execute(f"UPDATE documents SET {sets} WHERE id = ?", (*cols.values(), doc_id))
            conn.execute("DELETE FROM document_items WHERE document_id = ?", (doc_id,))
        else:
            cols["created_at"] = ts
            cols["created_by"] = _clean(data.get("created_by")) or _user_name(user)
            cur = conn.execute(f"INSERT INTO documents({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                               tuple(cols.values()))
            doc_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO document_items(document_id, product_id, description, quantity, unit, unit_price,"
            " tax_rate, line_total, sort_order, sku, cost_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(doc_id, i["product_id"], i["description"], i["quantity"], i["unit"], i["unit_price"],
              i["tax_rate"], i["line_total"], i["sort_order"], i["sku"], i["cost_price"]) for i in items])
        conn.execute("DELETE FROM stock_movements WHERE ref_type = 'invoice' AND ref_id = ?", (doc_id,))
        if doc_type == INVOICE:
            for i in items:
                if i["product_id"]:
                    prod = get_product(db, i["product_id"])
                    if prod and prod.get("track_stock"):
                        _insert_movement(conn, i["product_id"], -float(i["quantity"]), MOVE_SALE, "invoice", doc_id,
                                         i["cost_price"], date.isoformat(), f"Invoice {number}")
    bump_counter(db, doc_type, number)
    db.log(doc_type, f"{'Updated' if data.get('id') else 'Created'} {DOC_LABEL[doc_type].lower()} {number}"
                     + (f" ({_user_name(user)})" if user else ""), doc_type, doc_id)
    return int(doc_id)


def delete_document(db: Database, doc_id: int) -> None:
    row = db.query_one("SELECT doc_type, number FROM documents WHERE id = ?", (doc_id,))
    with db.transaction() as conn:
        conn.execute("DELETE FROM stock_movements WHERE ref_type = 'invoice' AND ref_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))  # items & payments cascade
    if row:
        db.log(row["doc_type"], f"Deleted {DOC_LABEL[row['doc_type']].lower()} {row['number']}", row["doc_type"], doc_id)


def _copy_payload(src: dict, doc_type: str, db: Database) -> tuple[dict, list[dict]]:
    settings = db.get_settings()
    days = parse_int(settings.get("invoice_due_days" if doc_type == INVOICE else "quotation_valid_days"), 14) or 0
    data = {
        "doc_type": doc_type, "number": next_number(db, doc_type), "customer_id": src.get("customer_id"),
        "date": today_iso(), "due_date": add_days(today_iso(), days), "template": src.get("template"),
        "currency": src.get("currency"), "notes": src.get("notes"), "terms": src.get("terms"),
        "discount_type": src.get("discount_type"), "discount_value": src.get("discount_value"),
        "tax_rate": src.get("tax_rate"), "bill_to_label": src.get("bill_to_label"),
        "bill_to_text": src.get("bill_to_text"), "display_options": src.get("display_options"),
        "prepared_by": src.get("prepared_by"), "received_by": src.get("received_by"),
    }
    items = [dict(i) for i in src.get("items", [])]
    return data, items


def duplicate_document(db: Database, doc_id: int, user=None) -> int:
    src = get_document(db, doc_id)
    if not src:
        raise ValidationError("Document not found.")
    data, items = _copy_payload(src, src["doc_type"], db)
    new_id = save_document(db, data, items, user)
    db.log(src["doc_type"], f"Duplicated {src['number']} as {data['number']}", src["doc_type"], new_id)
    return new_id


def convert_quotation_to_invoice(db: Database, quotation_id: int, user=None) -> int:
    src = get_document(db, quotation_id)
    if not src or src["doc_type"] != QUOTATION:
        raise ValidationError("Only quotations can be converted to invoices.")
    data, items = _copy_payload(src, INVOICE, db)
    data["source_quotation_id"] = quotation_id
    new_id = save_document(db, data, items, user)
    db.log(INVOICE, f"Converted quotation {src['number']} to invoice {data['number']}", INVOICE, new_id)
    return new_id


# =========================================================================== payments
def invoice_paid_amount(db: Database, invoice_id: int) -> float:
    return round2(db.scalar("SELECT SUM(amount) FROM payments WHERE invoice_id = ?", (invoice_id,), 0) or 0)


def invoice_credit_amount(db: Database, invoice_id: int) -> float:
    return round2(db.scalar("SELECT SUM(total) FROM returns WHERE invoice_id = ? AND kind = 'customer'", (invoice_id,), 0) or 0)


def add_payment(db: Database, invoice_id: int, amount, date, method: str = "", reference: str = "",
                allow_overpay: bool = False, user=None) -> int:
    inv = db.query_one("SELECT id, doc_type, number, total FROM documents WHERE id = ?", (invoice_id,))
    if not inv or inv["doc_type"] != INVOICE:
        raise ValidationError("Payments can only be recorded against invoices.")
    amt = parse_float(amount, None)
    if amt is None or amt <= 0:
        raise ValidationError("Payment amount must be greater than zero.")
    amt = round2(amt)
    d = parse_date(date)
    if not d:
        raise ValidationError("Payment date is not valid (YYYY-MM-DD).")
    remaining = round2(float(inv["total"]) - invoice_paid_amount(db, invoice_id) - invoice_credit_amount(db, invoice_id))
    if amt > remaining + 0.005 and not allow_overpay:
        raise OverpaymentError(amt, remaining)
    cur = db.execute(
        "INSERT INTO payments(invoice_id, amount, date, method, reference, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (invoice_id, amt, d.isoformat(), _clean(method), _clean(reference), now_stamp(), _user_name(user)))
    db.log("payment", f"Payment of {amt:,.2f} received for {inv['number']}", "payment", cur.lastrowid)
    return int(cur.lastrowid)


def mark_as_paid(db: Database, invoice_id: int, method: str = "", date=None, user=None) -> int | None:
    inv = db.query_one("SELECT total FROM documents WHERE id = ? AND doc_type = 'invoice'", (invoice_id,))
    if not inv:
        raise ValidationError("Invoice not found.")
    remaining = round2(float(inv["total"]) - invoice_paid_amount(db, invoice_id) - invoice_credit_amount(db, invoice_id))
    if remaining <= 0.005:
        return None
    return add_payment(db, invoice_id, remaining, date or today_iso(), method, "Marked as paid", user=user)


def delete_payment(db: Database, payment_id: int) -> None:
    row = db.query_one("SELECT p.*, d.number FROM payments p JOIN documents d ON d.id = p.invoice_id WHERE p.id = ?",
                       (payment_id,))
    db.execute("DELETE FROM payments WHERE id = ?", (payment_id,))
    if row:
        db.log("payment", f"Deleted payment of {row['amount']:,.2f} on {row['number']}", "payment", payment_id)


def list_payments(db: Database, method: str = "", customer_id=None, date_from=None, date_to=None,
                  search: str = "") -> list[dict]:
    sql = """
        SELECT p.*, d.number AS invoice_number, d.customer_id, c.name AS customer_name, c.company AS customer_company
        FROM payments p
        JOIN documents d ON d.id = p.invoice_id
        LEFT JOIN customers c ON c.id = d.customer_id
        WHERE 1 = 1
    """
    params: list = []
    if _clean(method):
        sql += " AND p.method = ?"
        params.append(_clean(method))
    if customer_id:
        sql += " AND d.customer_id = ?"
        params.append(customer_id)
    if _clean(search):
        sql += " AND (d.number LIKE ? OR c.name LIKE ? OR p.reference LIKE ?)"
        params += [_like(search)] * 3
    df, dtn = parse_date(date_from), parse_date(date_to)
    if df:
        sql += " AND p.date >= ?"
        params.append(df.isoformat())
    if dtn:
        sql += " AND p.date <= ?"
        params.append(dtn.isoformat())
    sql += " ORDER BY p.date DESC, p.id DESC"
    rows = db.query(sql, params)
    for r in rows:
        r["customer_display"] = r.get("customer_name") or "(no customer)"
    return rows


# =========================================================================== purchases
def list_purchases(db: Database, search: str = "", vendor_id=None, date_from=None, date_to=None) -> list[dict]:
    sql = """
        SELECT pu.*, v.name AS vendor_name, v.company AS vendor_company,
               (SELECT COUNT(*) FROM purchase_items i WHERE i.purchase_id = pu.id) AS item_count
        FROM purchases pu LEFT JOIN vendors v ON v.id = pu.vendor_id WHERE 1 = 1
    """
    params: list = []
    if _clean(search):
        sql += " AND (pu.number LIKE ? OR v.name LIKE ? OR pu.reference LIKE ?)"
        params += [_like(search)] * 3
    if vendor_id:
        sql += " AND pu.vendor_id = ?"
        params.append(vendor_id)
    df, dtn = parse_date(date_from), parse_date(date_to)
    if df:
        sql += " AND pu.date >= ?"
        params.append(df.isoformat())
    if dtn:
        sql += " AND pu.date <= ?"
        params.append(dtn.isoformat())
    sql += " ORDER BY pu.date DESC, pu.id DESC"
    rows = db.query(sql, params)
    for r in rows:
        r["vendor_display"] = r.get("vendor_name") or "(no vendor)"
    return rows


def get_purchase(db: Database, purchase_id) -> dict | None:
    row = db.query_one("SELECT pu.*, v.name AS vendor_name FROM purchases pu LEFT JOIN vendors v ON v.id = pu.vendor_id"
                       " WHERE pu.id = ?", (purchase_id,))
    if row:
        row["items"] = db.query("SELECT i.*, p.name AS product_name, p.unit FROM purchase_items i"
                                " LEFT JOIN products p ON p.id = i.product_id WHERE i.purchase_id = ?"
                                " ORDER BY i.sort_order, i.id", (purchase_id,))
    return row


def save_purchase(db: Database, data: dict, raw_items: list[dict], user=None) -> int:
    """Record goods bought from a vendor. Adds stock and updates each product's cost price."""
    number = _clean(data.get("number")) or next_purchase_number(db)
    pid = data.get("id")
    dup = db.scalar("SELECT COUNT(*) FROM purchases WHERE number = ?" + (" AND id != ?" if pid else ""),
                    (number, pid) if pid else (number,), 0)
    if dup:
        raise ValidationError(f"Purchase number '{number}' already exists.")
    date = parse_date(data.get("date"))
    if not date:
        raise ValidationError("Date is required (YYYY-MM-DD).")
    vendor_id = data.get("vendor_id") or None
    items = []
    for idx, raw in enumerate(raw_items or [], start=1):
        product_id = raw.get("product_id") or None
        desc = _clean(raw.get("description"))
        qty = parse_float(raw.get("quantity"), None)
        cost = parse_float(raw.get("unit_cost"), None)
        if qty in (None, 0) or (not product_id and not desc):
            continue  # blank / zero lines are ignored
        if not product_id:
            raise ValidationError(f"Line {idx}: choose a product.")
        if qty < 0:
            raise ValidationError(f"Line {idx}: quantity cannot be negative.")
        if cost is None or cost < 0:
            raise ValidationError(f"Line {idx}: unit cost must be a number of 0 or more.")
        prod = get_product(db, product_id)
        if not prod:
            raise ValidationError(f"Line {idx}: product no longer exists.")
        items.append({"product_id": product_id, "description": desc or prod["name"], "quantity": qty,
                      "unit_cost": round2(cost), "line_total": round2(qty * cost), "sort_order": idx})
    if not items:
        raise ValidationError("Add at least one product line with a quantity.")
    total = round2(sum(i["line_total"] for i in items))
    with db.transaction() as conn:
        if pid:
            conn.execute("UPDATE purchases SET number=?, vendor_id=?, date=?, reference=?, notes=?, total=? WHERE id=?",
                         (number, vendor_id, date.isoformat(), _clean(data.get("reference")), _clean(data.get("notes")),
                          total, pid))
            conn.execute("DELETE FROM purchase_items WHERE purchase_id = ?", (pid,))
            conn.execute("DELETE FROM stock_movements WHERE ref_type = 'purchase' AND ref_id = ?", (pid,))
        else:
            cur = conn.execute(
                "INSERT INTO purchases(number, vendor_id, date, reference, notes, total, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (number, vendor_id, date.isoformat(), _clean(data.get("reference")), _clean(data.get("notes")), total,
                 _user_name(user), now_stamp()))
            pid = cur.lastrowid
        for i in items:
            conn.execute("INSERT INTO purchase_items(purchase_id, product_id, description, quantity, unit_cost,"
                         " line_total, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (pid, i["product_id"], i["description"], i["quantity"], i["unit_cost"], i["line_total"],
                          i["sort_order"]))
            _insert_movement(conn, i["product_id"], i["quantity"], MOVE_PURCHASE, "purchase", pid, i["unit_cost"],
                             date.isoformat(), f"Purchase {number}")
            if data.get("update_cost", True):
                conn.execute("UPDATE products SET cost_price = ? WHERE id = ?", (i["unit_cost"], i["product_id"]))
    _bump(db, "purchase_prefix", "purchase_next_number", number)
    db.log("purchase", f"{'Updated' if data.get('id') else 'Recorded'} purchase {number} ({total:,.2f})", "purchase", pid)
    return int(pid)


def delete_purchase(db: Database, purchase_id: int) -> None:
    row = db.query_one("SELECT number FROM purchases WHERE id = ?", (purchase_id,))
    with db.transaction() as conn:
        conn.execute("DELETE FROM stock_movements WHERE ref_type = 'purchase' AND ref_id = ?", (purchase_id,))
        conn.execute("DELETE FROM purchases WHERE id = ?", (purchase_id,))
    if row:
        db.log("purchase", f"Deleted purchase {row['number']}", "purchase", purchase_id)


# =========================================================================== returns
def list_returns(db: Database, kind: str = "", search: str = "", date_from=None, date_to=None) -> list[dict]:
    sql = """
        SELECT r.*, c.name AS customer_name, v.name AS vendor_name, d.number AS invoice_number, pu.number AS purchase_number,
               (SELECT COUNT(*) FROM return_items i WHERE i.return_id = r.id) AS item_count
        FROM returns r
        LEFT JOIN customers c ON c.id = r.customer_id
        LEFT JOIN vendors v ON v.id = r.vendor_id
        LEFT JOIN documents d ON d.id = r.invoice_id
        LEFT JOIN purchases pu ON pu.id = r.purchase_id
        WHERE 1 = 1
    """
    params: list = []
    if kind:
        sql += " AND r.kind = ?"
        params.append(kind)
    if _clean(search):
        sql += " AND (r.number LIKE ? OR c.name LIKE ? OR v.name LIKE ? OR d.number LIKE ? OR r.reason LIKE ?)"
        params += [_like(search)] * 5
    df, dtn = parse_date(date_from), parse_date(date_to)
    if df:
        sql += " AND r.date >= ?"
        params.append(df.isoformat())
    if dtn:
        sql += " AND r.date <= ?"
        params.append(dtn.isoformat())
    sql += " ORDER BY r.date DESC, r.id DESC"
    rows = db.query(sql, params)
    for r in rows:
        r["party"] = (r.get("customer_name") if r["kind"] == "customer" else r.get("vendor_name")) or "-"
        r["ref"] = (r.get("invoice_number") if r["kind"] == "customer" else r.get("purchase_number")) or ""
    return rows


def get_return(db: Database, return_id) -> dict | None:
    row = db.query_one("SELECT * FROM returns WHERE id = ?", (return_id,))
    if row:
        row["items"] = db.query("SELECT i.*, p.name AS product_name FROM return_items i LEFT JOIN products p ON p.id = i.product_id"
                                " WHERE i.return_id = ? ORDER BY i.sort_order, i.id", (return_id,))
    return row


def save_return(db: Database, data: dict, raw_items: list[dict], user=None) -> int:
    """Customer return (items come back, credit reduces the invoice balance) or vendor return (items go back)."""
    kind = data.get("kind")
    if kind not in ("customer", "vendor"):
        raise ValidationError("Return kind must be customer or vendor.")
    date = parse_date(data.get("date"))
    if not date:
        raise ValidationError("Date is required (YYYY-MM-DD).")
    number = _clean(data.get("number")) or next_return_number(db)
    if db.scalar("SELECT COUNT(*) FROM returns WHERE number = ?", (number,), 0):
        raise ValidationError(f"Return number '{number}' already exists.")
    invoice_id = data.get("invoice_id") or None
    purchase_id = data.get("purchase_id") or None
    customer_id = data.get("customer_id") or None
    vendor_id = data.get("vendor_id") or None
    if invoice_id:
        inv = db.query_one("SELECT customer_id, total FROM documents WHERE id = ? AND doc_type = 'invoice'", (invoice_id,))
        if not inv:
            raise ValidationError("Invoice not found.")
        customer_id = customer_id or inv["customer_id"]
    if purchase_id:
        pu = db.query_one("SELECT vendor_id FROM purchases WHERE id = ?", (purchase_id,))
        if not pu:
            raise ValidationError("Purchase not found.")
        vendor_id = vendor_id or pu["vendor_id"]
    restock = 1 if data.get("restock", 1) in (1, True, "1", "True", "true") else 0
    items = []
    for idx, raw in enumerate(raw_items or [], start=1):
        desc = _clean(raw.get("description"))
        qty = parse_float(raw.get("quantity"), None)
        price = parse_float(raw.get("unit_price"), None)
        product_id = raw.get("product_id") or None
        if qty in (None, 0) or (not desc and not product_id):
            continue  # 0 = this line was not returned
        if qty < 0:
            raise ValidationError(f"Line {idx}: quantity cannot be negative.")
        if price is None or price < 0:
            raise ValidationError(f"Line {idx}: unit price must be a number of 0 or more.")
        if kind == "vendor" and not product_id:
            raise ValidationError(f"Line {idx}: choose the product being returned to the vendor.")
        prod = get_product(db, product_id) if product_id else None
        if kind == "vendor" and prod and prod.get("track_stock") and db.get_setting("allow_negative_stock", "0") != "1":
            if qty > prod["stock"] + 0.0001:
                raise StockError(f"{prod['name']}: only {prod['stock']:g} in stock, cannot return {qty:g} to the vendor.")
        items.append({"product_id": product_id, "description": desc or (prod["name"] if prod else ""),
                      "quantity": qty, "unit_price": round2(price), "line_total": round2(qty * price), "sort_order": idx})
    if not items:
        raise ValidationError("Enter a quantity greater than 0 on at least one line (0 means not returned).")
    total = round2(sum(i["line_total"] for i in items))
    if kind == "customer" and invoice_id:
        inv_total = float(inv["total"] or 0)
        existing = invoice_credit_amount(db, invoice_id)
        if total + existing > inv_total + 0.005 and not data.get("allow_over_credit"):
            raise ValidationError(f"Credit of {total:,.2f} plus earlier returns exceeds the invoice total {inv_total:,.2f}.")
    with db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO returns(kind, number, invoice_id, purchase_id, customer_id, vendor_id, date, reason, restock,"
            " total, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, number, invoice_id, purchase_id, customer_id, vendor_id, date.isoformat(), _clean(data.get("reason")),
             restock, total, _user_name(user), now_stamp()))
        rid = cur.lastrowid
        for i in items:
            conn.execute("INSERT INTO return_items(return_id, product_id, description, quantity, unit_price, line_total,"
                         " sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (rid, i["product_id"], i["description"], i["quantity"], i["unit_price"], i["line_total"], i["sort_order"]))
            if i["product_id"]:
                prod = get_product(db, i["product_id"])
                if prod and prod.get("track_stock"):
                    if kind == "customer" and restock:
                        _insert_movement(conn, i["product_id"], i["quantity"], MOVE_CUSTOMER_RETURN, "return", rid,
                                         prod.get("cost_price") or 0, date.isoformat(), f"Return {number}")
                    elif kind == "vendor":
                        _insert_movement(conn, i["product_id"], -i["quantity"], MOVE_VENDOR_RETURN, "return", rid,
                                         i["unit_price"], date.isoformat(), f"Return {number}")
    _bump(db, "return_prefix", "return_next_number", number)
    db.log("return", f"{'Customer' if kind == 'customer' else 'Vendor'} return {number} ({total:,.2f})", "return", rid)
    return int(rid)


def delete_return(db: Database, return_id: int) -> None:
    row = db.query_one("SELECT number FROM returns WHERE id = ?", (return_id,))
    with db.transaction() as conn:
        conn.execute("DELETE FROM stock_movements WHERE ref_type = 'return' AND ref_id = ?", (return_id,))
        conn.execute("DELETE FROM returns WHERE id = ?", (return_id,))
    if row:
        db.log("return", f"Deleted return {row['number']}", "return", return_id)


# =========================================================================== reports / dashboard
def best_sellers(db: Database, limit: int = 8, date_from=None, date_to=None) -> list[dict]:
    sql = """
        SELECT COALESCE(p.name, i.description) AS name, i.product_id,
               SUM(i.quantity) AS qty_sold, SUM(i.line_total) AS revenue,
               SUM(i.quantity * i.cost_price) AS cost, COUNT(DISTINCT d.id) AS invoices
        FROM document_items i
        JOIN documents d ON d.id = i.document_id AND d.doc_type = 'invoice'
        LEFT JOIN products p ON p.id = i.product_id
        WHERE 1 = 1
    """
    params: list = []
    df, dtn = parse_date(date_from), parse_date(date_to)
    if df:
        sql += " AND d.date >= ?"
        params.append(df.isoformat())
    if dtn:
        sql += " AND d.date <= ?"
        params.append(dtn.isoformat())
    sql += " GROUP BY COALESCE(i.product_id, i.description) ORDER BY qty_sold DESC, revenue DESC LIMIT ?"
    params.append(limit)
    rows = db.query(sql, params)
    for r in rows:
        r["qty_sold"] = round2(r["qty_sold"])
        r["revenue"] = round2(r["revenue"])
        r["cost"] = round2(r["cost"])
        r["profit"] = round2(r["revenue"] - r["cost"])
    return rows


def profit_summary(db: Database, date_from=None, date_to=None) -> dict:
    """Gross profit on invoiced lines (sale price - snapshot cost), before document discounts."""
    sql = ("SELECT SUM(i.line_total) AS revenue, SUM(i.quantity * i.cost_price) AS cost FROM document_items i"
           " JOIN documents d ON d.id = i.document_id AND d.doc_type = 'invoice' WHERE 1 = 1")
    params: list = []
    df, dtn = parse_date(date_from), parse_date(date_to)
    if df:
        sql += " AND d.date >= ?"
        params.append(df.isoformat())
    if dtn:
        sql += " AND d.date <= ?"
        params.append(dtn.isoformat())
    row = db.query_one(sql, params) or {}
    revenue = round2(row.get("revenue") or 0)
    cost = round2(row.get("cost") or 0)
    return {"revenue": revenue, "cost": cost, "profit": round2(revenue - cost)}


PERIOD_LABELS = {"week": "this week", "month": "this month", "last30": "last 30 days",
                 "year": "this year", "all": "all time"}


def _period_start(period: str):
    """Return the ISO start date for a dashboard period, or None for all-time."""
    today = dt.date.today()
    if period == "week":
        return (today - dt.timedelta(days=today.weekday())).isoformat()
    if period == "last30":
        return (today - dt.timedelta(days=30)).isoformat()
    if period == "year":
        return today.replace(month=1, day=1).isoformat()
    if period == "all":
        return None
    return today.replace(day=1).isoformat()  # month (default)


def dashboard_stats(db: Database, period: str = "month", recent: int = 6, best: int = 6) -> dict:
    invoices = list_documents(db, INVOICE)
    period = period if period in PERIOD_LABELS else "month"
    start = _period_start(period)
    recent = max(1, min(50, int(recent or 6)))
    outstanding = round2(sum(r["balance"] for r in invoices if r["balance"] > 0))
    overdue = [r for r in invoices if r["status"] == STATUS_OVERDUE]

    def _since(sql, params=()):
        if start:
            return round2(db.scalar(sql + " AND date >= ?", (*params, start), 0) or 0)
        return round2(db.scalar(sql.replace("WHERE date >= ?", "WHERE 1=1") if "WHERE date >= ?" in sql else sql,
                                params, 0) or 0)

    if start:
        paid_period = round2(db.scalar("SELECT SUM(amount) FROM payments WHERE date >= ?", (start,), 0) or 0)
        purchases_period = round2(db.scalar("SELECT SUM(total) FROM purchases WHERE date >= ?", (start,), 0) or 0)
        returns_period = round2(db.scalar("SELECT SUM(total) FROM returns WHERE kind = 'customer' AND date >= ?", (start,), 0) or 0)
        invoiced_period = round2(sum(float(r["total"] or 0) for r in invoices if (r["date"] or "") >= start))
    else:
        paid_period = round2(db.scalar("SELECT SUM(amount) FROM payments", (), 0) or 0)
        purchases_period = round2(db.scalar("SELECT SUM(total) FROM purchases", (), 0) or 0)
        returns_period = round2(db.scalar("SELECT SUM(total) FROM returns WHERE kind = 'customer'", (), 0) or 0)
        invoiced_period = round2(sum(float(r["total"] or 0) for r in invoices))
    open_quotes = [r for r in list_documents(db, QUOTATION) if r["status"] == STATUS_OPEN]
    low = low_stock_products(db)
    return {
        "period": period,
        "period_label": PERIOD_LABELS[period],
        "outstanding": outstanding,
        "paid_this_month": paid_period,
        "invoiced_this_month": invoiced_period,
        "overdue_count": len(overdue),
        "overdue_amount": round2(sum(r["balance"] for r in overdue)),
        "invoice_count": len(invoices),
        "open_quotations": len(open_quotes),
        "customer_count": db.scalar("SELECT COUNT(*) FROM customers", (), 0),
        "product_count": db.scalar("SELECT COUNT(*) FROM products WHERE active = 1", (), 0),
        "recent_invoices": invoices[:recent],
        "overdue_invoices": sorted(overdue, key=lambda r: r.get("due_date") or "")[:recent],
        "stock_value": stock_value(db),
        "low_stock": low,
        "low_stock_count": len(low),
        "purchases_this_month": purchases_period,
        "returns_this_month": returns_period,
        "profit_month": profit_summary(db, start),
        "profit_all": profit_summary(db),
        "best_sellers": best_sellers(db, best, start),
    }


def recent_activity(db: Database, limit: int = 12) -> list[dict]:
    return db.query("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,))


# =========================================================================== CSV export
def export_csv(path: str, headers: list[str], rows: list[list]) -> None:
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])


# =========================================================================== cloud sync (Supabase)
def cloud_client(db: Database):
    from cloud import Supabase
    return Supabase(db.get_setting("cloud_url", ""), db.get_setting("cloud_anon_key", ""))


def cloud_session(db: Database) -> dict:
    return db.get_secret("session") or {}


def cloud_token(db: Database) -> str:
    return (cloud_session(db) or {}).get("access_token", "")


def cloud_user(db: Database) -> dict:
    return (cloud_session(db) or {}).get("user", {}) or {}


def cloud_signed_in_email(db: Database) -> str:
    return cloud_user(db).get("email", "")


def cloud_configured(db: Database) -> bool:
    return bool(_clean(db.get_setting("cloud_url", "")) and _clean(db.get_setting("cloud_anon_key", "")))


def cloud_sign_in(db: Database, email: str, password: str) -> dict:
    data = cloud_client(db).sign_in(_clean(email), password)
    db.set_secret("session", {"access_token": data.get("access_token"),
                              "refresh_token": data.get("refresh_token"), "user": data.get("user", {})})
    db.log("cloud", f"Signed in to cloud as {_clean(email)}", "cloud", None)
    # convenience: an employee (or owner) who belongs to exactly one shop gets linked to it
    # automatically, so they never have to hunt for the right shop after signing in.
    try:
        shops = cloud_list_shops(db)
        if len(shops) == 1:
            cloud_link_shop(db, shops[0]["id"], shops[0].get("name", ""))
    except Exception:
        pass
    return data.get("user", {})


def cloud_sign_out(db: Database) -> None:
    db.set_secret("session", None)


def _stamp_shop_id(db: Database, shop_id: str) -> None:
    for t in SYNC_TABLES:
        db.execute(f"UPDATE {t} SET shop_id = ? WHERE shop_id IS NULL OR shop_id = ''", (shop_id,))


def cloud_create_shop(db: Database, name: str) -> dict:
    name = _clean(name)
    if not name:
        raise ValidationError("Enter a shop name.")
    tok = cloud_token(db)
    if not tok:
        raise ValidationError("Sign in to the cloud first.")
    sb = cloud_client(db)
    # a server-side function creates the shop + owner membership in one trusted step
    # (avoids the RLS chicken-and-egg where the row can't be read before membership exists)
    data = sb.rpc("create_shop", tok, {"p_name": name})
    shop = data[0] if isinstance(data, list) else data
    if not shop or not shop.get("id"):
        raise ValidationError("The shop was not created. Re-run SUPABASE_SETUP.sql and try again.")
    db.set_setting("cloud_shop_id", shop["id"])
    db.set_setting("cloud_shop_name", shop["name"])
    _stamp_shop_id(db, shop["id"])
    db.log("cloud", f"Created cloud shop '{name}'", "cloud", None)
    return shop


def cloud_list_shops(db: Database) -> list[dict]:
    tok = cloud_token(db)
    if not tok:
        return []
    return cloud_client(db).select("shops", tok, {"select": "id,name,created_at", "order": "created_at.asc"})


def cloud_link_shop(db: Database, shop_id: str, shop_name: str = "") -> None:
    db.set_setting("cloud_shop_id", shop_id)
    if shop_name:
        db.set_setting("cloud_shop_name", shop_name)
    _stamp_shop_id(db, shop_id)
    db.log("cloud", f"Linked to cloud shop '{shop_name or shop_id}'", "cloud", None)


def cloud_add_employee(db: Database, email: str, password: str, role: str = ROLE_EMPLOYEE, full_name: str = "") -> dict:
    email = _clean(email)
    if not email or "@" not in email:
        raise ValidationError("Enter a valid email.")
    if len(password or "") < 6:
        raise ValidationError("Password must be at least 6 characters.")
    service = db.get_secret("service_key")
    if not service:
        raise ValidationError("Paste the service_role key in the Team box first (owner only).")
    shop_id = db.get_setting("cloud_shop_id", "")
    if not shop_id:
        raise ValidationError("Create or select a shop first.")
    tok = cloud_token(db)
    sb = cloud_client(db)
    user = sb.admin_create_user(service, email, password, {"full_name": _clean(full_name), "role": role})
    try:
        sb.insert("members", tok, [{"user_id": user["id"], "shop_id": shop_id, "role": role}])
    except Exception:
        sb.upsert("members", tok, [{"user_id": user["id"], "shop_id": shop_id, "role": role}],
                  on_conflict="user_id,shop_id")
    db.log("cloud", f"Added cloud {role} {email}", "cloud", None)
    return user


def cloud_list_members(db: Database) -> list[dict]:
    tok = cloud_token(db)
    shop_id = db.get_setting("cloud_shop_id", "")
    if not tok or not shop_id:
        return []
    return cloud_client(db).select("members", tok,
                                   {"select": "user_id,role,created_at", "shop_id": f"eq.{shop_id}",
                                    "order": "created_at.asc"})


# =========================================================================== bulk product import
PRODUCT_CSV_HEADERS = ["name", "sku", "unit", "sale_price", "cost_price", "tax_rate", "description",
                       "opening_stock", "low_stock_level", "track_stock", "active"]
_PRODUCT_ALIASES = {
    "name": ("name", "product", "product_name", "item", "title"),
    "sku": ("sku", "code", "sku/code", "item_code", "barcode"),
    "unit": ("unit", "uom"),
    "sale_price": ("sale_price", "unit_price", "price", "selling_price", "rate"),
    "cost_price": ("cost_price", "cost", "purchase_price", "buy_price"),
    "tax_rate": ("tax_rate", "tax", "tax_%", "tax_percent", "gst"),
    "description": ("description", "desc", "details"),
    "opening_stock": ("opening_stock", "stock", "qty", "quantity", "opening_qty", "in_stock"),
    "low_stock_level": ("low_stock_level", "low_stock", "reorder_level", "alert_at", "min_stock"),
    "track_stock": ("track_stock", "track"),
    "active": ("active", "enabled"),
}


def products_csv_template(path: str) -> None:
    """Write a ready-to-fill product import sheet with two example rows."""
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(PRODUCT_CSV_HEADERS)
        w.writerow(["Wireless Mouse", "MSE-01", "pcs", "850", "600", "", "Optical USB mouse", "50", "5", "1", "1"])
        w.writerow(["Consulting", "SVC-01", "hr", "5000", "0", "0", "Hourly consulting", "", "", "0", "1"])


def _bool(v, default=1):
    s = str(v).strip().lower()
    if s in ("1", "yes", "y", "true", "t"):
        return 1
    if s in ("0", "no", "n", "false", "f"):
        return 0
    return default


def import_products_csv(db: Database, path: str) -> dict:
    """Create or update products from a CSV. Matches an existing product by SKU (if given) else by name.
    Returns {created, updated, skipped, errors:[...]} and never raises on a bad row."""
    import csv
    created = updated = skipped = 0
    errors: list[str] = []
    with open(path, "r", newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except Exception:
            dialect = csv.excel
        reader = csv.DictReader(fh, dialect=dialect)
        if not reader.fieldnames:
            raise ValidationError("The file is empty or is not a CSV.")
        header_map = {}
        for raw in reader.fieldnames:
            key = (raw or "").strip().lower().replace(" ", "_")
            for field, aliases in _PRODUCT_ALIASES.items():
                if key in aliases:
                    header_map[raw] = field
                    break
        if "name" not in header_map.values():
            raise ValidationError("The CSV needs at least a 'name' column. Use the template as a guide.")
        existing = list_products(db)
        by_sku = {_clean(p["sku"]).lower(): p for p in existing if _clean(p["sku"])}
        by_name = {_clean(p["name"]).lower(): p for p in existing}
        for n, raw_row in enumerate(reader, start=2):
            row = {field: (raw_row.get(raw) or "").strip() for raw, field in header_map.items()}
            name = row.get("name", "")
            if not name and not any(row.values()):
                continue
            if not name:
                errors.append(f"Row {n}: missing product name - skipped")
                skipped += 1
                continue
            match = by_sku.get(row["sku"].lower()) if row.get("sku") else None
            if not match:
                match = by_name.get(name.lower())
            data = {
                "name": name,
                "sku": row.get("sku", (match or {}).get("sku", "")),
                "unit": row.get("unit") or (match or {}).get("unit") or "pcs",
                "unit_price": (row.get("sale_price") or (match or {}).get("unit_price") or 0),
                "cost_price": (row.get("cost_price") or (match or {}).get("cost_price") or 0),
                "tax_rate": row.get("tax_rate", "" if not match else ("" if match.get("tax_rate") is None else match.get("tax_rate"))),
                "description": row.get("description", (match or {}).get("description", "")),
                "low_stock_level": (row.get("low_stock_level") or (match or {}).get("low_stock_level") or 0),
                "track_stock": _bool(row.get("track_stock"), (match or {}).get("track_stock", 1)),
                "active": _bool(row.get("active"), (match or {}).get("active", 1)),
            }
            if match:
                data["id"] = match["id"]
            elif row.get("opening_stock"):
                data["opening_stock"] = row["opening_stock"]
            try:
                pid = save_product(db, data)
            except ValidationError as e:
                errors.append(f"Row {n} ({name}): {e}")
                skipped += 1
                continue
            if match:
                updated += 1
                if row.get("opening_stock"):
                    try:
                        adjust_stock(db, pid, row["opening_stock"], note="CSV import stock update")
                    except ValidationError:
                        pass
            else:
                created += 1
                prod = get_product(db, pid)
                if _clean(data.get("sku")):
                    by_sku[_clean(data["sku"]).lower()] = prod
                by_name[name.lower()] = prod
    db.log("product", f"Imported products from CSV: {created} new, {updated} updated", "product", None)
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}
