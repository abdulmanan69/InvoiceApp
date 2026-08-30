"""InvoiceApp entry point: window, sidebar navigation, theme application, global error handling."""
from __future__ import annotations

import json
import os
import sys
import tkinter as tk
import traceback

import ttkbootstrap as tb

import models
from db import DEFAULT_SETTINGS, Database
from theme import apply_theme, build_palette
from utils import data_dir, now_stamp

APP_VERSION = "1.0.0"

NAV_ITEMS = [
    ("dashboard", "⌂", "Dashboard"),
    ("invoices", "▤", "Invoices"),
    ("quotations", "✎", "Quotations"),
    ("customers", "☺", "Customers"),
    ("vendors", "⚒", "Vendors"),
    ("products", "▦", "Products & Services"),
    ("payments", "¤", "Payments"),
    ("settings", "⚙", "Settings"),
]


def log_error(exc_type, exc, tb_obj) -> str:
    """Append a traceback to data/error.log and return the formatted text."""
    text = "".join(traceback.format_exception(exc_type, exc, tb_obj))
    try:
        with open(os.path.join(data_dir(), "error.log"), "a", encoding="utf-8") as fh:
            fh.write(f"\n[{now_stamp()}]\n{text}")
    except Exception:
        pass
    return text


class Sidebar(tk.Frame):
    def __init__(self, master, app):
        p = app.palette
        super().__init__(master, bg=p.sidebar_bg, width=232)
        self.app = app
        self.pack_propagate(False)
        self.items: dict[str, tuple[tk.Frame, tk.Label, tk.Label, tk.Frame]] = {}
        self.active = None

        brand = tk.Frame(self, bg=p.sidebar_bg)
        brand.pack(fill="x", padx=20, pady=(26, 18))
        name = app.settings.get("company_name") or "InvoiceApp"
        tk.Label(brand, text=name, font=p.fonts["heading"], bg=p.sidebar_bg, fg=p.on(p.sidebar_bg), anchor="w",
                 wraplength=190, justify="left").pack(fill="x")
        tk.Label(brand, text="Invoices - Quotations - Payments", font=p.fonts["small"], bg=p.sidebar_bg,
                 fg=p.sidebar_fg, anchor="w").pack(fill="x", pady=(2, 0))
        tk.Frame(self, bg=p.sidebar_hover, height=1).pack(fill="x", padx=16, pady=(0, 10))

        for key, icon, label in NAV_ITEMS:
            row = tk.Frame(self, bg=p.sidebar_bg, cursor="hand2")
            row.pack(fill="x", padx=10, pady=2)
            bar = tk.Frame(row, bg=p.sidebar_bg, width=3)
            bar.pack(side="left", fill="y")
            ic = tk.Label(row, text=icon, font=(p.font, p.font_size + 2), bg=p.sidebar_bg, fg=p.sidebar_fg, width=3)
            ic.pack(side="left", padx=(6, 4), pady=8)
            lb = tk.Label(row, text=label, font=p.fonts["base"], bg=p.sidebar_bg, fg=p.sidebar_fg, anchor="w")
            lb.pack(side="left", fill="x", expand=True, pady=8)
            for w in (row, bar, ic, lb):
                w.bind("<Button-1>", lambda e, k=key: app.navigate(k))
                w.bind("<Enter>", lambda e, k=key: self._hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._hover(k, False))
            self.items[key] = (row, ic, lb, bar)

        foot = tk.Frame(self, bg=p.sidebar_bg)
        foot.pack(side="bottom", fill="x", padx=20, pady=16)
        tk.Label(foot, text=f"InvoiceApp v{APP_VERSION}", font=p.fonts["small"], bg=p.sidebar_bg, fg=p.sidebar_fg,
                 anchor="w").pack(fill="x")
        tk.Label(foot, text="Local database - no internet needed", font=p.fonts["small"], bg=p.sidebar_bg,
                 fg=p.sidebar_fg, anchor="w").pack(fill="x")

    def _paint(self, key, bg, fg, bar_color):
        row, ic, lb, bar = self.items[key]
        row.configure(bg=bg)
        ic.configure(bg=bg, fg=fg)
        lb.configure(bg=bg, fg=fg)
        bar.configure(bg=bar_color)

    def _hover(self, key, on):
        if key == self.active:
            return
        p = self.app.palette
        self._paint(key, p.sidebar_hover if on else p.sidebar_bg, p.on(p.sidebar_bg) if on else p.sidebar_fg,
                    p.sidebar_hover if on else p.sidebar_bg)

    def set_active(self, key):
        p = self.app.palette
        if self.active and self.active in self.items:
            self._paint(self.active, p.sidebar_bg, p.sidebar_fg, p.sidebar_bg)
        self.active = key
        if key in self.items:
            self._paint(key, p.sidebar_active, p.on(p.sidebar_active), p.on(p.sidebar_active))


class App(tb.Window):
    def __init__(self, db_path: str | None = None):
        self.db = Database(db_path)
        self.settings = self.db.get_settings()
        self.palette = build_palette(self.settings)
        super().__init__(title="InvoiceApp", size=(1380, 860), minsize=(1120, 700))
        self.ui_style = tb.Style()
        apply_theme(self.ui_style, self.palette)
        self.configure(bg=self.palette.bg)
        self.report_callback_exception = self._tk_error
        self.current = "dashboard"
        self.pages: dict[str, tk.Frame] = {}
        self._build()
        self.navigate("dashboard")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        try:
            self.place_window_center()
        except Exception:
            pass

    # ------------------------------------------------------------------ layout
    def _build(self):
        from ui_customers import CustomersPage
        from ui_dashboard import DashboardPage
        from ui_documents import DocumentsPage
        from ui_payments import PaymentsPage
        from ui_products import ProductsPage
        from ui_settings import SettingsPage
        from ui_vendors import VendorsPage

        self.sidebar = Sidebar(self, self)
        self.sidebar.pack(side="left", fill="y")
        self.container = tk.Frame(self, bg=self.palette.bg)
        self.container.pack(side="left", fill="both", expand=True)
        self.pages = {
            "dashboard": DashboardPage(self.container, self),
            "invoices": DocumentsPage(self.container, self, models.INVOICE),
            "quotations": DocumentsPage(self.container, self, models.QUOTATION),
            "customers": CustomersPage(self.container, self),
            "vendors": VendorsPage(self.container, self),
            "products": ProductsPage(self.container, self),
            "payments": PaymentsPage(self.container, self),
            "settings": SettingsPage(self.container, self),
        }

    def navigate(self, name: str, **kwargs):
        if name not in self.pages:
            name = "dashboard"
        for key, page in self.pages.items():
            if key == name:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        self.current = name
        self.sidebar.set_active(name)
        self.pages[name].refresh(**kwargs)

    def refresh_all(self):
        """Refresh the visible page; other pages refresh when navigated to."""
        self.reload_settings()
        page = self.pages.get(self.current)
        if page:
            page.refresh()

    # ------------------------------------------------------------------ settings / theme
    def reload_settings(self):
        self.settings = self.db.get_settings()

    def payment_methods(self) -> list[str]:
        methods = self.db.get_list_setting("payment_methods")
        return methods or json.loads(DEFAULT_SETTINGS["payment_methods"])

    def apply_theme(self):
        """Rebuild the palette from settings and re-create every page so colors apply everywhere."""
        self.reload_settings()
        self.palette = build_palette(self.settings)
        apply_theme(self.ui_style, self.palette)
        self.configure(bg=self.palette.bg)
        current = self.current
        for w in (self.sidebar, self.container):
            w.destroy()
        self._build()
        self.navigate(current)

    # ------------------------------------------------------------------ lifecycle
    def _tk_error(self, exc_type, exc, tb_obj):
        text = log_error(exc_type, exc, tb_obj)
        try:
            from ui_common import show_error
            show_error(self, f"Something went wrong, but your data is safe.\n\n{exc}\n\n"
                             f"Details were written to data/error.log.", "Unexpected error")
        except Exception:
            print(text, file=sys.stderr)

    def on_close(self):
        try:
            self.db.close()
        finally:
            self.destroy()


def main():
    try:
        app = App()
    except Exception:
        text = log_error(*sys.exc_info())
        try:
            root = tk.Tk()
            root.withdraw()
            from tkinter import messagebox
            messagebox.showerror("InvoiceApp could not start", text[-1500:])
        except Exception:
            print(text, file=sys.stderr)
        sys.exit(1)
    app.mainloop()


if __name__ == "__main__":
    main()
