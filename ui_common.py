"""Reusable UI building blocks: cards, tables, badges, dialogs, form helpers.

Every color and font comes from the app palette (theme.Palette); nothing is hardcoded here.
"""
from __future__ import annotations

import datetime as dt
import tkinter as tk
from tkinter import filedialog

import ttkbootstrap as tb
from ttkbootstrap.dialogs import Messagebox, Querybox

from utils import fmt_date, mix, money, parse_date, to_iso


# =========================================================================== dialogs
def ask_yes_no(parent, message: str, title: str = "Please confirm") -> bool:
    res = Messagebox.yesno(message, title, parent=parent, localize=False)
    return str(res).lower() == "yes"


def show_error(parent, message: str, title: str = "Error") -> None:
    Messagebox.show_error(message, title, parent=parent, localize=False)


def show_info(parent, message: str, title: str = "Done") -> None:
    Messagebox.show_info(message, title, parent=parent, localize=False)


def show_warning(parent, message: str, title: str = "Warning") -> None:
    Messagebox.show_warning(message, title, parent=parent, localize=False)


def ask_save_path(parent, title: str, default_name: str, ext: str, filetypes) -> str | None:
    path = filedialog.asksaveasfilename(parent=parent, title=title, initialfile=default_name,
                                        defaultextension=ext, filetypes=filetypes)
    return path or None


def ask_open_path(parent, title: str, filetypes) -> str | None:
    path = filedialog.askopenfilename(parent=parent, title=title, filetypes=filetypes)
    return path or None


# =========================================================================== small widgets
class Card(tk.Frame):
    """A flat panel with a subtle border on the page background."""

    def __init__(self, master, app, padding=16, **kw):
        p = app.palette
        super().__init__(master, bg=p.card, highlightbackground=p.border, highlightthickness=1, bd=0,
                         padx=padding, pady=padding, **kw)
        self.app = app


class StatusBadge(tk.Label):
    def __init__(self, master, app, status: str = "", **kw):
        p = app.palette
        super().__init__(master, text=status, font=p.fonts["small_bold"], padx=10, pady=3, bd=0, **kw)
        self.app = app
        self.set(status)

    def set(self, status: str):
        p = self.app.palette
        bg = p.status_color(status)
        self.configure(text=(status or "").upper(), bg=bg, fg=p.on(bg))


class Pill(tk.Label):
    """Soft colored label (light background, colored text) for counts and hints."""

    def __init__(self, master, app, text: str, color: str | None = None, **kw):
        p = app.palette
        color = color or p.accent
        super().__init__(master, text=text, bg=mix(color, p.card, 0.85), fg=color, font=p.fonts["small_bold"],
                         padx=8, pady=2, **kw)


class PageHeader(tk.Frame):
    """Title + subtitle on the left, action buttons on the right."""

    def __init__(self, master, app, title: str, subtitle: str = ""):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app = app
        left = tk.Frame(self, bg=p.bg)
        left.pack(side="left", fill="x", expand=True)
        self.title_label = tk.Label(left, text=title, font=p.fonts["title"], bg=p.bg, fg=p.fg, anchor="w")
        self.title_label.pack(anchor="w")
        self.subtitle_label = tk.Label(left, text=subtitle, font=p.fonts["base"], bg=p.bg, fg=p.muted, anchor="w")
        self.subtitle_label.pack(anchor="w", pady=(2, 0))
        self.actions = tk.Frame(self, bg=p.bg)
        self.actions.pack(side="right", anchor="n")

    def set_subtitle(self, text: str):
        self.subtitle_label.configure(text=text)

    def button(self, text, command, kind="primary", **kw):
        b = button(self.actions, text, command, kind, **kw)
        b.pack(side="left", padx=(8, 0))
        return b


def button(master, text, command, kind="primary", width=None, **kw):
    """Create a themed button. kind: primary | secondary | success | danger | outline | danger-outline | link."""
    styles = {
        "primary": "primary", "secondary": "secondary", "success": "success", "danger": "danger",
        "warning": "warning", "outline": "primary-outline", "secondary-outline": "secondary-outline",
        "danger-outline": "danger-outline", "success-outline": "success-outline", "link": "link",
    }
    b = tb.Button(master, text=text, command=command, bootstyle=styles.get(kind, kind), **kw)
    if width:
        b.configure(width=width)
    return b


class EmptyState(tk.Frame):
    """Friendly placeholder for empty lists with an optional call-to-action button."""

    def __init__(self, master, app, message: str, hint: str = "", action_text: str = "", action=None, icon="◌"):
        p = app.palette
        super().__init__(master, bg=p.card)
        inner = tk.Frame(self, bg=p.card)
        inner.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(inner, text=icon, font=(p.font, 30), bg=p.card, fg=p.border).pack()
        tk.Label(inner, text=message, font=p.fonts["heading"], bg=p.card, fg=p.fg).pack(pady=(6, 2))
        if hint:
            tk.Label(inner, text=hint, font=p.fonts["base"], bg=p.card, fg=p.muted, justify="center").pack()
        if action_text and action:
            button(inner, action_text, action, "primary").pack(pady=(14, 0))


class SearchEntry(tk.Frame):
    """Entry with placeholder + debounced callback."""

    def __init__(self, master, app, placeholder="Search...", on_change=None, width=28, delay_ms=250):
        p = app.palette
        super().__init__(master, bg=p.bg)
        self.app, self.placeholder, self.on_change, self.delay = app, placeholder, on_change, delay_ms
        self.var = tk.StringVar()
        self.entry = tb.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left", fill="x", expand=True)
        self._after = None
        self._placeholder_on = False
        self._show_placeholder()
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.var.trace_add("write", self._changed)

    def _show_placeholder(self):
        if not self.var.get():
            self._placeholder_on = True
            self.entry.configure(foreground=self.app.palette.muted)
            self.var.set(self.placeholder)

    def _focus_in(self, _=None):
        if self._placeholder_on:
            self._placeholder_on = False
            self.var.set("")
            self.entry.configure(foreground=self.app.palette.fg)

    def _focus_out(self, _=None):
        if not self.var.get():
            self._show_placeholder()

    def _changed(self, *_):
        if self._placeholder_on or not self.on_change:
            return
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(self.delay, lambda: self.on_change(self.get()))

    def get(self) -> str:
        return "" if self._placeholder_on else self.var.get().strip()

    def clear(self):
        self._placeholder_on = False
        self.var.set("")
        self._show_placeholder()


class DateField(tk.Frame):
    """Text entry (YYYY-MM-DD) with a calendar picker button."""

    def __init__(self, master, app, value: str | None = None, width=12, bg=None):
        p = app.palette
        super().__init__(master, bg=bg or p.bg)
        self.app = app
        self.var = tk.StringVar(value=value or "")
        self.entry = tb.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left", fill="x", expand=True)
        tb.Button(self, text="📅", bootstyle="secondary-outline", command=self.pick, width=3).pack(side="left", padx=(4, 0))

    def pick(self):
        start = parse_date(self.var.get()) or dt.date.today()
        chosen = Querybox.get_date(parent=self, title="Select date", start_date=start)
        if chosen:
            self.var.set(chosen.isoformat())

    def get(self) -> str:
        return self.var.get().strip()

    def get_iso(self) -> str | None:
        return to_iso(self.var.get())

    def set(self, value):
        self.var.set(value or "")


class IdCombo(tb.Combobox):
    """Read-only combobox that maps display labels to ids."""

    def __init__(self, master, options: list[tuple], allow_blank=True, blank_label="", **kw):
        super().__init__(master, state="readonly", **kw)
        self.allow_blank, self.blank_label = allow_blank, blank_label
        self._labels, self._ids = [], []
        self.set_options(options)

    def set_options(self, options: list[tuple], keep=True):
        current = self.get_id() if keep else None
        self._labels = ([self.blank_label] if self.allow_blank else []) + [str(lbl) for _, lbl in options]
        self._ids = ([None] if self.allow_blank else []) + [i for i, _ in options]
        self.configure(values=self._labels)
        if current is not None and current in self._ids:
            self.set_id(current)
        elif self._labels:
            self.current(0)

    def get_id(self):
        idx = self.current()
        return self._ids[idx] if 0 <= idx < len(self._ids) else None

    def set_id(self, value):
        try:
            self.current(self._ids.index(value))
        except ValueError:
            if self._labels:
                self.current(0)


class DataTable(tk.Frame):
    """Treeview with scrollbar, column spec, row tags for status colors and zebra striping."""

    def __init__(self, master, app, columns: list[dict], height=14, on_double=None, on_select=None,
                 status_key: str | None = None):
        p = app.palette
        super().__init__(master, bg=p.card)
        self.app, self.columns, self.status_key = app, columns, status_key
        keys = [c["key"] for c in columns]
        self.tree = tb.Treeview(self, columns=keys, show="headings", height=height, bootstyle="primary",
                                selectmode="browse")
        vsb = tb.Scrollbar(self, orient="vertical", command=self.tree.yview, bootstyle="round")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        for c in columns:
            self.tree.heading(c["key"], text=c.get("title", c["key"]), anchor=c.get("anchor", "w"))
            self.tree.column(c["key"], width=c.get("width", 120), minwidth=c.get("min", 40),
                             anchor=c.get("anchor", "w"), stretch=c.get("stretch", False))
        self.tree.tag_configure("odd", background=p.subtle)
        self.tree.tag_configure("even", background=p.card)
        for status in ("Unpaid", "Partially Paid", "Paid", "Overdue", "Open", "Converted", "Expired"):
            self.tree.tag_configure(f"st_{status}", foreground=p.status_color(status))
        self.rows: dict[str, dict] = {}
        if on_double:
            self.tree.bind("<Double-1>", lambda e: on_double(self.selected()) if self.selected() else None)
            self.tree.bind("<Return>", lambda e: on_double(self.selected()) if self.selected() else None)
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda e: on_select(self.selected()))
        self.empty: EmptyState | None = None

    def set_rows(self, rows: list[dict], formatter=None, id_key="id"):
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        for n, row in enumerate(rows):
            values = formatter(row) if formatter else [row.get(c["key"], "") for c in self.columns]
            tags = ["odd" if n % 2 else "even"]
            if self.status_key and row.get(self.status_key):
                tags.append(f"st_{row[self.status_key]}")
            iid = str(row.get(id_key, n))
            self.tree.insert("", "end", iid=iid, values=values, tags=tags)
            self.rows[iid] = row

    def selected(self) -> dict | None:
        sel = self.tree.selection()
        return self.rows.get(sel[0]) if sel else None

    def select_first(self):
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])
            self.tree.focus(kids[0])

    def show_empty(self, message, hint="", action_text="", action=None):
        self.hide_empty()
        self.empty = EmptyState(self, self.app, message, hint, action_text, action)
        self.empty.place(relx=0, rely=0, relwidth=1, relheight=1)

    def hide_empty(self):
        if self.empty is not None:
            self.empty.destroy()
            self.empty = None


# =========================================================================== forms
class Form:
    """Grid-based form helper: form.entry('Name', 'name'), form.text(...), form.get() -> dict."""

    def __init__(self, master, app, columns=2, label_width=14):
        self.master, self.app, self.columns, self.label_width = master, app, columns, label_width
        self.vars: dict[str, tk.Variable] = {}
        self.widgets: dict[str, tk.Widget] = {}
        self.texts: dict[str, tk.Text] = {}
        self.row = 0
        self.col = 0
        for c in range(columns):
            master.grid_columnconfigure(c * 2 + 1, weight=1)

    def _bg(self):
        try:
            return self.master.cget("bg")
        except Exception:
            return self.app.palette.bg

    def _place_label(self, label, row, col, sticky="e", pady=6):
        p = self.app.palette
        tk.Label(self.master, text=label, font=p.fonts["base"], bg=self._bg(), fg=p.muted, anchor="e",
                 width=self.label_width).grid(row=row, column=col * 2, sticky=sticky, padx=(0, 8), pady=pady)

    def _next(self, span=1):
        if self.col + span > self.columns:
            self.row += 1
            self.col = 0
        r, c = self.row, self.col
        self.col += span
        if self.col >= self.columns:
            self.row += 1
            self.col = 0
        return r, c

    def entry(self, label, key, value="", span=1, width=None, **kw):
        r, c = self._next(span)
        self._place_label(label, r, c)
        var = tk.StringVar(value="" if value is None else str(value))
        w = tb.Entry(self.master, textvariable=var, **kw)
        if width:
            w.configure(width=width)
        w.grid(row=r, column=c * 2 + 1, columnspan=span * 2 - 1, sticky="ew", pady=6)
        self.vars[key], self.widgets[key] = var, w
        return w

    def combo(self, label, key, values, value="", span=1, readonly=True, **kw):
        r, c = self._next(span)
        self._place_label(label, r, c)
        var = tk.StringVar(value=value)
        w = tb.Combobox(self.master, textvariable=var, values=list(values),
                        state="readonly" if readonly else "normal", **kw)
        w.grid(row=r, column=c * 2 + 1, columnspan=span * 2 - 1, sticky="ew", pady=6)
        self.vars[key], self.widgets[key] = var, w
        return w

    def check(self, label, key, value=True, span=1):
        r, c = self._next(span)
        var = tk.BooleanVar(value=bool(value))
        w = tb.Checkbutton(self.master, text=label, variable=var, bootstyle="round-toggle")
        w.grid(row=r, column=c * 2 + 1, columnspan=span * 2 - 1, sticky="w", pady=6)
        self.vars[key], self.widgets[key] = var, w
        return w

    def text(self, label, key, value="", span=1, height=3):
        r, c = self._next(span)
        self._place_label(label, r, c, sticky="ne")
        p = self.app.palette
        w = tb.Text(self.master, height=height, wrap="word", font=p.fonts["base"])
        w.insert("1.0", value or "")
        w.grid(row=r, column=c * 2 + 1, columnspan=span * 2 - 1, sticky="ew", pady=6)
        self.texts[key], self.widgets[key] = w, w
        return w

    def custom(self, label, key, widget, span=1):
        r, c = self._next(span)
        self._place_label(label, r, c)
        widget.grid(row=r, column=c * 2 + 1, columnspan=span * 2 - 1, sticky="ew", pady=6)
        self.widgets[key] = widget
        return widget

    def get(self) -> dict:
        data = {k: v.get() for k, v in self.vars.items()}
        for k, t in self.texts.items():
            data[k] = t.get("1.0", "end").strip()
        return data

    def focus_first(self):
        for w in self.widgets.values():
            try:
                w.focus_set()
                return
            except Exception:
                continue


class Dialog(tb.Toplevel):
    """Modal dialog base: subclasses fill self.body and call self.buttons(...)."""

    def __init__(self, parent, app, title: str, width=620, height=None):
        super().__init__(title=title, transient=parent.winfo_toplevel(), resizable=(True, True))
        self.app, self.parent, self.result = app, parent, None
        p = app.palette
        self.configure(bg=p.bg)
        self.outer = tk.Frame(self, bg=p.bg, padx=20, pady=18)
        self.outer.pack(fill="both", expand=True)
        self.button_bar = tk.Frame(self.outer, bg=p.bg)
        self.button_bar.pack(side="bottom", fill="x", pady=(16, 0))
        self.body = tk.Frame(self.outer, bg=p.bg)
        self.body.pack(side="top", fill="both", expand=True)
        self.bind("<Escape>", lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._size = (width, height)

    def buttons(self, primary_text="Save", primary=None, extra: list | None = None, cancel_text="Cancel"):
        button(self.button_bar, cancel_text, self.close, "secondary-outline").pack(side="right")
        if primary:
            button(self.button_bar, primary_text, primary, "primary").pack(side="right", padx=(0, 8))
        for text, cmd, kind in (extra or []):
            button(self.button_bar, text, cmd, kind).pack(side="left", padx=(0, 8))

    def show(self):
        w, h = self._size
        self.update_idletasks()
        h = h or max(self.winfo_reqheight(), 200)
        try:
            top = self.parent.winfo_toplevel()
            px, py = top.winfo_rootx(), top.winfo_rooty()
            pw, ph = top.winfo_width(), top.winfo_height()
            x = max(0, px + (pw - w) // 2)
            y = max(0, py + (ph - h) // 2)
        except Exception:
            x, y = 200, 120
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(min(w, 480), min(h, 240))
        self.grab_set()
        self.focus_force()
        self.wait_window(self)
        return self.result

    def close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


# =========================================================================== formatting helpers
def fmt_money(app, value) -> str:
    return money(value, app.settings.get("currency_symbol", ""))


def fmt_day(app, value) -> str:
    return fmt_date(value, app.settings.get("date_format") or "%d %b %Y")


def section_label(master, app, text, bg=None):
    p = app.palette
    return tk.Label(master, text=text.upper(), font=p.fonts["small_bold"], bg=bg or p.card, fg=p.muted, anchor="w")


def hr(master, app):
    return tk.Frame(master, bg=app.palette.border, height=1)
