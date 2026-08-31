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
        self._section(card, "Cloud sync (Supabase) - all your PCs share the same data, still works offline")
        r = card.grid_size()[1]
        tk.Label(card, text="Owner: follow steps 1-4 below, once. Employees never open this tab - on their PC they "
                            "click 'Join a shop' on the login screen and paste the invite code from step 4. "
                            "Everything keeps working offline and syncs when internet returns.",
                 font=p.fonts["small"], bg=p.card, fg=p.muted, wraplength=780, justify="left").grid(
            row=r, column=0, columnspan=6, sticky="w", pady=(0, 2))
        r = card.grid_size()[1]
        self.cloud_hint = tk.Label(card, text="", font=p.fonts["small_bold"], bg=p.card, fg=p.accent, anchor="w")
        self.cloud_hint.grid(row=r, column=0, columnspan=6, sticky="w", pady=(0, 6))

        self._section(card, "STEP 1 (EASY) - ONE-TOKEN SETUP - recommended")
        r = card.grid_size()[1]
        tk.Label(card, text="Access token", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        self.cloud_pat = tk.StringVar()
        tb.Entry(card, textvariable=self.cloud_pat, width=40, show="*").grid(row=r, column=1, sticky="w", pady=4)
        prow = tk.Frame(card, bg=p.card)
        prow.grid(row=r, column=2, columnspan=2, sticky="w", padx=(8, 0))
        button(prow, "Get token", self.cloud_get_token, "secondary-outline").pack(side="left")
        button(prow, "Set everything up", self.cloud_easy, "primary").pack(side="left", padx=(8, 0))
        tk.Label(card, text="Sign up at supabase.com (free) -> press 'Get token' (opens the right page) -> Generate new "
                            "token -> paste it here -> 'Set everything up'. The app then creates and configures the "
                            "whole cloud by itself: project, database, security, invite system, instant employee "
                            "joins. The token is used once and never stored.",
                 font=p.fonts["small"], bg=p.card, fg=p.muted, wraplength=640, justify="left").grid(
            row=r + 1, column=1, columnspan=4, sticky="w", pady=(0, 4))
        self._toggle(card, "Enable cloud sync", "cloud_enabled", "off = pure offline (default)")
        self._row(card, "Project URL", "cloud_url", hint="Supabase -> Project Settings -> Data API -> URL")
        self._row(card, "Anon public key", "cloud_anon_key", hint="Project Settings -> API Keys -> anon public")
        r = card.grid_size()[1]
        row = tk.Frame(card, bg=p.card)
        row.grid(row=r, column=1, sticky="w", pady=(2, 4))
        button(row, "Connect & check", self.cloud_test, "primary").pack(side="left")
        button(row, "Database setup (copy SQL + open editor)", self.cloud_db_setup, "outline").pack(side="left", padx=(8, 0))
        tk.Label(card, text="Tip: copy anything containing the URL and key (even the whole dashboard page) and just "
                            "press Connect & check - the app finds both by itself.",
                 font=p.fonts["small"], bg=p.card, fg=p.muted, wraplength=640, justify="left").grid(
            row=card.grid_size()[1], column=1, columnspan=4, sticky="w", pady=(0, 4))
        self.cloud_status = tk.Label(row, text="", font=p.fonts["small"], bg=p.card, fg=p.muted)
        self.cloud_status.pack(side="left", padx=(10, 0))

        self._section(card, "STEP 2 - SIGN IN (your own cloud account)")
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
        button(row, "Create account", self.cloud_create_acct, "outline").pack(side="left", padx=(8, 0))
        button(row, "Sign out", self.cloud_signout, "secondary-outline").pack(side="left", padx=(8, 0))

        self._section(card, "STEP 3 - YOUR SHOP (created automatically when you sign in)")
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

        self._section(card, "Sync")
        r = card.grid_size()[1]
        tk.Label(card, text="Status", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        self.cloud_sync_lbl = tk.Label(card, text="", font=p.fonts["small"], bg=p.card, fg=p.muted, anchor="w")
        self.cloud_sync_lbl.grid(row=r, column=1, columnspan=4, sticky="w")
        r = card.grid_size()[1]
        srow = tk.Frame(card, bg=p.card)
        srow.grid(row=r, column=1, sticky="w", pady=(2, 6))
        button(srow, "Sync now", self.cloud_sync_now, "primary").pack(side="left")
        self.cloud_auto = tk.IntVar(value=1 if self.app.settings.get("cloud_auto_sync", "1") == "1" else 0)
        tb.Checkbutton(srow, text="Auto-sync every 30s", variable=self.cloud_auto, bootstyle="round-toggle",
                       command=self.cloud_toggle_auto).pack(side="left", padx=(14, 0))

        self._section(card, "STEP 4 - INVITE EMPLOYEES (one code, no keys)")
        r = card.grid_size()[1]
        tk.Label(card, text="Invite code", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        irow = tk.Frame(card, bg=p.card)
        irow.grid(row=r, column=1, columnspan=4, sticky="w", pady=4)
        button(irow, "Copy invite code", self.cloud_copy_invite, "primary").pack(side="left")
        tk.Label(card, text="Send that one code to your employee (WhatsApp, email...). On their PC they open the app, "
                            "click 'Join a shop' on the login screen, paste the code and pick their own email + "
                            "password. That is the whole setup for them.",
                 font=p.fonts["small"], bg=p.card, fg=p.muted, wraplength=560, justify="left").grid(
            row=r + 1, column=1, columnspan=4, sticky="w", pady=(0, 6))

        self._section(card, "ADVANCED (optional) - service_role key tools")
        r = card.grid_size()[1]
        tk.Label(card, text="Service key", font=p.fonts["base"], bg=p.card, fg=p.muted, anchor="e", width=20).grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=4)
        self.cloud_service = tk.StringVar(value="" if not self.app.db.get_secret("service_key") else "********")
        tb.Entry(card, textvariable=self.cloud_service, width=40, show="*").grid(row=r, column=1, sticky="w", pady=4)
        button(card, "Save key", self.cloud_save_service, "secondary-outline").grid(row=r, column=2, sticky="w", padx=(8, 0))
        tk.Label(card, text="Not needed for invites. Only for pre-creating accounts / resetting employee passwords. "
                            "Supabase -> Project Settings -> API Keys -> service_role. Stays on this (owner) PC.",
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
        self.on_sync_status(self.app.sync.status)

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
        if hasattr(self, "cloud_hint"):
            if not models.cloud_configured(db):
                nxt = "Next: STEP 1 - paste the Project URL + anon key and press Connect & check."
            elif not models.cloud_token(db):
                nxt = "Next: STEP 2 - sign in (or press Create account)."
            elif not models.cloud_shop_id(db):
                nxt = "Next: STEP 3 - press Create shop (empty name = your company name is used)."
            else:
                nxt = "All set. Copy the invite code (STEP 4) for each employee - sync runs by itself."
            self.cloud_hint.configure(text=nxt)

    def _cloud_busy(self, msg):
        self.cloud_status.configure(text=msg, fg=self.app.palette.muted)
        self.cloud_status.update_idletasks()

    def cloud_get_token(self):
        import webbrowser
        webbrowser.open("https://supabase.com/dashboard/account/tokens")

    def cloud_easy(self):
        import threading
        tok = self.cloud_pat.get().strip()
        if not tok.startswith("sbp_"):
            self.cloud_status.configure(text="Paste a personal ACCESS TOKEN (it starts with sbp_). Press 'Get token' "
                                             "to open the right page.", fg=self.app.palette.danger)
            return
        self._cloud_busy("Looking at your Supabase account...")

        def phase_a():
            try:
                projs = models.cloud_mgmt_projects(tok)
            except Exception as e:
                self.app.after(0, lambda: self.cloud_status.configure(text="Failed: " + str(e),
                                                                      fg=self.app.palette.danger))
                return
            self.app.after(0, lambda: self._easy_continue(tok, projs))

        threading.Thread(target=phase_a, daemon=True).start()

    def _easy_continue(self, tok, projs):
        import threading
        ref = None
        if len(projs) == 1:
            ref = projs[0].get("id") or projs[0].get("ref")
        elif len(projs) > 1:
            from ui_common import Dialog
            projs = sorted(projs, key=lambda pr: 0 if "invoice" in (pr.get("name") or "").lower() else 1)

            class PickProj(Dialog):
                def __init__(s, parent, app, items):
                    super().__init__(parent, app, "Choose the Supabase project", width=540)
                    pp = app.palette
                    tk.Label(s.body, text="You have several projects - which one is for InvoiceApp?",
                             font=pp.fonts["base"], bg=pp.bg, fg=pp.fg, anchor="w").pack(fill="x", pady=(0, 8))
                    for pr in items:
                        nm = f"{pr.get('name', '?')}   ({pr.get('id') or pr.get('ref', '')}  {pr.get('region', '')})"
                        button(s.body, nm, lambda p=pr: s.pick(p), "outline").pack(fill="x", pady=2)
                    s.buttons(None, None, cancel_text="Cancel")

                def pick(s, pr):
                    s.result = pr
                    s.close()

            chosen = PickProj(self, self.app, projs).show()
            if not chosen:
                self.cloud_status.configure(text="Cancelled.", fg=self.app.palette.muted)
                return
            ref = chosen.get("id") or chosen.get("ref")
        self._cloud_busy("Setting everything up - a brand new project takes ~2 minutes...")

        def cb(msg):
            self.app.after(0, lambda m=msg: self.cloud_status.configure(text=m, fg=self.app.palette.muted))

        def phase_b():
            try:
                models.cloud_easy_setup(self.app.db, tok, ref, cb)
            except Exception as e:
                self.app.after(0, lambda: self.cloud_status.configure(text="Setup failed: " + str(e),
                                                                      fg=self.app.palette.danger))
                return

            def done():
                self.vars["cloud_enabled"].set("1")
                self.vars["cloud_url"].set(self.app.db.get_setting("cloud_url", ""))
                self.vars["cloud_anon_key"].set(self.app.db.get_setting("cloud_anon_key", ""))
                if self.app.db.get_secret("service_key"):
                    self.cloud_service.set("********")
                self.app.reload_settings()
                self.cloud_pat.set("")
                self.cloud_status.configure(text="Everything is set up! Now STEP 2: type an email + password and press "
                                                 "Create account.", fg=self.app.palette.success)
                self._cloud_refresh_labels()

            self.app.after(0, done)

        threading.Thread(target=phase_b, daemon=True).start()

    def _smart_fill(self):
        """Fill URL/key from whatever is available: a blob pasted into either field, or the clipboard."""
        url = self.vars["cloud_url"].get().strip()
        key = self.vars["cloud_anon_key"].get().strip()
        u, k = cloud.parse_pasted(url + "\n" + key)
        if not (u and k):
            try:
                cu, ck = cloud.parse_pasted(self.clipboard_get())
                u, k = u or cu, k or ck
            except Exception:
                pass
        if u:
            self.vars["cloud_url"].set(u)
        if k and (not key or cloud.key_role(key) != "anon"):
            self.vars["cloud_anon_key"].set(k)

    def cloud_db_setup(self):
        self.cloud_copy_sql()
        self.cloud_open_sql()
        self.cloud_status.configure(text="SQL copied & editor opened: paste (Ctrl+V), press RUN, come back and press "
                                         "Connect & check.", fg=self.app.palette.success)

    def cloud_test(self):
        self._smart_fill()
        self._persist_cloud_conf()
        role = cloud.key_role(self.vars["cloud_anon_key"].get())
        if role == "service_role":
            self.cloud_status.configure(text="That is the SECRET service_role key! Paste the anon public key here "
                                             "(Supabase -> Project Settings -> API Keys -> anon public).",
                                        fg=self.app.palette.danger)
            return
        self._cloud_busy("Checking...")
        try:
            sb = models.cloud_client(self.app.db)
            sb.test_connection()
            ready = sb.db_ready()
        except Exception as e:
            self.cloud_status.configure(text="Failed: " + str(e), fg=self.app.palette.danger)
            return
        if not ready:
            self.cloud_status.configure(text="Connected, but the database is not set up yet. Click 'Copy setup SQL', "
                                             "then 'Open SQL editor', paste (Ctrl+V), press Run - then Connect & check "
                                             "again.", fg=self.app.palette.danger)
            return
        self.cloud_status.configure(text="Connected - database ready. Next: step 2.", fg=self.app.palette.success)
        self._cloud_refresh_labels()

    def cloud_signin(self):
        self._persist_cloud_conf()
        self._cloud_busy("Signing in...")
        try:
            models.cloud_sign_in(self.app.db, self.cloud_email.get(), self.cloud_pw.get())
        except Exception as e:
            self.cloud_status.configure(text="Sign in failed: " + str(e), fg=self.app.palette.danger)
            return
        self.cloud_pw.set("")
        extra = models.cloud_auto_shop(self.app.db)
        self.app.reload_settings()
        self.cloud_status.configure(text="Signed in" + (f" - {extra}" if extra else ""), fg=self.app.palette.success)
        self._cloud_refresh_labels()
        self.app.sync.trigger()

    def cloud_signout(self):
        models.cloud_sign_out(self.app.db)
        self.cloud_status.configure(text="Signed out", fg=self.app.palette.muted)
        self._cloud_refresh_labels()

    def cloud_create_shop(self):
        self._cloud_busy("Creating shop...")
        try:
            shop = models.cloud_create_shop(self.app.db, self.cloud_shop_name.get().strip()
                                            or self.app.settings.get("company_name", "") or "My Shop")
        except Exception as e:
            self.cloud_status.configure(text=str(e), fg=self.app.palette.danger)
            return
        self.app.reload_settings()
        self.cloud_status.configure(text=f"Shop '{shop['name']}' created & linked", fg=self.app.palette.success)
        self._cloud_refresh_labels()
        self.app.sync.trigger()

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
            self.app.sync.trigger()

    def cloud_save_service(self):
        v = self.cloud_service.get().strip()
        if v and v != "********" and cloud.key_role(v) == "anon":
            self.cloud_status.configure(text="That is the anon PUBLIC key - the service_role key is the other one "
                                             "(Project Settings -> API Keys -> service_role secret).",
                                        fg=self.app.palette.danger)
            return
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
            self.cloud_members.insert("end", f"{m.get('role', ''):10s}  {m.get('email') or m.get('user_id', '')}\n")

    def cloud_copy_sql(self):
        from utils import resource_path
        try:
            with open(resource_path("SUPABASE_SETUP.sql"), "r", encoding="utf-8") as fh:
                sql = fh.read()
        except Exception as e:
            self.cloud_status.configure(text="Could not load the SQL file: " + str(e), fg=self.app.palette.danger)
            return
        self.clipboard_clear()
        self.clipboard_append(sql)
        self.cloud_status.configure(text="Setup SQL copied. Now click 'Open SQL editor', paste (Ctrl+V) and press Run.",
                                    fg=self.app.palette.success)

    def cloud_open_sql(self):
        import re as _re
        import webbrowser
        m = _re.match(r"https?://([a-z0-9-]+)\.supabase\.", self.vars["cloud_url"].get().strip())
        webbrowser.open(f"https://supabase.com/dashboard/project/{m.group(1)}/sql/new" if m
                        else "https://supabase.com/dashboard")

    def cloud_create_acct(self):
        self._persist_cloud_conf()
        self._cloud_busy("Creating account...")
        try:
            out = models.cloud_create_account(self.app.db, self.cloud_email.get(), self.cloud_pw.get())
        except Exception as e:
            self.cloud_status.configure(text=str(e), fg=self.app.palette.danger)
            return
        if out == "confirm":
            self.cloud_status.configure(text="Account created - open the confirmation email Supabase sent you, click "
                                             "the link, then press Sign in.", fg=self.app.palette.danger)
        else:
            self.cloud_pw.set("")
            extra = models.cloud_auto_shop(self.app.db)
            self.app.reload_settings()
            self.cloud_status.configure(text="Account created & signed in." + (f" {extra}." if extra else ""),
                                        fg=self.app.palette.success)
            self.app.sync.trigger()
        self._cloud_refresh_labels()

    def cloud_copy_invite(self):
        self._cloud_busy("Building invite code...")
        try:
            code = models.cloud_invite_text(self.app.db)
        except Exception as e:
            self.cloud_status.configure(text=str(e), fg=self.app.palette.danger)
            return
        self.clipboard_clear()
        self.clipboard_append(code)
        self.cloud_status.configure(text="Invite code copied - send it to your employee (WhatsApp, email...).",
                                    fg=self.app.palette.success)

    def cloud_sync_now(self):
        import threading
        if not models.cloud_ready(self.app.db):
            self.cloud_sync_lbl.configure(text="Enable cloud, sign in and pick a shop first.",
                                          fg=self.app.palette.danger)
            return
        self.cloud_sync_lbl.configure(text="Syncing...", fg=self.app.palette.muted)

        def work():
            res = self.app.sync.sync_now()
            self.app.after(0, lambda: self.on_sync_status(res))

        threading.Thread(target=work, daemon=True).start()

    def cloud_toggle_auto(self):
        self.app.db.set_setting("cloud_auto_sync", "1" if self.cloud_auto.get() else "0")
        self.app.reload_settings()
        if self.cloud_auto.get():
            self.app.sync.trigger()

    def on_sync_status(self, status: dict):
        if not hasattr(self, "cloud_sync_lbl"):
            return
        if status.get("running"):
            self.cloud_sync_lbl.configure(text="Syncing...", fg=self.app.palette.muted)
            return
        err = status.get("last_error")
        if err:
            self.cloud_sync_lbl.configure(text="Error: " + err, fg=self.app.palette.danger)
        elif status.get("last_sync"):
            self.cloud_sync_lbl.configure(
                text=f"Last sync {status['last_sync']}  (pushed {status.get('pushed', 0)}, "
                     f"pulled {status.get('pulled', 0)})", fg=self.app.palette.success)
        else:
            self.cloud_sync_lbl.configure(text="Not synced yet.", fg=self.app.palette.muted)

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
