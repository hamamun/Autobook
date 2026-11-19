"""The portal fill loop, exercised against a fake portal.

No browser is involved. :class:`FakePortal` implements exactly the handful of
:class:`~autobook.portal.driver.Driver` methods the loop calls, and records what was done
to it. That makes the sequencing testable: skip statuses, unmatched rows, the commodity
code fallback, the review comparison, and the status read back after submit.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile

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

    def open_bookings(self):
        self.calls.append("open_bookings")

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
    assert portal.calls[0] == "open_bookings", "navigates to the list before filtering"


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


def test_a_timeout_on_one_po_does_not_abandon_the_batch(matching_rows) -> None:
    """A PortalError or a bare timeout on PO 1 must not stop PO 2."""
    from autobook.portal.driver import PortalError

    class Flaky(FakePortal):
        def filter_by_order(self, po_no):
            if po_no == "4500046108":
                raise PortalError('Timeout: waiting for locator("...")')
            super().filter_by_order(po_no)

    portal = Flaky(rows={"4500046108-1-10": "A6C3T-BC9J-S-BW1",
                         "4500046110-1-10": "A6C3T-BC9J-S-BW1"},
                   review_totals={"Total quantity": "40", "Total packages": "1",
                                  "Total weight": "8.1", "Total volume": "0.053"})
    only_s = [line("A6C3T-BC9J-S-BWI", qty=40, pkgs=1, kg=8.1, cbm=0.0528)]

    outcomes = run(["4500046108", "4500046110"],
                   {"4500046108": only_s, "4500046110": only_s}, portal)

    assert outcomes[0].result.status == STATUS_FAILED
    assert "Timeout" in outcomes[0].result.problems[0]
    assert outcomes[1].result.status == STATUS_DONE


def test_a_bare_exception_is_also_contained() -> None:
    """Anything unexpected must be recorded, not raised out of the batch."""
    class Broken(FakePortal):
        def filter_by_order(self, po_no):
            raise AttributeError("'NoneType' object has no attribute 'locator'")

    portal = Broken(rows={})
    outcomes = run(["4500046108"], {"4500046108": []}, portal)

    assert outcomes[0].result.status == STATUS_FAILED
    assert "AttributeError" in outcomes[0].result.problems[0]


# --------------------------------------------------------------------------
# browser modes
# --------------------------------------------------------------------------

def test_attach_mode_reuses_the_operators_context(monkeypatch, tmp_path) -> None:
    """Attaching must not launch a browser."""
    pytest.importorskip("playwright")
    from autobook.portal import driver as driver_module

    calls = {}

    class FakeContext:
        pages = []
        closed = False
        def close(self): FakeContext.closed = True

    class FakeBrowser:
        contexts = [FakeContext()]
        def new_context(self):
            calls["new_context"] = True
            return FakeContext()

    class FakeChromium:
        def connect_over_cdp(self, url):
            calls["url"] = url
            return FakeBrowser()
        def launch_persistent_context(self, **kwargs):
            calls["launched"] = True
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()
        def stop(self): calls["stopped"] = True

    monkeypatch.setattr("playwright.sync_api.sync_playwright",
                        lambda: type("M", (), {"start": staticmethod(lambda: FakePlaywright())}))

    playwright, context = driver_module.launch(tmp_path / "profile", attach=True, port=9222)
    assert calls["url"] == "http://127.0.0.1:9222"
    assert "launched" not in calls, "attaching must not start its own browser"
    assert isinstance(context, FakeContext)


def test_owned_mode_launches_with_the_dedicated_profile(monkeypatch, tmp_path) -> None:
    pytest.importorskip("playwright")
    from autobook.portal import driver as driver_module

    calls = {}

    class FakeChromium:
        def launch_persistent_context(self, **kwargs):
            calls.update(kwargs)
            return object()

    class FakePlaywright:
        chromium = FakeChromium()

    monkeypatch.setattr("playwright.sync_api.sync_playwright",
                        lambda: type("M", (), {"start": staticmethod(lambda: FakePlaywright())}))

    driver_module.launch(tmp_path / "profile", channel="msedge", attach=False)
    assert calls["user_data_dir"] == str(tmp_path / "profile")
    assert calls["channel"] == "msedge"


# --------------------------------------------------------------------------
# sign-in
# --------------------------------------------------------------------------

class FakePage:
    """Enough of a Playwright page to test the sign-in gate."""

    def __init__(self, url="https://www.maersk.com/scp/home", urls=None):
        self.url = url
        self._urls = list(urls or [])
        self.waits = 0

    def wait_for_timeout(self, ms):
        self.waits += 1
        if self._urls:
            self.url = self._urls.pop(0)

    def goto(self, url, wait_until=None):
        self.goto_url = url


def test_a_portal_url_is_signed_in() -> None:
    from autobook.portal.driver import Driver

    assert Driver(FakePage("https://www.maersk.com/scp/cmhub/x")).signed_in()


@pytest.mark.parametrize("url", [
    # The real sign-in page, copied from the operator's browser.
    "https://accounts.maersk.com/ocean-maeu/auth/login?nonce=uksUe8TESBeWonbRlZ3C"
    "&scope=openid%20profile%20email&client_id=portaluser"
    "&redirect_uri=https%3A%2F%2Fwww.maersk.com%2Fportaluser%2Foidc%2Fcallback"
    "&response_type=code&originalUrl=https%3A%2F%2Fwww.maersk.com%2Fscp%2F",
    # The callback on the way back - not signed in yet, or we navigate too early.
    "https://www.maersk.com/portaluser/oidc/callback?code=abc&state=xyz",
    "https://login.microsoftonline.com/common/oauth2/authorize",
    "https://maersk-pingfed.forgerock.com/login",
])
def test_a_login_url_is_not_signed_in(url) -> None:
    from autobook.portal.driver import Driver

    assert not Driver(FakePage(url)).signed_in()


def test_a_blank_tab_is_not_signed_in() -> None:
    """A freshly opened tab must not be mistaken for a loaded portal."""
    from autobook.portal.driver import Driver

    assert not Driver(FakePage("about:blank")).signed_in()


def test_waiting_returns_true_once_the_login_page_goes_away() -> None:
    from autobook.portal.driver import Driver

    page = FakePage("https://login.microsoftonline.com/x",
                    urls=["https://login.microsoftonline.com/y",
                          "https://www.maersk.com/scp/home"])
    told = []
    assert Driver(page).wait_for_sign_in(timeout_s=10, on_wait=told.append) is True
    assert told, "the operator is told to sign in"


def test_waiting_gives_up_and_says_so() -> None:
    from autobook.portal.driver import Driver

    page = FakePage("https://login.microsoftonline.com/x")
    assert Driver(page).wait_for_sign_in(timeout_s=1) is False


def test_credentials_are_never_part_of_the_api() -> None:
    """A password must never be a parameter, a setting, or a stored value."""
    import inspect

    from autobook import settings as settings_module
    from autobook.portal import session

    params = set(inspect.signature(session.fill_from_data_sheet).parameters)
    assert not any("password" in p or "credential" in p or "secret" in p or "token" in p
                   for p in params)
    fields = set(settings_module.Settings.__dataclass_fields__)
    assert not any("password" in f or "credential" in f or "token" in f for f in fields)


def test_a_progress_note_does_not_end_the_run() -> None:
    """``note`` is progress. Clearing the worker on it would let the operator start a
    second run while the first is still waiting on the sign-in."""
    # Read the file rather than importing it: this box has no tkinter, and the point
    # being tested is the order of two branches in the source.
    from pathlib import Path

    ui = Path(__file__).resolve().parents[1] / "autobook" / "ui" / "app.py"
    src = ui.read_text(encoding="utf-8")
    src = src[src.index("def _drain_messages"):src.index("def _on_finished")]
    note_branch = src.index('kind == "note"')
    clear = src.index("self._worker = None")
    assert note_branch < clear, "the note branch must come before the clear"


def test_only_one_snapshot_helper_exists() -> None:
    """Diagnosis has one implementation; a stale copy on Selectors would rot."""
    from autobook.portal.driver import Driver, Selectors

    assert hasattr(Driver, "snapshot")
    assert not hasattr(Selectors, "snapshot")


# --------------------------------------------------------------------------
# navigation: hidden spans are not links
# --------------------------------------------------------------------------

class FakeElement:
    """One element in the page, with the only property that matters: visibility."""

    def __init__(self, visible: bool, on_click=None):
        self.visible = visible
        self.clicks = 0
        self.hovered = False
        self._on_click = on_click

    def is_visible(self) -> bool:
        return self.visible

    def hover(self) -> None:
        self.hovered = True

    def click(self) -> None:
        if not self.visible:
            raise AssertionError("clicked a hidden element")
        self.clicks += 1
        if self._on_click:
            self._on_click()

    def wait_for(self, state=None, timeout=None) -> None:
        if state == "visible" and not self.visible:
            raise AssertionError("wait_for(visible) on a hidden element")


class FakeLocator:
    """A Playwright locator over a fixed set of elements."""

    def __init__(self, elements):
        self._elements = list(elements)

    @property
    def first(self):
        if not self._elements:
            raise AssertionError("strict mode: no element to take .first of")
        return self._elements[0]

    def count(self) -> int:
        return len(self._elements)

    def nth(self, index):
        return self._elements[index]


class FakeNavPage:
    """The real portal's shape: 61 hidden ``<span>Bookings</span>``, one real link."""

    HIDDEN_SPANS = 61

    def __init__(self, *, route_works=False, visible_link=True):
        self.url = "https://www.maersk.com/scp/cmhub/home"
        self.route_works = route_works
        self.visible_link = visible_link
        self.gotos = []
        self.filters_visible = False
        self.hidden_link = FakeElement(False)

    def locator(self, selector):
        if selector == 'button:has-text("Filters")':
            return FakeLocator([FakeElement(True)] if self.filters_visible else [])
        if "Bookings" in selector or "Export" in selector:
            # Every text match also hits the closed flyouts and templates behind them.
            elements = [FakeElement(False) for _ in range(self.HIDDEN_SPANS)]
            if self.visible_link:
                def follow_link():
                    if self.route_works:
                        self.filters_visible = True
                elements.append(FakeElement(True, on_click=follow_link))
            return FakeLocator(elements)
        return FakeLocator([])

    def goto(self, url, wait_until=None):
        self.gotos.append(url)
        if self.route_works:
            self.filters_visible = True

    def wait_for_timeout(self, ms):
        pass


def test_navigation_goes_by_route_first() -> None:
    from autobook.portal.driver import BOOKINGS_URL, Driver

    page = FakeNavPage(route_works=True)
    Driver(page).open_bookings()
    assert page.gotos == [BOOKINGS_URL]


def test_a_hidden_bookings_span_is_never_clicked() -> None:
    """The regression: `.first` picked a hidden span and the run timed out."""
    from autobook.portal.driver import PortalError, Driver

    page = FakeNavPage(route_works=False, visible_link=False)
    try:
        Driver(page).open_bookings()
    except PortalError as exc:
        assert "Could not open the bookings list" in str(exc)
    else:
        raise AssertionError("should have reported a clear error, not hung")


def test_a_visible_bookings_link_is_used_when_the_route_fails() -> None:
    """Route dead, but the nav link works -> the run still gets where it is going."""
    from autobook.portal.driver import Driver

    class RouteDeadLinkWorks(FakeNavPage):
        def goto(self, url, wait_until=None):
            self.gotos.append(url)          # the route loads, but not the list

        def locator(self, selector):
            found = super().locator(selector)
            if "Bookings" in selector or "Export" in selector:
                visible = [FakeElement(True, on_click=None)]
                visible[0]._on_click = lambda: setattr(self, "filters_visible", True)
                return FakeLocator([FakeElement(False)] * self.HIDDEN_SPANS + visible)
            return found

    page = RouteDeadLinkWorks(route_works=False, visible_link=True)
    Driver(page).open_bookings()
    assert page.gotos, "the route is tried before the navigation"
    assert page.filters_visible, "the visible link was followed"


def test_navigation_is_skipped_when_already_on_the_list() -> None:
    from autobook.portal.driver import Driver

    page = FakeNavPage(route_works=True)
    page.filters_visible = True
    Driver(page).open_bookings()
    assert page.gotos == [], "no need to navigate twice"


def test_the_inventory_names_what_the_page_contains() -> None:
    """A traceback says a selector failed; the inventory says what to use instead."""
    from autobook.portal.driver import Driver

    text = Driver.format_inventory({
        "url": "https://www.maersk.com/scp/cmhub/home",
        "title": "Maersk",
        "buttons": ["Filters  [bookings-filters]"],
        "links": ["Bookings  -> /scp/cmhub/ordermanagement/bookings"],
        "inputs": [{"placeholder": "Order", "testid": "order"}],
        "testids": {"order": 1, "filters": 2},
    })
    assert "-- VISIBLE BUTTONS (1) --" in text
    assert "bookings-filters" in text
    assert "filters  x2" in text


def test_the_inventory_script_is_valid_javascript() -> None:
    """It is a string until Playwright runs it, so a typo would only surface during a
    failure - the worst possible moment to discover it."""
    import re
    from pathlib import Path

    from autobook.portal.driver import Driver

    js = Driver._INVENTORY_JS
    assert js.count("(") == js.count(")")
    assert js.count("{") == js.count("}")
    # A doubled backslash turns /\s+/ into a literal backslash-s. That happened once.
    assert "\\\\" not in js, "a stray Python escape leaked into the JS"
    assert re.search(r"replace\(/\\s\+/g", js), "the whitespace collapse is intact"

    node = shutil.which("node")
    if node:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write("const f = " + js.strip() + ";")
            path = handle.name
        try:
            result = subprocess.run([node, "--check", path], capture_output=True,
                                    text=True)
        finally:
            Path(path).unlink()
        assert result.returncode == 0, result.stderr


def test_failure_evidence_includes_the_inventory(tmp_path) -> None:
    from autobook.portal.driver import Driver

    class P:
        url = "https://www.maersk.com/scp/x"

        def screenshot(self, path, full_page=False):
            from pathlib import Path
            Path(path).write_bytes(b"png")

        def content(self):
            return "<html></html>"

        def evaluate(self, js):
            return {"url": self.url, "title": "T", "buttons": ["Filters"],
                    "links": [], "inputs": [], "testids": {"a": 1}}

    made = Driver(P()).snapshot(tmp_path, "portal-failure")
    assert made["screenshot"] and made["html"]
    assert "-inventory.txt" in made["inventory"]
    assert "VISIBLE BUTTONS" in open(made["inventory"], encoding="utf-8").read()
