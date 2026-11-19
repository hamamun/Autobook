"""Filling the Maersk SCP booking page from the data sheet.

Split so that everything testable is testable without a browser:

``values``
    Match keys, number comparison and PO totals. No browser, no I/O.
``report``
    The per-PO result rows that become the report tab.
``driver``
    The Playwright layer - selectors, waits, clicks. Nothing else decides anything.
``fill``
    Drives ``driver`` for one PO at a time and records what happened.

The browser itself is optional: importing this package must not require Playwright, so
a machine without it can still prepare data sheets.
"""

from .report import (BookingReport, PoResult, STATUS_ABANDONED, STATUS_DONE,
                     STATUS_FAILED, STATUS_LEFT, STATUS_NOT_DONE,
                     STATUS_NOT_FOUND, STATUS_INCOMPLETE, STATUS_SKIPPED)
from .values import (compared_key, compare_number, compare_whole, portal_text_to_key,
                     sku_core, to_decimal, DISPLAY_PLACES, LineComparison, PoTotals)

__all__ = [
    "BookingReport", "PoResult", "LineComparison", "PoTotals",
    "STATUS_ABANDONED", "STATUS_DONE", "STATUS_FAILED", "STATUS_LEFT",
    "STATUS_NOT_DONE", "STATUS_NOT_FOUND", "STATUS_INCOMPLETE", "STATUS_SKIPPED",
    "compared_key", "portal_text_to_key", "compare_number", "compare_whole",
    "sku_core", "to_decimal",
    "DISPLAY_PLACES",
]
