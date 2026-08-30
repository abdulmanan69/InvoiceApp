"""PDF rendering for invoices and quotations: three layouts (Modern, Classic, Minimal).

All templates share one story builder and differ in page decoration, fonts and table styling.
Pagination is handled by platypus; the item table repeats its header on every page.
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

from utils import data_dir, fmt_date, fmt_number, is_hex_color, mix, money

TEMPLATE_NAMES = ["Modern", "Classic", "Minimal"]
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


# --------------------------------------------------------------------------- base template
class BaseTemplate:
    name = "Base"
    header_first = 46 * mm      # height reserved above the frame on page 1
    header_later = 20 * mm
    footer = 16 * mm
    margin = 16 * mm
    serif = False
    zebra = True

    def __init__(self, doc: dict, settings: dict, page_size=A4):
        self.doc = doc
        self.settings = settings
        self.page_size = page_size
        self.width, self.height = page_size
        accent_hex = _hex(settings, "theme_accent", "#2563eb")
        fg_hex = _hex(settings, "theme_fg", "#0f172a")
        self.accent = colors.HexColor(accent_hex)
        self.text = colors.HexColor(fg_hex)
        self.muted = colors.HexColor(_hex(settings, "theme_muted", "#64748b"))
        self.line = colors.HexColor(mix(fg_hex, "#ffffff", 0.82))
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
        f, fb = self.font, self.font_bold
        self.st = {
            "body": ParagraphStyle("body", fontName=f, fontSize=9.2, leading=12, textColor=self.text),
            "body_r": ParagraphStyle("body_r", fontName=f, fontSize=9.2, leading=12, textColor=self.text, alignment=TA_RIGHT),
            "small": ParagraphStyle("small", fontName=f, fontSize=8, leading=10.5, textColor=self.muted),
            "label": ParagraphStyle("label", fontName=fb, fontSize=7.4, leading=10, textColor=self.muted),
            "strong": ParagraphStyle("strong", fontName=fb, fontSize=9.6, leading=12.5, textColor=self.text),
            "strong_r": ParagraphStyle("strong_r", fontName=fb, fontSize=9.6, leading=12.5, textColor=self.text, alignment=TA_RIGHT),
            "th": ParagraphStyle("th", fontName=fb, fontSize=8.2, leading=10, textColor=self.text),
            "th_r": ParagraphStyle("th_r", fontName=fb, fontSize=8.2, leading=10, textColor=self.text, alignment=TA_RIGHT),
            "total": ParagraphStyle("total", fontName=fb, fontSize=11.5, leading=14, textColor=self.accent),
            "total_r": ParagraphStyle("total_r", fontName=fb, fontSize=11.5, leading=14, textColor=self.accent, alignment=TA_RIGHT),
            "h": ParagraphStyle("h", fontName=fb, fontSize=8.4, leading=11, textColor=self.accent, spaceAfter=2),
        }

    def money(self, value) -> str:
        return money(value, self.symbol)

    def date(self, value) -> str:
        return fmt_date(value, self.date_format) or "-"

    @property
    def frame_width(self) -> float:
        return self.width - 2 * self.margin

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
        story = [NextPageTemplate("later")] + self.story()
        pdf.build(story)
        return out_path

    # ------------------------------------------------------------------ story pieces
    def story(self) -> list:
        parts = []
        parts += self.parties_block()
        parts.append(Spacer(1, 7 * mm))
        parts.append(self.items_table())
        parts.append(Spacer(1, 5 * mm))
        parts.append(KeepTogether([self.totals_table()]))
        footer = self.footer_block()
        if footer:
            parts.append(Spacer(1, 8 * mm))
            parts += footer
        return parts

    def company_lines(self) -> list[str]:
        s = self.settings
        lines = [ln.strip() for ln in (s.get("company_address") or "").splitlines() if ln.strip()]
        contact = "  |  ".join(x for x in (s.get("company_phone"), s.get("company_email"), s.get("company_website")) if x)
        if contact:
            lines.append(contact)
        if s.get("company_tax_number"):
            lines.append(f"Tax No: {s['company_tax_number']}")
        return lines

    def customer_paragraphs(self, address_key: str = "billing_address") -> list:
        cust = self.doc.get("customer") or {}
        if not cust:
            return [_p("(no customer selected)", self.st["small"])]
        out = [_p(cust.get("name", ""), self.st["strong"])]
        if cust.get("company"):
            out.append(_p(cust["company"], self.st["body"]))
        if cust.get(address_key):
            out.append(_p(cust[address_key], self.st["body"]))
        contact = "  |  ".join(x for x in (cust.get("phone"), cust.get("email")) if x)
        if contact:
            out.append(_p(contact, self.st["small"]))
        if cust.get("tax_number"):
            out.append(_p(f"Tax No: {cust['tax_number']}", self.st["small"]))
        return out

    def meta_rows(self) -> list[tuple[str, str]]:
        d = self.doc
        rows = [(f"{self.title.title()} No.", d.get("number", "")), ("Date", self.date(d.get("date")))]
        if d.get("due_date"):
            rows.append(("Due Date" if self.is_invoice else "Valid Until", self.date(d.get("due_date"))))
        if d.get("currency"):
            rows.append(("Currency", d["currency"]))
        if d.get("source_quotation_number"):
            rows.append(("Quotation Ref", d["source_quotation_number"]))
        return rows

    def status_badge(self):
        label = self.status.upper()
        if not label:
            return Spacer(1, 1)
        style = ParagraphStyle("badge", fontName=self.font_bold, fontSize=7.6, leading=9.5,
                               textColor=colors.white if _lum(self.status_color) < 0.6 else self.text,
                               alignment=TA_CENTER)
        badge = Table([[Paragraph(label, style)]], colWidths=[min(36 * mm, max(20 * mm, len(label) * 1.9 * mm + 6 * mm))])
        badge.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), self.status_color), ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ]))
        wrap = Table([[badge]], colWidths=[36 * mm])
        wrap.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        return wrap

    def parties_block(self) -> list:
        """Bill-to (left), ship-to (middle, only if different) and meta (right)."""
        cust = self.doc.get("customer") or {}
        cols = [[_p("BILL TO", self.st["h"])] + self.customer_paragraphs("billing_address")]
        ship = (cust.get("shipping_address") or "").strip()
        if ship and ship != (cust.get("billing_address") or "").strip():
            cols.append([_p("SHIP TO", self.st["h"]), _p(cust.get("name", ""), self.st["strong"]), _p(ship, self.st["body"])])
        meta_data = [[_p(k, self.st["label"]), _p(v, self.st["strong_r"])] for k, v in self.meta_rows()]
        meta_data.append([_p("Status", self.st["label"]), self.status_badge()])
        meta = Table(meta_data, colWidths=[26 * mm, 36 * mm])
        meta.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("LINEBELOW", (0, 0), (-1, -2), 0.4, self.line),
        ]))
        cols.append([meta])
        meta_w = 64 * mm
        rest = self.frame_width - meta_w
        widths = [rest / (len(cols) - 1)] * (len(cols) - 1) + [meta_w]
        t = Table([cols], colWidths=widths)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-2, -1), 6 * mm), ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return [t]

    def items_table(self) -> Table:
        items = self.doc.get("items") or []
        default_tax = float(self.doc.get("tax_rate") or 0)
        show_tax = any(float(i.get("tax_rate") if i.get("tax_rate") is not None else default_tax) for i in items)
        tax_label = self.settings.get("tax_label") or "Tax"
        head = [_p("#", self.st["th"]), _p("Description", self.st["th"]), _p("Qty", self.st["th_r"]),
                _p("Unit", self.st["th"]), _p("Unit Price", self.st["th_r"])]
        if show_tax:
            head.append(_p(f"{tax_label} %", self.st["th_r"]))
        head.append(_p("Amount", self.st["th_r"]))
        rows = [head]
        for n, it in enumerate(items, start=1):
            rate = it.get("tax_rate") if it.get("tax_rate") is not None else default_tax
            row = [_p(str(n), self.st["body"]), _p(it.get("description", ""), self.st["body"]),
                   _p(fmt_number(it.get("quantity")), self.st["body_r"]), _p(it.get("unit") or "", self.st["body"]),
                   _p(self.money(it.get("unit_price")), self.st["body_r"])]
            if show_tax:
                row.append(_p(fmt_number(rate), self.st["body_r"]))
            row.append(_p(self.money(it.get("line_total")), self.st["body_r"]))
            rows.append(row)
        if not items:
            rows.append([_p("", self.st["body"]), _p("No items", self.st["small"])] + [_p("", self.st["body"])] * (len(head) - 2))
        fixed = [9 * mm, 16 * mm, 16 * mm, 30 * mm] + ([15 * mm] if show_tax else []) + [32 * mm]
        widths = [fixed[0], self.frame_width - sum(fixed)] + fixed[1:]
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle(self.items_style(len(rows))))
        return t

    def items_style(self, nrows: int) -> list:
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("BACKGROUND", (0, 0), (-1, 0), self.soft),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, self.accent),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, self.line),
        ]
        if self.zebra:
            for r in range(2, nrows, 2):
                style.append(("BACKGROUND", (0, r), (-1, r), self.zebra_color))
        return style

    def totals_rows(self) -> list[tuple[str, str, str]]:
        d = self.doc
        rows = [("Subtotal", self.money(d.get("subtotal")), "body")]
        if float(d.get("discount_amount") or 0) > 0:
            label = "Discount"
            if d.get("discount_type") == "percent":
                label += f" ({fmt_number(d.get('discount_value'))}%)"
            rows.append((label, "-" + self.money(d.get("discount_amount")), "body"))
        if float(d.get("tax_amount") or 0) > 0:
            rows.append((self.settings.get("tax_label") or "Tax", self.money(d.get("tax_amount")), "body"))
        rows.append(("Total", self.money(d.get("total")), "total"))
        if self.is_invoice and float(d.get("paid") or 0) > 0:
            rows.append(("Paid", "-" + self.money(d.get("paid")), "body"))
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
        st = [("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
              ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
              ("LINEBELOW", (0, 0), (-1, -2), 0.4, self.line)]
        for i, (_, _, kind) in enumerate(rows):
            if kind == "total":
                st.append(("BACKGROUND", (0, i), (-1, i), self.soft))
                st.append(("LINEABOVE", (0, i), (-1, i), 0.8, self.accent))
        inner.setStyle(TableStyle(st))
        outer = Table([[Spacer(1, 1), inner]], colWidths=[self.frame_width - 78 * mm, 78 * mm])
        outer.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        return outer

    def footer_block(self) -> list:
        sections = []
        if self.doc.get("notes"):
            sections.append(("NOTES", self.doc["notes"]))
        if self.doc.get("terms"):
            sections.append(("TERMS & CONDITIONS", self.doc["terms"]))
        if self.is_invoice and (self.settings.get("bank_details") or "").strip():
            sections.append(("PAYMENT DETAILS", self.settings["bank_details"]))
        return [KeepTogether([_p(title, self.st["h"]), _p(text, self.st["small"]), Spacer(1, 3 * mm)])
                for title, text in sections]

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
        left = f"{self.settings.get('company_name', '')}   -   {self.title.title()} {self.doc.get('number', '')}"
        canv.drawString(self.margin, y - 4 * mm, left)
        canv.drawRightString(self.width - self.margin, y - 4 * mm, f"Page {doc.page}")
        canv.restoreState()

    def _draw_logo(self, canv, x, y_top, max_w, max_h, center_x=None) -> tuple[float, float]:
        """Draw the logo with its top-left at (x, y_top) (or centred on center_x). Returns (w, h) drawn."""
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


# --------------------------------------------------------------------------- Modern
class ModernTemplate(BaseTemplate):
    """Bold color band across the top, sans-serif, colored table header, zebra rows."""
    name = "Modern"
    header_first = 52 * mm
    header_later = 22 * mm

    def _build_styles(self):
        super()._build_styles()
        self.st["th"] = ParagraphStyle("th", fontName=self.font_bold, fontSize=8.2, leading=10, textColor=self.on_accent)
        self.st["th_r"] = ParagraphStyle("th_r", fontName=self.font_bold, fontSize=8.2, leading=10,
                                         textColor=self.on_accent, alignment=TA_RIGHT)

    def draw_header(self, canv, first: bool):
        canv.saveState()
        band_h = 40 * mm if first else 13 * mm
        canv.setFillColor(self.accent)
        canv.rect(0, self.height - band_h, self.width, band_h, stroke=0, fill=1)
        x = self.margin
        top = self.height - 8 * mm
        canv.setFillColor(self.on_accent)
        if first:
            logo_w, _ = self._draw_logo(canv, x, top, 40 * mm, 24 * mm)
            if logo_w:
                x += logo_w + 6 * mm
            canv.setFont(self.font_bold, 15)
            canv.drawString(x, top - 5.5 * mm, self.settings.get("company_name", ""))
            canv.setFont(self.font, 8)
            yy = top - 11 * mm
            for line in self.company_lines()[:4]:
                canv.drawString(x, yy, line)
                yy -= 3.9 * mm
            canv.setFont(self.font_bold, 26)
            canv.drawRightString(self.width - self.margin, top - 9 * mm, self.title)
            canv.setFont(self.font, 9.5)
            canv.drawRightString(self.width - self.margin, top - 15.5 * mm, f"# {self.doc.get('number', '')}")
        else:
            canv.setFont(self.font_bold, 10)
            canv.drawString(x, self.height - 8.5 * mm, self.settings.get("company_name", ""))
            canv.drawRightString(self.width - self.margin, self.height - 8.5 * mm,
                                 f"{self.title.title()} {self.doc.get('number', '')} (continued)")
        canv.restoreState()

    def items_style(self, nrows: int) -> list:
        style = super().items_style(nrows)
        style += [("BACKGROUND", (0, 0), (-1, 0), self.accent), ("LINEBELOW", (0, 0), (-1, 0), 0, self.accent)]
        return style


# --------------------------------------------------------------------------- Classic
class ClassicTemplate(BaseTemplate):
    """Centered serif header with double rule, formal ruled table."""
    name = "Classic"
    serif = True
    header_first = 66 * mm
    header_later = 26 * mm
    zebra = False

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
            canv.setFont(self.font_bold, 17)
            canv.drawCentredString(cx, y - 5.5 * mm, self.settings.get("company_name", ""))
            y -= 10 * mm
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
            canv.setFont(self.font_bold, 16)
            canv.drawCentredString(cx, y - 8.5 * mm, self.title)
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
        return [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("LINEABOVE", (0, 0), (-1, 0), 1.0, self.text),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, self.text),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, self.line),
            ("LINEBELOW", (0, -1), (-1, -1), 1.0, self.text),
        ]


# --------------------------------------------------------------------------- Minimal
class MinimalTemplate(BaseTemplate):
    """Thin hairlines, generous whitespace, large light title."""
    name = "Minimal"
    header_first = 50 * mm
    header_later = 24 * mm
    margin = 20 * mm
    zebra = False

    def draw_header(self, canv, first: bool):
        canv.saveState()
        top = self.height - self.margin + 4 * mm
        x = self.margin
        if first:
            logo_w, logo_h = self._draw_logo(canv, x, top, 34 * mm, 16 * mm)
            yy = top - (logo_h + 6 * mm if logo_h else 4 * mm)
            canv.setFillColor(self.text)
            canv.setFont(self.font_bold, 11.5)
            canv.drawString(x, yy, self.settings.get("company_name", ""))
            canv.setFont(self.font, 7.8)
            canv.setFillColor(self.muted)
            yy -= 4.2 * mm
            for line in self.company_lines()[:3]:
                canv.drawString(x, yy, line)
                yy -= 3.6 * mm
            canv.setFillColor(colors.HexColor(mix(_hex(self.settings, "theme_fg", "#0f172a"), "#ffffff", 0.6)))
            canv.setFont(self.font, 30)
            canv.drawRightString(self.width - self.margin, top - 10 * mm, self.title.title())
            canv.setFillColor(self.muted)
            canv.setFont(self.font, 8.5)
            canv.drawRightString(self.width - self.margin, top - 15.5 * mm, f"No. {self.doc.get('number', '')}")
            line_y = self.height - self.header_first + 4 * mm
        else:
            canv.setFillColor(self.text)
            canv.setFont(self.font_bold, 9.5)
            canv.drawString(x, top - 6 * mm, self.settings.get("company_name", ""))
            canv.setFillColor(self.muted)
            canv.setFont(self.font, 8.5)
            canv.drawRightString(self.width - self.margin, top - 6 * mm,
                                 f"{self.title.title()} {self.doc.get('number', '')} / continued")
            line_y = self.height - self.header_later + 4 * mm
        canv.setStrokeColor(self.line)
        canv.setLineWidth(0.5)
        canv.line(self.margin, line_y, self.width - self.margin, line_y)
        canv.restoreState()

    def items_style(self, nrows: int) -> list:
        return [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, self.text),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, self.line),
        ]


TEMPLATES = {"Modern": ModernTemplate, "Classic": ClassicTemplate, "Minimal": MinimalTemplate}


def render_pdf(doc: dict, settings: dict, out_path: str, template: str | None = None,
               page_size: str | None = None) -> str:
    """Render one document to a PDF file. Returns the output path."""
    name = template or doc.get("template") or settings.get("default_template") or "Modern"
    cls = TEMPLATES.get(name, ModernTemplate)
    size = PAGE_SIZES.get((page_size or settings.get("pdf_page_size") or "A4"), A4)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    return cls(doc, settings, size).build(out_path)
