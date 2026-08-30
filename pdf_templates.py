"""PDF rendering for invoices and quotations.

Seven layouts share one story builder (parties block, items table, totals, notes, signatures) and
differ in page decoration, fonts and table styling. Every visual element can be switched on/off per
document through display options (see db.DISPLAY_DEFAULTS). Pagination is handled by platypus; the
item table repeats its header on every page.
"""
from __future__ import annotations

import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from db import DISPLAY_DEFAULTS
from utils import data_dir, fmt_date, fmt_number, is_hex_color, mix, money

TEMPLATE_NAMES = ["Modern", "Classic", "Minimal", "Bold", "Corporate", "Elegant", "Compact"]
TEMPLATE_DESCRIPTIONS = {
    "Modern": "Colour band header, sans-serif, zebra rows",
    "Classic": "Centred serif header with double rule, formal",
    "Minimal": "Hairlines and whitespace, large light title",
    "Bold": "Dark header block, big company name, strong grid",
    "Corporate": "Accent stripe, two-column header, boxed totals",
    "Elegant": "Serif, thin double rules, understated colour",
    "Compact": "Dense layout for long item lists",
}
PAGE_SIZES = {"A4": A4, "Letter": LETTER}

_FONT_CACHE: dict[str, tuple[str, str]] = {}


# --------------------------------------------------------------------------- fonts
def _register_font_family(key: str, candidates: list[tuple[str, str, str]], fallback: tuple[str, str]) -> tuple[str, str]:
    """Register a TrueType family from Windows fonts if present; else return the built-in fallback."""
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for family, regular, bold in candidates:
        reg_path, bold_path = os.path.join(fonts_dir, regular), os.path.join(fonts_dir, bold)
        if os.path.isfile(reg_path) and os.path.isfile(bold_path):
            try:
                pdfmetrics.registerFont(TTFont(family, reg_path))
                pdfmetrics.registerFont(TTFont(family + "-Bold", bold_path))
                pdfmetrics.registerFontFamily(family, normal=family, bold=family + "-Bold",
                                              italic=family, boldItalic=family + "-Bold")
                _FONT_CACHE[key] = (family, family + "-Bold")
                return _FONT_CACHE[key]
            except Exception:
                continue
    _FONT_CACHE[key] = fallback
    return fallback


def sans_fonts() -> tuple[str, str]:
    return _register_font_family(
        "sans",
        [("SegoeUI", "segoeui.ttf", "segoeuib.ttf"), ("Arial", "arial.ttf", "arialbd.ttf"),
         ("Calibri", "calibri.ttf", "calibrib.ttf")],
        ("Helvetica", "Helvetica-Bold"),
    )


def serif_fonts() -> tuple[str, str]:
    return _register_font_family(
        "serif",
        [("Georgia", "georgia.ttf", "georgiab.ttf"), ("TimesNewRoman", "times.ttf", "timesbd.ttf")],
        ("Times-Roman", "Times-Bold"),
    )


# --------------------------------------------------------------------------- helpers
def _c(hex_color, default: str = "#2563eb") -> colors.Color:
    return colors.HexColor(hex_color if is_hex_color(hex_color or "") else default)


def _hex(settings: dict, key: str, default: str) -> str:
    v = settings.get(key) or ""
    return v if is_hex_color(v) else default


def _lum(c: colors.Color) -> float:
    r, g, b = c.rgb()
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _p(text, style: ParagraphStyle) -> Paragraph:
    text = "" if text is None else str(text)
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _logo_path(settings: dict) -> str | None:
    name = (settings.get("company_logo") or "").strip()
    if not name:
        return None
    path = name if os.path.isabs(name) else os.path.join(data_dir(), name)
    return path if os.path.isfile(path) else None


def status_colors(settings: dict) -> dict:
    return {
        "Unpaid": _hex(settings, "theme_muted", "#64748b"),
        "Partially Paid": _hex(settings, "theme_warning", "#d97706"),
        "Paid": _hex(settings, "theme_success", "#16a34a"),
        "Overdue": _hex(settings, "theme_danger", "#dc2626"),
        "Open": _hex(settings, "theme_accent", "#2563eb"),
        "Converted": _hex(settings, "theme_success", "#16a34a"),
        "Expired": _hex(settings, "theme_muted", "#64748b"),
    }


def currency_symbol(doc: dict, settings: dict) -> str:
    code = (doc.get("currency") or "").strip()
    default_code = (settings.get("currency_code") or "").strip()
    if code and default_code and code.upper() != default_code.upper():
        return code.upper()
    return settings.get("currency_symbol") or default_code or ""


def _pad(l=5, r=5, t=5, b=5) -> list:
    return [("LEFTPADDING", (0, 0), (-1, -1), l), ("RIGHTPADDING", (0, 0), (-1, -1), r),
            ("TOPPADDING", (0, 0), (-1, -1), t), ("BOTTOMPADDING", (0, 0), (-1, -1), b)]


# --------------------------------------------------------------------------- base template
class BaseTemplate:
    name = "Base"
    header_first = 50 * mm      # height reserved above the frame on page 1
    header_later = 20 * mm
    footer = 16 * mm
    margin = 16 * mm
    serif = False
    zebra = True
    body_size = 9.2
    company_size = 20
    title_size = 15
    customer_name_size = 12.5
    customer_company_size = 11
    header_fill = "soft"        # soft | accent | none | dark

    def __init__(self, doc: dict, settings: dict, page_size=A4, opts: dict | None = None):
        self.doc = doc
        self.settings = settings
        self.opts = dict(DISPLAY_DEFAULTS)
        self.opts.update(opts or {})
        self.page_size = page_size
        self.width, self.height = page_size
        accent_hex = _hex(settings, "theme_accent", "#2563eb")
        fg_hex = _hex(settings, "theme_fg", "#0f172a")
        self.accent = colors.HexColor(accent_hex)
        self.text = colors.HexColor(fg_hex)
        self.dark = colors.HexColor(mix(fg_hex, "#000000", 0.2))
        self.muted = colors.HexColor(_hex(settings, "theme_muted", "#64748b"))
        self.line = colors.HexColor(mix(fg_hex, "#ffffff", 0.78))
        self.soft = colors.HexColor(mix(accent_hex, "#ffffff", 0.90))
        self.zebra_color = colors.HexColor(mix(fg_hex, "#ffffff", 0.96))
        self.on_accent = colors.white if _lum(self.accent) < 0.55 else self.text
        self.font, self.font_bold = (serif_fonts() if self.serif else sans_fonts())
        self.symbol = currency_symbol(doc, settings)
        self.date_format = settings.get("date_format") or "%d %b %Y"
        self.is_invoice = doc.get("doc_type") == "invoice"
        self.title = "INVOICE" if self.is_invoice else "QUOTATION"
        self.status = doc.get("status") or ""
        self.status_color = _c(status_colors(settings).get(self.status), "#64748b")
        self._build_styles()

    # ------------------------------------------------------------------ styles
    def _build_styles(self):
        f, fb, bs = self.font, self.font_bold, self.body_size
        lead = bs + 2.8
        head_color = self.on_accent if self.header_fill == "accent" else (colors.white if self.header_fill == "dark" else self.text)
        self.st = {
            "body": ParagraphStyle("body", fontName=f, fontSize=bs, leading=lead, textColor=self.text),
            "body_r": ParagraphStyle("body_r", fontName=f, fontSize=bs, leading=lead, textColor=self.text, alignment=TA_RIGHT),
            "small": ParagraphStyle("small", fontName=f, fontSize=bs - 1.2, leading=bs + 1.3, textColor=self.muted),
            "label": ParagraphStyle("label", fontName=fb, fontSize=bs - 1.8, leading=bs + 0.8, textColor=self.muted),
            "strong": ParagraphStyle("strong", fontName=fb, fontSize=bs + 0.4, leading=lead + 0.5, textColor=self.text),
            "strong_r": ParagraphStyle("strong_r", fontName=fb, fontSize=bs + 0.4, leading=lead + 0.5, textColor=self.text, alignment=TA_RIGHT),
            "cust_name": ParagraphStyle("cust_name", fontName=fb, fontSize=self.customer_name_size,
                                        leading=self.customer_name_size + 3, textColor=self.text),
            "cust_company": ParagraphStyle("cust_company", fontName=fb, fontSize=self.customer_company_size,
                                           leading=self.customer_company_size + 3, textColor=self.dark),
            "th": ParagraphStyle("th", fontName=fb, fontSize=bs - 1, leading=bs + 1, textColor=head_color),
            "th_r": ParagraphStyle("th_r", fontName=fb, fontSize=bs - 1, leading=bs + 1, textColor=head_color, alignment=TA_RIGHT),
            "total": ParagraphStyle("total", fontName=fb, fontSize=bs + 2.3, leading=bs + 5, textColor=self.accent),
            "total_r": ParagraphStyle("total_r", fontName=fb, fontSize=bs + 2.3, leading=bs + 5, textColor=self.accent, alignment=TA_RIGHT),
            "h": ParagraphStyle("h", fontName=fb, fontSize=bs - 0.8, leading=bs + 2, textColor=self.accent, spaceAfter=2),
            "sig_label": ParagraphStyle("sig_label", fontName=fb, fontSize=bs - 1.6, leading=bs + 0.6, textColor=self.muted,
                                        alignment=TA_CENTER),
            "sig_name": ParagraphStyle("sig_name", fontName=f, fontSize=bs, leading=lead, textColor=self.text,
                                       alignment=TA_CENTER),
        }

    def money(self, value) -> str:
        return money(value, self.symbol)

    def date(self, value) -> str:
        return fmt_date(value, self.date_format) or "-"

    @property
    def frame_width(self) -> float:
        return self.width - 2 * self.margin

    def on(self, key: str) -> bool:
        return bool(self.opts.get(key, 1))

    # ------------------------------------------------------------------ build
    def build(self, out_path: str) -> str:
        first = Frame(self.margin, self.footer, self.frame_width, self.height - self.header_first - self.footer,
                      id="first", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        later = Frame(self.margin, self.footer, self.frame_width, self.height - self.header_later - self.footer,
                      id="later", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        pdf = BaseDocTemplate(
            out_path, pagesize=self.page_size, title=f"{self.title.title()} {self.doc.get('number', '')}",
            author=self.settings.get("company_name", ""), leftMargin=self.margin, rightMargin=self.margin,
            topMargin=self.header_first, bottomMargin=self.footer,
        )
        pdf.addPageTemplates([
            PageTemplate(id="first", frames=[first], onPage=self.draw_first_page),
            PageTemplate(id="later", frames=[later], onPage=self.draw_later_page),
        ])
        pdf.build([NextPageTemplate("later")] + self.story())
        return out_path

    # ------------------------------------------------------------------ story
    def story(self) -> list:
        parts = self.parties_block()
        parts.append(Spacer(1, 6 * mm))
        parts.append(self.items_table())
        parts.append(Spacer(1, 5 * mm))
        parts.append(KeepTogether([self.totals_table()]))
        footer = self.footer_block()
        if footer:
            parts.append(Spacer(1, 7 * mm))
            parts += footer
        sig = self.signature_block()
        if sig is not None:
            parts.append(Spacer(1, 10 * mm))
            parts.append(sig)
        return parts

    # ------------------------------------------------------------------ company / customer text
    def company_lines(self) -> list[str]:
        s = self.settings
        if not self.on("show_company_details"):
            return []
        lines = [ln.strip() for ln in (s.get("company_address") or "").splitlines() if ln.strip()]
        contact = "  |  ".join(x for x in (s.get("company_phone"), s.get("company_email"), s.get("company_website")) if x)
        if contact:
            lines.append(contact)
        if s.get("company_tax_number"):
            lines.append(f"Tax No: {s['company_tax_number']}")
        return lines

    def bill_to_label(self) -> str:
        return (self.doc.get("bill_to_label") or self.settings.get("bill_to_label") or "Bill To").strip()

    def customer_paragraphs(self) -> list:
        custom = (self.doc.get("bill_to_text") or "").strip()
        if custom:
            lines = [ln for ln in custom.splitlines() if ln.strip()]
            out = [_p(lines[0], self.st["cust_name"])] if lines else []
            for ln in lines[1:]:
                out.append(_p(ln, self.st["body"]))
            return out
        cust = self.doc.get("customer") or {}
        if not cust:
            return [_p("(no customer selected)", self.st["small"])]
        out = [_p(cust.get("name", ""), self.st["cust_name"])]
        if cust.get("company"):
            out.append(_p(cust["company"], self.st["cust_company"]))
        if cust.get("billing_address"):
            out.append(_p(cust["billing_address"], self.st["body"]))
        if self.on("show_customer_contact"):
            contact = "  |  ".join(x for x in (cust.get("phone"), cust.get("email")) if x)
            if contact:
                out.append(_p(contact, self.st["small"]))
            if cust.get("tax_number"):
                out.append(_p(f"Tax No: {cust['tax_number']}", self.st["small"]))
        return out

    def meta_rows(self) -> list[tuple[str, str]]:
        d = self.doc
        rows = [(f"{self.title.title()} No.", d.get("number", "")), ("Date", self.date(d.get("date")))]
        if d.get("due_date") and self.on("show_due_date"):
            rows.append(("Due Date" if self.is_invoice else "Valid Until", self.date(d.get("due_date"))))
        if d.get("currency") and self.on("show_currency"):
            rows.append(("Currency", d["currency"]))
        if d.get("source_quotation_number"):
            rows.append(("Quotation Ref", d["source_quotation_number"]))
        return rows

    def status_badge(self):
        label = self.status.upper()
        style = ParagraphStyle("badge", fontName=self.font_bold, fontSize=7.6, leading=9.5,
                               textColor=colors.white if _lum(self.status_color) < 0.6 else self.text, alignment=TA_CENTER)
        badge = Table([[Paragraph(label, style)]], colWidths=[min(36 * mm, max(20 * mm, len(label) * 1.9 * mm + 6 * mm))])
        badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), self.status_color), ("ROUNDEDCORNERS", [3, 3, 3, 3]),
                                   *_pad(5, 5, 3, 3)]))
        wrap = Table([[badge]], colWidths=[36 * mm])
        wrap.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT"), *_pad(0, 0, 0, 0)]))
        return wrap

    def parties_block(self) -> list:
        cust = self.doc.get("customer") or {}
        cols = [[_p(self.bill_to_label().upper(), self.st["h"])] + self.customer_paragraphs()]
        ship = (cust.get("shipping_address") or "").strip()
        if self.on("show_ship_to") and not (self.doc.get("bill_to_text") or "").strip() and ship \
                and ship != (cust.get("billing_address") or "").strip():
            cols.append([_p("SHIP TO", self.st["h"]), _p(cust.get("name", ""), self.st["strong"]), _p(ship, self.st["body"])])
        meta_data = [[_p(k, self.st["label"]), _p(v, self.st["strong_r"])] for k, v in self.meta_rows()]
        if self.status and self.on("show_status"):
            meta_data.append([_p("Status", self.st["label"]), self.status_badge()])
        meta = Table(meta_data, colWidths=[26 * mm, 36 * mm])
        meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), *_pad(0, 0, 2.5, 2.5),
                                  ("LINEBELOW", (0, 0), (-1, -2), 0.4, self.line)]))
        cols.append([meta])
        meta_w = 64 * mm
        rest = self.frame_width - meta_w
        widths = [rest / (len(cols) - 1)] * (len(cols) - 1) + [meta_w]
        t = Table([cols], colWidths=widths)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), *_pad(0, 0, 0, 0),
                               ("RIGHTPADDING", (0, 0), (-2, -1), 6 * mm)]))
        return [t]

    # ------------------------------------------------------------------ items
    def column_spec(self) -> list[tuple[str, str, float, str]]:
        """(key, heading, fixed width or 0 for flexible, align)"""
        items = self.doc.get("items") or []
        default_tax = float(self.doc.get("tax_rate") or 0)
        any_tax = any(float(i.get("tax_rate") if i.get("tax_rate") is not None else default_tax) for i in items)
        tax_label = self.settings.get("tax_label") or "Tax"
        spec = []
        if self.on("show_line_numbers"):
            spec.append(("n", "#", 9 * mm, "l"))
        if self.on("show_sku"):
            spec.append(("sku", "SKU", 22 * mm, "l"))
        spec.append(("description", "Description", 0, "l"))
        if self.on("show_qty"):
            spec.append(("qty", "Qty", 16 * mm, "r"))
        if self.on("show_unit"):
            spec.append(("unit", "Unit", 15 * mm, "l"))
        if self.on("show_unit_price"):
            spec.append(("price", "Unit Price", 30 * mm, "r"))
        if self.on("show_tax_col") and any_tax:
            spec.append(("tax", f"{tax_label} %", 15 * mm, "r"))
        spec.append(("amount", "Amount", 32 * mm, "r"))
        return spec

    def items_table(self) -> Table:
        items = self.doc.get("items") or []
        default_tax = float(self.doc.get("tax_rate") or 0)
        spec = self.column_spec()
        head = [_p(h, self.st["th_r"] if a == "r" else self.st["th"]) for _, h, _, a in spec]
        rows = [head]
        for n, it in enumerate(items, start=1):
            rate = it.get("tax_rate") if it.get("tax_rate") is not None else default_tax
            values = {"n": str(n), "sku": it.get("sku_display") or it.get("sku") or "", "description": it.get("description", ""),
                      "qty": fmt_number(it.get("quantity")), "unit": it.get("unit") or "",
                      "price": self.money(it.get("unit_price")), "tax": fmt_number(rate),
                      "amount": self.money(it.get("line_total"))}
            rows.append([_p(values[k], self.st["body_r"] if a == "r" else self.st["body"]) for k, _, _, a in spec])
        if not items:
            rows.append([_p("No items", self.st["small"]) if k == "description" else _p("", self.st["body"]) for k, _, _, _ in spec])
        fixed = sum(w for _, _, w, _ in spec)
        widths = [w if w else self.frame_width - fixed for _, _, w, _ in spec]
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle(self.items_style(len(rows))))
        return t

    def items_style(self, nrows: int) -> list:
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"), *_pad(5, 5, 5, 5)]
        fill = self.header_fill
        if fill == "accent":
            style += [("BACKGROUND", (0, 0), (-1, 0), self.accent)]
        elif fill == "dark":
            style += [("BACKGROUND", (0, 0), (-1, 0), self.dark)]
        elif fill == "soft":
            style += [("BACKGROUND", (0, 0), (-1, 0), self.soft), ("LINEBELOW", (0, 0), (-1, 0), 0.8, self.accent)]
        else:
            style += [("LINEBELOW", (0, 0), (-1, 0), 0.8, self.text)]
        if self.on("show_grid"):
            style += [("GRID", (0, 0), (-1, -1), 0.4, self.line), ("BOX", (0, 0), (-1, -1), 0.6, self.line)]
        else:
            style += [("LINEBELOW", (0, 1), (-1, -1), 0.4, self.line)]
        if self.zebra:
            for r in range(2, nrows, 2):
                style.append(("BACKGROUND", (0, r), (-1, r), self.zebra_color))
        return style

    # ------------------------------------------------------------------ totals
    def totals_rows(self) -> list[tuple[str, str, str]]:
        d = self.doc
        rows = [("Subtotal", self.money(d.get("subtotal")), "body")]
        if float(d.get("discount_amount") or 0) > 0 and self.on("show_discount"):
            label = "Discount"
            if d.get("discount_type") == "percent":
                label += f" ({fmt_number(d.get('discount_value'))}%)"
            rows.append((label, "-" + self.money(d.get("discount_amount")), "body"))
        if float(d.get("tax_amount") or 0) > 0 and self.on("show_tax_total"):
            rows.append((self.settings.get("tax_label") or "Tax", self.money(d.get("tax_amount")), "body"))
        rows.append(("Total", self.money(d.get("total")), "total"))
        if self.is_invoice and self.on("show_paid_balance"):
            if float(d.get("credit") or 0) > 0:
                rows.append(("Returns / credit", "-" + self.money(d.get("credit")), "body"))
            if float(d.get("paid") or 0) > 0:
                rows.append(("Paid", "-" + self.money(d.get("paid")), "body"))
            if float(d.get("paid") or 0) > 0 or float(d.get("credit") or 0) > 0:
                rows.append(("Balance Due", self.money(d.get("balance")), "strong"))
        return rows

    def totals_table(self) -> Table:
        rows = self.totals_rows()
        data = []
        for label, value, kind in rows:
            ls = self.st["total"] if kind == "total" else (self.st["strong"] if kind == "strong" else self.st["body"])
            rs = self.st["total_r"] if kind == "total" else (self.st["strong_r"] if kind == "strong" else self.st["body_r"])
            data.append([_p(label, ls), _p(value, rs)])
        inner = Table(data, colWidths=[36 * mm, 42 * mm])
        st = [*_pad(6, 6, 3.5, 3.5), ("LINEBELOW", (0, 0), (-1, -2), 0.4, self.line)]
        if self.on("show_grid"):
            st.append(("BOX", (0, 0), (-1, -1), 0.6, self.line))
        for i, (_, _, kind) in enumerate(rows):
            if kind == "total":
                st += [("BACKGROUND", (0, i), (-1, i), self.soft), ("LINEABOVE", (0, i), (-1, i), 0.8, self.accent)]
        inner.setStyle(TableStyle(st))
        outer = Table([[Spacer(1, 1), inner]], colWidths=[self.frame_width - 78 * mm, 78 * mm])
        outer.setStyle(TableStyle(_pad(0, 0, 0, 0)))
        return outer

    # ------------------------------------------------------------------ notes / signatures
    def footer_block(self) -> list:
        sections = []
        if self.doc.get("notes") and self.on("show_notes"):
            sections.append(("NOTES", self.doc["notes"]))
        if self.doc.get("terms") and self.on("show_terms"):
            sections.append(("TERMS & CONDITIONS", self.doc["terms"]))
        if self.is_invoice and (self.settings.get("bank_details") or "").strip() and self.on("show_bank_details"):
            sections.append(("PAYMENT DETAILS", self.settings["bank_details"]))
        return [KeepTogether([_p(title, self.st["h"]), _p(text, self.st["small"]), Spacer(1, 3 * mm)])
                for title, text in sections]

    def signature_block(self):
        if not self.on("show_signatures"):
            return None
        s = self.settings
        prepared_label = s.get("signature_prepared_label") or "Prepared by"
        received_label = s.get("signature_received_label") or "Received by"
        prepared = (self.doc.get("prepared_by") or s.get("signature_prepared_name") or "").strip()
        received = (self.doc.get("received_by") or s.get("signature_received_name") or "").strip()

        def box(label, name):
            t = Table([[Spacer(1, 11 * mm)], [_p(name or " ", self.st["sig_name"])], [_p(label.upper(), self.st["sig_label"])]],
                      colWidths=[62 * mm])
            t.setStyle(TableStyle([*_pad(2, 2, 1, 1), ("LINEBELOW", (0, 0), (-1, 0), 0.6, self.text)]))
            return t

        gap = self.frame_width - 2 * 62 * mm
        outer = Table([[box(prepared_label, prepared), Spacer(1, 1), box(received_label, received)]],
                      colWidths=[62 * mm, gap, 62 * mm])
        outer.setStyle(TableStyle([*_pad(0, 0, 0, 0), ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
        return KeepTogether([outer])

    # ------------------------------------------------------------------ page decoration
    def draw_first_page(self, canv, doc):
        self.draw_header(canv, first=True)
        self.draw_footer(canv, doc)

    def draw_later_page(self, canv, doc):
        self.draw_header(canv, first=False)
        self.draw_footer(canv, doc)

    def draw_header(self, canv, first: bool):
        raise NotImplementedError

    def draw_footer(self, canv, doc):
        canv.saveState()
        canv.setStrokeColor(self.line)
        canv.setLineWidth(0.4)
        y = self.footer - 4 * mm
        canv.line(self.margin, y, self.width - self.margin, y)
        canv.setFont(self.font, 7.5)
        canv.setFillColor(self.muted)
        canv.drawString(self.margin, y - 4 * mm, f"{self.settings.get('company_name', '')}   -   {self.title.title()} {self.doc.get('number', '')}")
        canv.drawRightString(self.width - self.margin, y - 4 * mm, f"Page {doc.page}")
        canv.restoreState()

    def _draw_logo(self, canv, x, y_top, max_w, max_h, center_x=None) -> tuple[float, float]:
        """Draw the logo with its top-left at (x, y_top) (or centred on center_x). Returns (w, h) drawn."""
        if not self.on("show_logo"):
            return 0.0, 0.0
        path = _logo_path(self.settings)
        if not path:
            return 0.0, 0.0
        try:
            reader = ImageReader(path)
            iw, ih = reader.getSize()
            scale = min(max_w / iw, max_h / ih)
            w, h = iw * scale, ih * scale
            if center_x is not None:
                x = center_x - w / 2
            canv.drawImage(reader, x, y_top - h, w, h, mask="auto")
            return w, h
        except Exception:
            return 0.0, 0.0

    def _draw_company_text(self, canv, x, y, color, size=None, line_size=8, line_color=None, max_lines=4) -> float:
        """Company name + detail lines, left aligned at x, baseline starting y. Returns the next free y."""
        size = size or self.company_size
        canv.setFillColor(color)
        canv.setFont(self.font_bold, size)
        canv.drawString(x, y, self.settings.get("company_name", ""))
        y -= size * 0.55 + 3 * mm
        canv.setFont(self.font, line_size)
        canv.setFillColor(line_color or color)
        for line in self.company_lines()[:max_lines]:
            canv.drawString(x, y, line)
            y -= line_size * 0.5 + 2.2 * mm
        return y

    def _continued(self, canv, y, color):
        canv.setFillColor(color)
        canv.setFont(self.font_bold, 10)
        canv.drawString(self.margin, y, self.settings.get("company_name", ""))
        canv.setFont(self.font, 9)
        canv.drawRightString(self.width - self.margin, y, f"{self.title.title()} {self.doc.get('number', '')} (continued)")


# --------------------------------------------------------------------------- Modern
class ModernTemplate(BaseTemplate):
    """Bold colour band across the top, sans-serif, coloured table header, zebra rows."""
    name = "Modern"
    header_first = 54 * mm
    header_later = 22 * mm
    header_fill = "accent"
    company_size = 21
    title_size = 15

    def draw_header(self, canv, first: bool):
        canv.saveState()
        band_h = 42 * mm if first else 13 * mm
        canv.setFillColor(self.accent)
        canv.rect(0, self.height - band_h, self.width, band_h, stroke=0, fill=1)
        x, top = self.margin, self.height - 9 * mm
        if first:
            logo_w, _ = self._draw_logo(canv, x, top, 40 * mm, 24 * mm)
            if logo_w:
                x += logo_w + 6 * mm
            self._draw_company_text(canv, x, top - 6 * mm, self.on_accent, self.company_size, 8.2)
            canv.setFillColor(self.on_accent)
            canv.setFont(self.font_bold, self.title_size)
            canv.drawRightString(self.width - self.margin, top - 5.5 * mm, self.title)
            canv.setFont(self.font, 9.5)
            canv.drawRightString(self.width - self.margin, top - 11.5 * mm, f"# {self.doc.get('number', '')}")
        else:
            self._continued(canv, self.height - 8.5 * mm, self.on_accent)
        canv.restoreState()


# --------------------------------------------------------------------------- Classic
class ClassicTemplate(BaseTemplate):
    """Centred serif header with double rule, formal ruled table."""
    name = "Classic"
    serif = True
    header_first = 72 * mm
    header_later = 26 * mm
    zebra = False
    header_fill = "none"
    company_size = 20

    def draw_header(self, canv, first: bool):
        canv.saveState()
        cx = self.width / 2
        top = self.height - self.margin + 3 * mm
        if first:
            y = top
            _, logo_h = self._draw_logo(canv, 0, y, 48 * mm, 16 * mm, center_x=cx)
            if logo_h:
                y -= logo_h + 3 * mm
            canv.setFillColor(self.text)
            canv.setFont(self.font_bold, self.company_size)
            canv.drawCentredString(cx, y - 6 * mm, self.settings.get("company_name", ""))
            y -= 11 * mm
            canv.setFont(self.font, 8.3)
            canv.setFillColor(self.muted)
            for line in self.company_lines()[:3]:
                canv.drawCentredString(cx, y, line)
                y -= 3.8 * mm
            y -= 1 * mm
            canv.setStrokeColor(self.text)
            canv.setLineWidth(1.1)
            canv.line(self.margin, y, self.width - self.margin, y)
            canv.setLineWidth(0.4)
            canv.line(self.margin, y - 1.4 * mm, self.width - self.margin, y - 1.4 * mm)
            canv.setFillColor(self.accent)
            canv.setFont(self.font_bold, 14)
            canv.drawCentredString(cx, y - 8.5 * mm, self.title)
            canv.setFillColor(self.muted)
            canv.setFont(self.font, 9)
            canv.drawCentredString(cx, y - 13 * mm, f"No. {self.doc.get('number', '')}")
        else:
            canv.setFillColor(self.text)
            canv.setFont(self.font_bold, 11)
            canv.drawCentredString(cx, top - 6 * mm, self.settings.get("company_name", ""))
            canv.setFont(self.font, 8.5)
            canv.setFillColor(self.muted)
            canv.drawCentredString(cx, top - 10.5 * mm, f"{self.title.title()} {self.doc.get('number', '')} - continued")
            canv.setStrokeColor(self.text)
            canv.setLineWidth(0.6)
            canv.line(self.margin, top - 13.5 * mm, self.width - self.margin, top - 13.5 * mm)
        canv.restoreState()

    def items_style(self, nrows: int) -> list:
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"), *_pad(5, 5, 5, 5),
                 ("LINEABOVE", (0, 0), (-1, 0), 1.0, self.text), ("LINEBELOW", (0, 0), (-1, 0), 0.6, self.text),
                 ("LINEBELOW", (0, -1), (-1, -1), 1.0, self.text)]
        if self.on("show_grid"):
            style += [("GRID", (0, 0), (-1, -1), 0.3, self.line), ("LINEAFTER", (0, 0), (-1, -1), 0.3, self.line)]
        else:
            style.append(("LINEBELOW", (0, 1), (-1, -2), 0.3, self.line))
        return style


# --------------------------------------------------------------------------- Minimal
class MinimalTemplate(BaseTemplate):
    """Thin hairlines, generous whitespace, large light title."""
    name = "Minimal"
    header_first = 52 * mm
    header_later = 24 * mm
    margin = 20 * mm
    zebra = False
    header_fill = "none"
    company_size = 16

    def draw_header(self, canv, first: bool):
        canv.saveState()
        top = self.height - self.margin + 4 * mm
        x = self.margin
        if first:
            logo_w, logo_h = self._draw_logo(canv, x, top, 34 * mm, 16 * mm)
            yy = top - (logo_h + 8 * mm if logo_h else 6 * mm)
            self._draw_company_text(canv, x, yy, self.text, self.company_size, 7.8, self.muted, 3)
            canv.setFillColor(colors.HexColor(mix(_hex(self.settings, "theme_fg", "#0f172a"), "#ffffff", 0.6)))
            canv.setFont(self.font, 30)
            canv.drawRightString(self.width - self.margin, top - 10 * mm, self.title.title())
            canv.setFillColor(self.muted)
            canv.setFont(self.font, 8.5)
            canv.drawRightString(self.width - self.margin, top - 15.5 * mm, f"No. {self.doc.get('number', '')}")
            line_y = self.height - self.header_first + 4 * mm
        else:
            self._continued(canv, top - 6 * mm, self.text)
            line_y = self.height - self.header_later + 4 * mm
        canv.setStrokeColor(self.line)
        canv.setLineWidth(0.5)
        canv.line(self.margin, line_y, self.width - self.margin, line_y)
        canv.restoreState()

    def items_style(self, nrows: int) -> list:
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"), *_pad(4, 4, 6, 6), ("LINEBELOW", (0, 0), (-1, 0), 0.6, self.text)]
        if self.on("show_grid"):
            style += [("GRID", (0, 0), (-1, -1), 0.3, self.line)]
        else:
            style.append(("LINEBELOW", (0, 1), (-1, -1), 0.3, self.line))
        return style


# --------------------------------------------------------------------------- Bold
class BoldTemplate(BaseTemplate):
    """Dark header block with a very large company name; accent title tag; strong grid."""
    name = "Bold"
    header_first = 56 * mm
    header_later = 22 * mm
    header_fill = "dark"
    company_size = 24
    zebra = True

    def draw_header(self, canv, first: bool):
        canv.saveState()
        band_h = 44 * mm if first else 13 * mm
        canv.setFillColor(self.dark)
        canv.rect(0, self.height - band_h, self.width, band_h, stroke=0, fill=1)
        canv.setFillColor(self.accent)
        canv.rect(0, self.height - band_h - 2 * mm, self.width, 2 * mm, stroke=0, fill=1)
        x, top = self.margin, self.height - 9 * mm
        if first:
            logo_w, _ = self._draw_logo(canv, x, top, 40 * mm, 26 * mm)
            if logo_w:
                x += logo_w + 6 * mm
            self._draw_company_text(canv, x, top - 7 * mm, colors.white, self.company_size, 8.2,
                                    colors.HexColor("#d1d5db"))
            # title tag
            tw = 46 * mm
            canv.setFillColor(self.accent)
            canv.roundRect(self.width - self.margin - tw, top - 12 * mm, tw, 12 * mm, 2 * mm, stroke=0, fill=1)
            canv.setFillColor(self.on_accent)
            canv.setFont(self.font_bold, 14)
            canv.drawCentredString(self.width - self.margin - tw / 2, top - 8.3 * mm, self.title)
            canv.setFillColor(colors.HexColor("#d1d5db"))
            canv.setFont(self.font, 9.5)
            canv.drawRightString(self.width - self.margin, top - 17.5 * mm, f"# {self.doc.get('number', '')}")
        else:
            self._continued(canv, self.height - 8.5 * mm, colors.white)
        canv.restoreState()

    def items_style(self, nrows: int) -> list:
        style = super().items_style(nrows)
        if self.on("show_grid"):
            style += [("BOX", (0, 0), (-1, -1), 1.0, self.dark), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(mix(_hex(self.settings, "theme_fg", "#0f172a"), "#ffffff", 0.65)))]
        return style


# --------------------------------------------------------------------------- Corporate
class CorporateTemplate(BaseTemplate):
    """Accent stripe down the left edge, two-column header, accent company name."""
    name = "Corporate"
    header_first = 50 * mm
    header_later = 22 * mm
    header_fill = "soft"
    company_size = 20
    zebra = False

    def draw_header(self, canv, first: bool):
        canv.saveState()
        canv.setFillColor(self.accent)
        canv.rect(0, 0, 5 * mm, self.height, stroke=0, fill=1)
        x, top = self.margin, self.height - self.margin + 3 * mm
        if first:
            logo_w, _ = self._draw_logo(canv, x, top, 36 * mm, 20 * mm)
            if logo_w:
                x += logo_w + 6 * mm
            self._draw_company_text(canv, x, top - 6.5 * mm, self.accent, self.company_size, 8, self.muted)
            # title box on the right
            bw = 52 * mm
            canv.setFillColor(self.soft)
            canv.rect(self.width - self.margin - bw, top - 22 * mm, bw, 22 * mm, stroke=0, fill=1)
            canv.setFillColor(self.text)
            canv.setFont(self.font_bold, 16)
            canv.drawCentredString(self.width - self.margin - bw / 2, top - 9 * mm, self.title)
            canv.setFont(self.font, 9.5)
            canv.setFillColor(self.muted)
            canv.drawCentredString(self.width - self.margin - bw / 2, top - 15 * mm, f"No. {self.doc.get('number', '')}")
            canv.drawCentredString(self.width - self.margin - bw / 2, top - 19.5 * mm, self.date(self.doc.get("date")))
            line_y = self.height - self.header_first + 4 * mm
        else:
            self._continued(canv, top - 6 * mm, self.text)
            line_y = self.height - self.header_later + 4 * mm
        canv.setStrokeColor(self.accent)
        canv.setLineWidth(1.0)
        canv.line(self.margin, line_y, self.width - self.margin, line_y)
        canv.restoreState()


# --------------------------------------------------------------------------- Elegant
class ElegantTemplate(BaseTemplate):
    """Serif, thin double rules, understated colour, boxed totals."""
    name = "Elegant"
    serif = True
    header_first = 54 * mm
    header_later = 24 * mm
    margin = 18 * mm
    zebra = False
    header_fill = "none"
    company_size = 22

    def draw_header(self, canv, first: bool):
        canv.saveState()
        x, top = self.margin, self.height - self.margin + 3 * mm
        if first:
            logo_w, _ = self._draw_logo(canv, x, top, 36 * mm, 20 * mm)
            if logo_w:
                x += logo_w + 6 * mm
            self._draw_company_text(canv, x, top - 7 * mm, self.text, self.company_size, 8.3, self.muted, 3)
            canv.setFillColor(self.accent)
            canv.setFont(self.font, 22)
            canv.drawRightString(self.width - self.margin, top - 8 * mm, self.title.title())
            canv.setFillColor(self.muted)
            canv.setFont(self.font, 9)
            canv.drawRightString(self.width - self.margin, top - 14 * mm, f"No. {self.doc.get('number', '')}")
            line_y = self.height - self.header_first + 5 * mm
        else:
            self._continued(canv, top - 6 * mm, self.text)
            line_y = self.height - self.header_later + 5 * mm
        canv.setStrokeColor(self.accent)
        canv.setLineWidth(0.9)
        canv.line(self.margin, line_y, self.width - self.margin, line_y)
        canv.setLineWidth(0.3)
        canv.line(self.margin, line_y - 1.3 * mm, self.width - self.margin, line_y - 1.3 * mm)
        canv.restoreState()

    def items_style(self, nrows: int) -> list:
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"), *_pad(5, 5, 5.5, 5.5),
                 ("LINEABOVE", (0, 0), (-1, 0), 0.8, self.accent), ("LINEBELOW", (0, 0), (-1, 0), 0.3, self.accent),
                 ("LINEBELOW", (0, -1), (-1, -1), 0.8, self.accent)]
        if self.on("show_grid"):
            style += [("GRID", (0, 0), (-1, -1), 0.3, self.line)]
        else:
            style.append(("LINEBELOW", (0, 1), (-1, -2), 0.3, self.line))
        return style


# --------------------------------------------------------------------------- Compact
class CompactTemplate(BaseTemplate):
    """Dense layout: smaller type, tight padding, full grid - best for long item lists."""
    name = "Compact"
    header_first = 40 * mm
    header_later = 18 * mm
    margin = 12 * mm
    footer = 13 * mm
    body_size = 8.2
    company_size = 16
    customer_name_size = 11
    customer_company_size = 9.8
    header_fill = "soft"
    zebra = True

    def draw_header(self, canv, first: bool):
        canv.saveState()
        x, top = self.margin, self.height - self.margin + 2 * mm
        if first:
            logo_w, _ = self._draw_logo(canv, x, top, 30 * mm, 16 * mm)
            if logo_w:
                x += logo_w + 5 * mm
            self._draw_company_text(canv, x, top - 5.5 * mm, self.text, self.company_size, 7.6, self.muted, 3)
            canv.setFillColor(self.accent)
            canv.setFont(self.font_bold, 14)
            canv.drawRightString(self.width - self.margin, top - 5.5 * mm, self.title)
            canv.setFillColor(self.muted)
            canv.setFont(self.font, 8.5)
            canv.drawRightString(self.width - self.margin, top - 10.5 * mm, f"# {self.doc.get('number', '')}")
            line_y = self.height - self.header_first + 3 * mm
        else:
            self._continued(canv, top - 5 * mm, self.text)
            line_y = self.height - self.header_later + 3 * mm
        canv.setStrokeColor(self.accent)
        canv.setLineWidth(0.8)
        canv.line(self.margin, line_y, self.width - self.margin, line_y)
        canv.restoreState()

    def items_style(self, nrows: int) -> list:
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"), *_pad(3.5, 3.5, 2.8, 2.8),
                 ("BACKGROUND", (0, 0), (-1, 0), self.soft), ("LINEBELOW", (0, 0), (-1, 0), 0.7, self.accent)]
        if self.on("show_grid"):
            style += [("GRID", (0, 0), (-1, -1), 0.35, self.line), ("BOX", (0, 0), (-1, -1), 0.6, self.line)]
        else:
            style.append(("LINEBELOW", (0, 1), (-1, -1), 0.3, self.line))
        for r in range(2, nrows, 2):
            style.append(("BACKGROUND", (0, r), (-1, r), self.zebra_color))
        return style


TEMPLATES = {
    "Modern": ModernTemplate, "Classic": ClassicTemplate, "Minimal": MinimalTemplate, "Bold": BoldTemplate,
    "Corporate": CorporateTemplate, "Elegant": ElegantTemplate, "Compact": CompactTemplate,
}


def render_pdf(doc: dict, settings: dict, out_path: str, template: str | None = None,
               page_size: str | None = None, options: dict | None = None) -> str:
    """Render one document to a PDF file. Returns the output path.

    options: effective display switches (see models.document_display_options); None = built-in defaults
    merged with the document's own JSON.
    """
    name = template or doc.get("template") or settings.get("default_template") or "Modern"
    cls = TEMPLATES.get(name, ModernTemplate)
    size = PAGE_SIZES.get((page_size or settings.get("pdf_page_size") or "A4"), A4)
    if options is None:
        import json
        options = {}
        try:
            options.update({k: v for k, v in json.loads(settings.get("doc_display_defaults") or "{}").items() if k in DISPLAY_DEFAULTS})
        except Exception:
            pass
        raw = doc.get("display_options") or ""
        try:
            own = json.loads(raw) if raw.strip() else {}
            options.update({k: v for k, v in own.items() if k in DISPLAY_DEFAULTS})
        except Exception:
            pass
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    return cls(doc, settings, size, options).build(out_path)
