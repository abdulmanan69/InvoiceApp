# InvoiceApp — Invoice, Quotation & Payment Manager (PKR)

A standalone Windows desktop app for small businesses to manage **customers, vendors,
products/services, invoices, quotations and payments**. Everything runs locally in a single
SQLite file — no server, no internet, no subscription. Default currency is **Pakistani Rupee
(PKR, "Rs")**, changeable in Settings.

## Features

- **Dashboard** — outstanding balance, paid this month, overdue count, open quotations,
  recent invoices and an activity feed.
- **Invoices & Quotations** — searchable/filterable lists (status, customer, date range),
  editor with product auto-fill, per-line tax override, percentage or fixed discount,
  live totals, duplicate, print, PDF export, one-click **Convert quotation → invoice**.
- **Payments** — partial payments, overpayment guard (override with confirmation),
  **Mark as paid** (records a real payment row), global payment log with filters, CSV export.
- **Status** is always computed from payments vs. total: `Unpaid`, `Partially Paid`, `Paid`,
  `Overdue` (colour-coded everywhere). Quotations show `Open`, `Converted`, `Expired`.
- **Numbering** — configurable prefix + counter + zero-padding per document type; the number
  stays editable and duplicates are rejected on save.
- **3 PDF templates** — *Modern* (colour band), *Classic* (centred serif, formal rules),
  *Minimal* (hairlines & whitespace). A4 or Letter, logo, company/client blocks, itemised
  table with repeated header on every page, totals, status badge, notes/terms, bank details.
- **Settings** — company profile & logo, currency, tax defaults, numbering, payment-method
  list, default notes/terms, template & page size, **theme colours (live-applied to the UI
  and PDFs)**, database backup/restore. No business data is hardcoded anywhere.
- CSV export for invoices, customers and payments.

## Run from source

```bat
python -m pip install -r requirements.txt
python main.py
```

Requires Python 3.11+ on Windows 10/11. Dependencies: `reportlab` (PDF), `ttkbootstrap`
(modern ttk theme), `pillow` (logo preview / images), `pyinstaller` (packaging only).

Data lives in `data\invoice_app.db` next to `main.py` (or next to the exe when packaged).
PDFs produced by *Print* go to `data\exports\`. Unexpected errors are logged to
`data\error.log` — the app never loses data on a UI error.

## Tests

```bat
python -m unittest tests.test_flow -v
```

Covers the full spec flow: customer → product → invoice → partial payment (`Partially Paid`)
→ mark as paid (`Paid`) → quotation → convert → duplicate → PDF for every template/page size
(1 page for short docs, multi-page with repeated header for 60 lines) → missing logo / empty
invoice → backup → delete → restore → data survives.

## Build the portable exe

```bat
build.bat
```

`build.bat` installs dependencies, runs the tests, then runs PyInstaller
(`--onefile --windowed`, heavy modules excluded) and copies the result to
`InvoiceApp.exe` in the project root. Copy that single file anywhere; it creates its
`data\` folder beside itself on first launch.

> Windows SmartScreen may warn about an unsigned exe the first time — choose
> *More info → Run anyway*.

## Project layout

| File | Purpose |
| --- | --- |
| `main.py` | App window, sidebar navigation, theme application, global error handler |
| `db.py` | SQLite schema, settings store (with all defaults), backup/restore |
| `models.py` | CRUD, totals, computed statuses, numbering, conversions, dashboard stats, CSV |
| `pdf_templates.py` | Modern / Classic / Minimal PDF layouts (reportlab) |
| `theme.py` | Palette derived from settings → ttkbootstrap theme + fonts |
| `ui_common.py` | Cards, tables, badges, dialogs, form helpers |
| `ui_dashboard.py`, `ui_documents.py`, `ui_customers.py`, `ui_vendors.py`, `ui_products.py`, `ui_payments.py`, `ui_settings.py` | One module per screen |
| `utils.py` | Paths, money/number/date parsing & formatting |
| `tests/test_flow.py` | End-to-end logic test |
| `build.bat`, `requirements.txt` | Packaging |

## Backup & restore

*Settings → Data → Back up database…* copies the live database (SQLite online-backup API) to
any location. *Restore from backup…* validates the file, asks for confirmation, keeps an
`invoice_app.db.before-restore` safety copy, then replaces the current data.
