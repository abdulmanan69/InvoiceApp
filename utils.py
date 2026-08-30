"""Small shared helpers: paths, number/date parsing, money formatting."""
from __future__ import annotations

import datetime as dt
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP

APP_NAME = "InvoiceApp"
DB_FILENAME = "invoice_app.db"


# --------------------------------------------------------------------------- paths
def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def base_dir() -> str:
    """Directory the app lives in: next to the exe when frozen, else the source dir."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def data_dir() -> str:
    """Writable folder for the database, logo and exports.

    Prefers a ``data`` folder next to the app (portable use). If that location is read-only
    (e.g. installed under Program Files), falls back to %LOCALAPPDATA%/InvoiceApp/data.
    """
    preferred = os.path.join(base_dir(), "data")
    try:
        os.makedirs(preferred, exist_ok=True)
        probe = os.path.join(preferred, ".write_test")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
        return preferred
    except Exception:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, APP_NAME, "data")
        os.makedirs(path, exist_ok=True)
        return path


def default_db_path() -> str:
    return os.path.join(data_dir(), DB_FILENAME)


def resource_path(rel: str) -> str:
    """Path to a bundled read-only resource (works inside PyInstaller onefile)."""
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, rel)


# --------------------------------------------------------------------------- numbers
def round2(value) -> float:
    try:
        return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0


def parse_float(text, default=None):
    """Parse user-entered number. Accepts commas, spaces, currency symbols. Returns default on failure."""
    if text is None:
        return default
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    if not s:
        return default
    s = re.sub(r"[^\d.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def parse_int(text, default=None):
    v = parse_float(text, None)
    if v is None:
        return default
    return int(v)


def money(amount, symbol: str = "Rs", decimals: int = 2) -> str:
    """Format money like 'Rs 12,345.00'. Never raises."""
    try:
        amount = float(amount or 0)
    except (TypeError, ValueError):
        amount = 0.0
    sign = "-" if amount < 0 else ""
    body = f"{abs(amount):,.{decimals}f}"
    symbol = (symbol or "").strip()
    return f"{sign}{symbol} {body}".strip() if symbol else f"{sign}{body}"


def fmt_number(value, max_decimals: int = 2) -> str:
    """Quantity formatter: 2 -> '2', 2.5 -> '2.5', 2.125 -> '2.13'."""
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value == int(value):
        return str(int(value))
    s = f"{value:.{max_decimals}f}".rstrip("0").rstrip(".")
    return s


# --------------------------------------------------------------------------- dates
ISO = "%Y-%m-%d"


def today_iso() -> str:
    return dt.date.today().strftime(ISO)


def parse_date(text) -> dt.date | None:
    """Accept YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, or a date object."""
    if text is None:
        return None
    if isinstance(text, dt.datetime):
        return text.date()
    if isinstance(text, dt.date):
        return text
    s = str(text).strip()
    if not s:
        return None
    for fmt in (ISO, "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def to_iso(text) -> str | None:
    d = parse_date(text)
    return d.strftime(ISO) if d else None


def fmt_date(iso_text, style: str = "%d %b %Y") -> str:
    d = parse_date(iso_text)
    return d.strftime(style) if d else ""


def add_days(iso_text, days: int) -> str:
    d = parse_date(iso_text) or dt.date.today()
    return (d + dt.timedelta(days=int(days or 0))).strftime(ISO)


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- misc
def open_file(path: str) -> bool:
    """Open a file with the OS default handler. Returns False if it failed."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
        return True
    except Exception:
        return False


def print_file(path: str) -> bool:
    """Send a file to the default printer (Windows shell 'print' verb)."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path, "print")  # type: ignore[attr-defined]
            return True
    except Exception:
        pass
    return open_file(path)


def safe_filename(text: str) -> str:
    return re.sub(r"[^\w\-. ]+", "_", text or "").strip() or "document"


def luminance(hex_color: str) -> float:
    """Relative luminance 0..1 of a #rrggbb color (falls back to 1.0 on bad input)."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except Exception:
        return 1.0

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def is_hex_color(text: str) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", (text or "").strip()))


def mix(c1: str, c2: str, t: float) -> str:
    """Linear blend of two hex colors; t=0 -> c1, t=1 -> c2."""
    try:
        a = [int(c1.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        b = [int(c2.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    except Exception:
        return c1
    t = max(0.0, min(1.0, t))
    out = [round(x + (y - x) * t) for x, y in zip(a, b)]
    return "#%02x%02x%02x" % tuple(out)


def contrast_text(bg: str) -> str:
    return "#111827" if luminance(bg) > 0.45 else "#ffffff"
