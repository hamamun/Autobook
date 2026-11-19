"""The portal fill loop, exercised against a fake portal.

No browser is involved. :class:`FakePortal` implements exactly the handful of
:class:`~autobook.portal.driver.Driver` methods the loop calls, and records what was done
to it. That makes the sequencing testable: skip statuses, unmatched rows, the commodity
code fallback, the review comparison, and the status read back after submit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from autobook.booking import BookingLine
from autobook.portal.driver import Driver
from autobook.portal.fill import NeedsUser, fill_po, run
from autobook.portal.report import (PoResult, STATUS_ABANDONED, STATUS_DONE,
                                    STATUS_FAILED, STATUS_LEFT, STATUS_NOT_DONE,
                                    STATUS_NOT_FOUND, STATUS_INCOMPLETE, STATUS_SKIPPED)
from autobook.portal.values import compare_number, compare_whole, round_for_portal


def line(sku: str, qty: int, pkgs: int, kg: float, cbm: float,
         description: str = "Power W, Gs Black/Wash, Small, BW1") -> BookingLine:
    return BookingLine(
        source_file="a.xlsx", sheet_name="PL", po_no="4500046108", style_no="A6C3T",
        colour="BC9J-GS BLACK/Wash", colour_code="BC9J", size="S", sku=sku,
        ordered_qty=qty, booked_qty=qty, booked_packages=pkgs, qty_per_package=1,
        booked_volume=cbm, booked_gross_kg=kg, description=description,
    )


class FakePortal(Driver):
    """A portal that behaves like the real one where it matters."""

    def __init__(self, *, statuses=("Pending for confirmation",),
                 rows=None, status_after_submit="Pending for confirmation",
                 commodity_codes="PREFILLED", descriptions=None, review_totals=None,
                 errors_text="Errors: 0"):
        self.page = None
        self.statuses = list(statuses)
        self.rows = rows if rows is not None else {}
        self.status_after_submit = status_after_submit
        # The portal pre-fills commodity code, so the default fake does too. Tests that
        # care about the blank case override it.
        self.commodity_codes = ({key: commodity_codes for key in self.rows}
                                if isinstance(commodity_codes, str)
                                else dict(commodity_codes or {}))
        self.descriptions = dict(descriptions or {})
        self.review_totals = review_totals or {}
        self.errors_text = errors_text

        self.calls: list[str] = []
        self.filled: dict[str, dict[str, str]] = {}
        self.selected: dict[str, dict[str, str]] = {}
        self.submitted = False
        self.draft_saved = 0
        self.opened: list[str] = []

    # -- list ------------------------------------------------------------
    def filter_by_order(self, po_no):
        self.calls.append(f"filter:{po_no}")

    def result_state(self):
        return "empty" if not self.statuses else "rows"

    def booking_rows(self):
        return [{"booking": f"SBK{index:07d}", "status": status, "text": status}
                for index, status in enumerate(self.statuses, start=1)]

    def open_booking(self, booking_no):
        self.opened.append(booking_no)
        self.calls.append(f"open:{booking_no}")

    def clear_filters(self):
        self.calls.append("clear")

    def back_to_bookings(self):
        self.calls.append("back")

    # -- edit page -------------------------------------------------------
    def start_editing(self):
        self.calls.append("edit")

    def set_invoice_currency(self, currency="USD"):
        self.calls.append(f"currency:{currency}")

    def ensure_po_expanded(self, po_no):
        self.calls.append(f"expand:{po_no}")

    # -- grid ------------------------------------------------------------
    def row_keys(self):
        return list(self.rows)

    def sku_text(self, key):
        return f"{self.rows[key]} ({key})"

    def scroll_rows_once(self):
        return False

    def fill_row_field(self, key, field, value):
        self.filled.setdefault(key, {})[field] = str(value)

    def read_row_field(self, key, field):
        if field == "description":
            return self.descriptions.get(key, "")
        return self.filled.get(key, {}).get(field, "")

    def select_row_option(self, key, field, label):
        self.selected.setdefault(key, {})[field] = label

    def commodity_code_of(self, key):
        return self.commodity_codes.get(key, "")

    def fill_commodity_code(self, key, code):
        self.commodity_codes[key] = code
        self.calls.append(f"code:{key}={code}")

    # -- review ----------------------------------------------------------
    def save_draft(self):
        self.draft_saved += 1

    def go_to_review(self):
        self.calls.append("review")

    def review_total(self, label_prefix):
        return self.review_totals.get(label_prefix, "")

    def review_errors(self):
        return self.errors_text

    def submit(self):
        self.submitted = True
        self.statuses = [self.status_after_submit]


@pytest.fixture()
def two_lines():
    # A6C3T-BC9J-S 0.0528 cbm -> portal shows 0.053
    return [
        line("A6C3T-BC9J-S-BWI", qty=40, pkgs=1, kg=8.1, cbm=0.0528),
        line("A6C3T-BC9J-M-BWI", qty=100, pkgs=2, kg=20.4, cbm=0.1056),
    ]


@pytest.fixture()
def matching_rows():
    return {"4500046108-1-10": "A6C3T-BC9J-S-BW1",
            "4500046108-2-20": "A6C3T-BC9J-M-BW1"}


# --------------------------------------------------------------------------
# matching and numbers
# --------------------------------------------------------------------------

def test_the_suffix_is_ignored_on_both_sides() -> None:
    from autobook.portal.values import compared_key, portal_text_to_key

    assert (compared_key("4500046108", "A6C3T-BC9J-XS-BWI")
            == portal_text_to_key("A6C3T-BC9J-XS-BW1 (4500046108-6-60)"))


def test_a_different_size_does_not_match() -> None:
    from autobook.portal.values import compared_key, portal_text_to_key

    assert (compared_key("4500046108", "A6C3T-BC9J-L-BWI")
            != portal_text_to_key("A6C3T-BC9J-XS-BW1 (4500046108-6-60)"))


def test_a_different_po_does_not_match() -> None:
    from autobook.portal.values import compared_key, portal_text_to_key

    assert (compared_key("4500046110", "A6C3T-BC9J-XS-BWI")
            != portal_text_to_key("A6C3T-BC9J-XS-BW1 (4500046108-6-60)"))


def test_display_precision_is_rounding_not_tolerance() -> None:
    assert compare_number(0.0528, "0.053")      # 3 dp display
    assert compare_number(3.00, "3")            # trailing zeros
    assert not compare_number(0.0528, "0.052")  # a real difference stays a difference


def test_quantities_are_compared_as_whole_numbers() -> None:
    assert compare_whole(14, "14")
    assert not compare_whole(1442, "1050")


def test_volume_is_rounded_per_row_before_summing() -> None:
    """The portal stores 0.053 for our 0.0528, so it sums rounded values."""
    from autobook.portal.values import PoTotals

    lines = [line("A-BWI", 1, 1, 1, 0.0528) for _ in range(3)]
    totals = PoTotals.from_lines(lines)
    assert totals.volume == Decimal("0.159")      # 3 x 0.053
    assert totals.volume != Decimal("0.1584")     # not the raw sum


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------

def test_a_clean_po_is_filled_and_submitted(two_lines, matching_rows) -> None:
    portal = FakePortal(rows=matching_rows,
                        review_totals={"Total quantity": "140",
                                       "Total packages": "3",
                                       "Total weight": "28.500",
                                       "Total volume": "0.159"})
    outcome = fill_po(portal, "4500046108", two_lines)

    assert portal.submitted
    assert outcome.result.status == STATUS_DONE
    assert outcome.result.matched == 2
    # values written, volume rounded for the portal's display
    assert portal.filled["4500046108-1-10"]["book-qty"] == "40"
    assert portal.filled["4500046108-1-10"]["volume"] == "0.053"
    assert portal.filled["4500046108-1-10"]["weight"] == "8.1"
    assert portal.filled["4500046108-1-10"]["book-pkg"] == "1"
    # cargo type always, currency set, draft saved once
    assert portal.selected["4500046108-1-10"]["cargo-type"] == "Flat pack"
    assert "currency:USD" in portal.calls
    assert portal.draft_saved == 1


def test_stuffed_and_cancel_are_skipped(two_lines, matching_rows) -> None:
    for status in ("Stuffed", "Cancel", "  cancel ", "STUFFED"):
        portal = FakePortal(statuses=(status,), rows=matching_rows)
        outcome = fill_po(portal, "4500046108", two_lines)
        assert outcome.result.status == STATUS_SKIPPED, status
        assert not portal.submitted
        assert portal.opened == []


def test_unstuffed_is_not_mistaken_for_stuffed(two_lines, matching_rows) -> None:
    portal = FakePortal(statuses=("Unstuffed",), rows=matching_rows,
                        review_totals={"Total quantity": "140", "Total packages": "3",
                                       "Total weight": "28.5", "Total volume": "0.159"})
    outcome = fill_po(portal, "4500046108", two_lines)
    assert outcome.result.status != STATUS_SKIPPED
    assert portal.submitted


def test_no_booking_found(two_lines) -> None:
    portal = FakePortal(statuses=(), rows={})
    outcome = fill_po(portal, "4500046108", two_lines)
    assert outcome.result.status == STATUS_NOT_FOUND
    assert portal.opened == []


def test_several_bookings_asks_the_operator(two_lines, matching_rows) -> None:
    portal = FakePortal(statuses=("Pending for confirmation", "Booking confirmed"),
                        rows=matching_rows,
                        review_totals={"Total quantity": "140", "Total packages": "3",
                                       "Total weight": "28.5", "Total volume": "0.159"})
    asked = {}

    def ask(question, choices):
        asked["question"] = question
        asked["choices"] = choices
        return choices[1]

    fill_po(portal, "4500046108", two_lines, ask=ask)
    assert len(asked["choices"]) == 2
    assert "2 bookings" in asked["question"]
    assert portal.opened == ["SBK0000002"]      # the choice made


def test_several_bookings_raises_when_nobody_can_be_asked(two_lines, matching_rows) -> None:
    portal = FakePortal(statuses=("Pending for confirmation", "Booking confirmed"),
                        rows=matching_rows)
    with pytest.raises(NeedsUser):
        fill_po(portal, "4500046108", two_lines)


def test_our_sku_missing_from_the_portal_is_skipped_and_still_submits(two_lines) -> None:
    portal = FakePortal(rows={"4500046108-1-10": "A6C3T-BC9J-S-BW1"},   # M is absent
                        review_totals={"Total quantity": "40", "Total packages": "1",
                                       "Total weight": "8.1", "Total volume": "0.053"})
    outcome = fill_po(portal, "4500046108", two_lines)

    # A missing line means the booking would carry less than the packing list, so it is
    # never submitted.
    assert outcome.result.status == STATUS_INCOMPLETE
    assert outcome.result.matched == 1
    assert len(outcome.result.skipped) == 1
    assert "A6C3T-BC9J-M-BWI" in outcome.result.skipped[0]
    assert not portal.submitted, "a missing line must block the booking"
    assert "review" not in portal.calls, "must not reach the Review page"
    assert portal.draft_saved == 1, "the work done so far is kept as a draft"
    assert portal.calls[-1] == "back", "returns to the list for the next PO"


def test_a_missing_line_is_named_in_the_report(two_lines) -> None:
    portal = FakePortal(rows={"4500046108-1-10": "A6C3T-BC9J-S-BW1"},
                        review_totals={"Total quantity": "40", "Total packages": "1",
                                       "Total weight": "8.1", "Total volume": "0.053"})
    outcome = fill_po(portal, "4500046108", two_lines)

    result = outcome.result
    assert result.status == STATUS_INCOMPLETE
    assert any("not submitted" in problem for problem in result.problems)
    assert any("A6C3T-BC9J-M-BWI" in problem for problem in result.problems)


def test_a_totals_mismatch_stops_the_submit(two_lines, matching_rows) -> None:
    portal = FakePortal(rows=matching_rows,
                        review_totals={"Total quantity": "999", "Total packages": "3",
                                       "Total weight": "28.5", "Total volume": "0.159"})
    outcome = fill_po(portal, "4500046108", two_lines)

    assert not portal.submitted
    assert outcome.result.status == STATUS_FAILED
    assert any("Total quantity" in problem for problem in outcome.result.problems)


def test_portal_errors_stop_the_submit(two_lines, matching_rows) -> None:
    portal = FakePortal(rows=matching_rows, errors_text="Errors: 2",
                        review_totals={"Total quantity": "140", "Total packages": "3",
                                       "Total weight": "28.5", "Total volume": "0.159"})
    outcome = fill_po(portal, "4500046108", two_lines)
    assert not portal.submitted
    assert outcome.result.status == STATUS_FAILED


def test_stop_before_submit_leaves_the_booking(two_lines, matching_rows) -> None:
    portal = FakePortal(rows=matching_rows,
                        review_totals={"Total quantity": "140", "Total packages": "3",
                                       "Total weight": "28.5", "Total volume": "0.159"})
    outcome = fill_po(portal, "4500046108", two_lines, stop_before_submit=True)
    assert not portal.submitted
    assert outcome.result.status == STATUS_LEFT


def test_a_status_other_than_success_after_submit_is_not_done(two_lines, matching_rows) -> None:
    portal = FakePortal(rows=matching_rows, status_after_submit="Draft",
                        review_totals={"Total quantity": "140", "Total packages": "3",
                                       "Total weight": "28.5", "Total volume": "0.159"})
    outcome = fill_po(portal, "4500046108", two_lines)
    assert portal.submitted
    assert outcome.result.status == STATUS_NOT_DONE
    assert outcome.result.portal_status == "Draft"


def test_booking_confirmed_also_counts_as_done(two_lines, matching_rows) -> None:
    portal = FakePortal(rows=matching_rows, status_after_submit="Booking confirmed",
                        review_totals={"Total quantity": "140", "Total packages": "3",
                                       "Total weight": "28.5", "Total volume": "0.159"})
    outcome = fill_po(portal, "4500046108", two_lines)
    assert outcome.result.status == STATUS_DONE


# --------------------------------------------------------------------------
# description and commodity code
# --------------------------------------------------------------------------

def test_description_is_only_filled_when_blank(two_lines, matching_rows) -> None:
    portal = FakePortal(rows=matching_rows,
                        descriptions={"4500046108-1-10": "Portal already has this"},
                        review_totals={"Total quantity": "140", "Total packages": "3",
                                       "Total weight": "28.5", "Total volume": "0.159"})
    fill_po(portal, "4500046108", two_lines)

    assert "description" not in portal.filled["4500046108-1-10"]
    assert portal.filled["4500046108-2-20"]["description"]


def test_blank_commodity_code_is_copied_from_another_row(two_lines, matching_rows) -> None:
    portal = FakePortal(rows=matching_rows,
                        commodity_codes={"4500046108-1-10": "6109100018",
                                         "4500046108-2-20": ""},
                        review_totals={"Total quantity": "140", "Total packages": "3",
                                       "Total weight": "28.5", "Total volume": "0.159"})
    fill_po(portal, "4500046108", two_lines)

    assert portal.commodity_codes["4500046108-2-20"] == "6109100018"


def test_blank_commodity_code_with_none_anywhere_asks_the_operator(two_lines,
                                                                  matching_rows) -> None:
    portal = FakePortal(rows=matching_rows, commodity_codes={},
                        review_totals={"Total quantity": "140", "Total packages": "3",
                                       "Total weight": "28.5", "Total volume": "0.159"})
    asked = {}

    def ask(question, choices):
        asked["question"] = question
        return "6109100018"

    fill_po(portal, "4500046108", two_lines, ask=ask)
    assert "commodity code" in asked["question"].lower()
    assert portal.commodity_codes["4500046108-1-10"] == "6109100018"
    assert portal.commodity_codes["4500046108-2-20"] == "6109100018"


# --------------------------------------------------------------------------
# several POs
# --------------------------------------------------------------------------

def test_filters_are_cleared_between_pos(two_lines, matching_rows) -> None:
    portal = FakePortal(rows=matching_rows,
                        review_totals={"Total quantity": "140", "Total packages": "3",
                                       "Total weight": "28.5", "Total volume": "0.159"})
    run(["4500046108", "4500046110"], {"4500046108": two_lines,
                                       "4500046110": two_lines}, portal)

    clears = [call for call in portal.calls if call == "clear"]
    assert len(clears) == 1, "cleared once, between the two POs"
    assert portal.calls.index("clear") > portal.calls.index("filter:4500046108")


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------

def test_a_finished_result_settles_its_own_status() -> None:
    assert PoResult(po_no="1", submitted=True,
                    portal_status="Pending for confirmation").finish().status == STATUS_DONE
    assert PoResult(po_no="1", submitted=True,
                    portal_status="Draft").finish().status == STATUS_NOT_DONE
    assert PoResult(po_no="1", submitted=False).finish().status == STATUS_ABANDONED
    failed = PoResult(po_no="1", submitted=True,
                      portal_status="Booking confirmed", problems=["boom"]).finish()
    assert failed.status == STATUS_FAILED
    skipped = PoResult(po_no="1", status=STATUS_SKIPPED, submitted=True).finish()
    assert skipped.status == STATUS_SKIPPED


# --------------------------------------------------------------------------
# the report tab
# --------------------------------------------------------------------------

def test_report_tab_is_written_next_to_the_data(tmp_path) -> None:
    from openpyxl import load_workbook

    from autobook.portal.report import BookingReport
    from autobook.schema import SHEET_REPORT
    from autobook.writer import write_workbook

    report = BookingReport()
    report.add(PoResult(po_no="4500046108", booking_no="SBK0005269616",
                        status=STATUS_INCOMPLETE, submitted=False,
                        matched=17, skipped=["A6C3T-EDVB-XS-BWI (no matching row)"]))
    report.add(PoResult(po_no="4500060896", status=STATUS_NOT_FOUND,
                        problems=["No booking found for PO 4500060896"]))

    out = write_workbook([], tmp_path / "data.xlsx", report=report)
    wb = load_workbook(out)
    try:
        ws = wb[SHEET_REPORT]
        headers = [cell.value for cell in ws[1]]
        rows = [{headers[i]: cell.value for i, cell in enumerate(row)}
                for row in ws.iter_rows(min_row=2)]
    finally:
        wb.close()

    assert len(rows) == 2
    assert rows[0]["PO no"] == "4500046108"
    assert rows[0]["Result"] == STATUS_INCOMPLETE
    assert rows[0]["SKUs filled"] == 17
    assert rows[0]["SKUs skipped"] == 1
    assert "not on the portal" in rows[0]["What happened"]
    assert "A6C3T-EDVB-XS-BWI" in rows[0]["What happened"]
    assert rows[0]["Submitted"] == "no"
    assert rows[1]["Result"] == STATUS_NOT_FOUND
    assert rows[1]["Submitted"] == "no"
    assert "No booking found" in rows[1]["What happened"]


def test_no_report_tab_without_a_portal_run(tmp_path) -> None:
    from openpyxl import load_workbook

    from autobook.schema import SHEET_REPORT
    from autobook.writer import write_workbook

    out = write_workbook([], tmp_path / "data.xlsx")
    wb = load_workbook(out)
    try:
        assert SHEET_REPORT not in wb.sheetnames
    finally:
        wb.close()


def test_an_incomplete_run_is_not_a_success() -> None:
    """It must not read as green anywhere, and it must not count as done."""
    from autobook.portal.report import BookingReport

    result = PoResult(po_no="1", status=STATUS_INCOMPLETE, submitted=False,
                      skipped=["A6C3T-RCQX-M-BWI"]).finish()
    assert not result.ok
    assert result.status == STATUS_INCOMPLETE

    report = BookingReport()
    report.add(result)
    assert report.done == []
    assert len(report.incomplete) == 1
    assert report.failed == [result]


def test_the_batch_carries_on_after_an_incomplete_po(two_lines) -> None:
    """An incomplete PO is reported and the next PO is still worked."""
    portal = FakePortal(rows={"4500046108-1-10": "A6C3T-BC9J-S-BW1",
                              "4500046110-1-10": "A6C3T-BC9J-S-BW1"},
                        review_totals={"Total quantity": "40", "Total packages": "1",
                                       "Total weight": "8.1", "Total volume": "0.053"},
                        commodity_codes="6109100018")
    only_s = [line("A6C3T-BC9J-S-BWI", qty=40, pkgs=1, kg=8.1, cbm=0.0528)]

    outcomes = run(["4500046108", "4500046110"],
                   {"4500046108": two_lines,      # M is missing -> incomplete
                    "4500046110": only_s},         # complete
                   portal)

    assert outcomes[0].result.status == STATUS_INCOMPLETE
    assert outcomes[1].result.status == STATUS_DONE
    assert portal.submitted, "the second PO was still submitted"
    assert "back" in portal.calls and "clear" in portal.calls
