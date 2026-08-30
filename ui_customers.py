"""Customers page: list, add/edit/delete, and a detail view with invoice history + running balance."""
from __future__ import annotations

import tkinter as tk

import models
from ui_common import (Card, DataTable, Dialog, Form, PageHeader, SearchEntry, ask_save_path, ask_yes_no, button,
                       fmt_day, fmt_money, show_error, show_info)


class CustomerDialog(Dialog):
    def __init__(self, parent, app, customer: dict | None = None):
        super().__init__(parent, app, "Edit customer" if customer else "New customer", width=720)
        self.customer = customer or {}
        c = self.customer
        f = Form(self.body, app, columns=2)
        self.form = f
        f.entry("Name *", "name", c.get("name", ""))
        f.entry("Company", "company", c.get("company", ""))
        f.entry("Phone", "phone", c.get("phone", ""))
        f.entry("Email", "email", c.get("email", ""))
        f.entry("Tax / VAT no.", "tax_number", c.get("tax_number", ""))
        f._next()  # keep layout balanced
        f.text("Billing address", "billing_address", c.get("billing_address", ""), height=3)
        f.text("Shipping address", "shipping_address", c.get("shipping_address", ""), height=3)
        f.text("Notes", "notes", c.get("notes", ""), span=2, height=2)
        self.buttons("Save customer", self.save)
        f.focus_first()

    def save(self):
        data = self.form.get()
        data["id"] = self.customer.get("id")
        try:
            self.result = models.save_customer(self.app.db, data)
        except models.ValidationError as e:
            show_error(self, str(e))
            return
        self.close()


class CustomerDetailDialog(Dialog):
    def __init__(self, parent, app, customer_id: int):
        self.customer_id = customer_id
        cust = models.get_customer(app.db, customer_id) or {}
        super().__init__(parent, app, cust.get("name", "Customer"), width=900, height=620)
        p = app.palette
        top = tk.Frame(self.body, bg=p.bg)
        top.pack(fill="x")
        info = Card(top, app)
        info.pack(side="left", fill="both", expand=True)
        tk.Label(info, text=cust.get("name", ""), font=p.fonts["title"], bg=p.card, fg=p.fg, anchor="w").pack(fill="x")
        lines = [cust.get("company"), cust.get("billing_address"),
                 "  |  ".join(x for x in (cust.get("phone"), cust.get("email")) if x),
                 f"Tax No: {cust['tax_number']}" if cust.get("tax_number") else ""]
        for ln in lines:
            if ln:
                tk.Label(info, text=ln, font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="w", justify="left").pack(fill="x")
        bal = Card(top, app)
        bal.pack(side="left", fill="y", padx=(12, 0))
        tk.Label(bal, text="RUNNING BALANCE", font=p.fonts["small_bold"], bg=p.card, fg=p.muted).pack(anchor="w")
        balance = cust.get("balance", 0) or 0
        tk.Label(bal, text=fmt_money(app, balance), font=p.fonts["big"], bg=p.card,
                 fg=p.danger if balance > 0 else p.success).pack(anchor="w", pady=(4, 0))
        tk.Label(bal, text="owed to you" if balance > 0 else "settled", font=p.fonts["small"], bg=p.card,
                 fg=p.muted).pack(anchor="w")

        docs_card = Card(self.body, app, padding=0)
        docs_card.pack(fill="both", expand=True, pady=(12, 0))
        head = tk.Frame(docs_card, bg=p.card)
        head.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(head, text="Invoices & quotations", font=p.fonts["heading"], bg=p.card, fg=p.fg).pack(side="left")
        button(head, "+ New invoice", self.new_invoice, "primary").pack(side="right")
        self.table = DataTable(docs_card, app, [
            {"key": "type", "title": "Type", "width": 90},
            {"key": "number", "title": "Number", "width": 110},
            {"key": "date", "title": "Date", "width": 100},
            {"key": "due", "title": "Due / Valid", "width": 100},
            {"key": "total", "title": "Total", "width": 120, "anchor": "e"},
            {"key": "paid", "title": "Paid", "width": 110, "anchor": "e"},
            {"key": "balance", "title": "Balance", "width": 110, "anchor": "e"},
            {"key": "status", "title": "Status", "width": 110},
        ], height=12, status_key="status", on_double=self.open_doc)
        self.table.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        rows = models.list_documents(app.db, models.INVOICE, customer_id=customer_id) + \
            models.list_documents(app.db, models.QUOTATION, customer_id=customer_id)
        rows.sort(key=lambda r: (r["date"], r["id"]), reverse=True)
        self.table.set_rows(rows, lambda r: [models.DOC_LABEL[r["doc_type"]], r["number"], fmt_day(app, r["date"]),
                                             fmt_day(app, r["due_date"]), fmt_money(app, r["total"]),
                                             fmt_money(app, r["paid"]) if r["doc_type"] == "invoice" else "",
                                             fmt_money(app, r["balance"]) if r["doc_type"] == "invoice" else "",
                                             r["status"]])
        if not rows:
            self.table.show_empty("No documents yet", "This customer has no invoices or quotations.",
                                  "Create invoice", self.new_invoice)
        self.buttons("Open selected", lambda: self.open_doc(self.table.selected()), cancel_text="Close")

    def open_doc(self, row):
        if not row:
            return
        page = "invoices" if row["doc_type"] == "invoice" else "quotations"
        self.close()
        self.app.navigate(page, action="edit", doc_id=row["id"])

    def new_invoice(self):
        self.close()
        self.app.navigate("invoices", action="new", customer_id=self.customer_id)


class CustomersPage(tk.Frame):
    name = "customers"

    def __init__(self, master, app):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app = app
        self.header = PageHeader(self, app, "Customers", "People and companies you invoice")
        self.header.pack(fill="x", padx=28, pady=(24, 12))
        self.header.button("Export CSV", self.export_csv, "secondary-outline")
        self.header.button("+ Add customer", self.add, "primary")

        bar = tk.Frame(self, bg=p.bg)
        bar.pack(fill="x", padx=28, pady=(0, 10))
        self.search = SearchEntry(bar, app, "Search name, company, phone, email...", self.refresh, width=40)
        self.search.pack(side="left")
        actions = tk.Frame(bar, bg=p.bg)
        actions.pack(side="right")
        button(actions, "View", self.view, "outline").pack(side="left", padx=(0, 6))
        button(actions, "Edit", self.edit, "secondary-outline").pack(side="left", padx=(0, 6))
        button(actions, "Delete", self.delete, "danger-outline").pack(side="left")

        card = Card(self, app, padding=0)
        card.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        self.table = DataTable(card, app, [
            {"key": "name", "title": "Name", "width": 200},
            {"key": "company", "title": "Company", "width": 200, "stretch": True},
            {"key": "phone", "title": "Phone", "width": 130},
            {"key": "email", "title": "Email", "width": 200},
            {"key": "invoices", "title": "Invoices", "width": 80, "anchor": "e"},
            {"key": "balance", "title": "Balance", "width": 130, "anchor": "e"},
        ], height=18, on_double=lambda r: self.view())
        self.table.pack(fill="both", expand=True, padx=2, pady=2)

    def refresh(self, *_, **__):
        rows = models.list_customers(self.app.db, self.search.get())
        self.table.set_rows(rows, lambda r: [r["name"], r["company"], r["phone"], r["email"], r["invoice_count"],
                                             fmt_money(self.app, r["balance"])])
        if rows:
            self.table.hide_empty()
        elif self.search.get():
            self.table.show_empty("No customers match your search")
        else:
            self.table.show_empty("No customers yet", "Add the people and companies you send invoices to.",
                                  "Add customer", self.add)

    def _selected(self):
        row = self.table.selected()
        if not row:
            show_info(self, "Select a customer first.", "No selection")
        return row

    def add(self):
        if CustomerDialog(self, self.app).show():
            self.app.refresh_all()

    def edit(self):
        row = self._selected()
        if row and CustomerDialog(self, self.app, row).show():
            self.app.refresh_all()

    def view(self):
        row = self._selected()
        if row:
            CustomerDetailDialog(self, self.app, row["id"]).show()
            self.app.refresh_all()

    def delete(self):
        row = self._selected()
        if not row:
            return
        if not ask_yes_no(self, f"Delete customer '{row['name']}'? This cannot be undone.", "Delete customer"):
            return
        try:
            models.delete_customer(self.app.db, row["id"])
        except models.ValidationError as e:
            show_error(self, str(e), "Cannot delete")
            return
        self.app.refresh_all()

    def export_csv(self):
        rows = models.list_customers(self.app.db)
        if not rows:
            show_info(self, "There are no customers to export.", "Nothing to export")
            return
        path = ask_save_path(self, "Export customers", "customers.csv", ".csv", [("CSV files", "*.csv")])
        if not path:
            return
        try:
            models.export_csv(path, ["Name", "Company", "Billing address", "Shipping address", "Phone", "Email",
                                     "Tax number", "Invoices", "Balance", "Notes"],
                              [[r["name"], r["company"], r["billing_address"], r["shipping_address"], r["phone"],
                                r["email"], r["tax_number"], r["invoice_count"], r["balance"], r["notes"]] for r in rows])
        except OSError as e:
            show_error(self, f"Could not write the file:\n{e}")
            return
        show_info(self, f"Exported {len(rows)} customer(s) to:\n{path}", "Export complete")
