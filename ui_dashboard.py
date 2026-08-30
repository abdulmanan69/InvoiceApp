"""Dashboard page: KPI cards, recent invoices, recent activity."""
from __future__ import annotations

import tkinter as tk

import models
from ui_common import Card, DataTable, PageHeader, button, fmt_day, fmt_money


class DashboardPage(tk.Frame):
    name = "dashboard"

    def __init__(self, master, app):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app = app
        self.header = PageHeader(self, app, "Dashboard", "")
        self.header.pack(fill="x", padx=28, pady=(24, 12))
        self.header.button("+ New Invoice", lambda: app.navigate("invoices", action="new"), "primary")
        self.header.button("+ New Quotation", lambda: app.navigate("quotations", action="new"), "outline")

        self.kpi_row = tk.Frame(self, bg=p.bg)
        self.kpi_row.pack(fill="x", padx=28)
        self.kpis: dict[str, tuple[tk.Label, tk.Label]] = {}
        for i, (key, title) in enumerate((("outstanding", "Outstanding balance"), ("paid_this_month", "Paid this month"),
                                          ("overdue", "Overdue invoices"), ("open_quotations", "Open quotations"))):
            self.kpi_row.grid_columnconfigure(i, weight=1, uniform="kpi")
            card = Card(self.kpi_row, app, padding=18)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 12, 0))
            tk.Label(card, text=title.upper(), font=p.fonts["small_bold"], bg=p.card, fg=p.muted, anchor="w").pack(fill="x")
            value = tk.Label(card, text="-", font=p.fonts["big"], bg=p.card, fg=p.fg, anchor="w")
            value.pack(fill="x", pady=(6, 0))
            sub = tk.Label(card, text="", font=p.fonts["small"], bg=p.card, fg=p.muted, anchor="w")
            sub.pack(fill="x", pady=(2, 0))
            self.kpis[key] = (value, sub)

        body = tk.Frame(self, bg=p.bg)
        body.pack(fill="both", expand=True, padx=28, pady=(16, 24))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        left = Card(body, app, padding=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        head = tk.Frame(left, bg=p.card)
        head.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(head, text="Recent invoices", font=p.fonts["heading"], bg=p.card, fg=p.fg).pack(side="left")
        button(head, "View all", lambda: app.navigate("invoices"), "link").pack(side="right")
        self.recent = DataTable(left, app, [
            {"key": "number", "title": "Number", "width": 90},
            {"key": "customer", "title": "Customer", "width": 150, "stretch": True},
            {"key": "date", "title": "Date", "width": 90},
            {"key": "total", "title": "Total", "width": 105, "anchor": "e"},
            {"key": "balance", "title": "Balance", "width": 105, "anchor": "e"},
            {"key": "status", "title": "Status", "width": 100},
        ], height=8, status_key="status", on_double=lambda r: app.navigate("invoices", action="edit", doc_id=r["id"]))
        self.recent.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        right = Card(body, app, padding=0)
        right.grid(row=0, column=1, sticky="nsew")
        tk.Label(right, text="Recent activity", font=p.fonts["heading"], bg=p.card, fg=p.fg, anchor="w").pack(
            fill="x", padx=16, pady=(14, 8))
        self.activity = tk.Frame(right, bg=p.card)
        self.activity.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    # ------------------------------------------------------------------ data
    def refresh(self, **_):
        p = self.app.palette
        stats = models.dashboard_stats(self.app.db)
        self.header.set_subtitle(
            f"{self.app.settings.get('company_name', '')}  |  {stats['invoice_count']} invoices  |  "
            f"{stats['customer_count']} customers")
        v, s = self.kpis["outstanding"]
        v.configure(text=fmt_money(self.app, stats["outstanding"]), fg=p.fg)
        s.configure(text=f"across {stats['invoice_count']} invoice(s)")
        v, s = self.kpis["paid_this_month"]
        v.configure(text=fmt_money(self.app, stats["paid_this_month"]), fg=p.success)
        s.configure(text=f"invoiced this month: {fmt_money(self.app, stats['invoiced_this_month'])}")
        v, s = self.kpis["overdue"]
        v.configure(text=str(stats["overdue_count"]), fg=p.danger if stats["overdue_count"] else p.fg)
        s.configure(text=f"{fmt_money(self.app, stats['overdue_amount'])} overdue")
        v, s = self.kpis["open_quotations"]
        v.configure(text=str(stats["open_quotations"]), fg=p.accent if stats["open_quotations"] else p.fg)
        s.configure(text="awaiting a decision")

        rows = stats["recent_invoices"]
        self.recent.set_rows(rows, lambda r: [r["number"], r["customer_display"], fmt_day(self.app, r["date"]),
                                              fmt_money(self.app, r["total"]), fmt_money(self.app, r["balance"]),
                                              r["status"]])
        if rows:
            self.recent.hide_empty()
        else:
            self.recent.show_empty("No invoices yet", "Create your first invoice to see it here.",
                                   "Create invoice", lambda: self.app.navigate("invoices", action="new"))

        for w in self.activity.winfo_children():
            w.destroy()
        entries = models.recent_activity(self.app.db, 10)
        if not entries:
            tk.Label(self.activity, text="Nothing has happened yet.\nActivity will appear here as you work.",
                     font=p.fonts["base"], bg=p.card, fg=p.muted, justify="left").pack(anchor="w", pady=8)
            return
        for e in entries:
            row = tk.Frame(self.activity, bg=p.card)
            row.pack(fill="x", pady=3)
            dot_color = {"payment": p.success, "invoice": p.accent, "quotation": p.info, "customer": p.warning}.get(
                e["kind"], p.muted)
            tk.Label(row, text=(e["ts"] or "")[:16], font=p.fonts["small"], bg=p.card, fg=p.muted).pack(
                side="right", padx=(8, 0))
            tk.Label(row, text="●", font=p.fonts["small"], bg=p.card, fg=dot_color).pack(side="left", padx=(0, 8))
            msg = tk.Label(row, text=e["message"], font=p.fonts["base"], bg=p.card, fg=p.fg, anchor="w")
            msg.pack(side="left", fill="x", expand=True)
