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

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e .
python -m autobook
```

Linux/macOS activate with `source .venv/bin/activate`.

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

## Predefined data sheet headers

Supplier name, Supplier address, Buyer / brand, Order no, Split PO no, Style no,
Description, Destination country, Order qty, Ship qty, Short ship, Total cartons,
Total net wt, Total gross wt, Total CBM, Colour / size breakdown, Source file,
Confidence, Notes / issues.

Defined once in `autobook/schema.py`.

## Deliberate limits in this milestone

* PDF page text is read and detected, but table mapping for PDFs is not built yet — a
  scanned PDF reports "no text layer" instead of producing nonsense.
* Legacy `.xls` is rejected with an instruction to re-save as `.xlsx`.
* One profile (the Gymshark packing list sample) ships; unknown layouts go to Review.
* No browser automation yet — that is the next milestone.
