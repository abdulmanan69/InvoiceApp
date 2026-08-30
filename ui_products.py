"""Products / services page: searchable list + add/edit/delete."""
from __future__ import annotations

import tkinter as tk

import ttkbootstrap as tb

import models
from ui_common import (Card, DataTable, Dialog, Form, PageHeader, SearchEntry, ask_yes_no, button, fmt_money,
                       show_error, show_info)
from utils import fmt_number


class ProductDialog(Dialog):
    def __init__(self, parent, app, product: dict | None = None):
        super().__init__(parent, app, "Edit product / service" if product else "New product / service", width=680)
        self.product = product or {}
        pr = self.product
        f = Form(self.body, app, columns=2)
        self.form = f
        f.entry("Name *", "name", pr.get("name", ""), span=2)
        f.entry("SKU / code", "sku", pr.get("sku", ""))
        f.entry("Unit", "unit", pr.get("unit", "pcs"))
        f.entry("Unit price *", "unit_price", fmt_number(pr.get("unit_price", 0)) if pr else "")
        f.entry("Tax % override", "tax_rate", "" if pr.get("tax_rate") is None else fmt_number(pr.get("tax_rate")))
        f.text("Description", "description", pr.get("description", ""), span=2, height=3)
        f.check("Active (available for new invoices)", "active", pr.get("active", 1) in (1, True), span=2)
        p = app.palette
        tk.Label(self.body, text="Leave the tax override blank to use the document's default tax rate.",
                 font=p.fonts["small"], bg=p.bg, fg=p.muted, anchor="w").grid(row=99, column=0, columnspan=4, sticky="w")
        self.buttons("Save product", self.save)
        f.focus_first()

    def save(self):
        data = self.form.get()
        data["id"] = self.product.get("id")
        try:
            self.result = models.save_product(self.app.db, data)
        except models.ValidationError as e:
            show_error(self, str(e))
            return
        self.close()


class ProductsPage(tk.Frame):
    name = "products"

    def __init__(self, master, app):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app = app
        self.header = PageHeader(self, app, "Products & Services", "Reusable line items with default prices")
        self.header.pack(fill="x", padx=28, pady=(24, 12))
        self.header.button("+ Add product", self.add, "primary")

        bar = tk.Frame(self, bg=p.bg)
        bar.pack(fill="x", padx=28, pady=(0, 10))
        self.search = SearchEntry(bar, app, "Search name, SKU, description...", self.refresh, width=40)
        self.search.pack(side="left")
        self.show_inactive = tk.BooleanVar(value=False)
        tb.Checkbutton(bar, text="Show inactive", variable=self.show_inactive, command=self.refresh,
                       bootstyle="round-toggle").pack(side="left", padx=16)
        actions = tk.Frame(bar, bg=p.bg)
        actions.pack(side="right")
        button(actions, "Edit", self.edit, "secondary-outline").pack(side="left", padx=(0, 6))
        button(actions, "Delete", self.delete, "danger-outline").pack(side="left")

        card = Card(self, app, padding=0)
        card.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        self.table = DataTable(card, app, [
            {"key": "sku", "title": "SKU", "width": 110},
            {"key": "name", "title": "Name", "width": 220},
            {"key": "description", "title": "Description", "width": 300, "stretch": True},
            {"key": "unit", "title": "Unit", "width": 70},
            {"key": "unit_price", "title": "Unit price", "width": 130, "anchor": "e"},
            {"key": "tax_rate", "title": "Tax %", "width": 80, "anchor": "e"},
            {"key": "active", "title": "Status", "width": 90},
        ], height=18, on_double=lambda r: self.edit())
        self.table.pack(fill="both", expand=True, padx=2, pady=2)

    def refresh(self, *_, **__):
        rows = models.list_products(self.app.db, self.search.get(), active_only=not self.show_inactive.get())
        self.table.set_rows(rows, lambda r: [r["sku"], r["name"], (r["description"] or "").replace("\n", " "), r["unit"],
                                             fmt_money(self.app, r["unit_price"]),
                                             "default" if r["tax_rate"] is None else fmt_number(r["tax_rate"]),
                                             "Active" if r["active"] else "Inactive"])
        if rows:
            self.table.hide_empty()
        elif self.search.get():
            self.table.show_empty("No products match your search")
        else:
            self.table.show_empty("No products or services yet", "Add items once, then pick them on any invoice.",
                                  "Add product", self.add)

    def _selected(self):
        row = self.table.selected()
        if not row:
            show_info(self, "Select a product first.", "No selection")
        return row

    def add(self):
        if ProductDialog(self, self.app).show():
            self.refresh()

    def edit(self):
        row = self._selected()
        if row and ProductDialog(self, self.app, row).show():
            self.refresh()

    def delete(self):
        row = self._selected()
        if row and ask_yes_no(self, f"Delete '{row['name']}'?\nExisting invoice lines keep their text and price.",
                              "Delete product"):
            models.delete_product(self.app.db, row["id"])
            self.refresh()
