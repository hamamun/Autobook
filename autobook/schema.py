"""Canonical column definitions for the output data sheet.

The header row is *predefined* and lives here, in one place, so the writer, the
preview and (later) the Maersk line builder all agree on the same names and order.
Changing a heading is a one-line edit here, not a hunt through the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    key: str          # internal name, used by extractors and the writer
    header: str       # what the operator sees
    width: int = 16
    number_format: str | None = None


COLUMNS: tuple[Column, ...] = (
    Column("supplier", "Supplier name", 30),
    Column("supplier_address", "Supplier address", 46),
    Column("buyer", "Buyer / brand", 16),
    Column("order_no", "Order no", 12),
    Column("split_po_no", "Split PO no", 15),
    Column("style_no", "Style no", 12),
    Column("description", "Description", 22),
    Column("destination", "Destination country", 12),
    Column("order_qty", "Order qty (pcs)", 12, "#,##0"),
    Column("ship_qty", "Ship qty (pcs)", 12, "#,##0"),
    Column("short_ship", "Short ship (pcs)", 12, "#,##0"),
    Column("total_cartons", "Total cartons", 11, "#,##0"),
    Column("total_net_kg", "Total net wt (kg)", 12, "#,##0.00"),
    Column("total_gross_kg", "Total gross wt (kg)", 12, "#,##0.00"),
    Column("total_cbm", "Total CBM", 10, "#,##0.0000"),
    Column("source_file", "Source file", 34),
    Column("confidence", "Confidence", 12),
    Column("issues", "Notes / issues", 48),
)

HEADERS: tuple[str, ...] = tuple(c.header for c in COLUMNS)
KEYS: tuple[str, ...] = tuple(c.key for c in COLUMNS)

#: Sheets in the produced workbook, in tab order.
SHEET_SUMMARY = "Packing_lists"
SHEET_BOOKING = "Booking_lines"
SHEET_LINES = "Carton_lines"
SHEET_REVIEW = "Review"
SHEET_REPORT = "Report"

#: One row per PO worked by the portal, success or failure.
REPORT_COLUMNS: tuple[Column, ...] = (
    Column("po_no", "PO no", 15),
    Column("booking_no", "Booking no", 16),
    Column("status", "Result", 14),
    Column("portal_status", "Portal status", 22),
    Column("matched", "SKUs filled", 12, "#,##0"),
    Column("skipped", "SKUs skipped", 12, "#,##0"),
    Column("submitted", "Submitted", 11),
    Column("problems", "What happened", 66),
)
