"""One portal run: read the data sheet, drive the browser, write the report back.

This is the seam between the spreadsheet world and the browser world. It is also the
only part that can fail because Playwright is not installed, so the import is deferred
until the browser is actually needed - preparing a data sheet must never require it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from ..booking import BookingLine
from .fill import PoOutcome, run
from .report import BookingReport, PoResult

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    """What a whole portal run produced, in words the operator can read."""

    report: BookingReport
    outcomes: list[PoOutcome] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    evidence_dir: Path | None = None

    @property
    def headline(self) -> str:
        return f"Portal run finished - {self.report.summary_line()}"


def lines_from_data_sheet(path: Path) -> dict[str, list[BookingLine]]:
    """Group the ``Booking_lines`` rows of a data sheet by PO number.

    The data sheet is our own output, so the column headings are known - they come from
    ``schema.REPORT...`` definitions and never vary. Rows are read by heading, not by
    position, so a column inserted later does not break the mapping.
    """
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    try:
        if "Booking_lines" not in wb.sheetnames:
            raise ValueError(f"{path.name} has no Booking_lines tab")
        ws = wb["Booking_lines"]
        header = [str(cell.value or "").strip() for cell in ws[1]]
        index = {name: position for position, name in enumerate(header)}

        def value(row, heading, default=""):
            position = index.get(heading)
            if position is None:
                return default
            cell = row[position]
            return cell if cell is not None else default

        by_po: dict[str, list[BookingLine]] = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            sku = str(value(row, "SKU number")).strip()
            if not sku:
                continue
            po_no = str(value(row, "PO no")).strip()
            by_po.setdefault(po_no, []).append(BookingLine(
                source_file=str(value(row, "Source file")),
                sheet_name="",
                po_no=po_no,
                style_no=sku.split("-")[0] if "-" in sku else "",
                colour="",
                colour_code="",
                size="",
                sku=sku,
                ordered_qty=int(value(row, "Ordered quantity", 0) or 0),
                booked_qty=int(value(row, "Booked quantity", 0) or 0),
                booked_packages=int(value(row, "Booked packages", 0) or 0),
                qty_per_package=int(value(row, "Qty per package", 0) or 0),
                booked_volume=float(value(row, "Booked volume", 0) or 0),
                booked_gross_kg=float(value(row, "Booked gross weight", 0) or 0),
                description=str(value(row, "Description of goods")),
            ))
        return by_po
    finally:
        wb.close()


def fill_from_data_sheet(data_sheet: Path,
                         *,
                         profile_dir: Path,
                         ask: Callable[[str, Sequence[str]], str] | None = None,
                         stop_before_submit: bool = False,
                         channel: str = "msedge",
                         headless: bool = False,
                         driver=None,
                         attach: bool = False,
                         port: int = 9222,
                         evidence_dir: Path | None = None,
                         on_wait: Callable[[str], None] | None = None,
                         login_timeout_s: int | None = None) -> RunSummary:
    """Fill every PO in ``data_sheet`` and return the report.

    ``driver`` is injectable so the whole run can be exercised without a browser.
    """
    by_po = lines_from_data_sheet(data_sheet)
    lines: list[str] = [f"{len(by_po)} PO(s) in the data sheet: {', '.join(by_po)}"]

    # Evidence goes next to the data sheet: when the selectors are wrong, a screenshot
    # and the page HTML are what turn a guess into a one-line fix.
    if evidence_dir is None:
        evidence_dir = Path(data_sheet).parent / "portal-failures"
    evidence_dir = Path(evidence_dir)

    owns_browser = driver is None
    playwright = None
    context = None
    try:
        if owns_browser:
            from .driver import Driver, launch
            playwright, context = launch(Path(profile_dir), headless=headless,
                                         channel=channel, attach=attach, port=port)
            page = context.pages[0] if context.pages else context.new_page()
            driver = Driver(page)

            # Open the portal, and if it lands on a sign-in screen, wait for the operator
            # to sign in. Autobook never handles credentials: they are typed into
            # Maersk's own page, and only the resulting session is reused.
            driver.open_portal()
            timeout_s = (login_timeout_s if login_timeout_s is not None
                         else driver.LOGIN_TIMEOUT_S)
            if not driver.signed_in():
                if not driver.wait_for_sign_in(timeout_s, on_wait=on_wait):
                    raise RuntimeError(
                        "Not signed in. Sign in to Maersk in the browser window and run "
                        "again - the session is kept, so this only happens once.")

        try:
            outcomes = run(by_po.keys(), by_po, driver, ask=ask,
                           stop_before_submit=stop_before_submit)
        except Exception as exc:
            made = driver.snapshot(evidence_dir, "portal-failure")
            detail = ""
            if made:
                detail = (f"\n\nSaved for diagnosis:"
                          f"\n  screenshot: {made.get('screenshot', '-')}"
                          f"\n  page HTML : {made.get('html', '-')}"
                          f"\n  inventory : {made.get('inventory', '-')}"
                          f"\n  page URL  : {made.get('url', '-')}")
            raise RuntimeError(f"{exc}{detail}") from exc

        report = BookingReport()
        for outcome in outcomes:
            report.add(outcome.result)
            result = outcome.result
            detail = f" - {result.portal_status}" if result.portal_status else ""
            filled = f" [{result.matched} SKU(s) filled]"
            lines.append(f"PO {result.po_no}: {result.status}{filled}{detail}")
            for problem in result.problems:
                lines.append(f"    {problem}")
            for skipped in result.skipped:
                lines.append(f"    skipped: {skipped}")

        lines.append(report.summary_line())
        return RunSummary(report=report, outcomes=outcomes, lines=lines,
                          evidence_dir=evidence_dir)
    finally:
        # When we launched the browser we close it; when attached to the operator's own
        # browser we leave it open - closing a window they are using would be rude and
        # loses their session view.
        if owns_browser and context is not None and not attach:
            context.close()
        if playwright is not None:
            playwright.stop()
