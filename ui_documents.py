"""Invoices and quotations: list page (filters, actions) and the document editor dialog."""
from __future__ import annotations

import os
import tkinter as tk

import ttkbootstrap as tb

import models
from pdf_templates import TEMPLATE_NAMES, render_pdf
from ui_common import (Card, DataTable, DateField, Dialog, IdCombo, PageHeader, SearchEntry, StatusBadge,
                       ask_save_path, ask_yes_no, button, fmt_day, fmt_money, show_error, show_info)
from ui_customers import CustomerDialog
from ui_payments import PaymentDialog
from utils import (add_days, data_dir, fmt_number, open_file, parse_float, parse_int, print_file, safe_filename,
                   today_iso)


# =========================================================================== PDF helpers
def _doc_for_pdf(app, doc_id: int) -> dict | None:
    doc = models.get_document(app.db, doc_id)
    if doc and doc.get("source_quotation_id"):
        src = app.db.query_one("SELECT number FROM documents WHERE id = ?", (doc["source_quotation_id"],))
        if src:
            doc["source_quotation_number"] = src["number"]
    return doc


def export_pdf(parent, app, doc_id: int, ask: bool = True, open_after: bool = True) -> str | None:
    doc = _doc_for_pdf(app, doc_id)
    if not doc:
        show_error(parent, "Document not found.")
        return None
    name = f"{safe_filename(doc['number'])}.pdf"
    if ask:
        path = ask_save_path(parent, "Export PDF", name, ".pdf", [("PDF files", "*.pdf")])
        if not path:
            return None
    else:
        folder = os.path.join(data_dir(), "exports")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
    try:
        render_pdf(doc, app.settings, path)
    except PermissionError:
        show_error(parent, "The PDF could not be written. If it is open in another program, close it and try again.")
        return None
    except Exception as e:  # never crash the UI on a rendering problem
        show_error(parent, f"The PDF could not be created:\n{e}")
        return None
    if open_after and not open_file(path):
        show_info(parent, f"PDF saved to:\n{path}", "PDF saved")
    return path


def print_pdf(parent, app, doc_id: int) -> None:
    path = export_pdf(parent, app, doc_id, ask=False, open_after=False)
    if path and not print_file(path):
        show_info(parent, f"Could not send to printer automatically. The PDF is at:\n{path}", "Print")


# =========================================================================== line item row
class LineRow:
    def __init__(self, editor, master, products: list[dict], item: dict | None = None):
        self.editor, self.products = editor, products
        p = editor.app.palette
        item = item or {}
        self.frame = tk.Frame(master, bg=p.card)
        self.frame.pack(fill="x", pady=2)
        for c, w in enumerate((1, 6, 1, 1, 2, 1, 2, 0)):
            self.frame.grid_columnconfigure(c, weight=w, minsize=(48 if w == 0 else 0))
        self.product = IdCombo(self.frame, [(pr["id"], pr["name"]) for pr in products], blank_label="(custom)", width=18)
        self.product.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.product.bind("<<ComboboxSelected>>", self.on_product)
        self.desc = tk.StringVar(value=item.get("description", ""))
        self.qty = tk.StringVar(value=fmt_number(item.get("quantity", 1)) if item else "1")
        self.unit = tk.StringVar(value=item.get("unit", ""))
        self.price = tk.StringVar(value=fmt_number(item.get("unit_price", 0)) if item else "")
        self.tax = tk.StringVar(value="" if item.get("tax_rate") is None else fmt_number(item.get("tax_rate")))
        widths = {"description": None, "quantity": 7, "unit": 7, "unit_price": 12, "tax_rate": 6}
        entries = []
        for c, (key, var) in enumerate((("description", self.desc), ("quantity", self.qty), ("unit", self.unit),
                                         ("unit_price", self.price), ("tax_rate", self.tax)), start=1):
            e = tb.Entry(self.frame, textvariable=var, width=widths[key])
            e.grid(row=0, column=c, sticky="ew", padx=(0, 4))
            if key in ("quantity", "unit_price", "tax_rate"):
                e.configure(justify="right")
            var.trace_add("write", lambda *_: editor.recalc())
            entries.append(e)
        self.desc_entry = entries[0]
        self.amount = tk.Label(self.frame, text="", font=p.fonts["bold"], bg=p.card, fg=p.fg, anchor="e", width=14)
        self.amount.grid(row=0, column=6, sticky="ew", padx=(0, 4))
        tb.Button(self.frame, text="✕", bootstyle="danger-link", command=self.remove, width=3).grid(row=0, column=7)
        if item.get("product_id"):
            self.product.set_id(item["product_id"])

    def on_product(self, _=None):
        pid = self.product.get_id()
        pr = next((x for x in self.products if x["id"] == pid), None)
        if not pr:
            return
        desc = pr["name"] if not pr.get("description") else f"{pr['name']} - {pr['description']}"
        self.desc.set(desc.replace("\n", " "))
        self.unit.set(pr.get("unit") or "")
        self.price.set(fmt_number(pr.get("unit_price") or 0))
        self.tax.set("" if pr.get("tax_rate") is None else fmt_number(pr["tax_rate"]))
        if not self.qty.get().strip():
            self.qty.set("1")
        self.editor.recalc()

    def data(self) -> dict:
        return {"product_id": self.product.get_id(), "description": self.desc.get(), "quantity": self.qty.get(),
                "unit": self.unit.get(), "unit_price": self.price.get(), "tax_rate": self.tax.get().strip()}

    def remove(self):
        self.editor.remove_row(self)

    def destroy(self):
        self.frame.destroy()


# =========================================================================== editor dialog
class DocumentEditor(Dialog):
    def __init__(self, parent, app, doc_type: str, doc_id: int | None = None, customer_id=None):
        self.doc_type = doc_type
        label = models.DOC_LABEL[doc_type]
        self.doc = models.get_document(app.db, doc_id) if doc_id else None
        title = f"Edit {label} {self.doc['number']}" if self.doc else f"New {label}"
        super().__init__(parent, app, title, width=1160, height=780)
        p = app.palette
        s = app.settings
        self.is_invoice = doc_type == models.INVOICE
        self.rows: list[LineRow] = []
        self.products = models.list_products(app.db, active_only=True)
        self._loading = True

        # ---------------------------------------------------------- header card
        head = Card(self.body, app, padding=14)
        head.pack(fill="x")
        head.grid_columnconfigure(1, weight=3)
        head.grid_columnconfigure(3, weight=1)
        head.grid_columnconfigure(5, weight=1)

        def lbl(master, text, r, c):
            tk.Label(master, text=text, font=p.fonts["small_bold"], bg=p.card, fg=p.muted, anchor="w").grid(
                row=r, column=c, sticky="w", padx=(0 if c == 0 else 14, 6), pady=4)

        lbl(head, "CUSTOMER", 0, 0)
        cust_box = tk.Frame(head, bg=p.card)
        cust_box.grid(row=0, column=1, sticky="ew", pady=4)
        self.customer = IdCombo(cust_box, [], blank_label="(no customer)")
        self.customer.pack(side="left", fill="x", expand=True)
        button(cust_box, "+ New", self.quick_customer, "secondary-outline").pack(side="left", padx=(6, 0))
        self.reload_customers(customer_id or (self.doc or {}).get("customer_id"))

        lbl(head, f"{label.upper()} NO.", 0, 2)
        self.number = tk.StringVar(value=self.doc["number"] if self.doc else models.next_number(app.db, doc_type))
        tb.Entry(head, textvariable=self.number, width=16).grid(row=0, column=3, sticky="ew", pady=4)
        lbl(head, "TEMPLATE", 0, 4)
        self.template = tb.Combobox(head, values=TEMPLATE_NAMES, state="readonly", width=12)
        tpl = (self.doc or {}).get("template") or s.get("default_template") or TEMPLATE_NAMES[0]
        self.template.set(tpl if tpl in TEMPLATE_NAMES else TEMPLATE_NAMES[0])
        self.template.grid(row=0, column=5, sticky="ew", pady=4)

        lbl(head, "DATE", 1, 0)
        dates = tk.Frame(head, bg=p.card)
        dates.grid(row=1, column=1, sticky="w", pady=4)
        self.date = DateField(dates, app, (self.doc or {}).get("date") or today_iso(), bg=p.card)
        self.date.pack(side="left")
        tk.Label(dates, text="DUE DATE" if self.is_invoice else "VALID UNTIL", font=p.fonts["small_bold"], bg=p.card,
                 fg=p.muted).pack(side="left", padx=(16, 6))
        days = parse_int(s.get("invoice_due_days" if self.is_invoice else "quotation_valid_days"), 14) or 0
        self.due = DateField(dates, app, (self.doc or {}).get("due_date") or add_days(today_iso(), days), bg=p.card)
        self.due.pack(side="left")
        lbl(head, "CURRENCY", 1, 2)
        self.currency = tk.StringVar(value=(self.doc or {}).get("currency") or s.get("currency_code", ""))
        tb.Entry(head, textvariable=self.currency, width=8).grid(row=1, column=3, sticky="w", pady=4)
        lbl(head, "DEFAULT TAX %", 1, 4)
        self.tax_rate = tk.StringVar(value=fmt_number((self.doc or {}).get("tax_rate", s.get("default_tax_rate", 0))))
        tb.Entry(head, textvariable=self.tax_rate, width=8, justify="right").grid(row=1, column=5, sticky="w", pady=4)
        self.tax_rate.trace_add("write", lambda *_: self.recalc())

        # ---------------------------------------------------------- items card
        items = Card(self.body, app, padding=14)
        items.pack(fill="both", expand=True, pady=(10, 0))
        hdr = tk.Frame(items, bg=p.card)
        hdr.pack(fill="x")
        for c, (text, w, anchor) in enumerate((("Product", 1, "w"), ("Description", 6, "w"), ("Qty", 1, "e"),
                                               ("Unit", 1, "w"), ("Unit price", 2, "e"), ("Tax %", 1, "e"),
                                               ("Amount", 2, "e"), ("", 0, "w"))):
            hdr.grid_columnconfigure(c, weight=w, minsize=(48 if w == 0 else 0))
            tk.Label(hdr, text=text.upper(), font=p.fonts["small_bold"], bg=p.card, fg=p.muted, anchor=anchor,
                     width=(18 if c == 0 else None)).grid(row=0, column=c, sticky="ew", padx=(0, 4))
        self.items_box = tb.ScrolledFrame(items, auto_hide=True, height=200)
        self.items_box.pack(fill="both", expand=True, pady=(4, 6))
        foot = tk.Frame(items, bg=p.card)
        foot.pack(fill="x")
        button(foot, "+ Add line", self.add_row, "outline").pack(side="left")
        tk.Label(foot, text="Pick a product to auto-fill, or type a custom line. Blank tax % uses the default rate.",
                 font=p.fonts["small"], bg=p.card, fg=p.muted).pack(side="left", padx=12)

        # ---------------------------------------------------------- bottom: notes + totals
        bottom = tk.Frame(self.body, bg=p.bg)
        bottom.pack(fill="x", pady=(10, 0))
        bottom.grid_columnconfigure(0, weight=3)
        bottom.grid_columnconfigure(1, weight=2)
        notes = Card(bottom, app, padding=14)
        notes.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        notes.grid_columnconfigure(1, weight=1)
        tk.Label(notes, text="NOTES", font=p.fonts["small_bold"], bg=p.card, fg=p.muted).grid(row=0, column=0, sticky="nw", padx=(0, 8))
        self.notes = tb.Text(notes, height=3, wrap="word", font=p.fonts["base"])
        self.notes.insert("1.0", (self.doc or {}).get("notes") if self.doc else s.get("default_notes", ""))
        self.notes.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        tk.Label(notes, text="TERMS", font=p.fonts["small_bold"], bg=p.card, fg=p.muted).grid(row=1, column=0, sticky="nw", padx=(0, 8))
        self.terms = tb.Text(notes, height=3, wrap="word", font=p.fonts["base"])
        self.terms.insert("1.0", (self.doc or {}).get("terms") if self.doc else s.get("default_terms", ""))
        self.terms.grid(row=1, column=1, sticky="ew")

        totals = Card(bottom, app, padding=14)
        totals.grid(row=0, column=1, sticky="nsew")
        totals.grid_columnconfigure(1, weight=1)
        self.total_labels: dict[str, tk.Label] = {}

        def trow(r, key, text, font_key="base", color=None):
            tk.Label(totals, text=text, font=p.fonts[font_key], bg=p.card, fg=color or p.muted, anchor="w").grid(
                row=r, column=0, sticky="w", pady=3)
            v = tk.Label(totals, text="", font=p.fonts[font_key], bg=p.card, fg=color or p.fg, anchor="e")
            v.grid(row=r, column=1, sticky="e", pady=3)
            self.total_labels[key] = v

        trow(0, "subtotal", "Subtotal")
        disc = tk.Frame(totals, bg=p.card)
        disc.grid(row=1, column=0, sticky="w", pady=3)
        tk.Label(disc, text="Discount", font=p.fonts["base"], bg=p.card, fg=p.muted).pack(side="left")
        self.discount_type = tb.Combobox(disc, values=["%", s.get("currency_symbol") or "fixed"], state="readonly", width=5)
        self.discount_type.current(1 if (self.doc or {}).get("discount_type") == "fixed" else 0)
        self.discount_type.pack(side="left", padx=(8, 4))
        self.discount_type.bind("<<ComboboxSelected>>", lambda e: self.recalc())
        self.discount_value = tk.StringVar(value=fmt_number((self.doc or {}).get("discount_value", 0)))
        tb.Entry(disc, textvariable=self.discount_value, width=8, justify="right").pack(side="left")
        self.discount_value.trace_add("write", lambda *_: self.recalc())
        v = tk.Label(totals, text="", font=p.fonts["base"], bg=p.card, fg=p.fg, anchor="e")
        v.grid(row=1, column=1, sticky="e")
        self.total_labels["discount_amount"] = v
        trow(2, "tax_amount", s.get("tax_label") or "Tax")
        tk.Frame(totals, bg=p.border, height=1).grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)
        trow(4, "total", "Total", "heading", p.accent)
        if self.doc and self.is_invoice:
            trow(5, "paid", "Paid", "base", p.success)
            trow(6, "balance", "Balance due", "bold")
            StatusBadge(totals, app, self.doc["status"]).grid(row=7, column=1, sticky="e", pady=(6, 0))

        # ---------------------------------------------------------- rows
        for it in (self.doc or {}).get("items", []):
            self.add_row(it)
        if not self.rows:
            self.add_row()
        self._loading = False
        self.recalc()

        extra = []
        if self.doc and self.is_invoice and self.doc["balance"] > 0.005:
            extra.append(("Record payment", self.record_payment, "success-outline"))
        extra.append(("Save & export PDF", lambda: self.save(export=True), "outline"))
        self.buttons(f"Save {label.lower()}", self.save, extra)
        self.bind("<Control-s>", lambda e: self.save())

    # ------------------------------------------------------------------ helpers
    def reload_customers(self, select_id=None):
        self.customer.set_options([(c["id"], c["name"] + (f" - {c['company']}" if c["company"] else ""))
                                   for c in models.list_customers(self.app.db)])
        if select_id:
            self.customer.set_id(select_id)

    def quick_customer(self):
        new_id = CustomerDialog(self, self.app).show()
        if new_id:
            self.reload_customers(new_id)

    def add_row(self, item: dict | None = None):
        row = LineRow(self, self.items_box, self.products, item)
        self.rows.append(row)
        if item is None and not self._loading:
            row.desc_entry.focus_set()
        self.recalc()

    def remove_row(self, row: LineRow):
        if row in self.rows:
            self.rows.remove(row)
            row.destroy()
        if not self.rows:
            self.add_row()
        self.recalc()

    def header_data(self) -> dict:
        return {
            "id": self.doc["id"] if self.doc else None, "doc_type": self.doc_type, "number": self.number.get(),
            "customer_id": self.customer.get_id(), "date": self.date.get(), "due_date": self.due.get(),
            "template": self.template.get(), "currency": self.currency.get().strip().upper(),
            "notes": self.notes.get("1.0", "end").strip(), "terms": self.terms.get("1.0", "end").strip(),
            "discount_type": "fixed" if self.discount_type.current() == 1 else "percent",
            "discount_value": self.discount_value.get(), "tax_rate": self.tax_rate.get(),
            "source_quotation_id": (self.doc or {}).get("source_quotation_id"),
        }

    def recalc(self):
        """Live totals. Never raises: bad inputs count as zero until fixed."""
        if self._loading:
            return
        default_tax = parse_float(self.tax_rate.get(), 0) or 0
        items = []
        for r in self.rows:
            d = r.data()
            qty = parse_float(d["quantity"], 0) or 0
            price = parse_float(d["unit_price"], 0) or 0
            tax = parse_float(d["tax_rate"], None) if d["tax_rate"] else None
            line = round(qty * price, 2)
            r.amount.configure(text=fmt_money(self.app, line))
            items.append({"line_total": line, "tax_rate": tax, "effective_tax_rate": default_tax if tax is None else tax})
        dtype = "fixed" if self.discount_type.current() == 1 else "percent"
        t = models.compute_totals(items, dtype, self.discount_value.get(), default_tax)
        for k in ("subtotal", "tax_amount", "total"):
            self.total_labels[k].configure(text=fmt_money(self.app, t[k]))
        self.total_labels["discount_amount"].configure(
            text=("-" if t["discount_amount"] else "") + fmt_money(self.app, t["discount_amount"]))
        if "paid" in self.total_labels and self.doc:
            paid = float(self.doc.get("paid") or 0)
            self.total_labels["paid"].configure(text="-" + fmt_money(self.app, paid))
            self.total_labels["balance"].configure(text=fmt_money(self.app, t["total"] - paid))

    # ------------------------------------------------------------------ actions
    def save(self, export: bool = False):
        try:
            doc_id = models.save_document(self.app.db, self.header_data(), [r.data() for r in self.rows])
        except models.ValidationError as e:
            show_error(self, str(e), "Cannot save")
            return
        self.result = doc_id
        self.close()
        if export:
            export_pdf(self.parent, self.app, doc_id)

    def record_payment(self):
        if not self.doc:
            return
        if PaymentDialog(self, self.app, self.doc).show():
            self.result = self.doc["id"]
            self.close()


# =========================================================================== list page
class DocumentsPage(tk.Frame):
    def __init__(self, master, app, doc_type: str):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app, self.doc_type = app, doc_type
        self.is_invoice = doc_type == models.INVOICE
        self.name = "invoices" if self.is_invoice else "quotations"
        label = models.DOC_LABEL[doc_type]
        self.header = PageHeader(self, app, f"{label}s",
                                 "Bill your customers and track what they owe" if self.is_invoice
                                 else "Send quotes and turn accepted ones into invoices")
        self.header.pack(fill="x", padx=28, pady=(24, 12))
        if self.is_invoice:
            self.header.button("Export CSV", self.export_csv, "secondary-outline")
        self.header.button(f"+ New {label.lower()}", self.new, "primary")

        bar = tk.Frame(self, bg=p.bg)
        bar.pack(fill="x", padx=28, pady=(0, 10))
        self.search = SearchEntry(bar, app, "Search number, customer...", self.refresh, width=22)
        self.search.pack(side="left")

        def lbl(text):
            tk.Label(bar, text=text, font=p.fonts["base"], bg=p.bg, fg=p.muted).pack(side="left", padx=(14, 4))

        lbl("Status")
        statuses = ["All"] + (models.INVOICE_STATUSES if self.is_invoice else models.QUOTATION_STATUSES)
        self.status = tb.Combobox(bar, values=statuses, state="readonly", width=13)
        self.status.current(0)
        self.status.pack(side="left")
        self.status.bind("<<ComboboxSelected>>", self.refresh)
        lbl("Customer")
        self.customer = IdCombo(bar, [], blank_label="All", width=18)
        self.customer.pack(side="left")
        self.customer.bind("<<ComboboxSelected>>", self.refresh)
        lbl("From")
        self.date_from = DateField(bar, app, width=10)
        self.date_from.pack(side="left")
        lbl("To")
        self.date_to = DateField(bar, app, width=10)
        self.date_to.pack(side="left")
        button(bar, "Apply", self.refresh, "outline").pack(side="left", padx=(10, 0))
        button(bar, "Clear", self.clear_filters, "link").pack(side="left")

        card = Card(self, app, padding=0)
        card.pack(fill="both", expand=True, padx=28, pady=(0, 10))
        cols = [
            {"key": "number", "title": "Number", "width": 120},
            {"key": "customer", "title": "Customer", "width": 240, "stretch": True},
            {"key": "date", "title": "Date", "width": 105},
            {"key": "due", "title": "Due" if self.is_invoice else "Valid until", "width": 105},
            {"key": "total", "title": "Total", "width": 130, "anchor": "e"},
        ]
        if self.is_invoice:
            cols += [{"key": "paid", "title": "Paid", "width": 120, "anchor": "e"},
                     {"key": "balance", "title": "Balance", "width": 120, "anchor": "e"}]
        cols.append({"key": "status", "title": "Status", "width": 120})
        self.table = DataTable(card, app, cols, height=16, status_key="status", on_double=lambda r: self.edit(r["id"]))
        self.table.pack(fill="both", expand=True, padx=2, pady=2)

        actions = tk.Frame(self, bg=p.bg)
        actions.pack(fill="x", padx=28, pady=(0, 24))
        self.summary = tk.Label(actions, text="", font=p.fonts["base"], bg=p.bg, fg=p.muted)
        self.summary.pack(side="left")
        right = tk.Frame(actions, bg=p.bg)
        right.pack(side="right")
        specs = [("Delete", self.delete, "danger-outline"), ("Print", self.print_selected, "secondary-outline"),
                 ("Export PDF", self.export_selected, "secondary-outline"), ("Duplicate", self.duplicate, "secondary-outline")]
        if self.is_invoice:
            specs += [("Mark as paid", self.mark_paid, "success-outline"), ("Record payment", self.record_payment, "success")]
        else:
            specs += [("Convert to invoice", self.convert, "success")]
        specs.append(("Edit", lambda: self.edit(), "primary"))
        for text, cmd, kind in specs:
            button(right, text, cmd, kind).pack(side="right", padx=(6, 0))

    # ------------------------------------------------------------------ list
    def clear_filters(self):
        self.search.clear()
        self.status.current(0)
        self.customer.set_id(None)
        self.date_from.set("")
        self.date_to.set("")
        self.refresh()

    def refresh(self, *_, action=None, doc_id=None, customer_id=None, **__):
        self.customer.set_options([(c["id"], c["name"]) for c in models.list_customers(self.app.db)])
        status = "" if self.status.get() == "All" else self.status.get()
        rows = models.list_documents(self.app.db, self.doc_type, self.search.get(), status, self.customer.get_id(),
                                     self.date_from.get(), self.date_to.get())

        def fmt(r):
            vals = [r["number"], r["customer_display"], fmt_day(self.app, r["date"]), fmt_day(self.app, r["due_date"]),
                    fmt_money(self.app, r["total"])]
            if self.is_invoice:
                vals += [fmt_money(self.app, r["paid"]), fmt_money(self.app, r["balance"])]
            return vals + [r["status"]]

        self.table.set_rows(rows, fmt)
        total = sum(float(r["total"] or 0) for r in rows)
        text = f"{len(rows)} {models.DOC_LABEL[self.doc_type].lower()}(s)   -   total {fmt_money(self.app, total)}"
        if self.is_invoice:
            text += f"   -   outstanding {fmt_money(self.app, sum(r['balance'] for r in rows if r['balance'] > 0))}"
        self.summary.configure(text=text)
        if rows:
            self.table.hide_empty()
        elif any((self.search.get(), status, self.customer.get_id(), self.date_from.get(), self.date_to.get())):
            self.table.show_empty("Nothing matches these filters", "", "Clear filters", self.clear_filters)
        else:
            label = models.DOC_LABEL[self.doc_type].lower()
            self.table.show_empty(f"No {label}s yet", f"Create your first {label} to get started.",
                                  f"Create {label}", self.new)
        if action == "new":
            self.after(50, lambda: self.new(customer_id=customer_id))
        elif action == "edit" and doc_id:
            self.after(50, lambda: self.edit(doc_id))

    def _selected(self):
        row = self.table.selected()
        if not row:
            show_info(self, f"Select a {models.DOC_LABEL[self.doc_type].lower()} first.", "No selection")
        return row

    # ------------------------------------------------------------------ actions
    def new(self, customer_id=None):
        if DocumentEditor(self, self.app, self.doc_type, customer_id=customer_id).show():
            self.app.refresh_all()

    def edit(self, doc_id=None):
        if doc_id is None:
            row = self._selected()
            if not row:
                return
            doc_id = row["id"]
        if DocumentEditor(self, self.app, self.doc_type, doc_id=doc_id).show():
            self.app.refresh_all()

    def duplicate(self):
        row = self._selected()
        if not row:
            return
        try:
            new_id = models.duplicate_document(self.app.db, row["id"])
        except models.ValidationError as e:
            show_error(self, str(e))
            return
        self.app.refresh_all()
        self.edit(new_id)

    def delete(self):
        row = self._selected()
        if not row:
            return
        extra = "\nAll payments recorded against it will be deleted too." if self.is_invoice and row["paid"] else ""
        if ask_yes_no(self, f"Delete {models.DOC_LABEL[self.doc_type].lower()} {row['number']}?{extra}\nThis cannot be undone.",
                      "Delete"):
            models.delete_document(self.app.db, row["id"])
            self.app.refresh_all()

    def export_selected(self):
        row = self._selected()
        if row:
            export_pdf(self, self.app, row["id"])

    def print_selected(self):
        row = self._selected()
        if row:
            print_pdf(self, self.app, row["id"])

    def record_payment(self):
        row = self._selected()
        if not row:
            return
        if row["balance"] <= 0.005 and not ask_yes_no(
                self, "This invoice is already fully paid. Record another payment anyway?", "Already paid"):
            return
        if PaymentDialog(self, self.app, row).show():
            self.app.refresh_all()

    def mark_paid(self):
        row = self._selected()
        if not row:
            return
        if row["balance"] <= 0.005:
            show_info(self, f"{row['number']} is already fully paid.", "Nothing to do")
            return
        methods = self.app.payment_methods()
        if ask_yes_no(self, f"Record a payment of {fmt_money(self.app, row['balance'])} for {row['number']} and mark it as paid?",
                      "Mark as paid"):
            try:
                models.mark_as_paid(self.app.db, row["id"], methods[0] if methods else "")
            except models.ValidationError as e:
                show_error(self, str(e))
                return
            self.app.refresh_all()

    def convert(self):
        row = self._selected()
        if not row:
            return
        if row["status"] == models.STATUS_CONVERTED and not ask_yes_no(
                self, f"{row['number']} was already converted. Create another invoice from it?", "Already converted"):
            return
        try:
            new_id = models.convert_quotation_to_invoice(self.app.db, row["id"])
        except models.ValidationError as e:
            show_error(self, str(e))
            return
        self.app.refresh_all()
        self.app.navigate("invoices", action="edit", doc_id=new_id)

    def export_csv(self):
        rows = models.list_documents(self.app.db, self.doc_type)
        if not rows:
            show_info(self, "There are no invoices to export.", "Nothing to export")
            return
        path = ask_save_path(self, "Export invoices", "invoices.csv", ".csv", [("CSV files", "*.csv")])
        if not path:
            return
        try:
            models.export_csv(path, ["Number", "Customer", "Date", "Due date", "Subtotal", "Discount", "Tax", "Total",
                                     "Paid", "Balance", "Status", "Currency"],
                              [[r["number"], r["customer_display"], r["date"], r["due_date"], r["subtotal"],
                                r["discount_amount"], r["tax_amount"], r["total"], r["paid"], r["balance"], r["status"],
                                r["currency"]] for r in rows])
        except OSError as e:
            show_error(self, f"Could not write the file:\n{e}")
            return
        show_info(self, f"Exported {len(rows)} invoice(s) to:\n{path}", "Export complete")
