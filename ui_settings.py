"""Settings page: company, documents & numbering, PDF layout, payment methods, inventory, users, appearance, data."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import tkinter as tk
from tkinter import colorchooser

import ttkbootstrap as tb

import models
from db import DEFAULT_SETTINGS, DISPLAY_DEFAULTS, DISPLAY_LABELS
from pdf_templates import TEMPLATE_DESCRIPTIONS, TEMPLATE_NAMES
from ui_common import (Card, DataTable, PageHeader, StatusBadge, ask_open_path, ask_save_path, ask_yes_no, button,
                       show_error, show_info)
import cloud
from utils import data_dir, is_hex_color, open_file, parse_float

THEME_KEYS = ("theme_accent", "theme_bg", "theme_fg", "theme_success", "theme_warning", "theme_danger", "theme_muted",
              "ui_font", "ui_font_size")


class SettingsPage(tk.Frame):
    name = "settings"

    def __init__(self, master, app):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app = app
        self.vars: dict[str, tk.StringVar] = {}
        self.texts: dict[str, tk.Text] = {}
        self.swatches: dict[str, tk.Label] = {}
        self.display_vars: dict[str, tk.BooleanVar] = {}
        self._logo_image = None

        self.header = PageHeader(self, app, "Settings", "Everything brandable lives here - nothing is hardcoded")
        self.header.pack(fill="x", padx=28, pady=(24, 12))
        self.header.button("Save settings", self.save, "primary")

        self.nb = tb.Notebook(self, bootstyle="primary")
        self.nb.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        self.tab_company()
        self.tab_documents()
        self.tab_pdf_layout()
        self.tab_payments()
        self.tab_inventory()
        self.tab_users()
        self.tab_cloud()
        self.tab_dashboard()
        self.tab_appearance()
        self.tab_data()
        self.tab_about()

    # ------------------------------------------------------------------ helpers
    def _tab(self, title):
        p = self.app.palette
        outer = tk.Frame(self.nb, bg=p.bg)
        self.nb.add(outer, text=title)
        sf = tb.ScrolledFrame(outer, auto_hide=False)
        sf.pack(fill="both", expand=True)
        card = Card(sf, self.app, padding=20)
        card.pack(fill="both", expand=True, padx=2, pady=10)
        return card

    def _row(self, master, label, key, width=None, hint="", r=None, c=0, span=1):
        p = self.app.palette
        r = master.grid_size()[1] if r is None else r
        tk.Label(master, text=label, font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=c * 3, sticky="e", padx=(0, 8), pady=5)
        var = tk.StringVar(value=self.app.settings.get(key, ""))
        e = tb.Entry(master, textvariable=var, width=width)
        e.grid(row=r, column=c * 3 + 1, sticky="ew" if not width else "w", pady=5, columnspan=(span * 3 - 2))
        self.vars[key] = var
        if hint:
            tk.Label(master, text=hint, font=p.fonts["small"], bg=p.card, fg=p.muted, anchor="w").grid(
                row=r, column=c * 3 + 2, sticky="w", padx=(8, 0))
        return e

    def _text(self, master, label, key, height=3):
        p = self.app.palette
        r = master.grid_size()[1]
        tk.Label(master, text=label, font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="ne", width=20).grid(
            row=r, column=0, sticky="ne", padx=(0, 8), pady=5)
        t = tb.Text(master, height=height, wrap="word", font=p.fonts["base"])
        t.insert("1.0", self.app.settings.get(key, ""))
        t.grid(row=r, column=1, columnspan=5, sticky="ew", pady=5)
        self.texts[key] = t
        return t

    def _toggle(self, master, label, key, hint="", r=None, c=0):
        p = self.app.palette
        r = master.grid_size()[1] if r is None else r
        var = tk.StringVar(value="1" if self.app.settings.get(key, "0") == "1" else "0")
        self.vars[key] = var
        bv = tk.BooleanVar(value=var.get() == "1")
        bv.trace_add("write", lambda *_: var.set("1" if bv.get() else "0"))
        cb = tb.Checkbutton(master, text=label, variable=bv, bootstyle="round-toggle")
        cb.grid(row=r, column=c * 3, columnspan=2, sticky="w", pady=5)
        if hint:
            tk.Label(master, text=hint, font=p.fonts["small"], bg=p.card, fg=p.muted, anchor="w").grid(
                row=r, column=c * 3 + 2, sticky="w", padx=(8, 0))
        cb._bool = bv  # keep a reference alive
        return cb

    def _section(self, master, text):
        p = self.app.palette
        r = master.grid_size()[1]
        tk.Label(master, text=text.upper(), font=p.fonts["small_bold"], bg=p.card, fg=p.accent, anchor="w").grid(
            row=r, column=0, columnspan=6, sticky="w", pady=(14 if r else 0, 4))

    # ------------------------------------------------------------------ tabs
    def tab_company(self):
        card = self._tab("Company")
        card.grid_columnconfigure(1, weight=1)
        card.grid_columnconfigure(4, weight=1)
        self._section(card, "Company profile (printed on every document)")
        self._row(card, "Company name", "company_name")
        self._row(card, "Tagline", "company_tagline")
        self._row(card, "Phone", "company_phone")
        self._row(card, "Email", "company_email")
        self._row(card, "Website", "company_website")
        self._row(card, "Tax / NTN number", "company_tax_number")
        self._text(card, "Address", "company_address", 3)
        self._section(card, "Logo")
        p = self.app.palette
        r = card.grid_size()[1]
        tk.Label(card, text="Logo image", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="ne", padx=(0, 8), pady=5)
        box = tk.Frame(card, bg=p.card)
        box.grid(row=r, column=1, columnspan=5, sticky="w")
        self.logo_preview = tk.Label(box, bg=p.subtle, width=28, height=6, text="No logo", fg=p.muted, font=p.fonts["small"])
        self.logo_preview.pack(side="left")
        btns = tk.Frame(box, bg=p.card)
        btns.pack(side="left", padx=12, anchor="n")
        button(btns, "Choose image...", self.choose_logo, "outline").pack(anchor="w")
        button(btns, "Remove logo", self.remove_logo, "danger-outline").pack(anchor="w", pady=(6, 0))
        tk.Label(btns, text="PNG or JPG. Placement depends on the template.", font=p.fonts["small"], bg=p.card,
                 fg=p.muted).pack(anchor="w", pady=(8, 0))
        self.vars["company_logo"] = tk.StringVar(value=self.app.settings.get("company_logo", ""))
        self.update_logo_preview()

    def tab_documents(self):
        card = self._tab("Documents & numbering")
        card.grid_columnconfigure(1, weight=1)
        card.grid_columnconfigure(4, weight=1)
        self._section(card, "Currency & tax")
        r = card.grid_size()[1]
        self._row(card, "Currency code", "currency_code", 10, "e.g. PKR", r, 0)
        self._row(card, "Currency symbol", "currency_symbol", 10, "e.g. Rs", r, 1)
        r = card.grid_size()[1]
        self._row(card, "Default tax rate %", "default_tax_rate", 10, "used unless a product overrides it", r, 0)
        self._row(card, "Tax label", "tax_label", 14, "e.g. GST, Sales Tax, VAT", r, 1)
        self._section(card, "Invoice numbering")
        r = card.grid_size()[1]
        self._row(card, "Prefix", "invoice_prefix", 12, "", r, 0)
        self._row(card, "Next number", "invoice_next_number", 10, "", r, 1)
        r = card.grid_size()[1]
        self._row(card, "Zero padding", "invoice_number_padding", 10, "4 -> INV-0001", r, 0)
        self._row(card, "Due after (days)", "invoice_due_days", 10, "", r, 1)
        self._section(card, "Quotation numbering")
        r = card.grid_size()[1]
        self._row(card, "Prefix", "quotation_prefix", 12, "", r, 0)
        self._row(card, "Next number", "quotation_next_number", 10, "", r, 1)
        r = card.grid_size()[1]
        self._row(card, "Zero padding", "quotation_number_padding", 10, "", r, 0)
        self._row(card, "Valid for (days)", "quotation_valid_days", 10, "", r, 1)
        self._section(card, "Default texts")
        r = card.grid_size()[1]
        self._row(card, "Date format", "date_format", 14, "%d %b %Y -> 30 Aug 2026,  %d/%m/%Y -> 30/08/2026", r, 0, span=2)
        self._text(card, "Default notes", "default_notes", 2)
        self._text(card, "Default terms", "default_terms", 3)
        self._text(card, "Bank / payment details", "bank_details", 3)

    def tab_pdf_layout(self):
        card = self._tab("PDF layout")
        p = self.app.palette
        card.grid_columnconfigure(1, weight=1)
        card.grid_columnconfigure(4, weight=1)
        self._section(card, "Template")
        r = card.grid_size()[1]
        tk.Label(card, text="Default template", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=5)
        self.vars["default_template"] = tk.StringVar(value=self.app.settings.get("default_template", TEMPLATE_NAMES[0]))
        tb.Combobox(card, textvariable=self.vars["default_template"], values=TEMPLATE_NAMES, state="readonly", width=12).grid(
            row=r, column=1, sticky="w", pady=5)
        tk.Label(card, text="Page size", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=3, sticky="e", padx=(0, 8), pady=5)
        self.vars["pdf_page_size"] = tk.StringVar(value=self.app.settings.get("pdf_page_size", "A4"))
        tb.Combobox(card, textvariable=self.vars["pdf_page_size"], values=["A4", "Letter"], state="readonly", width=10).grid(
            row=r, column=4, sticky="w", pady=5)
        r = card.grid_size()[1]
        desc = "\n".join(f"{n}: {d}" for n, d in TEMPLATE_DESCRIPTIONS.items())
        tk.Label(card, text=desc, font=p.fonts["small"], bg=p.card, fg=p.muted, justify="left", anchor="w").grid(
            row=r, column=1, columnspan=5, sticky="w", pady=(0, 6))
        self._section(card, "Labels & signatures")
        r = card.grid_size()[1]
        self._row(card, "Bill-to heading", "bill_to_label", 18, "e.g. Bill To, Customer, Client", r, 0)
        r = card.grid_size()[1]
        self._row(card, "Left signature label", "signature_prepared_label", 18, "e.g. Prepared by", r, 0)
        self._row(card, "Left signature name", "signature_prepared_name", 18, "blank = logged-in user", r, 1)
        r = card.grid_size()[1]
        self._row(card, "Right signature label", "signature_received_label", 18, "e.g. Received by", r, 0)
        self._row(card, "Right signature name", "signature_received_name", 18, "blank = written by hand", r, 1)
        self._section(card, "What to show on PDFs by default (each invoice can override these)")
        current = self.app.db.display_defaults()
        r = card.grid_size()[1]
        grid = tk.Frame(card, bg=p.card)
        grid.grid(row=r, column=0, columnspan=6, sticky="w")
        keys = list(DISPLAY_DEFAULTS.keys())
        for i, key in enumerate(keys):
            var = tk.BooleanVar(value=bool(current.get(key, DISPLAY_DEFAULTS[key])))
            self.display_vars[key] = var
            tb.Checkbutton(grid, text=DISPLAY_LABELS.get(key, key), variable=var, bootstyle="round-toggle").grid(
                row=i % 11, column=i // 11, sticky="w", padx=(0, 30), pady=3)

    def tab_payments(self):
        card = self._tab("Payment methods")
        p = self.app.palette
        tk.Label(card, text="Methods offered when recording a payment. The first one is the default.",
                 font=p.fonts["base"], bg=p.card, fg=p.muted).pack(anchor="w", pady=(0, 8))
        box = tk.Frame(card, bg=p.card)
        box.pack(anchor="w", fill="x")
        self.methods = tk.Listbox(box, height=8, width=36, font=p.fonts["base"], bg=p.input_bg, fg=p.fg,
                                  selectbackground=p.accent, selectforeground=p.accent_fg, relief="flat",
                                  highlightthickness=1, highlightbackground=p.border, activestyle="none")
        for m in self.app.payment_methods():
            self.methods.insert("end", m)
        self.methods.pack(side="left", fill="y")
        side = tk.Frame(box, bg=p.card)
        side.pack(side="left", padx=12, anchor="n")
        self.new_method = tk.StringVar()
        row = tk.Frame(side, bg=p.card)
        row.pack(anchor="w")
        e = tb.Entry(row, textvariable=self.new_method, width=24)
        e.pack(side="left")
        e.bind("<Return>", lambda _: self.add_method())
        button(row, "Add", self.add_method, "outline").pack(side="left", padx=(6, 0))
        button(side, "Remove selected", self.remove_method, "danger-outline").pack(anchor="w", pady=(8, 0))
        mv = tk.Frame(side, bg=p.card)
        mv.pack(anchor="w", pady=(8, 0))
        button(mv, "Move up", lambda: self.move_method(-1), "secondary-outline").pack(side="left")
        button(mv, "Move down", lambda: self.move_method(1), "secondary-outline").pack(side="left", padx=(6, 0))

    def tab_inventory(self):
        card = self._tab("Inventory")
        card.grid_columnconfigure(1, weight=1)
        card.grid_columnconfigure(4, weight=1)
        p = self.app.palette
        r = card.grid_size()[1]
        tk.Label(card, text="How stock works:  purchases from vendors ADD stock  ->  invoices SUBTRACT stock  ->  customer returns "
                            "add it back  ->  returns to vendor remove it.  Quotations never touch stock.",
                 font=p.fonts["base"], bg=p.card, fg=p.muted, wraplength=760, justify="left").grid(row=r, column=0, columnspan=6, sticky="w", pady=(0, 6))
        self._section(card, "Stock rules")
        r = card.grid_size()[1]
        self._row(card, "Low stock alert at", "low_stock_threshold", 10, "units - each product can override this in its own settings", r, 0)
        r = card.grid_size()[1]
        self._toggle(card, "Allow invoices to exceed stock (negative stock)", "allow_negative_stock",
                     "off = an invoice cannot sell more than you have", r, 0)
        self._section(card, "Purchase & return numbering")
        r = card.grid_size()[1]
        self._row(card, "Purchase prefix", "purchase_prefix", 12, "", r, 0)
        self._row(card, "Next purchase no.", "purchase_next_number", 10, "", r, 1)
        r = card.grid_size()[1]
        self._row(card, "Return prefix", "return_prefix", 12, "", r, 0)
        self._row(card, "Next return no.", "return_next_number", 10, "", r, 1)

    def tab_users(self):
        card = self._tab("Users")
        p = self.app.palette
        card.grid_columnconfigure(1, weight=1)
        self._section(card, "Access")
        r = card.grid_size()[1]
        self._toggle(card, "Require sign-in when the app starts", "require_login",
                     "off = opens straight away as the first owner", r, 0)
        self._section(card, "Accounts")
        r = card.grid_size()[1]
        box = tk.Frame(card, bg=p.card)
        box.grid(row=r, column=0, columnspan=6, sticky="ew")
        self.users_table = DataTable(box, self.app, [
            {"key": "username", "title": "Username", "width": 160}, {"key": "full_name", "title": "Name", "width": 220, "stretch": True},
            {"key": "role", "title": "Role", "width": 100}, {"key": "active", "title": "Status", "width": 90},
            {"key": "created", "title": "Created", "width": 140}], height=7, on_double=lambda row: self.edit_user())
        self.users_table.pack(fill="x")
        acts = tk.Frame(card, bg=p.card)
        acts.grid(row=r + 1, column=0, columnspan=6, sticky="w", pady=(8, 0))
        button(acts, "+ Add user", self.add_user, "primary").pack(side="left")
        button(acts, "Edit / reset password", self.edit_user, "outline").pack(side="left", padx=(8, 0))
        button(acts, "Delete", self.delete_user, "danger-outline").pack(side="left", padx=(8, 0))
        tk.Label(card, text="Owners: everything. Employees: dashboard (no money), invoices, quotations, customers, "
                            "products (no cost prices) and stock levels.", font=p.fonts["small"], bg=p.card, fg=p.muted,
                 justify="left").grid(row=r + 2, column=0, columnspan=6, sticky="w", pady=(10, 0))
        self.refresh_users()

    def tab_appearance(self):
        card = self._tab("Appearance")
        p = self.app.palette
        card.grid_columnconfigure(5, weight=1)
        self._section(card, "Theme colors (applied live across the app and PDFs)")
        specs = (("theme_accent", "Accent"), ("theme_bg", "Background"), ("theme_fg", "Text"),
                 ("theme_success", "Paid / success"), ("theme_warning", "Partially paid / warning"),
                 ("theme_danger", "Overdue / danger"), ("theme_muted", "Unpaid / muted"))
        for key, label in specs:
            r = card.grid_size()[1]
            tk.Label(card, text=label, font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
                row=r, column=0, sticky="e", padx=(0, 8), pady=4)
            var = tk.StringVar(value=self.app.settings.get(key, ""))
            self.vars[key] = var
            tb.Entry(card, textvariable=var, width=10).grid(row=r, column=1, sticky="w", pady=4)
            sw = tk.Label(card, text="   ", bg=var.get() if is_hex_color(var.get()) else p.card, width=4,
                          relief="flat", highlightthickness=1, highlightbackground=p.border)
            sw.grid(row=r, column=2, sticky="w", padx=6)
            self.swatches[key] = sw
            var.trace_add("write", lambda *_, k=key: self._swatch(k))
            button(card, "Pick...", lambda k=key: self.pick_color(k), "secondary-outline").grid(row=r, column=3, sticky="w")
        import tkinter.font as tkfont
        from pdf_templates import PDF_FONT_CHOICES
        try:
            fams = sorted({f for f in tkfont.families(self) if f and not f.startswith("@")})
        except Exception:
            fams = ["Segoe UI", "Arial", "Calibri", "Verdana", "Tahoma", "Georgia", "Times New Roman"]
        cur_font = self.app.settings.get("ui_font", "Segoe UI")
        if cur_font not in fams:
            fams = [cur_font] + fams
        r = card.grid_size()[1]
        tk.Label(card, text="App font", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        self.vars["ui_font"] = tk.StringVar(value=cur_font)
        tb.Combobox(card, textvariable=self.vars["ui_font"], values=fams, state="readonly", width=24).grid(
            row=r, column=1, sticky="w", pady=4)
        tk.Label(card, text="App font size", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=14).grid(
            row=r, column=3, sticky="e", padx=(0, 8), pady=4)
        self.vars["ui_font_size"] = tk.StringVar(value=self.app.settings.get("ui_font_size", "10"))
        tb.Combobox(card, textvariable=self.vars["ui_font_size"], values=[str(x) for x in range(8, 15)],
                    state="readonly", width=6).grid(row=r, column=4, sticky="w", pady=4)
        r = card.grid_size()[1]
        tk.Label(card, text="PDF font", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        self.vars["pdf_font"] = tk.StringVar(value=self.app.settings.get("pdf_font", "Auto"))
        tb.Combobox(card, textvariable=self.vars["pdf_font"], values=PDF_FONT_CHOICES, state="readonly", width=18).grid(
            row=r, column=1, sticky="w", pady=4)
        tk.Label(card, text="font used on invoice / quotation PDFs (Auto = per template)", font=p.fonts["small"],
                 bg=p.card, fg=p.muted).grid(row=r, column=2, columnspan=3, sticky="w", padx=(8, 0))
        r = card.grid_size()[1]
        tk.Label(card, text="Corner radius", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        self._radius_map = {"Square (sharp)": 0, "Soft": 10, "Rounded": 16}
        cur_r = int(self.app.settings.get("ui_radius", "10") or 0)
        cur_label = next((k for k, v in self._radius_map.items() if v == cur_r), "Soft")
        self.radius_combo = tb.Combobox(card, values=list(self._radius_map), state="readonly", width=16)
        self.radius_combo.set(cur_label)
        self.radius_combo.grid(row=r, column=1, sticky="w", pady=4)
        tk.Label(card, text="rounded panels & cards across the app", font=p.fonts["small"], bg=p.card,
                 fg=p.muted).grid(row=r, column=2, columnspan=3, sticky="w", padx=(8, 0))
        r = card.grid_size()[1]
        prev = tk.Frame(card, bg=p.card)
        prev.grid(row=r, column=0, columnspan=6, sticky="w", pady=(14, 0))
        tk.Label(prev, text="Status badges:", font=p.fonts["base"], bg=p.card, fg=p.muted).pack(side="left", padx=(0, 8))
        for s in ("Unpaid", "Partially Paid", "Paid", "Overdue"):
            StatusBadge(prev, self.app, s).pack(side="left", padx=(0, 6))
        r = card.grid_size()[1]
        act = tk.Frame(card, bg=p.card)
        act.grid(row=r, column=0, columnspan=6, sticky="w", pady=(16, 0))
        button(act, "Apply theme now", self.apply_theme, "primary").pack(side="left")
        button(act, "Reset colors to defaults", self.reset_theme, "secondary-outline").pack(side="left", padx=(8, 0))
        presets = tk.Frame(card, bg=p.card)
        presets.grid(row=r + 1, column=0, columnspan=6, sticky="w", pady=(12, 0))
        tk.Label(presets, text="Presets:", font=p.fonts["base"], bg=p.card, fg=p.muted).pack(side="left", padx=(0, 8))
        for name, accent, bg, fg in (("Ocean", "#2563eb", "#f4f6fb", "#0f172a"), ("Emerald", "#059669", "#f2f7f4", "#0b1f17"),
                                     ("Plum", "#7c3aed", "#f7f5fb", "#1e1b2e"), ("Sunset", "#ea580c", "#fbf6f2", "#1f1410"),
                                     ("Midnight", "#60a5fa", "#0f172a", "#e2e8f0")):
            button(presets, name, lambda a=accent, b=bg, f=fg: self._preset(a, b, f), "link").pack(side="left")

    def tab_data(self):
        card = self._tab("Data")
        p = self.app.palette
        tk.Label(card, text="DATABASE", font=p.fonts["small_bold"], bg=p.card, fg=p.accent).pack(anchor="w")
        tk.Label(card, text=self.app.db.path, font=p.fonts["mono"], bg=p.card, fg=p.fg).pack(anchor="w", pady=(2, 12))
        row = tk.Frame(card, bg=p.card)
        row.pack(anchor="w")
        button(row, "Back up database...", self.backup, "primary").pack(side="left")
        button(row, "Restore from backup...", self.restore, "danger-outline").pack(side="left", padx=(8, 0))
        button(row, "Open data folder", lambda: open_file(data_dir()), "secondary-outline").pack(side="left", padx=(8, 0))
        tk.Label(card, text="A backup is a complete copy of the .db file (customers, invoices, stock, users...). Restoring "
                            "replaces ALL current data (a safety copy *.before-restore is kept next to the database).",
                 font=p.fonts["small"], bg=p.card, fg=p.muted, wraplength=700, justify="left").pack(anchor="w", pady=(10, 0))

    def tab_cloud(self):
        card = self._tab("Cloud sync")
        p = self.app.palette
        card.grid_columnconfigure(1, weight=1)
        self._section(card, "Cloud sync (Supabase) - share data across shops, still works offline")
        r = card.grid_size()[1]
        tk.Label(card, text="Turn this on to sync invoices, quotations, customers, products and stock across the "
                            "owner's and employees' PCs. When there is no internet the app keeps working and syncs "
                            "later. First run SUPABASE_SETUP.sql in your Supabase project (SQL editor).",
                 font=p.fonts["small"], bg=p.card, fg=p.muted, wraplength=780, justify="left").grid(
            row=r, column=0, columnspan=6, sticky="w", pady=(0, 6))
        self._toggle(card, "Enable cloud sync", "cloud_enabled", "off = pure offline (default)")
        self._row(card, "Project URL", "cloud_url", hint="Supabase -> Project Settings -> Data API -> URL")
        self._row(card, "Anon public key", "cloud_anon_key", hint="Project Settings -> API Keys -> anon public")
        r = card.grid_size()[1]
        row = tk.Frame(card, bg=p.card)
        row.grid(row=r, column=1, sticky="w", pady=(2, 4))
        button(row, "Test connection", self.cloud_test, "outline").pack(side="left")
        self.cloud_status = tk.Label(row, text="", font=p.fonts["small"], bg=p.card, fg=p.muted)
        self.cloud_status.pack(side="left", padx=(10, 0))

        self._section(card, "Sign in")
        r = card.grid_size()[1]
        tk.Label(card, text="Signed in as", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        self.cloud_who = tk.Label(card, text="", font=p.fonts["bold"], bg=p.card, fg=p.fg, anchor="w")
        self.cloud_who.grid(row=r, column=1, sticky="w")
        r = card.grid_size()[1]
        tk.Label(card, text="Email", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        self.cloud_email = tk.StringVar()
        tb.Entry(card, textvariable=self.cloud_email, width=32).grid(row=r, column=1, sticky="w", pady=4)
        r = card.grid_size()[1]
        tk.Label(card, text="Password", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        self.cloud_pw = tk.StringVar()
        tb.Entry(card, textvariable=self.cloud_pw, width=32, show="*").grid(row=r, column=1, sticky="w", pady=4)
        r = card.grid_size()[1]
        row = tk.Frame(card, bg=p.card)
        row.grid(row=r, column=1, sticky="w", pady=(2, 4))
        button(row, "Sign in", self.cloud_signin, "primary").pack(side="left")
        button(row, "Sign out", self.cloud_signout, "secondary-outline").pack(side="left", padx=(8, 0))

        self._section(card, "Shop")
        r = card.grid_size()[1]
        tk.Label(card, text="Current shop", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        self.cloud_shop_lbl = tk.Label(card, text="", font=p.fonts["bold"], bg=p.card, fg=p.fg, anchor="w")
        self.cloud_shop_lbl.grid(row=r, column=1, sticky="w")
        r = card.grid_size()[1]
        row = tk.Frame(card, bg=p.card)
        row.grid(row=r, column=1, sticky="w", pady=(2, 4))
        self.cloud_shop_name = tk.StringVar()
        tb.Entry(row, textvariable=self.cloud_shop_name, width=24).pack(side="left")
        button(row, "Create shop", self.cloud_create_shop, "outline").pack(side="left", padx=(8, 0))
        button(row, "Select existing", self.cloud_select_shop, "secondary-outline").pack(side="left", padx=(8, 0))

        self._section(card, "Team (owner only) - add employees who can sign in on their own PC")
        r = card.grid_size()[1]
        tk.Label(card, text="Service key", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        self.cloud_service = tk.StringVar(value="" if not self.app.db.get_secret("service_key") else "********")
        tb.Entry(card, textvariable=self.cloud_service, width=40, show="*").grid(row=r, column=1, sticky="w", pady=4)
        button(card, "Save key", self.cloud_save_service, "secondary-outline").grid(row=r, column=2, sticky="w", padx=(8, 0))
        tk.Label(card, text="Supabase -> Project Settings -> API Keys -> service_role. Stored only on this (owner) PC.",
                 font=p.fonts["small"], bg=p.card, fg=p.muted).grid(row=r + 1, column=1, columnspan=4, sticky="w")
        r = card.grid_size()[1]
        row = tk.Frame(card, bg=p.card)
        row.grid(row=r, column=1, columnspan=4, sticky="w", pady=(6, 0))
        self.emp_email = tk.StringVar()
        self.emp_pw = tk.StringVar()
        self.emp_role = tb.Combobox(row, values=["employee", "owner"], state="readonly", width=10)
        self.emp_role.set("employee")
        tk.Label(row, text="Email", font=p.fonts["small"], bg=p.card, fg=p.muted).pack(side="left")
        tb.Entry(row, textvariable=self.emp_email, width=22).pack(side="left", padx=(4, 8))
        tk.Label(row, text="Password", font=p.fonts["small"], bg=p.card, fg=p.muted).pack(side="left")
        tb.Entry(row, textvariable=self.emp_pw, width=16, show="*").pack(side="left", padx=(4, 8))
        self.emp_role.pack(side="left", padx=(0, 8))
        button(row, "Add employee", self.cloud_add_employee, "primary").pack(side="left")
        r = card.grid_size()[1]
        self.cloud_members = tk.Text(card, height=5, width=70, font=p.fonts["small"], wrap="none")
        self.cloud_members.grid(row=r, column=1, columnspan=4, sticky="w", pady=(8, 0))
        button(card, "Refresh team", self.cloud_refresh_members, "link").grid(row=r + 1, column=1, sticky="w")
        self._cloud_refresh_labels()

    # ------------------------------------------------------------------ cloud actions
    def _persist_cloud_conf(self):
        self.app.db.set_settings({"cloud_url": self.vars["cloud_url"].get().strip(),
                                  "cloud_anon_key": self.vars["cloud_anon_key"].get().strip(),
                                  "cloud_enabled": self.vars["cloud_enabled"].get()})
        self.app.reload_settings()

    def _cloud_refresh_labels(self):
        db = self.app.db
        email = models.cloud_signed_in_email(db)
        self.cloud_who.configure(text=email or "(not signed in)")
        if email and not self.cloud_email.get():
            self.cloud_email.set(email)
        self.cloud_shop_lbl.configure(text=self.app.settings.get("cloud_shop_name") or "(none selected)")

    def _cloud_busy(self, msg):
        self.cloud_status.configure(text=msg, fg=self.app.palette.muted)
        self.cloud_status.update_idletasks()

    def cloud_test(self):
        self._persist_cloud_conf()
        self._cloud_busy("Testing...")
        try:
            models.cloud_client(self.app.db).test_connection()
        except Exception as e:
            self.cloud_status.configure(text="Failed: " + str(e), fg=self.app.palette.danger)
            return
        self.cloud_status.configure(text="Connected OK", fg=self.app.palette.success)

    def cloud_signin(self):
        self._persist_cloud_conf()
        self._cloud_busy("Signing in...")
        try:
            models.cloud_sign_in(self.app.db, self.cloud_email.get(), self.cloud_pw.get())
        except Exception as e:
            self.cloud_status.configure(text="Sign in failed: " + str(e), fg=self.app.palette.danger)
            return
        self.cloud_pw.set("")
        self.cloud_status.configure(text="Signed in", fg=self.app.palette.success)
        self._cloud_refresh_labels()

    def cloud_signout(self):
        models.cloud_sign_out(self.app.db)
        self.cloud_status.configure(text="Signed out", fg=self.app.palette.muted)
        self._cloud_refresh_labels()

    def cloud_create_shop(self):
        self._cloud_busy("Creating shop...")
        try:
            shop = models.cloud_create_shop(self.app.db, self.cloud_shop_name.get())
        except Exception as e:
            self.cloud_status.configure(text=str(e), fg=self.app.palette.danger)
            return
        self.app.reload_settings()
        self.cloud_status.configure(text=f"Shop '{shop['name']}' created & linked", fg=self.app.palette.success)
        self._cloud_refresh_labels()

    def cloud_select_shop(self):
        self._cloud_busy("Loading shops...")
        try:
            shops = models.cloud_list_shops(self.app.db)
        except Exception as e:
            self.cloud_status.configure(text=str(e), fg=self.app.palette.danger)
            return
        if not shops:
            self.cloud_status.configure(text="No shops yet - create one.", fg=self.app.palette.muted)
            return
        from ui_common import Dialog

        class Picker(Dialog):
            def __init__(s, parent, app, shops):
                super().__init__(parent, app, "Select a shop", width=460)
                s.choice = None
                pp = app.palette
                for sh in shops:
                    button(s.body, sh["name"], (lambda x=sh: s._pick(x)), "secondary-outline").pack(fill="x", pady=3)
                s.buttons(None, None, cancel_text="Cancel")

            def _pick(s, sh):
                s.result = sh
                s.close()
        chosen = Picker(self, self.app, shops).show()
        if chosen:
            models.cloud_link_shop(self.app.db, chosen["id"], chosen["name"])
            self.app.reload_settings()
            self.cloud_status.configure(text=f"Linked to '{chosen['name']}'", fg=self.app.palette.success)
            self._cloud_refresh_labels()

    def cloud_save_service(self):
        v = self.cloud_service.get().strip()
        if v and v != "********":
            self.app.db.set_secret("service_key", v)
            self.cloud_service.set("********")
            self.cloud_status.configure(text="Service key saved (this PC only)", fg=self.app.palette.success)
        elif not v:
            self.app.db.set_secret("service_key", None)
            self.cloud_status.configure(text="Service key removed", fg=self.app.palette.muted)

    def cloud_add_employee(self):
        self._cloud_busy("Creating employee...")
        try:
            models.cloud_add_employee(self.app.db, self.emp_email.get(), self.emp_pw.get(), self.emp_role.get())
        except Exception as e:
            self.cloud_status.configure(text=str(e), fg=self.app.palette.danger)
            return
        self.cloud_status.configure(text=f"Employee {self.emp_email.get()} added", fg=self.app.palette.success)
        self.emp_email.set("")
        self.emp_pw.set("")
        self.cloud_refresh_members()

    def cloud_refresh_members(self):
        try:
            members = models.cloud_list_members(self.app.db)
        except Exception as e:
            self.cloud_members.delete("1.0", "end")
            self.cloud_members.insert("1.0", "Could not load team: " + str(e))
            return
        self.cloud_members.delete("1.0", "end")
        if not members:
            self.cloud_members.insert("1.0", "(no team members yet)")
            return
        for m in members:
            self.cloud_members.insert("end", f"{m.get('role', ''):10s}  {m.get('user_id', '')}\n")

    def tab_dashboard(self):
        card = self._tab("Dashboard")
        p = self.app.palette
        card.grid_columnconfigure(1, weight=1)
        card.grid_columnconfigure(4, weight=1)
        self._section(card, "What the dashboard shows")
        # stats period
        r = card.grid_size()[1]
        tk.Label(card, text="Stats period", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=5)
        self._period_labels = ["This week", "This month", "Last 30 days", "This year", "All time"]
        self._period_keys = ["week", "month", "last30", "year", "all"]
        cur = self.app.settings.get("dashboard_period", "month")
        self.period_combo = tb.Combobox(card, values=self._period_labels, state="readonly", width=16)
        self.period_combo.current(self._period_keys.index(cur) if cur in self._period_keys else 1)
        self.period_combo.grid(row=r, column=1, sticky="w", pady=5)
        tk.Label(card, text="applies to Received / Invoiced / Profit / Purchases / Best sellers", font=p.fonts["small"],
                 bg=p.card, fg=p.muted).grid(row=r, column=2, columnspan=3, sticky="w", padx=(8, 0))
        r = card.grid_size()[1]
        self._row(card, "Recent invoices to show", "dashboard_recent", 8, "1 - 50", r, 0)
        self._section(card, "Panels & cards")
        r = card.grid_size()[1]
        self._toggle(card, "Quick action buttons", "dashboard_quick_actions", "", r, 0)
        self._toggle(card, "Low stock panel", "dashboard_show_low_stock", "", r, 1)
        r = card.grid_size()[1]
        self._toggle(card, "Best sellers panel (owner)", "dashboard_show_best", "", r, 0)
        self._toggle(card, "Recent activity panel", "dashboard_show_activity", "", r, 1)
        r = card.grid_size()[1]
        self._toggle(card, "Gross profit card (owner)", "dashboard_show_profit", "", r, 0)
        self._section(card, "Money & behaviour")
        r = card.grid_size()[1]
        tk.Label(card, text="Currency decimals", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=5)
        self.vars["currency_decimals"] = tk.StringVar(value=self.app.settings.get("currency_decimals", "2"))
        tb.Combobox(card, textvariable=self.vars["currency_decimals"], values=["0", "2", "3"], state="readonly",
                    width=6).grid(row=r, column=1, sticky="w", pady=5)
        tk.Label(card, text="0 = whole rupees (Rs 1,500), 2 = Rs 1,500.00", font=p.fonts["small"], bg=p.card,
                 fg=p.muted).grid(row=r, column=2, columnspan=3, sticky="w", padx=(8, 0))
        r = card.grid_size()[1]
        self._row(card, "Overdue grace days", "overdue_grace_days", 8, "days after the due date before an invoice is 'Overdue'", r, 0)
        r = card.grid_size()[1]
        self._toggle(card, "Enable Quotations (show the Quotations screen)", "enable_quotations", "", r, 0)

    def tab_about(self):
        card = self._tab("About")
        p = self.app.palette
        try:
            from main import APP_VERSION
        except Exception:
            APP_VERSION = ""

        tk.Label(card, text=self.app.settings.get("company_name") or "InvoiceApp", font=p.fonts["title"],
                 bg=p.card, fg=p.fg, anchor="w").pack(anchor="w")
        tk.Label(card, text=f"InvoiceApp  v{APP_VERSION}" if APP_VERSION else "InvoiceApp",
                 font=p.fonts["heading"], bg=p.card, fg=p.accent, anchor="w").pack(anchor="w", pady=(2, 0))
        tk.Label(card, text="Invoice, quotation, payment and inventory manager for small businesses.\n"
                            "Runs fully offline on a single local database - no server, no subscription.",
                 font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="w", justify="left").pack(anchor="w", pady=(6, 0))

        tk.Frame(card, bg=p.border, height=1).pack(fill="x", pady=16)

        tk.Label(card, text="DEVELOPER", font=p.fonts["small_bold"], bg=p.card, fg=p.accent, anchor="w").pack(anchor="w")
        tk.Label(card, text="Abdul Manan", font=p.fonts["heading"], bg=p.card, fg=p.fg, anchor="w").pack(anchor="w", pady=(2, 0))

        row = tk.Frame(card, bg=p.card)
        row.pack(anchor="w", pady=(4, 0))
        tk.Label(row, text="GitHub:", font=p.fonts["base"], bg=p.card, fg=p.muted).pack(side="left")
        link = tk.Label(row, text="@abdulmanan69", font=p.fonts["bold"], bg=p.card, fg=p.accent, cursor="hand2")
        link.pack(side="left", padx=(6, 0))
        url = "https://github.com/abdulmanan69"
        link.bind("<Button-1>", lambda e: open_file(url))
        link.bind("<Enter>", lambda e: link.configure(font=(p.font, p.font_size, "underline")))
        link.bind("<Leave>", lambda e: link.configure(font=p.fonts["bold"]))

        btns = tk.Frame(card, bg=p.card)
        btns.pack(anchor="w", pady=(12, 0))
        button(btns, "Open GitHub profile", lambda: open_file(url), "primary").pack(side="left")

        tk.Label(card, text="Made with care. Thank you for using InvoiceApp.", font=p.fonts["small"], bg=p.card,
                 fg=p.muted, anchor="w").pack(anchor="w", pady=(18, 0))

    # ------------------------------------------------------------------ users
    def refresh_users(self):
        rows = models.list_users(self.app.db)
        self.users_table.set_rows(rows, lambda u: [u["username"], u["full_name"], u["role"].title(),
                                                   "Active" if u["active"] else "Disabled", (u["created_at"] or "")[:10]])

    def add_user(self):
        from ui_auth import UserDialog
        if UserDialog(self, self.app).show():
            self.refresh_users()

    def edit_user(self):
        from ui_auth import UserDialog
        row = self.users_table.selected()
        if not row:
            show_info(self, "Select a user first.", "No selection")
            return
        if UserDialog(self, self.app, row).show():
            self.refresh_users()

    def delete_user(self):
        row = self.users_table.selected()
        if not row:
            show_info(self, "Select a user first.", "No selection")
            return
        if row["id"] == (self.app.user or {}).get("id"):
            show_error(self, "You cannot delete the account you are signed in with.")
            return
        if ask_yes_no(self, f"Delete user '{row['username']}'?", "Delete user"):
            try:
                models.delete_user(self.app.db, row["id"])
            except models.ValidationError as e:
                show_error(self, str(e))
                return
            self.refresh_users()

    # ------------------------------------------------------------------ logo
    def update_logo_preview(self):
        p = self.app.palette
        name = self.vars["company_logo"].get().strip()
        path = name if os.path.isabs(name) else os.path.join(data_dir(), name)
        if name and os.path.isfile(path):
            try:
                from PIL import Image, ImageTk
                im = Image.open(path)
                im.thumbnail((220, 90))
                self._logo_image = ImageTk.PhotoImage(im)
                self.logo_preview.configure(image=self._logo_image, text="", width=im.width, height=im.height)
                return
            except Exception:
                pass
        self._logo_image = None
        self.logo_preview.configure(image="", text="No logo" if not name else "Logo file missing", width=28, height=6, bg=p.subtle)

    def choose_logo(self):
        path = ask_open_path(self, "Choose logo image", [("Images", "*.png *.jpg *.jpeg *.gif *.bmp"), ("All files", "*.*")])
        if not path:
            return
        ext = os.path.splitext(path)[1].lower() or ".png"
        target = os.path.join(data_dir(), f"logo{ext}")
        try:
            if os.path.abspath(path) != os.path.abspath(target):
                shutil.copy2(path, target)
        except OSError as e:
            show_error(self, f"Could not copy the logo:\n{e}")
            return
        self.vars["company_logo"].set(os.path.basename(target))
        self.update_logo_preview()

    def remove_logo(self):
        self.vars["company_logo"].set("")
        self.update_logo_preview()

    # ------------------------------------------------------------------ payment methods
    def add_method(self):
        m = self.new_method.get().strip()
        if not m:
            return
        if m in self.methods.get(0, "end"):
            show_info(self, f"'{m}' is already in the list.")
            return
        self.methods.insert("end", m)
        self.new_method.set("")

    def remove_method(self):
        sel = self.methods.curselection()
        if not sel:
            return
        if self.methods.size() <= 1:
            show_error(self, "Keep at least one payment method.")
            return
        self.methods.delete(sel[0])

    def move_method(self, delta):
        sel = self.methods.curselection()
        if not sel:
            return
        i, j = sel[0], sel[0] + delta
        if 0 <= j < self.methods.size():
            v = self.methods.get(i)
            self.methods.delete(i)
            self.methods.insert(j, v)
            self.methods.selection_set(j)

    # ------------------------------------------------------------------ theme
    def _swatch(self, key):
        v = self.vars[key].get().strip()
        if is_hex_color(v):
            self.swatches[key].configure(bg=v)

    def pick_color(self, key):
        initial = self.vars[key].get() if is_hex_color(self.vars[key].get()) else "#2563eb"
        try:
            _, hexv = colorchooser.askcolor(color=initial, parent=self, title="Pick a color")
        except Exception:
            hexv = None
        if hexv:
            self.vars[key].set(hexv)

    def _preset(self, accent, bg, fg):
        self.vars["theme_accent"].set(accent)
        self.vars["theme_bg"].set(bg)
        self.vars["theme_fg"].set(fg)

    def reset_theme(self):
        for k in THEME_KEYS:
            self.vars[k].set(DEFAULT_SETTINGS[k])

    def apply_theme(self):
        if self.save(quiet=True):
            self.app.apply_theme()

    # ------------------------------------------------------------------ data
    def backup(self):
        name = f"invoice_backup_{dt.datetime.now():%Y%m%d_%H%M}.db"
        path = ask_save_path(self, "Back up database", name, ".db", [("Database backup", "*.db")])
        if not path:
            return
        try:
            self.app.db.backup_to(path)
        except Exception as e:
            show_error(self, f"Backup failed:\n{e}")
            return
        show_info(self, f"Backup saved to:\n{path}", "Backup complete")

    def restore(self):
        path = ask_open_path(self, "Choose a backup to restore", [("Database backup", "*.db"), ("All files", "*.*")])
        if not path:
            return
        if not ask_yes_no(self, "Restoring will REPLACE all current data with the contents of the backup.\n\n"
                                f"{path}\n\nContinue?", "Restore database"):
            return
        try:
            self.app.db.restore_from(path)
        except Exception as e:
            show_error(self, f"Restore failed:\n{e}")
            return
        self.app.reload_settings()
        self.app.apply_theme()
        show_info(self.app, "Database restored successfully.", "Restore complete")

    # ------------------------------------------------------------------ save
    def collect(self) -> dict | None:
        data = {k: v.get().strip() for k, v in self.vars.items()}
        for k, t in self.texts.items():
            data[k] = t.get("1.0", "end").strip()
        if not data.get("company_name"):
            show_error(self, "Company name is required.")
            return None
        for key, lo, hi in (("default_tax_rate", 0, 100), ("invoice_due_days", 0, 3650), ("quotation_valid_days", 0, 3650),
                            ("invoice_number_padding", 0, 10), ("quotation_number_padding", 0, 10),
                            ("invoice_next_number", 1, 10 ** 9), ("quotation_next_number", 1, 10 ** 9),
                            ("purchase_next_number", 1, 10 ** 9), ("return_next_number", 1, 10 ** 9),
                            ("low_stock_threshold", 0, 10 ** 9), ("ui_font_size", 8, 14),
                            ("dashboard_recent", 1, 50), ("overdue_grace_days", 0, 3650), ("currency_decimals", 0, 4)):
            v = parse_float(data.get(key), None)
            if v is None or v < lo or v > hi:
                show_error(self, f"'{key.replace('_', ' ')}' must be a number between {lo} and {hi}.")
                return None
            data[key] = str(int(v)) if key not in ("default_tax_rate", "low_stock_threshold") else str(v)
        data["dashboard_period"] = self._period_keys[self.period_combo.current()] if self.period_combo.current() >= 0 else "month"
        for key in THEME_KEYS[:7]:
            if not is_hex_color(data.get(key, "")):
                show_error(self, f"'{key.replace('_', ' ')}' must be a hex color like #2563eb.")
                return None
        data["payment_methods"] = json.dumps(list(self.methods.get(0, "end")))
        data["doc_display_defaults"] = json.dumps({k: (1 if v.get() else 0) for k, v in self.display_vars.items()})
        data["ui_radius"] = str(self._radius_map.get(self.radius_combo.get(), 10))
        data.setdefault("company_logo", "")
        return data

    def save(self, quiet=False) -> bool:
        data = self.collect()
        if data is None:
            return False
        self.app.db.set_settings(data)
        self.app.reload_settings()
        if not quiet:
            self.app.apply_theme()  # rebuilds sidebar + pages so names, currency and colors update everywhere
            show_info(self.app, "Settings saved.", "Saved")
        return True

    def refresh(self, **_):
        pass
