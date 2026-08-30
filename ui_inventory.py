"""Inventory: stock levels, purchases from vendors, customer/vendor returns, best sellers, stock history."""
from __future__ import annotations

import tkinter as tk

import ttkbootstrap as tb

import models
from ui_common import (Card, DataTable, DateField, Dialog, Form, IdCombo, PageHeader, SearchEntry, ask_yes_no, button,
                       fmt_day, fmt_money, show_error, show_info)
from ui_vendors import VendorDialog
from utils import fmt_number, parse_float, today_iso


# =========================================================================== shared line grid
class LineGrid(tk.Frame):
    """Editable rows: product combo | description | qty | unit price/cost | line total | remove."""

    def __init__(self, master, app, products: list[dict], price_key="unit_price", price_title="Unit price",
                 on_change=None, product_required=True, height=200):
        p = app.palette
        super().__init__(master, bg=p.card)
        self.app, self.products, self.price_key, self.on_change = app, products, price_key, on_change
        self.product_required = product_required
        self.rows: list[dict] = []
        hdr = tk.Frame(self, bg=p.card)
        hdr.pack(fill="x")
        self.weights = (3, 5, 1, 2, 2, 0)
        for c, (text, w, anchor) in enumerate((("Product", 3, "w"), ("Description", 5, "w"), ("Qty", 1, "e"),
                                               (price_title, 2, "e"), ("Line total", 2, "e"), ("", 0, "w"))):
            hdr.grid_columnconfigure(c, weight=w, minsize=(44 if w == 0 else 0))
            tk.Label(hdr, text=text.upper(), font=p.fonts["small_bold"], bg=p.card, fg=p.muted, anchor=anchor).grid(
                row=0, column=c, sticky="ew", padx=(0, 4))
        self.box = tb.ScrolledFrame(self, auto_hide=True, height=height)
        self.box.pack(fill="both", expand=True, pady=(4, 4))
        foot = tk.Frame(self, bg=p.card)
        foot.pack(fill="x")
        button(foot, "+ Add line", lambda: self.add_row(), "outline").pack(side="left")
        self.total_label = tk.Label(foot, text="", font=p.fonts["heading"], bg=p.card, fg=p.fg)
        self.total_label.pack(side="right")

    def add_row(self, item: dict | None = None):
        p = self.app.palette
        item = item or {}
        fr = tk.Frame(self.box, bg=p.card)
        fr.pack(fill="x", pady=2)
        for c, w in enumerate(self.weights):
            fr.grid_columnconfigure(c, weight=w, minsize=(44 if w == 0 else 0))
        row = {"frame": fr, "product": IdCombo(fr, [(pr["id"], f"{pr['name']} ({fmt_number(pr.get('stock', 0))} {pr.get('unit') or ''})".strip())
                                                   for pr in self.products], blank_label="(none)" if not self.product_required else "(choose)", width=24),
               "desc": tk.StringVar(value=item.get("description", "")),
               "qty": tk.StringVar(value=fmt_number(item.get("quantity", 1)) if item else "1"),
               "price": tk.StringVar(value=fmt_number(item.get(self.price_key, 0)) if item else "")}
        row["product"].grid(row=0, column=0, sticky="ew", padx=(0, 4))
        row["product"].bind("<<ComboboxSelected>>", lambda e, r=row: self._on_product(r))
        tb.Entry(fr, textvariable=row["desc"]).grid(row=0, column=1, sticky="ew", padx=(0, 4))
        tb.Entry(fr, textvariable=row["qty"], width=7, justify="right").grid(row=0, column=2, sticky="ew", padx=(0, 4))
        tb.Entry(fr, textvariable=row["price"], width=12, justify="right").grid(row=0, column=3, sticky="ew", padx=(0, 4))
        row["total"] = tk.Label(fr, text="", font=p.fonts["bold"], bg=p.card, fg=p.fg, anchor="e", width=14)
        row["total"].grid(row=0, column=4, sticky="ew", padx=(0, 4))
        tb.Button(fr, text="✕", bootstyle="danger-link", width=3, command=lambda r=row: self.remove_row(r)).grid(row=0, column=5)
        for var in (row["qty"], row["price"], row["desc"]):
            var.trace_add("write", lambda *_: self.recalc())
        if item.get("product_id"):
            row["product"].set_id(item["product_id"])
        self.rows.append(row)
        self.recalc()
        return row

    def _on_product(self, row):
        pid = row["product"].get_id()
        pr = next((x for x in self.products if x["id"] == pid), None)
        if not pr:
            return
        if not row["desc"].get().strip():
            row["desc"].set(pr["name"])
        if not row["price"].get().strip():
            row["price"].set(fmt_number(pr.get("cost_price" if self.price_key == "unit_cost" else "unit_price") or 0))
        self.recalc()

    def remove_row(self, row):
        if row in self.rows:
            self.rows.remove(row)
            row["frame"].destroy()
        self.recalc()

    def recalc(self):
        total = 0.0
        for r in self.rows:
            line = round((parse_float(r["qty"].get(), 0) or 0) * (parse_float(r["price"].get(), 0) or 0), 2)
            r["total"].configure(text=fmt_money(self.app, line))
            total += line
        self.total_label.configure(text=f"Total  {fmt_money(self.app, total)}")
        if self.on_change:
            self.on_change(total)

    def data(self) -> list[dict]:
        return [{"product_id": r["product"].get_id(), "description": r["desc"].get(), "quantity": r["qty"].get(),
                 self.price_key: r["price"].get()} for r in self.rows]


# =========================================================================== dialogs
class PurchaseDialog(Dialog):
    def __init__(self, parent, app, purchase_id=None):
        self.purchase = models.get_purchase(app.db, purchase_id) if purchase_id else None
        super().__init__(parent, app, "Edit purchase" if self.purchase else "New purchase from vendor", width=980, height=640)
        p = app.palette
        pu = self.purchase or {}
        head = Card(self.body, app, padding=14)
        head.pack(fill="x")
        head.grid_columnconfigure(1, weight=1)
        head.grid_columnconfigure(3, weight=1)

        def lbl(text, r, c):
            tk.Label(head, text=text, font=p.fonts["small_bold"], bg=p.card, fg=p.muted).grid(row=r, column=c, sticky="w",
                                                                                              padx=(0 if c == 0 else 14, 6), pady=4)

        lbl("VENDOR", 0, 0)
        vbox = tk.Frame(head, bg=p.card)
        vbox.grid(row=0, column=1, sticky="ew", pady=4)
        self.vendor = IdCombo(vbox, [], blank_label="(no vendor)")
        self.vendor.pack(side="left", fill="x", expand=True)
        button(vbox, "+ New", self.new_vendor, "secondary-outline").pack(side="left", padx=(6, 0))
        self.reload_vendors(pu.get("vendor_id"))
        lbl("PURCHASE NO.", 0, 2)
        self.number = tk.StringVar(value=pu.get("number") or models.next_purchase_number(app.db))
        tb.Entry(head, textvariable=self.number, width=14).grid(row=0, column=3, sticky="w", pady=4)
        lbl("DATE", 1, 0)
        self.date = DateField(head, app, pu.get("date") or today_iso(), bg=p.card)
        self.date.grid(row=1, column=1, sticky="w", pady=4)
        lbl("REFERENCE / BILL NO.", 1, 2)
        self.reference = tk.StringVar(value=pu.get("reference", ""))
        tb.Entry(head, textvariable=self.reference).grid(row=1, column=3, sticky="ew", pady=4)
        lbl("NOTES", 2, 0)
        self.notes = tk.StringVar(value=pu.get("notes", ""))
        tb.Entry(head, textvariable=self.notes).grid(row=2, column=1, columnspan=3, sticky="ew", pady=4)

        lines = Card(self.body, app, padding=14)
        lines.pack(fill="both", expand=True, pady=(10, 0))
        self.grid = LineGrid(lines, app, models.list_products(app.db, active_only=True), "unit_cost", "Unit cost")
        self.grid.pack(fill="both", expand=True)
        for it in pu.get("items", []):
            self.grid.add_row(it)
        if not self.grid.rows:
            self.grid.add_row()
        self.update_cost = tk.BooleanVar(value=True)
        tb.Checkbutton(lines, text="Update each product's cost price to the cost entered here", variable=self.update_cost,
                       bootstyle="round-toggle").pack(anchor="w", pady=(8, 0))
        self.buttons("Save purchase", self.save)

    def reload_vendors(self, select_id=None):
        self.vendor.set_options([(v["id"], v["name"]) for v in models.list_vendors(self.app.db)])
        if select_id:
            self.vendor.set_id(select_id)

    def new_vendor(self):
        vid = VendorDialog(self, self.app).show()
        if vid:
            self.reload_vendors(vid)

    def save(self):
        data = {"id": (self.purchase or {}).get("id"), "number": self.number.get(), "vendor_id": self.vendor.get_id(),
                "date": self.date.get(), "reference": self.reference.get(), "notes": self.notes.get(),
                "update_cost": self.update_cost.get()}
        try:
            self.result = models.save_purchase(self.app.db, data, self.grid.data(), self.app.user)
        except models.ValidationError as e:
            show_error(self, str(e), "Cannot save")
            return
        self.close()


class ReturnDialog(Dialog):
    """kind='customer': goods come back from a customer (optionally against an invoice, credit reduces balance).
    kind='vendor': goods go back to a vendor (optionally against a purchase)."""

    def __init__(self, parent, app, kind: str, invoice: dict | None = None):
        self.kind = kind
        title = "Customer return (items received back)" if kind == "customer" else "Return items to vendor"
        super().__init__(parent, app, title, width=980, height=640)
        p = app.palette
        self.invoice = invoice
        head = Card(self.body, app, padding=14)
        head.pack(fill="x")
        head.grid_columnconfigure(1, weight=1)
        head.grid_columnconfigure(3, weight=1)

        def lbl(text, r, c):
            tk.Label(head, text=text, font=p.fonts["small_bold"], bg=p.card, fg=p.muted).grid(row=r, column=c, sticky="w",
                                                                                              padx=(0 if c == 0 else 14, 6), pady=4)

        lbl("RETURN NO.", 0, 0)
        self.number = tk.StringVar(value=models.next_return_number(app.db))
        tb.Entry(head, textvariable=self.number, width=14).grid(row=0, column=1, sticky="w", pady=4)
        lbl("DATE", 0, 2)
        self.date = DateField(head, app, today_iso(), bg=p.card)
        self.date.grid(row=0, column=3, sticky="w", pady=4)
        if kind == "customer":
            lbl("INVOICE", 1, 0)
            invoices = models.list_documents(app.db, models.INVOICE)
            self.ref = IdCombo(head, [(d["id"], f"{d['number']} - {d['customer_display']} ({fmt_money(app, d['total'])})") for d in invoices],
                               blank_label="(not linked to an invoice)")
            self.ref.grid(row=1, column=1, sticky="ew", pady=4)
            self.ref.bind("<<ComboboxSelected>>", lambda e: self.load_from_ref())
            lbl("CUSTOMER", 1, 2)
            self.party = IdCombo(head, [(c["id"], c["name"]) for c in models.list_customers(app.db)], blank_label="(none)")
            self.party.grid(row=1, column=3, sticky="ew", pady=4)
        else:
            lbl("VENDOR", 1, 0)
            self.party = IdCombo(head, [(v["id"], v["name"]) for v in models.list_vendors(app.db)], blank_label="(none)")
            self.party.grid(row=1, column=1, sticky="ew", pady=4)
            lbl("PURCHASE", 1, 2)
            purchases = models.list_purchases(app.db)
            self.ref = IdCombo(head, [(pu["id"], f"{pu['number']} - {pu['vendor_display']} ({fmt_money(app, pu['total'])})") for pu in purchases],
                               blank_label="(not linked to a purchase)")
            self.ref.grid(row=1, column=3, sticky="ew", pady=4)
            self.ref.bind("<<ComboboxSelected>>", lambda e: self.load_from_ref())
        lbl("REASON", 2, 0)
        self.reason = tk.StringVar()
        tb.Entry(head, textvariable=self.reason).grid(row=2, column=1, columnspan=3, sticky="ew", pady=4)

        lines = Card(self.body, app, padding=14)
        lines.pack(fill="both", expand=True, pady=(10, 0))
        products = models.list_products(app.db)
        self.grid = LineGrid(lines, app, products, "unit_price", "Unit price" if kind == "customer" else "Unit cost",
                             product_required=(kind == "vendor"))
        self.grid.pack(fill="both", expand=True)
        self.restock = tk.BooleanVar(value=True)
        if kind == "customer":
            tb.Checkbutton(lines, text="Put returned items back into stock", variable=self.restock,
                           bootstyle="round-toggle").pack(anchor="w", pady=(8, 0))
            hint = "Credit = sum of the lines; it reduces the invoice balance. Quantities are the amounts coming back."
        else:
            hint = "Quantities leave your stock. Unit cost is what the vendor refunds or credits you."
        tk.Label(lines, text=hint, font=p.fonts["small"], bg=p.card, fg=p.muted, anchor="w").pack(anchor="w", pady=(4, 0))
        if invoice:
            self.ref.set_id(invoice["id"])
            self.load_from_ref()
        if not self.grid.rows:
            self.grid.add_row()
        self.buttons("Save return", self.save)

    def load_from_ref(self):
        ref_id = self.ref.get_id()
        for r in list(self.grid.rows):
            self.grid.remove_row(r)
        if not ref_id:
            self.grid.add_row()
            return
        if self.kind == "customer":
            doc = models.get_document(self.app.db, ref_id)
            if doc:
                if doc.get("customer_id"):
                    self.party.set_id(doc["customer_id"])
                for it in doc.get("items", []):
                    self.grid.add_row({"product_id": it.get("product_id"), "description": it.get("description"),
                                       "quantity": it.get("quantity"), "unit_price": it.get("unit_price")})
        else:
            pu = models.get_purchase(self.app.db, ref_id)
            if pu:
                if pu.get("vendor_id"):
                    self.party.set_id(pu["vendor_id"])
                for it in pu.get("items", []):
                    self.grid.add_row({"product_id": it.get("product_id"), "description": it.get("description"),
                                       "quantity": it.get("quantity"), "unit_price": it.get("unit_cost")})
        if not self.grid.rows:
            self.grid.add_row()

    def save(self):
        data = {"kind": self.kind, "number": self.number.get(), "date": self.date.get(), "reason": self.reason.get(),
                "restock": self.restock.get()}
        if self.kind == "customer":
            data["invoice_id"], data["customer_id"] = self.ref.get_id(), self.party.get_id()
        else:
            data["purchase_id"], data["vendor_id"] = self.ref.get_id(), self.party.get_id()
        try:
            self.result = models.save_return(self.app.db, data, self.grid.data(), self.app.user)
        except models.ValidationError as e:
            show_error(self, str(e), "Cannot save")
            return
        self.close()


class AdjustStockDialog(Dialog):
    def __init__(self, parent, app, product: dict):
        super().__init__(parent, app, f"Adjust stock - {product['name']}", width=460)
        self.product = product
        p = app.palette
        tk.Label(self.body, text=f"Current stock: {fmt_number(product.get('stock', 0))} {product.get('unit') or ''}",
                 font=p.fonts["heading"], bg=p.bg, fg=p.fg, anchor="w").pack(fill="x", pady=(0, 10))
        box = tk.Frame(self.body, bg=p.bg)
        box.pack(fill="x")
        self.form = Form(box, app, columns=1, label_width=16)
        self.form.entry("New quantity", "qty", fmt_number(product.get("stock", 0)))
        self.form.entry("Note", "note", "Stock count")
        self.buttons("Save adjustment", self.save)
        self.form.widgets["qty"].focus_set()
        self.form.widgets["qty"].select_range(0, "end")

    def save(self):
        d = self.form.get()
        try:
            models.adjust_stock(self.app.db, self.product["id"], d["qty"], d["note"], self.app.user)
        except models.ValidationError as e:
            show_error(self, str(e))
            return
        self.result = True
        self.close()


class HistoryDialog(Dialog):
    def __init__(self, parent, app, product: dict | None = None):
        super().__init__(parent, app, f"Stock history - {product['name']}" if product else "Stock movements", width=900, height=560)
        cols = [{"key": "date", "title": "Date", "width": 100}, {"key": "product", "title": "Product", "width": 220, "stretch": True},
                {"key": "kind", "title": "Type", "width": 130}, {"key": "qty", "title": "Qty", "width": 90, "anchor": "e"},
                {"key": "cost", "title": "Unit cost", "width": 110, "anchor": "e"}, {"key": "note", "title": "Note", "width": 220}]
        table = DataTable(self.body, app, cols, height=18)
        table.pack(fill="both", expand=True)
        rows = models.stock_history(app.db, product["id"] if product else None, 500)
        table.set_rows(rows, lambda r: [fmt_day(app, r["date"]), r["product_name"], r["kind_label"],
                                        ("+" if r["qty"] > 0 else "") + fmt_number(r["qty"]), fmt_money(app, r["unit_cost"]), r["note"]])
        if not rows:
            table.show_empty("No stock movements yet", "Purchases, sales and returns will appear here.")
        self.buttons(None, None, cancel_text="Close")


# =========================================================================== page
class InventoryPage(tk.Frame):
    name = "inventory"

    def __init__(self, master, app):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app = app
        self.owner = app.is_owner
        self.header = PageHeader(self, app, "Inventory", "Stock levels, purchases from vendors, returns and best sellers")
        self.header.pack(fill="x", padx=28, pady=(24, 12))
        if self.owner:
            self.header.button("Return to vendor", lambda: self.new_return("vendor"), "secondary-outline")
            self.header.button("Customer return", lambda: self.new_return("customer"), "secondary-outline")
            self.header.button("+ New purchase", self.new_purchase, "primary")
        self.nb = tb.Notebook(self, bootstyle="primary")
        self.nb.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        self.tab_stock()
        if self.owner:
            self.tab_purchases()
            self.tab_returns()
            self.tab_best()
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self.refresh())

    # ------------------------------------------------------------------ tabs
    def _tab(self, title):
        p = self.app.palette
        outer = tk.Frame(self.nb, bg=p.bg)
        self.nb.add(outer, text=title)
        return outer

    def tab_stock(self):
        p = self.app.palette
        outer = self._tab("Stock")
        bar = tk.Frame(outer, bg=p.bg)
        bar.pack(fill="x", pady=(10, 8))
        self.stock_search = SearchEntry(bar, self.app, "Search product / SKU...", self.refresh, width=32)
        self.stock_search.pack(side="left")
        self.low_only = tk.BooleanVar(value=False)
        tb.Checkbutton(bar, text="Low stock only", variable=self.low_only, command=self.refresh, bootstyle="round-toggle").pack(side="left", padx=14)
        acts = tk.Frame(bar, bg=p.bg)
        acts.pack(side="right")
        button(acts, "History", self.history, "secondary-outline").pack(side="left", padx=(0, 6))
        if self.owner:
            button(acts, "Adjust stock", self.adjust, "outline").pack(side="left")
        cols = [{"key": "sku", "title": "SKU", "width": 100}, {"key": "name", "title": "Product", "width": 240, "stretch": True},
                {"key": "unit", "title": "Unit", "width": 60}, {"key": "stock", "title": "In stock", "width": 100, "anchor": "e"},
                {"key": "low", "title": "Low at", "width": 80, "anchor": "e"}]
        if self.owner:
            cols += [{"key": "cost", "title": "Cost price", "width": 110, "anchor": "e"},
                     {"key": "price", "title": "Sale price", "width": 110, "anchor": "e"},
                     {"key": "margin", "title": "Margin", "width": 80, "anchor": "e"},
                     {"key": "value", "title": "Stock value", "width": 120, "anchor": "e"}]
        else:
            cols += [{"key": "price", "title": "Sale price", "width": 110, "anchor": "e"}]
        cols.append({"key": "status", "title": "Status", "width": 90})
        card = Card(outer, self.app, padding=0)
        card.pack(fill="both", expand=True)
        self.stock_table = DataTable(card, self.app, cols, height=16, status_key="status", on_double=lambda r: self.history())
        self.stock_table.tree.tag_configure("st_Low", foreground=p.danger)
        self.stock_table.tree.tag_configure("st_OK", foreground=p.fg)
        self.stock_table.tree.tag_configure("st_Out", foreground=p.danger)
        self.stock_table.pack(fill="both", expand=True, padx=2, pady=2)
        self.stock_summary = tk.Label(outer, text="", font=p.fonts["base"], bg=p.bg, fg=p.muted, anchor="w")
        self.stock_summary.pack(fill="x", pady=(8, 0))

    def tab_purchases(self):
        p = self.app.palette
        outer = self._tab("Purchases")
        bar = tk.Frame(outer, bg=p.bg)
        bar.pack(fill="x", pady=(10, 8))
        self.pur_search = SearchEntry(bar, self.app, "Search number, vendor, reference...", self.refresh, width=32)
        self.pur_search.pack(side="left")
        acts = tk.Frame(bar, bg=p.bg)
        acts.pack(side="right")
        button(acts, "Delete", self.delete_purchase, "danger-outline").pack(side="left", padx=(0, 6))
        button(acts, "View / edit", self.edit_purchase, "outline").pack(side="left")
        card = Card(outer, self.app, padding=0)
        card.pack(fill="both", expand=True)
        self.pur_table = DataTable(card, self.app, [
            {"key": "number", "title": "Number", "width": 110}, {"key": "date", "title": "Date", "width": 100},
            {"key": "vendor", "title": "Vendor", "width": 220, "stretch": True}, {"key": "reference", "title": "Reference", "width": 160},
            {"key": "items", "title": "Lines", "width": 60, "anchor": "e"}, {"key": "total", "title": "Total", "width": 130, "anchor": "e"},
            {"key": "by", "title": "By", "width": 120}], height=16, on_double=lambda r: self.edit_purchase())
        self.pur_table.pack(fill="both", expand=True, padx=2, pady=2)

    def tab_returns(self):
        p = self.app.palette
        outer = self._tab("Returns")
        bar = tk.Frame(outer, bg=p.bg)
        bar.pack(fill="x", pady=(10, 8))
        self.ret_search = SearchEntry(bar, self.app, "Search number, customer, vendor...", self.refresh, width=32)
        self.ret_search.pack(side="left")
        tk.Label(bar, text="Type", font=p.fonts["base"], bg=p.bg, fg=p.muted).pack(side="left", padx=(14, 4))
        self.ret_kind = tb.Combobox(bar, values=["All", "Customer returns", "Vendor returns"], state="readonly", width=16)
        self.ret_kind.current(0)
        self.ret_kind.pack(side="left")
        self.ret_kind.bind("<<ComboboxSelected>>", self.refresh)
        acts = tk.Frame(bar, bg=p.bg)
        acts.pack(side="right")
        button(acts, "Delete", self.delete_return, "danger-outline").pack(side="left")
        card = Card(outer, self.app, padding=0)
        card.pack(fill="both", expand=True)
        self.ret_table = DataTable(card, self.app, [
            {"key": "number", "title": "Number", "width": 110}, {"key": "date", "title": "Date", "width": 100},
            {"key": "kind", "title": "Type", "width": 90}, {"key": "party", "title": "Customer / Vendor", "width": 200, "stretch": True},
            {"key": "ref", "title": "Invoice / Purchase", "width": 130}, {"key": "reason", "title": "Reason", "width": 180},
            {"key": "items", "title": "Lines", "width": 60, "anchor": "e"}, {"key": "total", "title": "Value", "width": 120, "anchor": "e"},
            {"key": "restock", "title": "Stock", "width": 90}], height=16)
        self.ret_table.pack(fill="both", expand=True, padx=2, pady=2)

    def tab_best(self):
        p = self.app.palette
        outer = self._tab("Best sellers")
        bar = tk.Frame(outer, bg=p.bg)
        bar.pack(fill="x", pady=(10, 8))
        tk.Label(bar, text="From", font=p.fonts["base"], bg=p.bg, fg=p.muted).pack(side="left", padx=(0, 4))
        self.best_from = DateField(bar, self.app, width=10)
        self.best_from.pack(side="left")
        tk.Label(bar, text="To", font=p.fonts["base"], bg=p.bg, fg=p.muted).pack(side="left", padx=(12, 4))
        self.best_to = DateField(bar, self.app, width=10)
        self.best_to.pack(side="left")
        button(bar, "Apply", self.refresh, "outline").pack(side="left", padx=(10, 0))
        button(bar, "All time", lambda: (self.best_from.set(""), self.best_to.set(""), self.refresh()), "link").pack(side="left")
        card = Card(outer, self.app, padding=0)
        card.pack(fill="both", expand=True)
        self.best_table = DataTable(card, self.app, [
            {"key": "rank", "title": "#", "width": 40}, {"key": "name", "title": "Product", "width": 260, "stretch": True},
            {"key": "qty", "title": "Qty sold", "width": 100, "anchor": "e"}, {"key": "invoices", "title": "Invoices", "width": 80, "anchor": "e"},
            {"key": "revenue", "title": "Revenue", "width": 130, "anchor": "e"}, {"key": "cost", "title": "Cost", "width": 120, "anchor": "e"},
            {"key": "profit", "title": "Gross profit", "width": 130, "anchor": "e"}], height=16)
        self.best_table.pack(fill="both", expand=True, padx=2, pady=2)

    # ------------------------------------------------------------------ refresh
    def refresh(self, *_, **__):
        a = self.app
        products = models.list_products(a.db, self.stock_search.get())
        threshold = parse_float(a.settings.get("low_stock_threshold"), 5) or 0

        def status(pr):
            if not pr.get("track_stock"):
                return "n/a"
            level = pr["low_stock_level"] if (pr.get("low_stock_level") or 0) > 0 else threshold
            return "Out" if pr["stock"] <= 0 else ("Low" if pr["stock"] <= level else "OK")

        for pr in products:
            pr["status"] = status(pr)
        if self.low_only.get():
            products = [pr for pr in products if pr["status"] in ("Low", "Out")]

        def fmt(pr):
            vals = [pr["sku"], pr["name"], pr["unit"], fmt_number(pr["stock"]) if pr.get("track_stock") else "-",
                    fmt_number(pr["low_stock_level"]) if pr.get("low_stock_level") else fmt_number(threshold)]
            if self.owner:
                cost, price = float(pr.get("cost_price") or 0), float(pr.get("unit_price") or 0)
                margin = f"{(price - cost) / price * 100:.0f}%" if price else "-"
                vals += [fmt_money(a, cost), fmt_money(a, price), margin, fmt_money(a, max(pr["stock"], 0) * cost)]
            else:
                vals += [fmt_money(a, pr.get("unit_price"))]
            return vals + [pr["status"]]

        self.stock_table.set_rows(products, fmt)
        if products:
            self.stock_table.hide_empty()
        else:
            self.stock_table.show_empty("No products", "Add products first, then record purchases to build stock.",
                                        "Go to products", lambda: a.navigate("products"))
        low = sum(1 for pr in products if pr["status"] in ("Low", "Out"))
        text = f"{len(products)} product(s)   -   {low} low / out of stock"
        if self.owner:
            text += f"   -   stock value {fmt_money(a, models.stock_value(a.db))}"
        self.stock_summary.configure(text=text)
        if not self.owner:
            return
        rows = models.list_purchases(a.db, self.pur_search.get())
        self.pur_table.set_rows(rows, lambda r: [r["number"], fmt_day(a, r["date"]), r["vendor_display"], r["reference"],
                                                 r["item_count"], fmt_money(a, r["total"]), r["created_by"]])
        if rows:
            self.pur_table.hide_empty()
        else:
            self.pur_table.show_empty("No purchases yet", "Record what you buy from vendors to fill your stock.",
                                      "New purchase", self.new_purchase)
        kind = {"Customer returns": "customer", "Vendor returns": "vendor"}.get(self.ret_kind.get(), "")
        rows = models.list_returns(a.db, kind, self.ret_search.get())
        self.ret_table.set_rows(rows, lambda r: [r["number"], fmt_day(a, r["date"]), "Customer" if r["kind"] == "customer" else "Vendor",
                                                 r["party"], r["ref"], r["reason"], r["item_count"], fmt_money(a, r["total"]),
                                                 ("Restocked" if r["restock"] else "Not restocked") if r["kind"] == "customer" else "Removed"])
        if rows:
            self.ret_table.hide_empty()
        else:
            self.ret_table.show_empty("No returns recorded", "Customer returns credit the invoice; vendor returns remove stock.")
        best = models.best_sellers(a.db, 50, self.best_from.get(), self.best_to.get())
        for n, r in enumerate(best, start=1):
            r["rank"] = n
            r["id"] = f"b{n}"
        self.best_table.set_rows(best, lambda r: [r["rank"], r["name"], fmt_number(r["qty_sold"]), r["invoices"],
                                                  fmt_money(a, r["revenue"]), fmt_money(a, r["cost"]), fmt_money(a, r["profit"])])
        if best:
            self.best_table.hide_empty()
        else:
            self.best_table.show_empty("No sales yet", "Best sellers are ranked by quantity sold on invoices.")

    # ------------------------------------------------------------------ actions
    def _selected_product(self):
        row = self.stock_table.selected()
        if not row:
            show_info(self, "Select a product first.", "No selection")
        return row

    def adjust(self):
        row = self._selected_product()
        if row and AdjustStockDialog(self, self.app, row).show():
            self.refresh()

    def history(self):
        HistoryDialog(self, self.app, self.stock_table.selected()).show()

    def new_purchase(self):
        if PurchaseDialog(self, self.app).show():
            self.app.refresh_all()

    def edit_purchase(self):
        row = self.pur_table.selected()
        if not row:
            show_info(self, "Select a purchase first.", "No selection")
            return
        if PurchaseDialog(self, self.app, row["id"]).show():
            self.app.refresh_all()

    def delete_purchase(self):
        row = self.pur_table.selected()
        if not row:
            show_info(self, "Select a purchase first.", "No selection")
            return
        if ask_yes_no(self, f"Delete purchase {row['number']}? The stock it added will be removed again.", "Delete purchase"):
            models.delete_purchase(self.app.db, row["id"])
            self.app.refresh_all()

    def new_return(self, kind):
        if ReturnDialog(self, self.app, kind).show():
            self.app.refresh_all()

    def delete_return(self):
        row = self.ret_table.selected()
        if not row:
            show_info(self, "Select a return first.", "No selection")
            return
        if ask_yes_no(self, f"Delete return {row['number']}? Its stock movement and credit will be reversed.", "Delete return"):
            models.delete_return(self.app.db, row["id"])
            self.app.refresh_all()
