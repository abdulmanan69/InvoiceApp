"""Products / services page: searchable list + add/edit/delete with cost price, sale price and stock settings."""
from __future__ import annotations

import tkinter as tk

import ttkbootstrap as tb

import models
from ui_common import (Card, DataTable, Dialog, Form, PageHeader, SearchEntry, ask_yes_no, button, fmt_money,
                       show_error, show_info)
from utils import fmt_number


class ProductDialog(Dialog):
    def __init__(self, parent, app, product: dict | None = None):
        super().__init__(parent, app, "Edit product / service" if product else "New product / service", width=720)
        self.product = product or {}
        pr = self.product
        owner = app.is_owner
        f = Form(self.body, app, columns=2)
        self.form = f
        f.entry("Name *", "name", pr.get("name", ""), span=2)
        f.entry("SKU / code", "sku", pr.get("sku", ""))
        f.entry("Unit", "unit", pr.get("unit", "pcs"))
        f.entry("Sale price *", "unit_price", fmt_number(pr.get("unit_price", 0)) if pr else "")
        if owner:
            f.entry("Cost price (bought at)", "cost_price", fmt_number(pr.get("cost_price", 0)) if pr else "")
        else:
            f._next()
        f.entry("Tax % override", "tax_rate", "" if pr.get("tax_rate") is None else fmt_number(pr.get("tax_rate")))
        f.entry("Low-stock alert at", "low_stock_level", fmt_number(pr.get("low_stock_level", 0)) if pr and pr.get("low_stock_level") else "")
        if not pr and owner:
            f.entry("Opening stock", "opening_stock", "")
        else:
            f._next()
        f.text("Description", "description", pr.get("description", ""), span=2, height=3)
        f.check("Track stock (invoices cannot exceed what is in stock)", "track_stock", pr.get("track_stock", 1) in (1, True), span=2)
        f.check("Active (available for new invoices)", "active", pr.get("active", 1) in (1, True), span=2)
        p = app.palette
        tk.Label(self.body, text="Blank tax override = document default. Blank low-stock level = the global threshold from Settings.\n"
                                 "Untick 'Track stock' for services or items you never run out of.",
                 font=p.fonts["small"], bg=p.bg, fg=p.muted, anchor="w", justify="left").grid(row=99, column=0, columnspan=4, sticky="w")
        self.buttons("Save product", self.save)
        f.focus_first()

    def save(self):
        data = self.form.get()
        data["id"] = self.product.get("id")
        if self.product and "cost_price" not in data:
            data["cost_price"] = self.product.get("cost_price", 0)
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
        self.owner = app.is_owner
        self.header = PageHeader(self, app, "Products & Services", "Reusable line items with prices and stock tracking")
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
        if self.owner:
            button(actions, "Delete", self.delete, "danger-outline").pack(side="left")

        card = Card(self, app, padding=0)
        card.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        cols = [
            {"key": "sku", "title": "SKU", "width": 100},
            {"key": "name", "title": "Name", "width": 220},
            {"key": "description", "title": "Description", "width": 240, "stretch": True},
            {"key": "unit", "title": "Unit", "width": 60},
            {"key": "stock", "title": "In stock", "width": 90, "anchor": "e"},
        ]
        if self.owner:
            cols += [{"key": "cost", "title": "Cost", "width": 100, "anchor": "e"},
                     {"key": "unit_price", "title": "Sale price", "width": 110, "anchor": "e"},
                     {"key": "margin", "title": "Margin", "width": 70, "anchor": "e"}]
        else:
            cols += [{"key": "unit_price", "title": "Sale price", "width": 110, "anchor": "e"}]
        cols += [{"key": "tax_rate", "title": "Tax %", "width": 70, "anchor": "e"},
                 {"key": "active", "title": "Status", "width": 80}]
        self.table = DataTable(card, app, cols, height=18, on_double=lambda r: self.edit())
        self.table.pack(fill="both", expand=True, padx=2, pady=2)

    def refresh(self, *_, **__):
        rows = models.list_products(self.app.db, self.search.get(), active_only=not self.show_inactive.get())

        def fmt(r):
            vals = [r["sku"], r["name"], (r["description"] or "").replace("\n", " "), r["unit"],
                    fmt_number(r["stock"]) if r.get("track_stock") else "-"]
            if self.owner:
                cost, price = float(r.get("cost_price") or 0), float(r.get("unit_price") or 0)
                vals += [fmt_money(self.app, cost), fmt_money(self.app, price),
                         f"{(price - cost) / price * 100:.0f}%" if price else "-"]
            else:
                vals += [fmt_money(self.app, r["unit_price"])]
            return vals + ["default" if r["tax_rate"] is None else fmt_number(r["tax_rate"]),
                           "Active" if r["active"] else "Inactive"]

        self.table.set_rows(rows, fmt)
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
        if row and ask_yes_no(self, f"Delete '{row['name']}'?\nExisting invoice lines keep their text and price; its stock "
                                    "history is removed.", "Delete product"):
            models.delete_product(self.app.db, row["id"])
            self.refresh()
