"""Login, first-run owner setup, and user management dialogs."""
from __future__ import annotations

import tkinter as tk

import ttkbootstrap as tb

import models
from ui_common import Dialog, Form, button, show_error, show_info


class _CenteredDialog(Dialog):
    """Dialog centred on the screen (used before the main window is visible)."""

    def show(self):
        w, h = self._size
        self.update_idletasks()
        h = h or max(self.winfo_reqheight(), 200)
        x = max(0, (self.winfo_screenwidth() - w) // 2)
        y = max(0, (self.winfo_screenheight() - h) // 2 - 40)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.deiconify()
        self.grab_set()
        self.focus_force()
        self.wait_window(self)
        return self.result


class SetupOwnerDialog(_CenteredDialog):
    """First run: create the owner account."""

    def __init__(self, parent, app):
        super().__init__(parent, app, "Welcome - create the owner account", width=520)
        p = app.palette
        tk.Label(self.body, text="Create the owner account", font=p.fonts["title"], bg=p.bg, fg=p.fg, anchor="w").pack(fill="x")
        tk.Label(self.body, text="The owner sees everything (payments, purchases, costs, settings).\n"
                                 "You can add employee accounts later in Settings > Users.",
                 font=p.fonts["base"], bg=p.bg, fg=p.muted, justify="left", anchor="w").pack(fill="x", pady=(4, 14))
        box = tk.Frame(self.body, bg=p.bg)
        box.pack(fill="x")
        self.form = Form(box, app, columns=1, label_width=16)
        self.form.entry("Your name", "full_name")
        self.form.entry("Username *", "username", "owner")
        self.form.entry("Password *", "password", show="*")
        self.form.entry("Confirm password *", "confirm", show="*")
        self.buttons("Create account", self.save, cancel_text="Quit",
                     extra=[("Join a shop (employee)", self.join_shop, "info-outline")])
        self.form.widgets["full_name"].focus_set()
        self.bind("<Return>", lambda e: self.save())

    def save(self):
        d = self.form.get()
        if d["password"] != d["confirm"]:
            show_error(self, "The two passwords do not match.")
            return
        try:
            uid = models.create_user(self.app.db, d["username"], d["password"], models.ROLE_OWNER, d["full_name"])
        except models.ValidationError as e:
            show_error(self, str(e))
            return
        self.result = models.get_user(self.app.db, uid)
        self.close()

    def join_shop(self):
        user = JoinShopDialog(self, self.app).show()
        if user:
            self.result = user
            self.close()


class JoinShopDialog(_CenteredDialog):
    """Employee onboarding on a new PC: sign in with the cloud account the owner created, which sets
    up a matching local account and starts syncing. No local owner account needed."""

    def __init__(self, parent, app):
        super().__init__(parent, app, "Join a shop", width=540)
        p = app.palette
        tk.Label(self.body, text="Join your shop", font=p.fonts["title"], bg=p.bg, fg=p.fg, anchor="w").pack(fill="x")
        tk.Label(self.body, text="Paste the invite code your owner sent you, then pick your own email and password.\n"
                                 "The app connects, joins the shop and keeps your data synced (works offline too).",
                 font=p.fonts["base"], bg=p.bg, fg=p.muted, justify="left", anchor="w").pack(fill="x", pady=(4, 14))
        box = tk.Frame(self.body, bg=p.bg)
        box.pack(fill="x")
        self.form = Form(box, app, columns=1, label_width=16)
        self.form.entry("Invite code *", "code")
        self.form.entry("Your name", "full_name")
        self.form.entry("Your email *", "email")
        self.form.entry("Choose a password *", "password", show="*")
        self.message = tk.Label(self.body, text="", font=p.fonts["small"], bg=p.bg, fg=p.muted, anchor="w",
                                wraplength=490, justify="left")
        self.message.pack(fill="x", pady=(6, 0))
        self.buttons("Join shop", self.join, cancel_text="Back")
        self.form.widgets["code"].focus_set()
        self.bind("<Return>", lambda e: self.join())

    def join(self):
        d = self.form.get()
        self.message.configure(text="Joining... signing in and downloading your data.", fg=self.app.palette.muted)
        self.update_idletasks()
        try:
            user = models.cloud_join_invite(self.app.db, d["code"], d["email"], d["password"], d["full_name"])
        except Exception as e:
            self.message.configure(text=str(e), fg=self.app.palette.danger)
            return
        self.result = user
        self.close()


class LoginDialog(_CenteredDialog):
    def __init__(self, parent, app):
        super().__init__(parent, app, "Sign in", width=440)
        p = app.palette
        tk.Label(self.body, text=app.settings.get("company_name") or "InvoiceApp", font=p.fonts["title"], bg=p.bg,
                 fg=p.fg, anchor="w").pack(fill="x")
        tk.Label(self.body, text="Sign in to continue", font=p.fonts["base"], bg=p.bg, fg=p.muted, anchor="w").pack(
            fill="x", pady=(2, 14))
        box = tk.Frame(self.body, bg=p.bg)
        box.pack(fill="x")
        self.form = Form(box, app, columns=1, label_width=12)
        self.form.entry("Username", "username")
        self.form.entry("Password", "password", show="*")
        self.message = tk.Label(self.body, text="", font=p.fonts["small"], bg=p.bg, fg=p.danger, anchor="w")
        self.message.pack(fill="x", pady=(6, 0))
        self.attempts = 0
        self.buttons("Sign in", self.login, cancel_text="Quit",
                     extra=[("Join a shop", self.join_shop, "info-outline")])
        self.form.widgets["username"].focus_set()
        self.bind("<Return>", lambda e: self.login())

    def join_shop(self):
        user = JoinShopDialog(self, self.app).show()
        if user:
            self.result = user
            self.close()

    def login(self):
        d = self.form.get()
        user = models.authenticate(self.app.db, d["username"], d["password"])
        if not user:
            self.attempts += 1
            self.message.configure(text="Wrong username or password." + (" (Ask the owner to reset it.)" if self.attempts >= 3 else ""))
            self.form.vars["password"].set("")
            return
        self.result = user
        self.close()


class UserDialog(Dialog):
    """Add or edit a user (owner only)."""

    def __init__(self, parent, app, user: dict | None = None):
        super().__init__(parent, app, "Edit user" if user else "New user", width=520)
        self.user = user or {}
        u = self.user
        self.form = Form(self.body, app, columns=1, label_width=16)
        self.form.entry("Full name", "full_name", u.get("full_name", ""))
        e = self.form.entry("Username *", "username", u.get("username", ""))
        if user:
            e.configure(state="disabled")
        self.form.combo("Role", "role", ["owner", "employee"], u.get("role", "employee"))
        self.form.entry("New password" if user else "Password *", "password", show="*")
        self.form.entry("Confirm password", "confirm", show="*")
        if user:
            self.form.check("Active (can sign in)", "active", bool(u.get("active", 1)))
        p = app.palette
        tk.Label(self.body, text="Owners see payments, purchases, costs, profit and settings.\n"
                                 "Employees can manage invoices, quotations, customers and products.",
                 font=p.fonts["small"], bg=p.bg, fg=p.muted, justify="left", anchor="w").grid(row=99, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.buttons("Save user", self.save)
        self.form.focus_first()

    def save(self):
        d = self.form.get()
        if d["password"] and d["password"] != d["confirm"]:
            show_error(self, "The two passwords do not match.")
            return
        try:
            if self.user:
                models.update_user(self.app.db, self.user["id"], full_name=d["full_name"], role=d["role"],
                                   active=d.get("active", True), password=d["password"] or None)
                self.result = self.user["id"]
            else:
                if not d["password"]:
                    show_error(self, "A password is required for a new user.")
                    return
                self.result = models.create_user(self.app.db, d["username"], d["password"], d["role"], d["full_name"])
        except models.ValidationError as e:
            show_error(self, str(e))
            return
        self.close()


class ChangePasswordDialog(Dialog):
    def __init__(self, parent, app):
        super().__init__(parent, app, "Change my password", width=460)
        self.form = Form(self.body, app, columns=1, label_width=18)
        self.form.entry("Current password", "current", show="*")
        self.form.entry("New password", "password", show="*")
        self.form.entry("Confirm new password", "confirm", show="*")
        self.buttons("Change password", self.save)
        self.form.focus_first()

    def save(self):
        d = self.form.get()
        user = self.app.user or {}
        if not models.authenticate(self.app.db, user.get("username", ""), d["current"]):
            show_error(self, "Current password is wrong.")
            return
        if d["password"] != d["confirm"]:
            show_error(self, "The two new passwords do not match.")
            return
        try:
            models.update_user(self.app.db, user["id"], password=d["password"])
        except models.ValidationError as e:
            show_error(self, str(e))
            return
        self.result = True
        self.close()
        show_info(self.parent, "Password changed.", "Done")
