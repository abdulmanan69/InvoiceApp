"""Dashboard page: KPI cards (money for owners, counts for employees), recent invoices, stock alerts, best sellers."""
from __future__ import annotations

import tkinter as tk

import models
from ui_common import Card, DataTable, PageHeader, button, fmt_day, fmt_money
from utils import fmt_number


class DashboardPage(tk.Frame):
    name = "dashboard"

    def __init__(self, master, app):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app = app
        self.owner = app.is_owner
        self.header = PageHeader(self, app, "Dashboard", "")
        self.header.pack(fill="x", padx=28, pady=(24, 12))
        self.header.button("+ New Invoice", lambda: app.navigate("invoices", action="new"), "primary")
        self.header.button("+ New Quotation", lambda: app.navigate("quotations", action="new"), "outline")

        self.kpis: dict[str, tuple[tk.Label, tk.Label]] = {}
        if self.owner:
            rows = [(("outstanding", "Outstanding balance"), ("paid_this_month", "Paid this month"),
                     ("overdue", "Overdue invoices"), ("open_quotations", "Open quotations")),
                    (("profit", "Gross profit this month"), ("stock_value", "Stock value (at cost)"),
                     ("low_stock", "Low stock items"), ("purchases", "Purchases this month"))]
        else:
            rows = [(("invoice_count", "Invoices"), ("open_quotations", "Open quotations"),
                     ("customers", "Customers"), ("low_stock", "Low stock items"))]
        for ri, row in enumerate(rows):
            fr = tk.Frame(self, bg=p.bg)
            fr.pack(fill="x", padx=28, pady=(0 if ri == 0 else 12, 0))
            for i, (key, title) in enumerate(row):
                fr.grid_columnconfigure(i, weight=1, uniform="kpi")
                card = Card(fr, app, padding=16)
                card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 12, 0))
                tk.Label(card, text=title.upper(), font=p.fonts["small_bold"], bg=p.card, fg=p.muted, anchor="w").pack(fill="x")
                value = tk.Label(card, text="-", font=p.fonts["big"], bg=p.card, fg=p.fg, anchor="w")
                value.pack(fill="x", pady=(4, 0))
                sub = tk.Label(card, text="", font=p.fonts["small"], bg=p.card, fg=p.muted, anchor="w")
                sub.pack(fill="x", pady=(2, 0))
                self.kpis[key] = (value, sub)

        body = tk.Frame(self, bg=p.bg)
        body.pack(fill="both", expand=True, padx=28, pady=(16, 24))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=3)
        body.grid_rowconfigure(1, weight=2)

        left = Card(body, app, padding=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(0, 12))
        head = tk.Frame(left, bg=p.card)
        head.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(head, text="Recent invoices", font=p.fonts["heading"], bg=p.card, fg=p.fg).pack(side="left")
        button(head, "View all", lambda: app.navigate("invoices"), "link").pack(side="right")
        self.recent = DataTable(left, app, [
            {"key": "number", "title": "Number", "width": 90},
            {"key": "customer", "title": "Customer", "width": 150, "stretch": True},
            {"key": "date", "title": "Date", "width": 90},
            {"key": "total", "title": "Total", "width": 105, "anchor": "e"},
            {"key": "balance", "title": "Balance", "width": 105, "anchor": "e"},
            {"key": "status", "title": "Status", "width": 100},
        ], height=6, status_key="status", on_double=lambda r: app.navigate("invoices", action="edit", doc_id=r["id"]))
        self.recent.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        low = Card(body, app, padding=0)
        low.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        head = tk.Frame(low, bg=p.card)
        head.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(head, text="Low stock", font=p.fonts["heading"], bg=p.card, fg=p.fg).pack(side="left")
        button(head, "Inventory", lambda: app.navigate("inventory"), "link").pack(side="right")
        self.low_table = DataTable(low, app, [
            {"key": "name", "title": "Product", "width": 220, "stretch": True},
            {"key": "stock", "title": "In stock", "width": 90, "anchor": "e"},
            {"key": "level", "title": "Alert at", "width": 90, "anchor": "e"},
        ], height=4)
        self.low_table.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        right = Card(body, app, padding=0)
        right.grid(row=0, column=1, sticky="nsew", pady=(0, 12))
        head = tk.Frame(right, bg=p.card)
        head.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(head, text="Best sellers" if self.owner else "Top products", font=p.fonts["heading"], bg=p.card, fg=p.fg).pack(side="left")
        cols = [{"key": "name", "title": "Product", "width": 140, "stretch": True},
                {"key": "qty", "title": "Sold", "width": 55, "anchor": "e"}]
        if self.owner:
            cols += [{"key": "revenue", "title": "Revenue", "width": 95, "anchor": "e"},
                     {"key": "profit", "title": "Profit", "width": 90, "anchor": "e"}]
        self.best_table = DataTable(right, app, cols, height=6)
        self.best_table.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        act = Card(body, app, padding=0)
        act.grid(row=1, column=1, sticky="nsew")
        tk.Label(act, text="Recent activity", font=p.fonts["heading"], bg=p.card, fg=p.fg, anchor="w").pack(fill="x", padx=16, pady=(12, 6))
        self.activity = tk.Frame(act, bg=p.card)
        self.activity.pack(fill="both", expand=True, padx=16, pady=(0, 12))

    # ------------------------------------------------------------------ data
    def _set(self, key, value, sub="", color=None):
        if key not in self.kpis:
            return
        v, s = self.kpis[key]
        v.configure(text=value, fg=color or self.app.palette.fg)
        s.configure(text=sub)

    def refresh(self, **_):
        a, p = self.app, self.app.palette
        st = models.dashboard_stats(a.db)
        self.header.set_subtitle(f"{a.settings.get('company_name', '')}  |  {st['invoice_count']} invoices  |  "
                                 f"{st['customer_count']} customers  |  {st['product_count']} products")
        self._set("outstanding", fmt_money(a, st["outstanding"]), f"across {st['invoice_count']} invoice(s)")
        self._set("paid_this_month", fmt_money(a, st["paid_this_month"]), f"invoiced this month: {fmt_money(a, st['invoiced_this_month'])}", p.success)
        self._set("overdue", str(st["overdue_count"]), f"{fmt_money(a, st['overdue_amount'])} overdue", p.danger if st["overdue_count"] else None)
        self._set("open_quotations", str(st["open_quotations"]), "awaiting a decision", p.accent if st["open_quotations"] else None)
        pm = st["profit_month"]
        self._set("profit", fmt_money(a, pm["profit"]), f"sales {fmt_money(a, pm['revenue'])}  -  cost {fmt_money(a, pm['cost'])}",
                  p.success if pm["profit"] >= 0 else p.danger)
        self._set("stock_value", fmt_money(a, st["stock_value"]), f"{st['product_count']} active product(s)")
        self._set("low_stock", str(st["low_stock_count"]), "at or below the alert level", p.danger if st["low_stock_count"] else None)
        self._set("purchases", fmt_money(a, st["purchases_this_month"]), f"customer returns: {fmt_money(a, st['returns_this_month'])}")
        self._set("invoice_count", str(st["invoice_count"]), f"{st['overdue_count']} overdue")
        self._set("customers", str(st["customer_count"]), "in your address book")

        rows = st["recent_invoices"]
        self.recent.set_rows(rows, lambda r: [r["number"], r["customer_display"], fmt_day(a, r["date"]),
                                              fmt_money(a, r["total"]), fmt_money(a, r["balance"]), r["status"]])
        if rows:
            self.recent.hide_empty()
        else:
            self.recent.show_empty("No invoices yet", "Create your first invoice to see it here.", "Create invoice",
                                   lambda: a.navigate("invoices", action="new"))

        low = st["low_stock"]
        self.low_table.set_rows(low, lambda r: [r["name"], fmt_number(r["stock"]),
                                                fmt_number(r["low_stock_level"] or a.settings.get("low_stock_threshold") or 0)])
        if low:
            self.low_table.hide_empty()
        else:
            self.low_table.show_empty("Stock levels are fine", "")

        best = st["best_sellers"]
        for n, r in enumerate(best):
            r["id"] = f"b{n}"
        self.best_table.set_rows(best, lambda r: [r["name"], fmt_number(r["qty_sold"])] +
                                 ([fmt_money(a, r["revenue"]), fmt_money(a, r["profit"])] if self.owner else []))
        if best:
            self.best_table.hide_empty()
        else:
            self.best_table.show_empty("No sales yet", "")

        for w in self.activity.winfo_children():
            w.destroy()
        entries = models.recent_activity(a.db, 8)
        if not entries:
            tk.Label(self.activity, text="Nothing has happened yet.", font=p.fonts["base"], bg=p.card, fg=p.muted).pack(anchor="w", pady=8)
            return
        for e in entries:
            row = tk.Frame(self.activity, bg=p.card)
            row.pack(fill="x", pady=2)
            dot = {"payment": p.success, "invoice": p.accent, "quotation": p.info, "customer": p.warning,
                   "purchase": p.info, "return": p.warning, "stock": p.muted, "user": p.muted}.get(e["kind"], p.muted)
            tk.Label(row, text=(e["ts"] or "")[:16], font=p.fonts["small"], bg=p.card, fg=p.muted).pack(side="right", padx=(8, 0))
            tk.Label(row, text="●", font=p.fonts["small"], bg=p.card, fg=dot).pack(side="left", padx=(0, 8))
            tk.Label(row, text=e["message"], font=p.fonts["base"], bg=p.card, fg=p.fg, anchor="w").pack(side="left", fill="x", expand=True)
