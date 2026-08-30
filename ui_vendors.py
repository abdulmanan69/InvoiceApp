"""Vendors page: list + add/edit/delete."""
from __future__ import annotations

import tkinter as tk

import models
from ui_common import Card, DataTable, Dialog, Form, PageHeader, SearchEntry, ask_yes_no, button, show_error, show_info


class VendorDialog(Dialog):
    def __init__(self, parent, app, vendor: dict | None = None):
        super().__init__(parent, app, "Edit vendor" if vendor else "New vendor", width=700)
        self.vendor = vendor or {}
        v = self.vendor
        f = Form(self.body, app, columns=2)
        self.form = f
        f.entry("Name *", "name", v.get("name", ""))
        f.entry("Company", "company", v.get("company", ""))
        f.entry("Phone", "phone", v.get("phone", ""))
        f.entry("Email", "email", v.get("email", ""))
        f.entry("Tax / VAT no.", "tax_number", v.get("tax_number", ""), span=2)
        f.text("Address", "address", v.get("address", ""), span=2, height=3)
        f.text("Notes", "notes", v.get("notes", ""), span=2, height=2)
        self.buttons("Save vendor", self.save)
        f.focus_first()

    def save(self):
        data = self.form.get()
        data["id"] = self.vendor.get("id")
        try:
            self.result = models.save_vendor(self.app.db, data)
        except models.ValidationError as e:
            show_error(self, str(e))
            return
        self.close()


class VendorsPage(tk.Frame):
    name = "vendors"

    def __init__(self, master, app):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app = app
        self.header = PageHeader(self, app, "Vendors", "Suppliers and services you purchase from")
        self.header.pack(fill="x", padx=28, pady=(24, 12))
        self.header.button("+ Add vendor", self.add, "primary")

        bar = tk.Frame(self, bg=p.bg)
        bar.pack(fill="x", padx=28, pady=(0, 10))
        self.search = SearchEntry(bar, app, "Search vendors...", self.refresh, width=40)
        self.search.pack(side="left")
        actions = tk.Frame(bar, bg=p.bg)
        actions.pack(side="right")
        button(actions, "Edit", self.edit, "secondary-outline").pack(side="left", padx=(0, 6))
        button(actions, "Delete", self.delete, "danger-outline").pack(side="left")

        card = Card(self, app, padding=0)
        card.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        self.table = DataTable(card, app, [
            {"key": "name", "title": "Name", "width": 200},
            {"key": "company", "title": "Company", "width": 200},
            {"key": "phone", "title": "Phone", "width": 130},
            {"key": "email", "title": "Email", "width": 200},
            {"key": "tax_number", "title": "Tax no.", "width": 120},
            {"key": "address", "title": "Address", "width": 240, "stretch": True},
        ], height=18, on_double=lambda r: self.edit())
        self.table.pack(fill="both", expand=True, padx=2, pady=2)

    def refresh(self, *_, **__):
        rows = models.list_vendors(self.app.db, self.search.get())
        self.table.set_rows(rows, lambda r: [r["name"], r["company"], r["phone"], r["email"], r["tax_number"],
                                             (r["address"] or "").replace("\n", ", ")])
        if rows:
            self.table.hide_empty()
        elif self.search.get():
            self.table.show_empty("No vendors match your search")
        else:
            self.table.show_empty("No vendors yet", "Keep track of the suppliers you buy from.", "Add vendor", self.add)

    def _selected(self):
        row = self.table.selected()
        if not row:
            show_info(self, "Select a vendor first.", "No selection")
        return row

    def add(self):
        if VendorDialog(self, self.app).show():
            self.refresh()

    def edit(self):
        row = self._selected()
        if row and VendorDialog(self, self.app, row).show():
            self.refresh()

    def delete(self):
        row = self._selected()
        if row and ask_yes_no(self, f"Delete vendor '{row['name']}'? This cannot be undone.", "Delete vendor"):
            models.delete_vendor(self.app.db, row["id"])
            self.refresh()
