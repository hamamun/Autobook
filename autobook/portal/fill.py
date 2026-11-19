"""Fill the portal for one PO at a time, and record what happened.

The loop is the operator's own click path (see ``docs/portal-steps.md``), in order:

    filter by PO → read the status → open the booking → edit
    → fill each matched row → save draft → review → compare → submit
    → filter the same PO again → read the status back → next PO

Every decision that can be made without a browser was moved to :mod:`.values`, and every
selector to :mod:`.driver`. This module only sequences them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from ..booking import BookingLine
from .driver import Driver, PortalError
from .report import (PoResult, STATUS_INCOMPLETE, STATUS_LEFT, STATUS_NOT_FOUND,
                     STATUS_SKIPPED)
from .values import (LineComparison, PoTotals, compared_key, portal_text_to_key,
                     round_for_portal)

logger = logging.getLogger(__name__)

#: Statuses that mean "do not work this booking".
SKIP_STATUSES = {"cancel", "stuffed"}

#: Statuses that mean the booking took after submit.
SUCCESS_STATUSES = {"pending for confirmation", "booking confirmed"}

#: Portal dropdown value (label on screen).
CARGO_TYPE = "Flat pack"

#: Always set on the edit page.
INVOICE_CURRENCY = "USD"


class NeedsUser(RuntimeError):
    """The run cannot continue without an answer from the operator.

    Carries a question and the choices, so the UI can ask and resume.
    """

    def __init__(self, question: str, choices: Sequence[str] = ()) -> None:
        super().__init__(question)
        self.question = question
        self.choices = list(choices)


@dataclass
class PoOutcome:
    """What one run through a PO produced."""

    result: PoResult
    comparison: list[LineComparison]

    @property
    def ok(self) -> bool:
        return self.result.ok


def _status_skips(status: str) -> bool:
    """Exact label match, trimmed and case-insensitive.

    Substring matching would catch ``Unstuffed`` / ``Partially stuffed``, which mean the
    opposite of ``Stuffed``.
    """
    return " ".join(status.split()).lower() in SKIP_STATUSES


def _status_succeeds(status: str) -> bool:
    return " ".join(status.split()).lower() in SUCCESS_STATUSES


def fill_po(driver: Driver,
            po_no: str,
            lines: Sequence[BookingLine],
            *,
            ask: Callable[[str, Sequence[str]], str] | None = None,
            stop_before_submit: bool = False) -> PoOutcome:
    """Work one PO end to end.

    ``ask`` is how a question reaches the operator; it returns the chosen answer. When no
    ``ask`` is supplied and an answer is needed, :class:`NeedsUser` is raised instead, so
    a headless run stops rather than guessing.
    """
    ask = ask or (lambda question, choices: (_ for _ in ()).throw(
        NeedsUser(question, choices)))

    result = PoResult(po_no=po_no)
    comparisons: list[LineComparison] = []

    # ---- filter and read the list ---------------------------------------
    driver.filter_by_order(po_no)

    if driver.result_state() == "empty":
        result.status = STATUS_NOT_FOUND
        result.problems.append(f"No booking found for PO {po_no}")
        return PoOutcome(result.finish(), comparisons)

    rows = [row for row in driver.booking_rows() if row["booking"]]
    if not rows:
        result.status = STATUS_NOT_FOUND
        result.problems.append(f"No booking row for PO {po_no}")
        return PoOutcome(result.finish(), comparisons)

    # ---- skip statuses before offering anything -------------------------
    workable = [row for row in rows if not _status_skips(row["status"])]
    for row in rows:
        if _status_skips(row["status"]):
            logger.info("%s: booking %s is %s - skipped",
                        po_no, row["booking"], row["status"])
    if not workable:
        result.status = STATUS_SKIPPED
        result.portal_status = ", ".join(sorted({r["status"] for r in rows}))
        result.problems.append(
            f"All bookings for this PO are {result.portal_status} - nothing to do")
        return PoOutcome(result.finish(), comparisons)

    # ---- one PO can match several bookings: ask which -------------------
    if len(workable) > 1:
        choices = [f"{row['booking']} ({row['status']})" for row in workable]
        answer = ask(
            f"PO {po_no} matches {len(workable)} bookings. Which one should be worked?",
            choices)
        chosen = next((row for row in workable if row["booking"] in answer), workable[0])
    else:
        chosen = workable[0]

    result.booking_no = chosen["booking"]
    result.portal_status = chosen["status"]

    driver.open_booking(result.booking_no)
    driver.start_editing()
    driver.set_invoice_currency(INVOICE_CURRENCY)
    driver.ensure_po_expanded(po_no)

    # ---- fill the rows that have a partner ------------------------------
    matched, skipped, filled = _fill_rows(driver, po_no, lines, result, ask)
    result.skipped = skipped

    # ---- a missing line stops everything --------------------------------
    # A booking without some of its goods is worse than no booking: it looks correct,
    # reports as confirmed, and the shortage is only discovered later. So the run stops
    # here, before Review and long before Submit.
    if skipped:
        result.status = STATUS_INCOMPLETE
        result.problems.insert(
            0, f"{len(skipped)} SKU(s) have no matching row on the portal, so the "
               "booking was not submitted")
        result.problems.extend(f"not on the portal: {label}" for label in skipped)
        if filled:
            driver.save_draft()          # keep the work that was done
        # Back to the list so the next PO starts from a clean page: leaving the edit
        # page open would make the next filter land in the wrong place.
        driver.back_to_bookings()
        return PoOutcome(result.finish(), comparisons)

    # ---- save once, then review ----------------------------------------
    if filled:
        driver.save_draft()
    driver.go_to_review()
    comparisons = _compare_review(driver, matched, result)

    errors = driver.review_errors()
    if errors and not errors.rstrip().endswith("0"):
        result.problems.append(f"Portal reported {errors}")

    clean = all(c.ok for c in comparisons) and not result.problems

    if stop_before_submit:
        result.status = STATUS_LEFT
        result.problems.append(
            "Stopped before submit at the operator's request")
        return PoOutcome(result.finish(), comparisons)

    if not clean:
        return PoOutcome(result.finish(), comparisons)

    # ---- submit, then read the status back -----------------------------
    driver.submit()
    result.submitted = True
    driver.filter_by_order(po_no)
    _read_back_status(driver, result)
    return PoOutcome(result.finish(), comparisons)


def _fill_rows(driver: Driver,
               po_no: str,
               lines: Sequence[BookingLine],
               result: PoResult,
               ask: Callable[[str, Sequence[str]], str]):
    """Fill every row we can pair with a portal row.

    Returns ``(matched lines, skipped SKU labels, number of rows filled)``.

    The portal renders only the rows in view, so the grid is walked by **scrolling until
    a key appears** rather than by reading a list.
    """
    wanted = {compared_key(po_no, line.sku): line for line in lines}
    matched: list[BookingLine] = []
    skipped: list[str] = []
    filled = 0

    # A code recovered from any row can satisfy later blanks.
    known_code = ""

    for key, line in wanted.items():
        label = line.sku
        portal_key = _find_row_key(driver, key)

        if portal_key is None:
            skipped.append(f"{label} (no matching row on the portal)")
            continue

        matched.append(line)
        filled += 1

        driver.fill_row_field(portal_key, "book-qty", line.booked_qty)
        driver.fill_row_field(portal_key, "volume", round_for_portal(line.booked_volume))
        driver.fill_row_field(portal_key, "weight", line.booked_gross_kg)
        driver.fill_row_field(portal_key, "book-pkg", line.booked_packages)

        # Description: the portal pre-fills it, so only a blank is filled.
        if not driver.read_row_field(portal_key, "description").strip():
            driver.fill_row_field(portal_key, "description", line.description)

        # Cargo type is fixed.
        driver.select_row_option(portal_key, "cargo-type", CARGO_TYPE)

        # Commodity code: the portal pre-fills it. Copy from another row, else ask.
        code = driver.commodity_code_of(portal_key).strip()
        if not code:
            if not known_code:
                known_code = _find_any_commodity_code(driver)
            if not known_code:
                known_code = _ask_for_code(ask, po_no)
            driver.fill_commodity_code(portal_key, known_code)
        else:
            known_code = known_code or code

    result.matched = filled
    return matched, skipped, filled


def _find_row_key(driver: Driver, key: tuple[str, str]) -> str | None:
    """Find the portal ``data-row-key`` whose SKU core equals ``key``'s.

    Scrolls the grid a page at a time, because only rendered rows exist in the DOM.
    """
    seen: set[str] = set()
    for _ in range(60):                      # bounded, so a bug cannot spin forever
        for row_key in driver.row_keys():
            if row_key in seen:
                continue
            seen.add(row_key)
            if portal_text_to_key(driver.sku_text(row_key)) == key:
                return row_key
        if not driver.scroll_rows_once():
            break
    return None


def _find_any_commodity_code(driver: Driver) -> str:
    """Any commodity code present on the page, used to fill a blank."""
    for row_key in driver.row_keys():
        code = driver.commodity_code_of(row_key).strip()
        if code:
            return code
    return ""


def _ask_for_code(ask: Callable[[str, Sequence[str]], str], po_no: str) -> str:
    answer = ask(
        f"PO {po_no}: no commodity code found on the page. Please type the code to use.",
        [])
    code = answer.strip()
    if not code:
        raise NeedsUser(f"PO {po_no}: a commodity code is required", [])
    return code


def _compare_review(driver: Driver,
                    matched: Sequence[BookingLine],
                    result: PoResult) -> list[LineComparison]:
    """Compare the reviewed totals and each reviewed row against our values."""
    totals = PoTotals.from_lines(matched)
    checks = totals.compare(
        quantity=driver.review_total("Total quantity"),
        packages=driver.review_total("Total packages"),
        gross_kg=driver.review_total("Total weight"),
        volume=driver.review_total("Total volume"),
    )
    comparisons: list[LineComparison] = []
    overall = LineComparison(key=("", "total"), label="PO totals")
    for name, (ours, portal, ok) in checks.items():
        overall.add(name, ours, portal, ok)
    comparisons.append(overall)

    if not overall.ok:
        result.problems.extend(f"{name}: ours {ours}, portal {portal}"
                               for name, (ours, portal, ok) in checks.items() if not ok)

    return comparisons


def _read_back_status(driver: Driver, result: PoResult) -> None:
    """After submit, the list is filtered again and the status read."""
    rows = [row for row in driver.booking_rows() if row["booking"]]
    match = next((row for row in rows if row["booking"] == result.booking_no), None)
    result.portal_status = match["status"] if match else ""


def run(po_numbers: Iterable[str],
        lines_by_po: dict[str, list[BookingLine]],
        driver: Driver,
        *,
        ask: Callable[[str, Sequence[str]], str] | None = None,
        stop_before_submit: bool = False) -> list[PoOutcome]:
    """Work every PO in turn, clearing filters between them."""
    outcomes: list[PoOutcome] = []
    for index, po_no in enumerate(po_numbers):
        if index:
            driver.clear_filters()
        try:
            outcomes.append(fill_po(driver, po_no, lines_by_po.get(po_no, []),
                                    ask=ask, stop_before_submit=stop_before_submit))
        except (PortalError, NeedsUser) as exc:
            # One bad PO must not end the batch. This PO is reported and the next one
            # starts; NeedsUser is a question nobody answered, not a crash.
            logger.exception("PO %s failed", po_no)
            result = PoResult(po_no=po_no)
            result.problems.append(str(exc) or exc.__class__.__name__)
            outcomes.append(PoOutcome(result.finish(), []))
            try:
                driver.back_to_bookings()
            except Exception:            # the page may already be unusable
                logger.warning("could not return to the bookings list", exc_info=True)
    return outcomes
