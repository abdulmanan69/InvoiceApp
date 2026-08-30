"""Payments: record-payment dialog and the global payments log page."""
from __future__ import annotations

import tkinter as tk

import ttkbootstrap as tb

import models
from ui_common import (Card, DataTable, DateField, Dialog, IdCombo, PageHeader, SearchEntry, ask_save_path,
                       ask_yes_no, button, fmt_day, fmt_money, show_error, show_info)
from utils import fmt_number, today_iso


class PaymentDialog(Dialog):
    """Record a payment against one invoice. Validates against the remaining balance (override with confirmation)."""

    def __init__(self, parent, app, invoice: dict):
        super().__init__(parent, app, f"Record payment - {invoice['number']}", width=560)
        self.invoice = invoice
        p = app.palette
        remaining = float(invoice.get("balance") or 0)
        head = Card(self.body, app, padding=14)
        head.pack(fill="x", pady=(0, 14))
        tk.Label(head, text=invoice.get("customer_display", ""), font=p.fonts["heading"], bg=p.card, fg=p.fg,
                 anchor="w").pack(fill="x")
        tk.Label(head, text=f"Invoice total {fmt_money(app, invoice['total'])}   |   Paid {fmt_money(app, invoice['paid'])}"
                            f"   |   Remaining {fmt_money(app, remaining)}",
                 font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="w").pack(fill="x", pady=(4, 0))
        form = tk.Frame(self.body, bg=p.bg)
        form.pack(fill="x")
        form.grid_columnconfigure(1, weight=1)
        self.amount = tk.StringVar(value=fmt_number(max(remaining, 0)))
        self.method = tk.StringVar(value=(app.payment_methods() or [""])[0])
        self.reference = tk.StringVar()
        labels = ("Amount *", "Date *", "Method", "Reference / note")
        self.date = DateField(form, app, today_iso())
        widgets = (tb.Entry(form, textvariable=self.amount), self.date,
                   tb.Combobox(form, textvariable=self.method, values=app.payment_methods(), state="readonly"),
                   tb.Entry(form, textvariable=self.reference))
        for r, (lbl, w) in enumerate(zip(labels, widgets)):
            tk.Label(form, text=lbl, font=p.fonts["base"], bg=p.bg, fg=p.muted, anchor="e", width=16).grid(
                row=r, column=0, sticky="e", padx=(0, 8), pady=6)
            w.grid(row=r, column=1, sticky="ew", pady=6)
        self.buttons("Record payment", self.save)
        widgets[0].focus_set()
        widgets[0].select_range(0, "end")

    def save(self):
        allow = False
        while True:
            try:
                self.result = models.add_payment(self.app.db, self.invoice["id"], self.amount.get(), self.date.get(),
                                                 self.method.get(), self.reference.get(), allow_overpay=allow)
                break
            except models.OverpaymentError as e:
                if ask_yes_no(self, f"{e}\n\nRecord it anyway as an overpayment / credit?", "Overpayment"):
                    allow = True
                    continue
                return
            except models.ValidationError as e:
                show_error(self, str(e))
                return
        self.close()


class PaymentsPage(tk.Frame):
    name = "payments"

    def __init__(self, master, app):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app = app
        self.header = PageHeader(self, app, "Payments", "Every payment recorded against an invoice")
        self.header.pack(fill="x", padx=28, pady=(24, 12))
        self.header.button("Export CSV", self.export_csv, "secondary-outline")

        bar = tk.Frame(self, bg=p.bg)
        bar.pack(fill="x", padx=28, pady=(0, 10))
        self.search = SearchEntry(bar, app, "Search invoice, customer, reference...", self.refresh, width=26)
        self.search.pack(side="left")

        def lbl(text):
            tk.Label(bar, text=text, font=p.fonts["base"], bg=p.bg, fg=p.muted).pack(side="left", padx=(14, 4))

        lbl("Method")
        self.method = tb.Combobox(bar, values=["All"], state="readonly", width=16)
        self.method.current(0)
        self.method.pack(side="left")
        self.method.bind("<<ComboboxSelected>>", self.refresh)
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
        card.pack(fill="both", expand=True, padx=28, pady=(0, 12))
        self.table = DataTable(card, app, [
            {"key": "date", "title": "Date", "width": 110},
            {"key": "invoice", "title": "Invoice", "width": 120},
            {"key": "customer", "title": "Customer", "width": 240, "stretch": True},
            {"key": "method", "title": "Method", "width": 150},
            {"key": "reference", "title": "Reference", "width": 220},
            {"key": "amount", "title": "Amount", "width": 140, "anchor": "e"},
        ], height=18, on_double=self.open_invoice)
        self.table.pack(fill="both", expand=True, padx=2, pady=2)

        foot = tk.Frame(self, bg=p.bg)
        foot.pack(fill="x", padx=28, pady=(0, 24))
        self.total_label = tk.Label(foot, text="", font=p.fonts["heading"], bg=p.bg, fg=p.fg)
        self.total_label.pack(side="left")
        button(foot, "Delete payment", self.delete, "danger-outline").pack(side="right")
        button(foot, "Open invoice", lambda: self.open_invoice(self.table.selected()), "outline").pack(side="right", padx=(0, 8))

    def clear_filters(self):
        self.search.clear()
        self.method.current(0)
        self.customer.set_id(None)
        self.date_from.set("")
        self.date_to.set("")
        self.refresh()

    def refresh(self, *_, **__):
        methods = ["All"] + self.app.payment_methods()
        current = self.method.get()
        self.method.configure(values=methods)
        self.method.set(current if current in methods else "All")
        self.customer.set_options([(c["id"], c["name"]) for c in models.list_customers(self.app.db)])
        method = "" if self.method.get() == "All" else self.method.get()
        rows = models.list_payments(self.app.db, method=method, customer_id=self.customer.get_id(),
                                    date_from=self.date_from.get(), date_to=self.date_to.get(), search=self.search.get())
        self.table.set_rows(rows, lambda r: [fmt_day(self.app, r["date"]), r["invoice_number"], r["customer_display"],
                                             r["method"], r["reference"], fmt_money(self.app, r["amount"])])
        total = sum(float(r["amount"] or 0) for r in rows)
        self.total_label.configure(text=f"{len(rows)} payment(s)   -   {fmt_money(self.app, total)}")
        if rows:
            self.table.hide_empty()
        else:
            self.table.show_empty("No payments recorded", "Payments you record on invoices will be listed here.",
                                  "Go to invoices", lambda: self.app.navigate("invoices"))

    def open_invoice(self, row):
        if row:
            self.app.navigate("invoices", action="edit", doc_id=row["invoice_id"])

    def delete(self):
        row = self.table.selected()
        if not row:
            show_info(self, "Select a payment first.", "No selection")
            return
        if ask_yes_no(self, f"Delete this payment of {fmt_money(self.app, row['amount'])} on {row['invoice_number']}?\n"
                            "The invoice balance will go back up.", "Delete payment"):
            models.delete_payment(self.app.db, row["id"])
            self.app.refresh_all()

    def export_csv(self):
        rows = models.list_payments(self.app.db)
        if not rows:
            show_info(self, "There are no payments to export.", "Nothing to export")
            return
        path = ask_save_path(self, "Export payments", "payments.csv", ".csv", [("CSV files", "*.csv")])
        if not path:
            return
        try:
            models.export_csv(path, ["Date", "Invoice", "Customer", "Method", "Reference", "Amount"],
                              [[r["date"], r["invoice_number"], r["customer_display"], r["method"], r["reference"],
                                r["amount"]] for r in rows])
        except OSError as e:
            show_error(self, f"Could not write the file:\n{e}")
            return
        show_info(self, f"Exported {len(rows)} payment(s) to:\n{path}", "Export complete")
