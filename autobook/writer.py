"""Build the populated data sheet.

Output is one workbook with three sheets:

* ``Packing_lists`` - one row per document, using the predefined headers
* ``Carton_lines``  - the detail behind those totals, for auditing
* ``Review``        - everything a human still needs to look at

Every input file gets a row, including ones that failed, so nothing disappears
without the operator seeing it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .models import PackingList
from .schema import COLUMNS, SHEET_LINES, SHEET_REVIEW, SHEET_SUMMARY, Column

_FONT = Font(size=10)
_HEAD_FILL = PatternFill("solid", fgColor="1F3864")
_HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
_THIN = Border(*[Side(style="thin", color="D9D9D9")] * 4)

# Confidence -> cell fill, so a weak value is visible at a glance.
_CONF_FILL = {
    "high": PatternFill("solid", fgColor="FFFFFF"),
    "medium": PatternFill("solid", fgColor="FFF2CC"),
    "low": PatternFill("solid", fgColor="FCE4D6"),
}


def _style_header(ws: Worksheet, columns: tuple[Column, ...] | list[Column]) -> None:
    for index, column in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=index, value=column.header)
        cell.fill = _HEAD_FILL
        cell.font = _HEAD_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(index)].width = column.width
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}1"


def _issues_text(pl: PackingList) -> str:
    return " | ".join(f"{issue.field}: {issue.problem}" for issue in pl.issues)


def _worst_confidence(pl: PackingList) -> str:
    """Overall confidence for the row: low beats medium beats high.

    The document layout match is included, so an unmatched file never shows as high.
    """
    values = [v for k, v in pl.confidence.items() if not k.startswith("_")]
    # A file whose layout was never identified must never present as confident.
    profile_match = pl.confidence.get("_profile", "")
    if profile_match in {"", "none", "pdf-unmapped"}:
        values.append("low")
    if not values:
        return "low"
    if "low" in values:
        return "low"
    if "medium" in values:
        return "medium"
    return "high"


def summary_row(pl: PackingList) -> dict[str, object]:
    """Flatten one packing list into the predefined column set."""
    short: int | None = None
    if pl.order_qty is not None and pl.ship_qty is not None:
        short = pl.order_qty - pl.ship_qty

    return {
        "supplier": pl.supplier,
        "supplier_address": pl.supplier_address,
        "buyer": pl.buyer,
        "order_no": pl.order_no,
        "split_po_no": pl.split_po_no,
        "style_no": pl.style_no,
        "description": pl.description,
        "destination": pl.destination,
        "order_qty": pl.order_qty,
        "ship_qty": pl.ship_qty,
        "short_ship": short,
        "total_cartons": pl.total_cartons if pl.total_cartons is not None else (pl.carton_count or None),
        "total_net_kg": pl.total_net_kg,
        "total_gross_kg": pl.total_gross_kg,
        "total_cbm": pl.total_cbm,
        "source_file": pl.source.name,
        "confidence": _worst_confidence(pl),
        "issues": _issues_text(pl),
    }


def write_workbook(results: list[PackingList], out_path: Path,
                   prepared_at: datetime | None = None) -> Path:
    """Write the data sheet and return its path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prepared_at = prepared_at or datetime.now()

    wb = Workbook()

    # ---- sheet 1: one row per packing list --------------------------------
    ws = wb.active
    ws.title = SHEET_SUMMARY
    _style_header(ws, COLUMNS)
    for row_index, pl in enumerate(results, start=2):
        data = summary_row(pl)
        for col_index, column in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=row_index, column=col_index, value=data.get(column.key))
            cell.font = _FONT
            cell.border = _THIN
            if column.number_format:
                cell.number_format = column.number_format
            cell.alignment = Alignment(vertical="top", wrap_text=column.key in
                                       {"supplier_address", "issues"})
        confidence_cell = ws.cell(row=row_index, column=COLUMNS.index(
            next(c for c in COLUMNS if c.key == "confidence")) + 1)
        confidence_cell.fill = _CONF_FILL.get(str(confidence_cell.value), _CONF_FILL["low"])
    if len(results) == 0:
        ws.cell(row=2, column=1, value="No packing lists were prepared").font = Font(
            italic=True, size=10)

    # ---- sheet 2: carton detail ------------------------------------------
    detail_columns = [
        Column("source_file", "Source file", 30),
        Column("carton_no", "Carton no", 12),
        Column("ctn_count", "Cartons (per source row)", 14, "#,##0"),
        Column("colour", "Colour", 22),
        Column("size", "Size", 7),
        Column("qty", "Qty (pcs)", 9, "#,##0"),
        Column("net_kg", "Net kg", 9, "#,##0.00"),
        Column("gross_kg", "Gross kg", 9, "#,##0.00"),
        Column("cbm", "CBM", 9, "#,##0.0000"),
    ]
    ws2 = wb.create_sheet(SHEET_LINES)
    _style_header(ws2, detail_columns)
    row = 2
    for pl in results:
        shown_rows: set[tuple[str, int]] = set()
        for line in pl.cartons:
            # Print the carton count once per source row - repeating it on every size
            # line would make the column add up to several times the real total.
            key = (pl.source.name, line.row_ref)
            count_cell = None if key in shown_rows else line.ctn_count
            shown_rows.add(key)
            values = [pl.source.name, line.carton_no, count_cell, line.colour, line.size,
                      line.qty, line.net_kg, line.gross_kg, line.cbm]
            for col_index, (column, value) in enumerate(zip(detail_columns, values), start=1):
                cell = ws2.cell(row=row, column=col_index, value=value)
                cell.font = _FONT
                cell.border = _THIN
                if column.number_format:
                    cell.number_format = column.number_format
            row += 1

    # ---- sheet 3: what a human must look at ------------------------------
    review_columns = [
        Column("source_file", "Source file", 30),
        Column("field", "Field", 18),
        Column("severity", "Severity", 11),
        Column("problem", "Problem", 62),
        Column("action", "What to do", 52),
    ]
    ws3 = wb.create_sheet(SHEET_REVIEW)
    _style_header(ws3, review_columns)
    row = 2
    for pl in results:
        for issue in pl.issues:
            values = [pl.source.name, issue.field, issue.severity, issue.problem, issue.action]
            for col_index, value in enumerate(values, start=1):
                cell = ws3.cell(row=row, column=col_index, value=value)
                cell.font = _FONT
                cell.border = _THIN
                cell.alignment = Alignment(vertical="top", wrap_text=col_index >= 4)
                if col_index == 3:
                    cell.fill = (PatternFill("solid", fgColor="FFC7CE") if issue.severity == "error"
                                 else PatternFill("solid", fgColor="FFF2CC") if issue.severity == "review"
                                 else PatternFill("solid", fgColor="DDEBF7"))
            row += 1
    if row == 2:
        ws3.cell(row=2, column=1, value="Nothing to review").font = Font(italic=True, size=10)

    # ---- provenance ------------------------------------------------------
    info = wb.create_sheet("About")
    info["A1"] = "Autobook data sheet"
    info["A1"].font = Font(bold=True, size=12)
    info["A3"] = "Prepared at"
    info["B3"] = prepared_at.strftime("%Y-%m-%d %H:%M:%S")
    info["A4"] = "Packing lists"
    info["B4"] = len(results)
    info["A5"] = "Carton lines"
    info["B5"] = sum(len(pl.cartons) for pl in results)
    info["A6"] = "Open issues"
    info["B6"] = sum(len(pl.issues) for pl in results)
    info.column_dimensions["A"].width = 18
    info.column_dimensions["B"].width = 40

    wb.save(out_path)
    return out_path
