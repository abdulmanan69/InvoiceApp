# InvoiceApp — Invoice, Quotation, Inventory & Payment Manager (PKR)

A standalone Windows desktop app for small businesses: **customers, vendors, products, stock,
purchases, invoices, quotations, payments, returns** — all in one local SQLite file. No server,
no internet, no subscription. Default currency is **Pakistani Rupee (PKR, "Rs")**, changeable in
Settings.

## Features

### Documents
- **Invoices & quotations** — searchable/filterable lists, editor with product auto-fill (shows
  what is in stock), per-line tax override, % or fixed discount, live totals, duplicate, print,
  PDF export, one-click **Convert quotation → invoice**.
- **7 PDF templates** — Modern, Classic, Minimal, Bold, Corporate, Elegant, Compact. A4 or
  Letter. Big company name and bill-to name/company, logo, itemised table with grid borders,
  totals, status badge, notes/terms, bank details, **signature boxes** (prepared by / received
  by with names). Long lists paginate with the table header repeated.
- **Per-document PDF options** — *Show / hide sections & columns…* in the editor: turn off the
  status badge, due date, currency, logo, any table column (#, SKU, Qty, Unit, Unit price,
  Tax %), discount/tax/paid lines, notes, terms, bank details, signatures, grid. Defaults live in
  *Settings → PDF layout*.
- **Editable "Bill To"** — change the heading (e.g. "Client", "Invoice To") and type any bill-to
  text; leave it empty to print the customer's details automatically.
- Numbering: prefix + counter + padding per document type, editable, duplicates rejected.

### Money
- Payments (partial, overpayment guard, Mark as paid = real payment row), global payments log,
  CSV export. Status is always computed: Unpaid / Partially Paid / Paid / Overdue.
- **Customer returns** credit the invoice (balance drops) and optionally put items back in stock.

### Inventory
- Products carry a **cost price (what you paid)** and a **sale price**; margin shown to owners.
- **Purchases from vendors** add stock and update the cost price. **Returns to vendor** remove stock.
- Invoices **cannot sell more than is in stock** (50 in stock → max 50 on invoices; owners can
  allow negative stock in Settings). Editing an invoice frees its own stock first.
- Stock levels, low-stock alerts (global threshold or per product), stock adjustments, full
  movement history, **best sellers** (qty, revenue, gross profit) by date range.

### Access
- **Login with roles.** First run creates the **owner**. Owners see everything: payments,
  purchases, costs, profit, vendors, settings, users. **Employees** can work with invoices,
  quotations, customers, products (sale prices only) and view stock — no payments, no costs,
  no deletes. Manage accounts in *Settings → Users*; sign-in can be switched off.
- Owner dashboard: outstanding, paid this month, overdue, open quotes, **gross profit**, stock
  value, low stock, purchases, best sellers, activity feed. Employee dashboard shows counts only.

### Everything is configurable
Company profile & logo, currency, tax defaults, numbering, payment-method list, default
notes/terms, template & page size, bill-to heading, signature labels/names, PDF defaults, low
stock rules, **theme colours (live)**, backup/restore. Nothing business-specific is hardcoded.

## Run from source

```bat
python -m pip install -r requirements.txt
python main.py
```

Python 3.11+ on Windows 10/11. Dependencies: `reportlab` (PDF), `ttkbootstrap` (modern ttk
theme), `pillow` (logo preview / images), `pyinstaller` (packaging only).

Data lives in `data\invoice_app.db` next to `main.py` (or next to the exe). *Print* writes to
`data\exports\`. Errors are logged to `data\error.log`.

## Tests

```bat
python -m unittest tests.test_flow -v
```

Covers: customer → product → invoice → partial payment → paid → quotation → convert → PDFs for
all 7 templates × 2 sizes (1 page short, multi-page long) with every switch on/off → backup →
restore; purchases → stock limit → returns (credit + restock) → vendor returns → best sellers →
profit; users, roles and password checks; bad-number safety.

## Build the portable exe

```bat
build.bat
```

Installs dependencies, runs the tests, runs PyInstaller (`--onefile --windowed`, with the app
icon and version details baked in) and copies `InvoiceApp.exe` to the project root. Copy that one
file anywhere; it stores its data in a `data\` folder next to itself, or in
`%LOCALAPPDATA%\InvoiceApp` when that folder is read-only.

## Build the Windows installer

```bat
build.bat
build_installer.bat
```

`build_installer.bat` uses **Inno Setup 6** (install once with `winget install JRSoftware.InnoSetup`)
and produces `dist\InvoiceApp-Setup.exe`. Share that single file — double-clicking it installs
InvoiceApp per-user (no admin prompt), adds Start-menu and optional desktop shortcuts, and
registers an uninstaller in *Add or remove programs*.

## "Windows protected your PC" / "app not safe to run"

This appears for **any** program that is not signed with a paid code-signing certificate — it is
about the signature, not about the app being unsafe. To run it: **More info → Run anyway** (the
installer shows the same, click **More info → Run anyway**). The warning fades on its own once the
file builds reputation. Baking in the icon and version info (done here) and using the installer
make it less alarming. To remove it completely you need an OV/EV code-signing certificate
(a paid, yearly purchase from a certificate authority); once you have one, sign both
`InvoiceApp.exe` and `InvoiceApp-Setup.exe` with `signtool sign /fd SHA256 /a ...`.

## Project layout

| File | Purpose |
| --- | --- |
| `main.py` | App window, login flow, role-aware sidebar, theme application, error handler |
| `db.py` | SQLite schema + migrations, settings defaults, PDF display defaults, backup/restore |
| `models.py` | CRUD, totals, statuses, numbering, users/auth, stock movements, purchases, returns, reports |
| `pdf_templates.py` | The 7 PDF layouts + display-option handling (reportlab) |
| `theme.py` | Palette from settings → ttkbootstrap theme + fonts |
| `ui_common.py` | Cards, tables, badges, dialogs, forms, calendar popup |
| `ui_auth.py` | Owner setup, login, user management dialogs |
| `ui_inventory.py` | Stock, purchases, returns, best sellers, movement history |
| `ui_dashboard.py`, `ui_documents.py`, `ui_customers.py`, `ui_vendors.py`, `ui_products.py`, `ui_payments.py`, `ui_settings.py` | One module per screen |
| `utils.py` | Paths, money/number/date helpers |
| `tests/test_flow.py` | End-to-end logic tests |
| `build.bat`, `requirements.txt` | Packaging |

## Backup & restore

*Settings → Data → Back up database…* copies the live database anywhere. *Restore from backup…*
validates the file, asks for confirmation, keeps `invoice_app.db.before-restore`, then replaces the
current data (customers, invoices, stock, users — everything).

## Cloud sync quick start (optional)

Sync all shops' PCs through one free Supabase project. Everything keeps working offline.

**Owner (once):** create a project at supabase.com -> in the app: Settings -> Cloud sync ->
copy the Project URL + anon key from the dashboard (any blob containing both works) -> press
"Connect & check" -> if asked, press "Database setup" (SQL is copied, editor opens: paste, Run) ->
sign in / Create account (your shop is created automatically) -> press "Copy invite code".

**Each employee:** open the app -> "Join a shop" on the login screen -> paste the invite code +
pick their own email and password. Done - no keys, no other setup.

Tip: in Supabase -> Authentication -> Sign In/Providers -> Email, turn OFF "Confirm email"
so employees can join instantly.
