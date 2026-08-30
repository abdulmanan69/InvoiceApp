"""End-to-end logic tests (no GUI needed).

Run:  python -m unittest tests.test_flow -v
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402
from db import DISPLAY_DEFAULTS, Database  # noqa: E402
from pdf_templates import TEMPLATE_NAMES, render_pdf  # noqa: E402
from theme import build_palette  # noqa: E402


def pdf_pages(path: str) -> int:
    with open(path, "rb") as fh:
        return len(re.findall(rb"/Type\s*/Page[^s]", fh.read()))


class FullFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="invoiceapp_test_")
        self.db = Database(os.path.join(self.tmp, "test.db"))

    def tearDown(self):
        self.db.close()

    def test_full_flow(self):
        db = self.db
        cid = models.save_customer(db, {"name": "Ali Traders", "company": "Ali & Sons", "billing_address": "Lahore"})
        pid = models.save_product(db, {"name": "Consulting", "unit_price": "1,500", "unit": "hr", "tax_rate": "",
                                       "track_stock": 0})
        number = models.next_number(db, models.INVOICE)
        self.assertEqual(number, "INV-0001")
        inv = models.save_document(db, {
            "doc_type": models.INVOICE, "number": number, "customer_id": cid, "date": "2026-08-30",
            "due_date": "2026-09-13", "tax_rate": "17", "discount_type": "percent", "discount_value": "10",
            "display_options": {"show_status": 0, "show_due_date": 0}, "prepared_by": "Ali", "bill_to_label": "Client",
        }, [
            {"product_id": pid, "description": "Consulting", "quantity": "10", "unit": "hr", "unit_price": "1500"},
            {"description": "", "quantity": "", "unit_price": ""},
        ])
        doc = models.get_document(db, inv)
        self.assertEqual(len(doc["items"]), 1)
        self.assertEqual(doc["total"], 15795.0)
        self.assertEqual(doc["status"], models.STATUS_UNPAID)
        self.assertEqual(doc["bill_to_label"], "Client")
        opts = models.document_display_options(db, doc)
        self.assertEqual(opts["show_status"], 0)
        self.assertEqual(opts["show_due_date"], 0)
        self.assertEqual(opts["show_grid"], 1)
        self.assertEqual(models.next_number(db, models.INVOICE), "INV-0002")
        with self.assertRaises(models.ValidationError):
            models.save_document(db, {"doc_type": models.INVOICE, "number": "INV-0001", "date": "2026-08-30",
                                      "tax_rate": 0, "discount_value": 0}, [])
        models.add_payment(db, inv, "5000", "2026-08-30", "Cash")
        self.assertEqual(models.get_document(db, inv)["status"], models.STATUS_PARTIAL)
        with self.assertRaises(models.OverpaymentError):
            models.add_payment(db, inv, 99999, "2026-08-30", "Cash")
        models.mark_as_paid(db, inv, "Bank Transfer")
        doc = models.get_document(db, inv)
        self.assertEqual(doc["status"], models.STATUS_PAID)
        self.assertEqual(len(doc["payments"]), 2)
        self.assertIsNone(models.mark_as_paid(db, inv))
        self.assertEqual(models.compute_status(models.INVOICE, 100, 0, "2020-01-01"), models.STATUS_OVERDUE)
        # quotation -> convert
        q = models.save_document(db, {"doc_type": models.QUOTATION, "number": models.next_number(db, models.QUOTATION),
                                      "customer_id": cid, "date": "2026-08-30", "due_date": "2026-09-29",
                                      "tax_rate": 0, "discount_value": 0}, [{"description": "Widget", "quantity": 2, "unit_price": 100}])
        new_inv = models.convert_quotation_to_invoice(db, q)
        self.assertEqual(models.get_document(db, q)["status"], models.STATUS_CONVERTED)
        self.assertEqual(models.get_document(db, new_inv)["source_quotation_number"], "QT-0001")
        dup = models.duplicate_document(db, inv)
        self.assertEqual(models.get_document(db, dup)["bill_to_label"], "Client")
        # PDFs: every template x page size, short doc = 1 page, all display switches on and off
        for tpl in TEMPLATE_NAMES:
            for size in ("A4", "Letter"):
                path = os.path.join(self.tmp, f"{tpl}_{size}.pdf")
                render_pdf(models.get_document(db, inv), db.get_settings(), path, tpl, size)
                self.assertEqual(pdf_pages(path), 1, f"{tpl}/{size} should be one page")
            render_pdf(models.get_document(db, inv), db.get_settings(), os.path.join(self.tmp, f"{tpl}_off.pdf"), tpl,
                       options={k: 0 for k in DISPLAY_DEFAULTS})
            render_pdf(models.get_document(db, inv), db.get_settings(), os.path.join(self.tmp, f"{tpl}_on.pdf"), tpl,
                       options={k: 1 for k in DISPLAY_DEFAULTS})
        long_id = models.save_document(db, {"doc_type": models.INVOICE, "number": "LONG-1", "customer_id": cid,
                                            "date": "2026-08-30", "tax_rate": 0, "discount_value": 0},
                                       [{"description": f"Item {i}", "quantity": 1, "unit_price": i} for i in range(1, 61)])
        path = os.path.join(self.tmp, "long.pdf")
        render_pdf(models.get_document(db, long_id), db.get_settings(), path, "Compact", "A4")
        self.assertGreater(pdf_pages(path), 1)
        db.set_setting("company_logo", "does-not-exist.png")
        render_pdf(models.get_document(db, inv), db.get_settings(), os.path.join(self.tmp, "nologo.pdf"))
        empty = models.save_document(db, {"doc_type": models.INVOICE, "number": "EMPTY-1", "date": "2026-08-30",
                                          "tax_rate": 0, "discount_value": 0}, [])
        render_pdf(models.get_document(db, empty), db.get_settings(), os.path.join(self.tmp, "empty.pdf"))
        # backup / restore
        backup = os.path.join(self.tmp, "backup.db")
        db.backup_to(backup)
        before = len(models.list_documents(db, models.INVOICE))
        models.delete_document(db, inv)
        self.assertEqual(len(models.list_documents(db, models.INVOICE)), before - 1)
        db.restore_from(backup)
        self.assertEqual(len(models.list_documents(db, models.INVOICE)), before)
        self.assertEqual(models.get_document(db, inv)["status"], models.STATUS_PAID)
        with self.assertRaises(ValueError):
            db.restore_from(os.path.join(self.tmp, "Modern_A4.pdf"))
        with self.assertRaises(models.ValidationError):
            models.delete_customer(db, cid)
        self.assertIn("outstanding", models.dashboard_stats(db))

    def test_inventory_purchases_returns_and_stock_limit(self):
        db = self.db
        vid = models.save_vendor(db, {"name": "Textile Mills"})
        cid = models.save_customer(db, {"name": "Raza Textiles"})
        pid = models.save_product(db, {"name": "Cotton roll", "unit_price": 850, "cost_price": 500, "unit": "m",
                                       "opening_stock": 10})
        self.assertEqual(models.get_product(db, pid)["stock"], 10.0)
        pur = models.save_purchase(db, {"vendor_id": vid, "date": "2026-08-01", "reference": "BILL-7"},
                                   [{"product_id": pid, "quantity": 40, "unit_cost": 520}])
        self.assertEqual(models.get_product(db, pid)["stock"], 50.0)
        self.assertEqual(models.get_product(db, pid)["cost_price"], 520.0)  # cost updated from the purchase
        self.assertEqual(models.get_purchase(db, pur)["total"], 20800.0)
        # cannot sell more than 50
        with self.assertRaises(models.StockError):
            models.save_document(db, {"doc_type": models.INVOICE, "number": "INV-0001", "customer_id": cid,
                                      "date": "2026-08-30", "tax_rate": 0, "discount_value": 0},
                                 [{"product_id": pid, "description": "Cotton roll", "quantity": 51, "unit_price": 850}])
        inv = models.save_document(db, {"doc_type": models.INVOICE, "number": "INV-0001", "customer_id": cid,
                                        "date": "2026-08-30", "tax_rate": 0, "discount_value": 0},
                                   [{"product_id": pid, "description": "Cotton roll", "quantity": 50, "unit_price": 850}])
        self.assertEqual(models.get_product(db, pid)["stock"], 0.0)
        self.assertEqual(models.get_document(db, inv)["items"][0]["cost_price"], 520.0)  # cost snapshot for profit
        # editing the same invoice down to 30 frees stock (its own sale is excluded from the check)
        models.save_document(db, {"id": inv, "doc_type": models.INVOICE, "number": "INV-0001", "customer_id": cid,
                                  "date": "2026-08-30", "tax_rate": 0, "discount_value": 0},
                             [{"product_id": pid, "description": "Cotton roll", "quantity": 30, "unit_price": 850}])
        self.assertEqual(models.get_product(db, pid)["stock"], 20.0)
        # quotations never touch stock
        models.save_document(db, {"doc_type": models.QUOTATION, "number": "QT-0001", "date": "2026-08-30",
                                  "tax_rate": 0, "discount_value": 0},
                             [{"product_id": pid, "description": "Cotton roll", "quantity": 500, "unit_price": 850}])
        self.assertEqual(models.get_product(db, pid)["stock"], 20.0)
        # customer return: 5 back into stock + credit of 4250 reduces the balance
        models.add_payment(db, inv, 10000, "2026-08-30", "Cash")
        rid = models.save_return(db, {"kind": "customer", "invoice_id": inv, "date": "2026-09-01", "reason": "damaged"},
                                 [{"product_id": pid, "description": "Cotton roll", "quantity": 5, "unit_price": 850}])
        self.assertEqual(models.get_product(db, pid)["stock"], 25.0)
        doc = models.get_document(db, inv)
        self.assertEqual(doc["credit"], 4250.0)
        self.assertEqual(doc["balance"], 25500.0 - 10000.0 - 4250.0)
        self.assertEqual(doc["status"], models.STATUS_PARTIAL)
        self.assertEqual(models.get_customer(db, cid)["balance"], doc["balance"])
        # vendor return: 5 go back to the vendor
        models.save_return(db, {"kind": "vendor", "purchase_id": pur, "date": "2026-09-02"},
                           [{"product_id": pid, "quantity": 5, "unit_price": 520}])
        self.assertEqual(models.get_product(db, pid)["stock"], 20.0)
        with self.assertRaises(models.StockError):
            models.save_return(db, {"kind": "vendor", "vendor_id": vid, "date": "2026-09-02"},
                               [{"product_id": pid, "quantity": 999, "unit_price": 520}])
        # deleting the return restores stock and credit
        models.delete_return(db, rid)
        self.assertEqual(models.get_product(db, pid)["stock"], 15.0)
        self.assertEqual(models.get_document(db, inv)["credit"], 0.0)
        # reports
        best = models.best_sellers(db)
        self.assertEqual(best[0]["name"], "Cotton roll")
        self.assertEqual(best[0]["qty_sold"], 30.0)
        self.assertEqual(best[0]["profit"], 30 * (850 - 520))
        stats = models.dashboard_stats(db)
        self.assertEqual(stats["stock_value"], 15 * 520.0)
        self.assertEqual(stats["profit_all"]["profit"], 30 * (850 - 520))
        history = models.stock_history(db, pid)
        self.assertGreaterEqual(len(history), 4)  # opening, purchase, sale, vendor return (customer return deleted)
        # deleting the invoice returns the stock
        models.delete_document(db, inv)
        self.assertEqual(models.get_product(db, pid)["stock"], 45.0)
        # allow negative stock switch
        db.set_setting("allow_negative_stock", "1")
        models.save_document(db, {"doc_type": models.INVOICE, "number": "INV-0002", "customer_id": cid,
                                  "date": "2026-08-30", "tax_rate": 0, "discount_value": 0},
                             [{"product_id": pid, "description": "Cotton roll", "quantity": 100, "unit_price": 850}])
        self.assertEqual(models.get_product(db, pid)["stock"], -55.0)

    def test_users_and_roles(self):
        db = self.db
        self.assertEqual(models.count_users(db), 0)
        owner = models.create_user(db, "owner", "secret1", models.ROLE_OWNER, "The Boss")
        emp = models.create_user(db, "sara", "pass1", models.ROLE_EMPLOYEE, "Sara")
        self.assertIsNone(models.authenticate(db, "owner", "wrong"))
        self.assertEqual(models.authenticate(db, "OWNER", "secret1")["role"], models.ROLE_OWNER)
        with self.assertRaises(models.ValidationError):
            models.create_user(db, "owner", "x1234")  # duplicate
        with self.assertRaises(models.ValidationError):
            models.update_user(db, owner, role=models.ROLE_EMPLOYEE)  # last owner
        with self.assertRaises(models.ValidationError):
            models.delete_user(db, owner)
        models.update_user(db, emp, password="newpass", full_name="Sara K")
        self.assertIsNotNone(models.authenticate(db, "sara", "newpass"))
        models.update_user(db, emp, active=0)
        self.assertIsNone(models.authenticate(db, "sara", "newpass"))
        models.delete_user(db, emp)
        self.assertEqual(len(models.list_users(db)), 1)

    def test_bad_numbers_never_crash_totals(self):
        t = models.compute_totals([], "percent", "abc", "xyz")
        self.assertEqual(t["total"], 0.0)
        t = models.compute_totals([{"line_total": 100, "tax_rate": None, "effective_tax_rate": 10}], "fixed", "500", 0)
        self.assertEqual(t["discount_amount"], 100.0)
        with self.assertRaises(models.ValidationError):
            models.normalize_items([{"description": "x", "quantity": "two", "unit_price": 1}], 0)
        self.assertEqual(models.parse_display_options("not json")["show_grid"], 1)
        self.assertEqual(models.parse_display_options(json.dumps({"show_sku": 1, "bogus": 1}))["show_sku"], 1)

    def test_settings_and_theme(self):
        db = self.db
        self.assertIn("Cash", db.get_list_setting("payment_methods"))
        settings = db.get_settings()
        self.assertEqual(settings["currency_code"], "PKR")
        self.assertEqual(settings["require_login"], "1")
        p = build_palette(settings)
        self.assertEqual(p.status_color("Paid"), settings["theme_success"])
        settings["theme_accent"] = "not-a-color"
        self.assertEqual(build_palette(settings).accent, "#2563eb")
        db.set_setting("doc_display_defaults", json.dumps({"show_signatures": 0}))
        self.assertEqual(db.display_defaults()["show_signatures"], 0)
        self.assertEqual(db.display_defaults()["show_grid"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
