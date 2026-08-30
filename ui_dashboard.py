"""Dashboard: greeting, quick actions, clickable KPI cards, and panels that follow the Settings > Dashboard controls.

Owners see money and profit; employees see counts. Everything here is driven by settings so the owner
can reshape it without code changes.
"""
from __future__ import annotations

import datetime as dt
import tkinter as tk

import models
from ui_common import Card, DataTable, PageHeader, button, fmt_day, fmt_money
from utils import fmt_number, mix, parse_int


def _greeting() -> str:
    h = dt.datetime.now().hour
    return "Good morning" if h < 12 else ("Good afternoon" if h < 17 else "Good evening")


class KpiCard(tk.Frame):
    """A KPI tile: colored accent strip, glyph chip, title, big value, sub-line; optionally clickable."""

    def __init__(self, master, app, glyph, title, color, on_click=None):
        p = app.palette
        super().__init__(master, bg=p.card, highlightbackground=p.border, highlightthickness=1, bd=0,
                         cursor="hand2" if on_click else "arrow")
        self.app, self.on_click, self.base = app, on_click, p.card
        strip = tk.Frame(self, bg=color, height=4)
        strip.pack(fill="x")
        body = tk.Frame(self, bg=p.card, padx=16, pady=14)
        body.pack(fill="both", expand=True)
        top = tk.Frame(body, bg=p.card)
        top.pack(fill="x")
        self.chip = tk.Label(top, text=glyph, font=(p.font, p.font_size + 4), bg=mix(color, p.card, 0.85), fg=color,
                             width=2, pady=2)
        self.chip.pack(side="left")
        tk.Label(top, text=title.upper(), font=p.fonts["small_bold"], bg=p.card, fg=p.muted, anchor="w").pack(
            side="left", padx=(10, 0))
        self.value = tk.Label(body, text="-", font=p.fonts["big"], bg=p.card, fg=p.fg, anchor="w")
        self.value.pack(fill="x", pady=(10, 0))
        self.sub = tk.Label(body, text="", font=p.fonts["small"], bg=p.card, fg=p.muted, anchor="w")
        self.sub.pack(fill="x", pady=(2, 0))
        self._kids = [self, body, top, self.value, self.sub]
        if on_click:
            for w in self._kids:
                w.bind("<Button-1>", lambda e: on_click())
                w.bind("<Enter>", lambda e: self._hover(True))
                w.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, on):
        c = self.app.palette.subtle if on else self.base
        for w in self._kids:
            try:
                w.configure(bg=c)
            except tk.TclError:
                pass

    def set(self, value, sub="", color=None):
        self.value.configure(text=value, fg=color or self.app.palette.fg)
        self.sub.configure(text=sub)


class DashboardPage(tk.Frame):
    name = "dashboard"

    def __init__(self, master, app):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app = app
        self.owner = app.is_owner
        self.cards: dict[str, KpiCard] = {}

        head = tk.Frame(self, bg=p.bg)
        head.pack(fill="x", padx=28, pady=(22, 6))
        left = tk.Frame(head, bg=p.bg)
        left.pack(side="left", fill="x", expand=True)
        who = (app.user or {}).get("full_name") or (app.user or {}).get("username") or ""
        tk.Label(left, text=f"{_greeting()}, {who}".rstrip(", "), font=p.fonts["title"], bg=p.bg, fg=p.fg,
                 anchor="w").pack(anchor="w")
        self.subtitle = tk.Label(left, text="", font=p.fonts["base"], bg=p.bg, fg=p.muted, anchor="w")
        self.subtitle.pack(anchor="w", pady=(2, 0))

        self.quick = tk.Frame(self, bg=p.bg)
        self.quick.pack(fill="x", padx=28, pady=(6, 4))
        self.kpi_area = tk.Frame(self, bg=p.bg)
        self.kpi_area.pack(fill="x", padx=28, pady=(6, 0))
        self.body = tk.Frame(self, bg=p.bg)
        self.body.pack(fill="both", expand=True, padx=28, pady=(14, 22))
        self.build()

    # ------------------------------------------------------------------ builders
    def _quotations_on(self) -> bool:
        return self.app.settings.get("enable_quotations", "1") == "1"

    def build(self):
        """(Re)build quick actions, KPI cards and panels from the current settings."""
        p, a = self.app.palette, self.app
        s = a.settings
        for w in list(self.quick.winfo_children()) + list(self.kpi_area.winfo_children()) + list(self.body.winfo_children()):
            w.destroy()
        self.cards.clear()

        if s.get("dashboard_quick_actions", "1") == "1":
            tk.Label(self.quick, text="QUICK ACTIONS", font=p.fonts["small_bold"], bg=p.bg, fg=p.muted).pack(side="left", padx=(0, 10))
            acts = [("+ New invoice", lambda: a.navigate("invoices", action="new"), "primary")]
            if self._quotations_on():
                acts.append(("+ New quotation", lambda: a.navigate("quotations", action="new"), "outline"))
            acts.append(("+ New customer", self.new_customer, "secondary-outline"))
            if self.owner:
                acts.append(("Receive stock", self.receive_stock, "success-outline"))
            else:
                acts.append(("Check stock", lambda: a.navigate("inventory"), "secondary-outline"))
            for text, cmd, kind in acts:
                button(self.quick, text, cmd, kind).pack(side="left", padx=(0, 8))

        self.kpi_specs = self._kpi_specs()
        self._rowfr = None
        for i, spec in enumerate(self.kpi_specs):
            col = i % 4
            if col == 0:
                rowfr = tk.Frame(self.kpi_area, bg=p.bg)
                rowfr.pack(fill="x", pady=(0 if i == 0 else 12, 0))
                for c in range(4):
                    rowfr.grid_columnconfigure(c, weight=1, uniform="kpi")
                self._rowfr = rowfr
            card = KpiCard(self._rowfr, a, spec["glyph"], spec["title"], spec["color"], spec.get("onclick"))
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 12, 0))
            self.cards[spec["key"]] = card

        show_best = self.owner and s.get("dashboard_show_best", "1") == "1"
        show_low = s.get("dashboard_show_low_stock", "1") == "1"
        show_act = s.get("dashboard_show_activity", "1") == "1"
        self.body.grid_columnconfigure(0, weight=3)
        self.body.grid_columnconfigure(1, weight=2)
        self.body.grid_rowconfigure(0, weight=3)
        self.body.grid_rowconfigure(1, weight=2)

        left = Card(self.body, a, padding=0)
        left.grid(row=0, column=0, rowspan=(1 if show_low else 2), sticky="nsew", padx=(0, 12), pady=(0, 12 if show_low else 0))
        h = tk.Frame(left, bg=p.card)
        h.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(h, text="Recent invoices", font=p.fonts["heading"], bg=p.card, fg=p.fg).pack(side="left")
        button(h, "View all", lambda: a.navigate("invoices"), "link").pack(side="right")
        self.recent = DataTable(left, a, [
            {"key": "number", "title": "Number", "width": 90},
            {"key": "customer", "title": "Customer", "width": 150, "stretch": True},
            {"key": "date", "title": "Date", "width": 90},
            {"key": "total", "title": "Total", "width": 105, "anchor": "e"},
            {"key": "balance", "title": "Balance", "width": 105, "anchor": "e"},
            {"key": "status", "title": "Status", "width": 100},
        ], height=7, status_key="status", on_double=lambda r: a.navigate("invoices", action="edit", doc_id=r["id"]))
        self.recent.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self.low_table = None
        if show_low:
            low = Card(self.body, a, padding=0)
            low.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
            h = tk.Frame(low, bg=p.card)
            h.pack(fill="x", padx=16, pady=(12, 6))
            tk.Label(h, text="Low stock", font=p.fonts["heading"], bg=p.card, fg=p.fg).pack(side="left")
            button(h, "Inventory", lambda: a.navigate("inventory"), "link").pack(side="right")
            self.low_table = DataTable(low, a, [
                {"key": "name", "title": "Product", "width": 220, "stretch": True},
                {"key": "stock", "title": "In stock", "width": 90, "anchor": "e"},
                {"key": "level", "title": "Alert at", "width": 90, "anchor": "e"},
            ], height=4)
            self.low_table.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self.best_table = None
        right_rows_used = 0
        if show_best:
            right = Card(self.body, a, padding=0)
            right.grid(row=0, column=1, sticky="nsew", pady=(0, 12 if show_act else 0))
            h = tk.Frame(right, bg=p.card)
            h.pack(fill="x", padx=16, pady=(12, 6))
            tk.Label(h, text="Best sellers", font=p.fonts["heading"], bg=p.card, fg=p.fg).pack(side="left")
            self.best_label = tk.Label(h, text="", font=p.fonts["small"], bg=p.card, fg=p.muted)
            self.best_label.pack(side="right")
            self.best_table = DataTable(right, a, [
                {"key": "name", "title": "Product", "width": 150, "stretch": True},
                {"key": "qty", "title": "Sold", "width": 55, "anchor": "e"},
                {"key": "revenue", "title": "Revenue", "width": 95, "anchor": "e"},
                {"key": "profit", "title": "Profit", "width": 90, "anchor": "e"},
            ], height=7)
            self.best_table.pack(fill="both", expand=True, padx=16, pady=(0, 12))
            right_rows_used = 1

        self.activity = None
        if show_act:
            act = Card(self.body, a, padding=0)
            act.grid(row=right_rows_used, column=1, rowspan=(2 - right_rows_used), sticky="nsew")
            tk.Label(act, text="Recent activity", font=p.fonts["heading"], bg=p.card, fg=p.fg, anchor="w").pack(
                fill="x", padx=16, pady=(12, 6))
            self.activity = tk.Frame(act, bg=p.card)
            self.activity.pack(fill="both", expand=True, padx=16, pady=(0, 12))

    def _kpi_specs(self):
        p, a = self.app.palette, self.app
        s = a.settings
        nav = a.navigate
        if self.owner:
            specs = [
                {"key": "outstanding", "glyph": "◆", "title": "Outstanding balance", "color": p.accent, "onclick": lambda: nav("invoices")},
                {"key": "paid", "glyph": "✔", "title": "Received", "color": p.success, "onclick": lambda: nav("payments")},
                {"key": "overdue", "glyph": "!", "title": "Overdue invoices", "color": p.danger, "onclick": lambda: nav("invoices")},
            ]
            if self._quotations_on():
                specs.append({"key": "open_quotations", "glyph": "✎", "title": "Open quotations", "color": p.info, "onclick": lambda: nav("quotations")})
            else:
                specs.append({"key": "invoiced", "glyph": "▤", "title": "Invoiced", "color": p.info, "onclick": lambda: nav("invoices")})
            if s.get("dashboard_show_profit", "1") == "1":
                specs.append({"key": "profit", "glyph": "▲", "title": "Gross profit", "color": p.success})
            specs += [
                {"key": "stock_value", "glyph": "▦", "title": "Stock value (cost)", "color": p.accent, "onclick": lambda: nav("inventory")},
                {"key": "low_stock", "glyph": "▽", "title": "Low stock items", "color": p.warning, "onclick": lambda: nav("inventory")},
                {"key": "purchases", "glyph": "⬇", "title": "Purchases", "color": p.info, "onclick": lambda: nav("inventory", tab="purchases")},
            ]
        else:
            specs = [{"key": "invoice_count", "glyph": "▤", "title": "Invoices", "color": p.accent, "onclick": lambda: nav("invoices")}]
            if self._quotations_on():
                specs.append({"key": "open_quotations", "glyph": "✎", "title": "Open quotations", "color": p.info, "onclick": lambda: nav("quotations")})
            specs += [
                {"key": "customers", "glyph": "☺", "title": "Customers", "color": p.success, "onclick": lambda: nav("customers")},
                {"key": "low_stock", "glyph": "▽", "title": "Low stock items", "color": p.warning, "onclick": lambda: nav("inventory")},
            ]
        return specs

    # ------------------------------------------------------------------ quick action helpers
    def new_customer(self):
        from ui_customers import CustomerDialog
        if CustomerDialog(self, self.app).show():
            self.app.refresh_all()

    def receive_stock(self):
        from ui_inventory import QuickStockInDialog
        if QuickStockInDialog(self, self.app).show():
            self.app.refresh_all()

    # ------------------------------------------------------------------ data
    def _set(self, key, value, sub="", color=None):
        if key in self.cards:
            self.cards[key].set(value, sub, color)

    def refresh(self, **_):
        a, p = self.app, self.app.palette
        period = a.settings.get("dashboard_period", "month")
        recent = parse_int(a.settings.get("dashboard_recent", "6"), 6) or 6
        st = models.dashboard_stats(a.db, period=period, recent=recent)
        pl = st["period_label"]
        self.subtitle.configure(text=f"{a.settings.get('company_name', '')}   -   {dt.date.today():%A, %d %B %Y}   -   "
                                     f"{'Owner' if self.owner else 'Employee'}")

        self._set("outstanding", fmt_money(a, st["outstanding"]), f"across {st['invoice_count']} invoice(s)")
        self._set("paid", fmt_money(a, st["paid_this_month"]), f"received {pl}", p.success)
        self._set("invoiced", fmt_money(a, st["invoiced_this_month"]), f"billed {pl}", p.info)
        self._set("overdue", str(st["overdue_count"]), f"{fmt_money(a, st['overdue_amount'])} overdue",
                  p.danger if st["overdue_count"] else None)
        self._set("open_quotations", str(st["open_quotations"]), "awaiting a decision",
                  p.accent if st["open_quotations"] else None)
        pm = st["profit_month"]
        self._set("profit", fmt_money(a, pm["profit"]), f"sales {fmt_money(a, pm['revenue'])} {pl}",
                  p.success if pm["profit"] >= 0 else p.danger)
        self._set("stock_value", fmt_money(a, st["stock_value"]), f"{st['product_count']} active product(s)")
        self._set("low_stock", str(st["low_stock_count"]), "at or below the alert level",
                  p.danger if st["low_stock_count"] else None)
        self._set("purchases", fmt_money(a, st["purchases_this_month"]), f"bought {pl}", p.info)
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

        if self.low_table is not None:
            low = st["low_stock"]
            self.low_table.set_rows(low, lambda r: [r["name"], fmt_number(r["stock"]),
                                                    fmt_number(r["low_stock_level"] or a.settings.get("low_stock_threshold") or 0)])
            self.low_table.hide_empty() if low else self.low_table.show_empty("Stock levels are fine", "")

        if self.best_table is not None:
            best = st["best_sellers"]
            self.best_label.configure(text=pl)
            for n, r in enumerate(best):
                r["id"] = f"b{n}"
            self.best_table.set_rows(best, lambda r: [r["name"], fmt_number(r["qty_sold"]), fmt_money(a, r["revenue"]),
                                                      fmt_money(a, r["profit"])])
            self.best_table.hide_empty() if best else self.best_table.show_empty("No sales yet", "")

        if self.activity is not None:
            for w in self.activity.winfo_children():
                w.destroy()
            entries = models.recent_activity(a.db, 8)
            if not entries:
                tk.Label(self.activity, text="Nothing has happened yet.", font=p.fonts["base"], bg=p.card,
                         fg=p.muted).pack(anchor="w", pady=8)
            for e in entries:
                row = tk.Frame(self.activity, bg=p.card)
                row.pack(fill="x", pady=2)
                dot = {"payment": p.success, "invoice": p.accent, "quotation": p.info, "customer": p.warning,
                       "purchase": p.info, "return": p.warning, "stock": p.muted, "user": p.muted}.get(e["kind"], p.muted)
                tk.Label(row, text=(e["ts"] or "")[:16], font=p.fonts["small"], bg=p.card, fg=p.muted).pack(side="right", padx=(8, 0))
                tk.Label(row, text="●", font=p.fonts["small"], bg=p.card, fg=dot).pack(side="left", padx=(0, 8))
                tk.Label(row, text=e["message"], font=p.fonts["base"], bg=p.card, fg=p.fg, anchor="w").pack(
                    side="left", fill="x", expand=True)
