# Autobook

Automation of booking. One pipeline: **packing list in → predefined data sheet out →
booking lines onto the Maersk SCP booking page.**

This milestone delivers the first two stages: file intake and data sheet preparation.

## What works now

1. **Browse for packing lists** — a native file dialog that always reopens in the folder
   you last used. Excel (`.xlsx`, `.xlsm`, `.xls`), `.csv` and `.pdf` can be selected,
   in one trip or several; the selection accumulates and duplicates are ignored.
2. **Copy into a fixed working directory** — nothing is edited in place. Each Prepare
   run gets its own dated sub-folder, name clashes become `name (2).xlsx`, and the
   originals are never moved or deleted.
3. **Prepare** — every file is searched for the fields defined in a YAML profile and the
   values are written into a data sheet with **predefined headers**, plus a carton-detail
   tab and a Review tab listing anything a human still needs to check.

## Run it

```bat
python -m venv .venv
.venv\Scripts\activate          :: Windows (cmd)
pip install -e ".[dev]"
python -m autobook
```

Linux/macOS activate with `source .venv/bin/activate`.

The entry point is `autobook/__main__.py`; **run the package, not a file**. Details,
VS Code setup and troubleshooting: `docs/running-in-vscode.md`.

## Where files go

| What | Windows default |
|---|---|
| Work directory (copies of your packing lists) | `%LOCALAPPDATA%\Autobook\work\<date-time>\` |
| Data sheet output | `%LOCALAPPDATA%\Autobook\output\data_sheet_<date-time>.xlsx` |
| Settings (last folder browsed, etc.) | `%LOCALAPPDATA%\Autobook\settings.json` |

Override for testing with the environment variables `AUTOBOOK_HOME`,
`AUTOBOOK_WORK_DIR` and `AUTOBOOK_OUTPUT_DIR`.

## Adding a document layout

No code: drop a YAML file in `profiles/`. The profile says where each field lives and
how the carton grid is laid out. See `profiles/gymshark_packing_list.yaml`.

```yaml
name: gymshark_packing_list
match:
  any_of: ["PACKING LIST"]
fields:
  supplier: {cell: [0, 0]}
  style_no: {label: "STYLE NO"}
  order_qty: {label: "ORDER QTY", cast: int}
  order_no: {label: "ORDER NO", fallback_filename_regex: '-GS-(\d+)\s'}
cartons:
  header_label: "CTN NO"
  stop_label: "SUMMARY"
  colour_col: 3
  size_start_col: 5
  size_end_col: 12
  cbm_col: 20
```

A file that matches no profile is never guessed at — it gets a row marked with an error
so the operator can see it was not used.

## Sheets in the data sheet

| Sheet | Purpose |
|---|---|
| `Packing_lists` | one row per document (18 predefined columns) |
| `Carton_lines` | every carton/size line, with its carton count — the audit trail |
| `Booking_lines` | **one row per portal SKU**, ready to type into the Maersk grid |
| `Review` | everything a human still needs to check |
| `About` | when it was prepared, counts, SKU suffix used |

Carton lines are aggregated per style/colour/size because the portal is organised by SKU,
not by carton. See `docs/maersk-field-mapping.md`.

## Predefined data sheet headers

Supplier name, Supplier address, Buyer / brand, Order no, Split PO no, Style no,
Description, Destination country, Order qty, Ship qty, Short ship, Total cartons,
Total net wt, Total gross wt, Total CBM, Source file, Confidence, Notes / issues — 18
columns, defined once in `autobook/schema.py`. (The colour/size breakdown column was
removed: the detail lives in the `Carton_lines` tab.)

**Total cartons** is the sum of the packing list's **CTN QTY** column, not a count of
table rows. In these documents "CTN NO" is a label and one row can cover several cartons
(e.g. row 10 with CTN QTY 3), so counting rows undercounts. The `Carton_lines` tab shows
`Cartons (per source row)` once per row, so that column adds up to the same total.

## Deliberate limits in this milestone

* PDF page text is read and detected, but table mapping for PDFs is not built yet — a
  scanned PDF reports "no text layer" instead of producing nonsense.
* Legacy `.xls` is rejected with an instruction to re-save as `.xlsx`.
* One profile (the Gymshark packing list sample) ships; unknown layouts go to Review.
* No browser automation yet — that is the next milestone.
