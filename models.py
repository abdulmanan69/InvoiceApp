"""Domain logic: CRUD repositories, totals, status, numbering, dashboard stats.

Everything here works on plain dicts (sqlite rows) and a Database instance.
"""
from __future__ import annotations

import datetime as dt
import re

from db import Database
from utils import now_stamp, parse_date, parse_float, parse_int, round2, today_iso, add_days

INVOICE = "invoice"
QUOTATION = "quotation"

STATUS_UNPAID = "Unpaid"
STATUS_PARTIAL = "Partially Paid"
STATUS_PAID = "Paid"
STATUS_OVERDUE = "Overdue"
# quotation statuses (also computed, never stored)
STATUS_OPEN = "Open"
STATUS_CONVERTED = "Converted"
STATUS_EXPIRED = "Expired"

INVOICE_STATUSES = [STATUS_UNPAID, STATUS_PARTIAL, STATUS_PAID, STATUS_OVERDUE]
QUOTATION_STATUSES = [STATUS_OPEN, STATUS_CONVERTED, STATUS_EXPIRED]

DOC_LABEL = {INVOICE: "Invoice", QUOTATION: "Quotation"}


class ValidationError(Exception):
    """Raised for user-facing validation failures. Message is safe to show."""


class OverpaymentError(ValidationError):
    def __init__(self, amount: float, remaining: float):
        self.amount, self.remaining = amount, remaining
        super().__init__(f"Payment of {amount:,.2f} exceeds the remaining balance of {remaining:,.2f}.")


# =========================================================================== helpers
def _clean(text) -> str:
    return (text or "").strip() if isinstance(text, str) else ("" if text is None else str(text))


def _like(term: str) -> str:
    return f"%{_clean(term)}%"


# =========================================================================== customers
def list_customers(db: Database, search: str = "") -> list[dict]:
    sql = """
        SELECT c.*,
               COALESCE((SELECT SUM(d.total) FROM documents d WHERE d.customer_id = c.id AND d.doc_type = 'invoice'), 0)
               - COALESCE((SELECT SUM(p.amount) FROM payments p JOIN documents d ON d.id = p.invoice_id
                           WHERE d.customer_id = c.id), 0) AS balance,
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
    invoiced = db.scalar(
        "SELECT SUM(total) FROM documents WHERE customer_id = ? AND doc_type = 'invoice'", (customer_id,), 0
    )
    paid = db.scalar(
        "SELECT SUM(p.amount) FROM payments p JOIN documents d ON d.id = p.invoice_id WHERE d.customer_id = ?",
        (customer_id,), 0,
    )
    return round2((invoiced or 0) - (paid or 0))


def save_customer(db: Database, data: dict) -> int:
    name = _clean(data.get("name"))
    if not name:
        raise ValidationError("Customer name is required.")
    fields = ("name", "company", "billing_address", "shipping_address", "phone", "email", "tax_number", "notes")
    values = [_clean(data.get(f)) for f in fields]
    values[0] = name
    cid = data.get("id")
    if cid:
        db.execute(
            "UPDATE customers SET " + ", ".join(f"{f} = ?" for f in fields) + " WHERE id = ?",
            (*values, cid),
        )
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
        raise ValidationError(
            f"This customer has {count} invoice(s)/quotation(s). Delete or reassign those documents first."
        )
    row = get_customer(db, customer_id)
    db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    if row:
        db.log("customer", f"Deleted customer {row['name']}", "customer", customer_id)


# =========================================================================== vendors
def list_vendors(db: Database, search: str = "") -> list[dict]:
    sql = "SELECT * FROM vendors"
    params: list = []
    if _clean(search):
        sql += " WHERE name LIKE ? OR company LIKE ? OR email LIKE ? OR phone LIKE ?"
        params = [_like(search)] * 4
    sql += " ORDER BY name COLLATE NOCASE"
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


# =========================================================================== products
def list_products(db: Database, search: str = "", active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM products"
    clauses, params = [], []
    if _clean(search):
        clauses.append("(name LIKE ? OR sku LIKE ? OR description LIKE ?)")
        params += [_like(search)] * 3
    if active_only:
        clauses.append("active = 1")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY name COLLATE NOCASE"
    return db.query(sql, params)


def get_product(db: Database, product_id) -> dict | None:
    return db.query_one("SELECT * FROM products WHERE id = ?", (product_id,)) if product_id else None


def save_product(db: Database, data: dict) -> int:
    name = _clean(data.get("name"))
    if not name:
        raise ValidationError("Product/service name is required.")
    price = parse_float(data.get("unit_price"), None)
    if price is None or price < 0:
        raise ValidationError("Unit price must be a number of 0 or more.")
    tax_raw = data.get("tax_rate")
    tax_rate = None
    if tax_raw not in (None, ""):
        tax_rate = parse_float(tax_raw, None)
        if tax_rate is None or tax_rate < 0 or tax_rate > 100:
            raise ValidationError("Tax rate override must be between 0 and 100, or left blank.")
    active = 1 if data.get("active", 1) in (1, True, "1", "True", "true") else 0
    values = (
        _clean(data.get("sku")), name, _clean(data.get("description")), round2(price),
        _clean(data.get("unit")) or "pcs", tax_rate, active,
    )
    pid = data.get("id")
    if pid:
        db.execute(
            "UPDATE products SET sku=?, name=?, description=?, unit_price=?, unit=?, tax_rate=?, active=? WHERE id=?",
            (*values, pid),
        )
        db.log("product", f"Updated product {name}", "product", pid)
        return int(pid)
    cur = db.execute(
        "INSERT INTO products(sku, name, description, unit_price, unit, tax_rate, active, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (*values, now_stamp()),
    )
    db.log("product", f"Added product {name}", "product", cur.lastrowid)
    return int(cur.lastrowid)


def delete_product(db: Database, product_id: int) -> None:
    row = get_product(db, product_id)
    db.execute("DELETE FROM products WHERE id = ?", (product_id,))  # items keep their text (ON DELETE SET NULL)
    if row:
        db.log("product", f"Deleted product {row['name']}", "product", product_id)


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
    """After saving a document numbered like the prefix pattern, advance the counter past it."""
    k_prefix, k_next, _ = _num_keys(doc_type)
    prefix = db.get_setting(k_prefix, "")
    m = re.fullmatch(re.escape(prefix) + r"(\d+)", _clean(number))
    if not m:
        return
    used = int(m.group(1))
    current = parse_int(db.get_setting(k_next, "1"), 1) or 1
    if used >= current:
        db.set_setting(k_next, str(used + 1))


# =========================================================================== totals
def normalize_items(raw_items: list[dict], default_tax_rate: float) -> list[dict]:
    """Validate and compute per-line totals. Raises ValidationError on bad numbers."""
    items = []
    for idx, raw in enumerate(raw_items or [], start=1):
        desc = _clean(raw.get("description"))
        qty = parse_float(raw.get("quantity"), None)
        price = parse_float(raw.get("unit_price"), None)
        if not desc and qty in (None, 0) and price in (None, 0):
            continue  # skip completely empty rows
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
        })
    return items


def compute_totals(items: list[dict], discount_type: str, discount_value, default_tax_rate) -> dict:
    """Subtotal -> discount (percent or fixed, on subtotal) -> tax (per line, after discount) -> total.

    Safe on empty lists and bad numbers (treated as 0).
    """
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
                   today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    due = parse_date(due_date)
    if doc_type == QUOTATION:
        if converted:
            return STATUS_CONVERTED
        if due and due < today:
            return STATUS_EXPIRED
        return STATUS_OPEN
    total = float(total or 0)
    paid = float(paid or 0)
    if paid >= total - 0.005:
        return STATUS_PAID
    if due and due < today:
        return STATUS_OVERDUE
    if paid > 0.005:
        return STATUS_PARTIAL
    return STATUS_UNPAID


# =========================================================================== documents
_DOC_SELECT = """
    SELECT d.*, c.name AS customer_name, c.company AS customer_company,
           COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = d.id), 0) AS paid,
           (SELECT COUNT(*) FROM documents x WHERE x.source_quotation_id = d.id) AS converted_count,
           (SELECT COUNT(*) FROM document_items i WHERE i.document_id = d.id) AS item_count
    FROM documents d LEFT JOIN customers c ON c.id = d.customer_id
"""


def _decorate(row: dict) -> dict:
    row["paid"] = round2(row.get("paid") or 0)
    row["balance"] = round2(float(row.get("total") or 0) - row["paid"])
    row["status"] = compute_status(row["doc_type"], row.get("total"), row["paid"], row.get("due_date"),
                                   bool(row.get("converted_count")))
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
    rows = [_decorate(r) for r in db.query(sql, params)]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def get_document(db: Database, doc_id) -> dict | None:
    if not doc_id:
        return None
    row = db.query_one(_DOC_SELECT + " WHERE d.id = ?", (doc_id,))
    if not row:
        return None
    _decorate(row)
    row["items"] = db.query("SELECT * FROM document_items WHERE document_id = ? ORDER BY sort_order, id", (doc_id,))
    row["payments"] = db.query("SELECT * FROM payments WHERE invoice_id = ? ORDER BY date, id", (doc_id,))
    row["customer"] = get_customer(db, row.get("customer_id"))
    return row


def save_document(db: Database, data: dict, raw_items: list[dict]) -> int:
    """Insert or update a document with its items. Validates everything first."""
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
    totals = compute_totals(items, discount_type, discount_value, tax_rate)
    ts = now_stamp()
    cols = {
        "doc_type": doc_type, "number": number, "customer_id": customer_id,
        "date": date.isoformat(), "due_date": due.isoformat() if due else None,
        "template": _clean(data.get("template")), "currency": _clean(data.get("currency")),
        "notes": _clean(data.get("notes")), "terms": _clean(data.get("terms")),
        "discount_type": discount_type, "discount_value": discount_value, "tax_rate": tax_rate,
        **totals, "source_quotation_id": data.get("source_quotation_id") or None, "updated_at": ts,
    }
    with db.transaction() as conn:
        if doc_id:
            sets = ", ".join(f"{k} = ?" for k in cols)
            conn.execute(f"UPDATE documents SET {sets} WHERE id = ?", (*cols.values(), doc_id))
            conn.execute("DELETE FROM document_items WHERE document_id = ?", (doc_id,))
        else:
            cols["created_at"] = ts
            cur = conn.execute(
                f"INSERT INTO documents({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                tuple(cols.values()),
            )
            doc_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO document_items(document_id, product_id, description, quantity, unit, unit_price,"
            " tax_rate, line_total, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(doc_id, i["product_id"], i["description"], i["quantity"], i["unit"], i["unit_price"],
              i["tax_rate"], i["line_total"], i["sort_order"]) for i in items],
        )
    bump_counter(db, doc_type, number)
    db.log(doc_type, f"{'Updated' if data.get('id') else 'Created'} {DOC_LABEL[doc_type].lower()} {number}",
           doc_type, doc_id)
    return int(doc_id)


def delete_document(db: Database, doc_id: int) -> None:
    row = db.query_one("SELECT doc_type, number FROM documents WHERE id = ?", (doc_id,))
    db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))  # items & payments cascade
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
        "tax_rate": src.get("tax_rate"),
    }
    items = [dict(i) for i in src.get("items", [])]
    return data, items


def duplicate_document(db: Database, doc_id: int) -> int:
    src = get_document(db, doc_id)
    if not src:
        raise ValidationError("Document not found.")
    data, items = _copy_payload(src, src["doc_type"], db)
    new_id = save_document(db, data, items)
    db.log(src["doc_type"], f"Duplicated {src['number']} as {data['number']}", src["doc_type"], new_id)
    return new_id


def convert_quotation_to_invoice(db: Database, quotation_id: int) -> int:
    src = get_document(db, quotation_id)
    if not src or src["doc_type"] != QUOTATION:
        raise ValidationError("Only quotations can be converted to invoices.")
    data, items = _copy_payload(src, INVOICE, db)
    data["source_quotation_id"] = quotation_id
    new_id = save_document(db, data, items)
    db.log(INVOICE, f"Converted quotation {src['number']} to invoice {data['number']}", INVOICE, new_id)
    return new_id


# =========================================================================== payments
def invoice_paid_amount(db: Database, invoice_id: int) -> float:
    return round2(db.scalar("SELECT SUM(amount) FROM payments WHERE invoice_id = ?", (invoice_id,), 0) or 0)


def add_payment(db: Database, invoice_id: int, amount, date, method: str = "", reference: str = "",
                allow_overpay: bool = False) -> int:
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
    remaining = round2(float(inv["total"]) - invoice_paid_amount(db, invoice_id))
    if amt > remaining + 0.005 and not allow_overpay:
        raise OverpaymentError(amt, remaining)
    cur = db.execute(
        "INSERT INTO payments(invoice_id, amount, date, method, reference, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (invoice_id, amt, d.isoformat(), _clean(method), _clean(reference), now_stamp()),
    )
    db.log("payment", f"Payment of {amt:,.2f} received for {inv['number']}", "payment", cur.lastrowid)
    return int(cur.lastrowid)


def mark_as_paid(db: Database, invoice_id: int, method: str = "", date=None) -> int | None:
    """Record one real payment for the full remaining balance. Returns payment id or None if nothing owed."""
    inv = db.query_one("SELECT total FROM documents WHERE id = ? AND doc_type = 'invoice'", (invoice_id,))
    if not inv:
        raise ValidationError("Invoice not found.")
    remaining = round2(float(inv["total"]) - invoice_paid_amount(db, invoice_id))
    if remaining <= 0.005:
        return None
    return add_payment(db, invoice_id, remaining, date or today_iso(), method, "Marked as paid")


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


# =========================================================================== dashboard
def dashboard_stats(db: Database) -> dict:
    invoices = list_documents(db, INVOICE)
    today = dt.date.today()
    month_start = today.replace(day=1).isoformat()
    outstanding = round2(sum(r["balance"] for r in invoices if r["balance"] > 0))
    overdue = [r for r in invoices if r["status"] == STATUS_OVERDUE]
    paid_month = round2(db.scalar("SELECT SUM(amount) FROM payments WHERE date >= ?", (month_start,), 0) or 0)
    invoiced_month = round2(sum(float(r["total"] or 0) for r in invoices if (r["date"] or "") >= month_start))
    open_quotes = [r for r in list_documents(db, QUOTATION) if r["status"] == STATUS_OPEN]
    return {
        "outstanding": outstanding,
        "paid_this_month": paid_month,
        "invoiced_this_month": invoiced_month,
        "overdue_count": len(overdue),
        "overdue_amount": round2(sum(r["balance"] for r in overdue)),
        "invoice_count": len(invoices),
        "open_quotations": len(open_quotes),
        "customer_count": db.scalar("SELECT COUNT(*) FROM customers", (), 0),
        "recent_invoices": invoices[:6],
        "overdue_invoices": sorted(overdue, key=lambda r: r.get("due_date") or "")[:6],
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
