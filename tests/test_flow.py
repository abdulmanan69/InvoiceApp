"""End-to-end logic test of the spec's required flow (no GUI needed).

Run:  python -m unittest tests.test_flow -v
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402
from db import Database  # noqa: E402
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
        # 1. customer
        cid = models.save_customer(db, {"name": "Ali Traders", "company": "Ali & Sons", "billing_address": "Lahore"})
        self.assertTrue(cid)
        # 2. product with comma-formatted price and blank tax override
        pid = models.save_product(db, {"name": "Consulting", "unit_price": "1,500", "unit": "hr", "tax_rate": ""})
        # 3. invoice using the product (+ an empty row that must be ignored)
        number = models.next_number(db, models.INVOICE)
        self.assertEqual(number, "INV-0001")
        inv = models.save_document(db, {
            "doc_type": models.INVOICE, "number": number, "customer_id": cid, "date": "2026-08-30",
            "due_date": "2026-09-13", "tax_rate": "17", "discount_type": "percent", "discount_value": "10",
        }, [
            {"product_id": pid, "description": "Consulting", "quantity": "10", "unit": "hr", "unit_price": "1500"},
            {"description": "", "quantity": "", "unit_price": ""},
        ])
        doc = models.get_document(db, inv)
        self.assertEqual(len(doc["items"]), 1)
        self.assertEqual(doc["subtotal"], 15000.0)
        self.assertEqual(doc["discount_amount"], 1500.0)
        self.assertEqual(doc["tax_amount"], 2295.0)
        self.assertEqual(doc["total"], 15795.0)
        self.assertEqual(doc["status"], models.STATUS_UNPAID)
        self.assertEqual(models.next_number(db, models.INVOICE), "INV-0002")
        # duplicate number prevention
        with self.assertRaises(models.ValidationError):
            models.save_document(db, {"doc_type": models.INVOICE, "number": "INV-0001", "date": "2026-08-30",
                                      "tax_rate": 0, "discount_value": 0}, [])
        # 4. partial payment
        models.add_payment(db, inv, "5000", "2026-08-30", "Cash")
        self.assertEqual(models.get_document(db, inv)["status"], models.STATUS_PARTIAL)
        # overpayment blocked unless allowed
        with self.assertRaises(models.OverpaymentError):
            models.add_payment(db, inv, 99999, "2026-08-30", "Cash")
        # 5. rest -> Paid via Mark as Paid (real payment row)
        models.mark_as_paid(db, inv, "Bank Transfer")
        doc = models.get_document(db, inv)
        self.assertEqual(doc["status"], models.STATUS_PAID)
        self.assertEqual(doc["paid"], 15795.0)
        self.assertEqual(len(doc["payments"]), 2)
        self.assertIsNone(models.mark_as_paid(db, inv))
        # overdue detection
        self.assertEqual(models.compute_status(models.INVOICE, 100, 0, "2020-01-01"), models.STATUS_OVERDUE)
        self.assertEqual(models.compute_status(models.INVOICE, 100, 50, "2020-01-01"), models.STATUS_OVERDUE)
        self.assertEqual(models.compute_status(models.INVOICE, 100, 50, "2999-01-01"), models.STATUS_PARTIAL)
        # 6. quotation -> convert
        q = models.save_document(db, {"doc_type": models.QUOTATION, "number": models.next_number(db, models.QUOTATION),
                                      "customer_id": cid, "date": "2026-08-30", "due_date": "2026-09-29",
                                      "tax_rate": 0, "discount_value": 0},
                                 [{"description": "Widget", "quantity": 2, "unit_price": 100}])
        self.assertEqual(models.get_document(db, q)["status"], models.STATUS_OPEN)
        new_inv = models.convert_quotation_to_invoice(db, q)
        self.assertEqual(models.get_document(db, q)["status"], models.STATUS_CONVERTED)
        self.assertEqual(models.get_document(db, new_inv)["total"], 200.0)
        self.assertEqual(models.get_document(db, new_inv)["source_quotation_id"], q)
        # duplicate
        dup = models.duplicate_document(db, inv)
        self.assertEqual(len(models.get_document(db, dup)["items"]), 1)
        # 7. PDF export for every template & page size (short doc = 1 page)
        for tpl in TEMPLATE_NAMES:
            for size in ("A4", "Letter"):
                path = os.path.join(self.tmp, f"{tpl}_{size}.pdf")
                render_pdf(models.get_document(db, inv), db.get_settings(), path, tpl, size)
                self.assertGreater(os.path.getsize(path), 1000)
                self.assertEqual(pdf_pages(path), 1, f"{tpl}/{size} should be one page")
        # long invoice paginates with repeated header (>1 page)
        long_id = models.save_document(db, {"doc_type": models.INVOICE, "number": "LONG-1", "customer_id": cid,
                                            "date": "2026-08-30", "tax_rate": 0, "discount_value": 0},
                                       [{"description": f"Item {i}", "quantity": 1, "unit_price": i} for i in range(1, 61)])
        path = os.path.join(self.tmp, "long.pdf")
        render_pdf(models.get_document(db, long_id), db.get_settings(), path, "Modern", "A4")
        self.assertGreater(pdf_pages(path), 1)
        # missing logo must not crash
        db.set_setting("company_logo", "does-not-exist.png")
        render_pdf(models.get_document(db, inv), db.get_settings(), os.path.join(self.tmp, "nologo.pdf"))
        # empty invoice (zero items, no customer) must render
        empty = models.save_document(db, {"doc_type": models.INVOICE, "number": "EMPTY-1", "date": "2026-08-30",
                                          "tax_rate": 0, "discount_value": 0}, [])
        render_pdf(models.get_document(db, empty), db.get_settings(), os.path.join(self.tmp, "empty.pdf"))
        # 8. backup -> destroy data -> restore -> data survives
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
        # customer with documents cannot be deleted; balance is computed
        with self.assertRaises(models.ValidationError):
            models.delete_customer(db, cid)
        self.assertEqual(models.get_customer(db, cid)["balance"], 200.0 + 15795.0 + 1830.0)  # converted (200) + duplicate (15795, unpaid) + LONG-1 (1830)
        # dashboard stats never crash
        stats = models.dashboard_stats(db)
        self.assertIn("outstanding", stats)

    def test_bad_numbers_never_crash_totals(self):
        t = models.compute_totals([], "percent", "abc", "xyz")
        self.assertEqual(t["total"], 0.0)
        t = models.compute_totals([{"line_total": 100, "tax_rate": None, "effective_tax_rate": 10}], "fixed", "500", 0)
        self.assertEqual(t["discount_amount"], 100.0)  # capped at subtotal
        self.assertEqual(t["total"], 0.0)
        with self.assertRaises(models.ValidationError):
            models.normalize_items([{"description": "x", "quantity": "two", "unit_price": 1}], 0)

    def test_payment_methods_and_theme_from_settings(self):
        db = self.db
        self.assertIn("Cash", db.get_list_setting("payment_methods"))
        db.set_list_setting("payment_methods", ["JazzCash", "Easypaisa"])
        self.assertEqual(db.get_list_setting("payment_methods"), ["JazzCash", "Easypaisa"])
        settings = db.get_settings()
        self.assertEqual(settings["currency_code"], "PKR")
        p = build_palette(settings)
        self.assertEqual(p.accent, settings["theme_accent"])
        self.assertEqual(p.status_color("Paid"), settings["theme_success"])
        settings["theme_accent"] = "not-a-color"
        self.assertEqual(build_palette(settings).accent, "#2563eb")


if __name__ == "__main__":
    unittest.main(verbosity=2)
