"""Color system + ttkbootstrap theme built from the settings table.

Nothing in the UI hardcodes colors: every widget asks the Palette.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from utils import contrast_text, is_hex_color, luminance, mix

_counter = itertools.count(1)

STATUS_KEYS = {
    "Unpaid": "muted",
    "Partially Paid": "warning",
    "Paid": "success",
    "Overdue": "danger",
    "Open": "accent",
    "Converted": "success",
    "Expired": "muted",
}


@dataclass
class Palette:
    accent: str = "#2563eb"
    bg: str = "#f4f6fb"
    fg: str = "#0f172a"
    success: str = "#16a34a"
    warning: str = "#d97706"
    danger: str = "#dc2626"
    muted: str = "#64748b"
    font: str = "Segoe UI"
    font_size: int = 10
    # derived
    is_dark: bool = False
    card: str = "#ffffff"
    border: str = "#e2e8f0"
    subtle: str = "#eef1f7"
    input_bg: str = "#ffffff"
    accent_soft: str = "#dbeafe"
    accent_fg: str = "#ffffff"
    sidebar_bg: str = "#111827"
    sidebar_fg: str = "#cbd5e1"
    sidebar_active: str = "#2563eb"
    sidebar_hover: str = "#1f2937"
    info: str = "#0891b2"
    fonts: dict = field(default_factory=dict)
    theme_name: str = ""

    # ---------------------------------------------------------------- helpers
    def status_color(self, status: str) -> str:
        return getattr(self, STATUS_KEYS.get(status, "muted"))

    def status_soft(self, status: str) -> str:
        return mix(self.status_color(status), self.card, 0.85)

    def on(self, bg: str) -> str:
        """Readable text color for a given background."""
        return contrast_text(bg)


def build_palette(settings: dict) -> Palette:
    def color(key, default):
        v = (settings.get(key) or "").strip()
        return v if is_hex_color(v) else default

    p = Palette(
        accent=color("theme_accent", "#2563eb"),
        bg=color("theme_bg", "#f4f6fb"),
        fg=color("theme_fg", "#0f172a"),
        success=color("theme_success", "#16a34a"),
        warning=color("theme_warning", "#d97706"),
        danger=color("theme_danger", "#dc2626"),
        muted=color("theme_muted", "#64748b"),
        font=(settings.get("ui_font") or "Segoe UI").strip() or "Segoe UI",
    )
    try:
        p.font_size = max(8, min(14, int(float(settings.get("ui_font_size") or 10))))
    except (TypeError, ValueError):
        p.font_size = 10

    p.is_dark = luminance(p.bg) < 0.4
    if p.is_dark:
        p.card = mix(p.bg, "#ffffff", 0.06)
        p.subtle = mix(p.bg, "#ffffff", 0.10)
        p.border = mix(p.bg, "#ffffff", 0.16)
        p.input_bg = mix(p.bg, "#ffffff", 0.09)
        p.accent_soft = mix(p.accent, p.bg, 0.75)
        p.sidebar_bg = mix(p.bg, "#000000", 0.35)
        p.sidebar_hover = mix(p.sidebar_bg, "#ffffff", 0.08)
    else:
        p.card = "#ffffff" if luminance(p.bg) > 0.85 else mix(p.bg, "#ffffff", 0.7)
        p.subtle = mix(p.bg, p.fg, 0.045)
        p.border = mix(p.bg, p.fg, 0.13)
        p.input_bg = "#ffffff"
        p.accent_soft = mix(p.accent, "#ffffff", 0.85)
        p.sidebar_bg = mix(p.accent, "#0b1220", 0.82)
        p.sidebar_hover = mix(p.sidebar_bg, "#ffffff", 0.08)
    p.accent_fg = contrast_text(p.accent)
    p.sidebar_fg = mix(contrast_text(p.sidebar_bg), p.sidebar_bg, 0.25)
    p.sidebar_active = p.accent
    p.info = mix(p.accent, "#0891b2", 0.5)

    f, s = p.font, p.font_size
    p.fonts = {
        "base": (f, s),
        "bold": (f, s, "bold"),
        "small": (f, max(7, s - 1)),
        "small_bold": (f, max(7, s - 1), "bold"),
        "heading": (f, s + 2, "bold"),
        "title": (f, s + 8, "bold"),
        "big": (f, s + 12, "bold"),
        "mono": ("Consolas", s),
    }
    return p


def apply_theme(style, palette: Palette) -> str:
    """Register a fresh ttkbootstrap theme from the palette and activate it. Returns the theme name."""
    from ttkbootstrap.style.theme import ThemeDefinition

    name = f"invoiceapp-{next(_counter)}"
    colors = {
        "primary": palette.accent,
        "secondary": palette.muted,
        "success": palette.success,
        "info": palette.info,
        "warning": palette.warning,
        "danger": palette.danger,
        "light": palette.subtle,
        "dark": mix(palette.fg, palette.bg, 0.15),
        "bg": palette.bg,
        "fg": palette.fg,
        "selectbg": palette.accent,
        "selectfg": palette.accent_fg,
        "border": palette.border,
        "inputfg": palette.fg,
        "inputbg": palette.input_bg,
        "active": mix(palette.bg, palette.fg, 0.10),
    }
    style.register_theme(ThemeDefinition(name, colors, "dark" if palette.is_dark else "light"))
    style.theme_use(name)
    palette.theme_name = name

    base, bold = palette.fonts["base"], palette.fonts["bold"]
    for st in ("TLabel", "TButton", "TEntry", "TCombobox", "TSpinbox", "TCheckbutton", "TRadiobutton",
               "TMenubutton", "TNotebook.Tab", "Treeview"):
        try:
            style.configure(st, font=base)
        except Exception:
            pass
    try:
        style.configure("Treeview", rowheight=int(palette.font_size * 2.9), font=base)
        style.configure("Treeview.Heading", font=bold, padding=(6, 6))
        style.configure("TButton", padding=(12, 6))
        style.configure("TNotebook.Tab", padding=(14, 8))
        style.configure("TEntry", padding=(6, 4))
        style.configure("TCombobox", padding=(6, 4))
    except Exception:
        pass
    return name
