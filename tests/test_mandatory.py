"""The five booking fields the portal cannot be submitted without.

Each one maps to a column on the data sheet. When a row's value is blank - or zero,
which the portal rejects just the same - the cell must go red and the row's Notes must
say what is missing, so nothing gets booked with a silent gap.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from autobook.booking import MANDATORY_BOOKING_FIELDS, is_blank, missing_mandatory
from autobook.pipeline import prepare

HEADER = ["CTN NO", "", "CTN QTY", "COLOUR", "", "SIZE", "", "", "", "", "", "",
          "", "", "", "", "", "TTL N.W", "TTL G.W", "", "CBM"]
SIZES = ["", "", "", "", "", "XS", "S", "M"]

#: The five fields, in portal order, and the Booking_lines heading for each.
PORTAL_FIELDS = {
    "SKU number": "sku",
    "Booked quantity": "booked_qty",
    "Booked volume": "booked_volume",
    "Booked packages": "booked_packages",
    "Booked gross weight": "booked_gross_kg",
}


def carton(ctn: str, size_col: int, pcs: int, net: str, gross: str,
           cbm: object) -> list[object]:
    cells: list[object] = [""] * 21
    cells[0] = ctn
    cells[2] = "1"
    cells[3] = "BC9J-GS BLACK/Wash"
    cells[size_col] = str(pcs)
    cells[17] = net
    cells[18] = gross
    cells[20] = cbm
    return cells


@pytest.fixture()
def sheet(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Packing list"
    for row in [
        ["J.M. FABRICS LIMITED"],
        ["ADDRESS: GAZIPUR"],
        ["GYMSHARK PACKING LIST"],
        ["STYLE NO", "", ":", "A6C3T"],
        ["SPLIT PO NO", "", ":", "4500060538"],
        ["SHIP QTY", "", ":", "63"],
        HEADER,
        SIZES,
        carton("1", 5, 5, "3.0", "3.6", 0.0528),    # complete
        carton("2", 6, 43, "25.8", "30.0", ""),     # CBM blank
        carton("3", 7, 15, "9.0", "10.8", 0),       # CBM zero
        ["SUMMARY"],
    ]:
        ws.append(row)
    path = tmp_path / "gaps.xlsx"
    wb.save(path)
    return path


def rows_by_sku(path: Path) -> dict[str, dict[str, object]]:
    wb = load_workbook(path)
    try:
        ws = wb["Booking_lines"]
        headers = [cell.value for cell in ws[1]]
        out = {}
        for row in ws.iter_rows(min_row=2):
            values = {headers[cell.column - 1]: cell for cell in row}
            sku = values["SKU number"].value
            if sku:
                out[sku] = values
        return out
    finally:
        wb.close()


def is_red(cell) -> bool:
    return "FFC7CE" in str(cell.fill.start_color.rgb)


# --------------------------------------------------------------------------
# the rules themselves
# --------------------------------------------------------------------------

def test_the_five_mandatory_fields_are_the_ones_asked_for() -> None:
    labels = [label for _, label in MANDATORY_BOOKING_FIELDS]
    assert labels == ["SKU number", "Booked quantity", "Booked volume",
                      "Booked packages", "Booked gross weight"]


@pytest.mark.parametrize("value", [None, "", "   ", 0, 0.0])
def test_blank_or_zero_counts_as_missing(value: object) -> None:
    assert is_blank(value) is True


@pytest.mark.parametrize("value", ["A6C3T-BC9J-XS-BWI", 5, 0.0528, 1])
def test_a_real_value_is_not_missing(value: object) -> None:
    assert is_blank(value) is False


def test_missing_mandatory_lists_every_gap() -> None:
    gaps = missing_mandatory({"sku": "X", "booked_qty": 5, "booked_volume": 0,
                              "booked_packages": None, "booked_gross_kg": ""})
    assert gaps == ["Booked volume", "Booked packages", "Booked gross weight"]


# --------------------------------------------------------------------------
# what lands in the workbook
# --------------------------------------------------------------------------

def test_complete_row_has_nothing_red(sheet: Path, tmp_path: Path) -> None:
    result = prepare([sheet], work_root=tmp_path / "w", out_dir=tmp_path / "o")
    cells = rows_by_sku(result.data_sheet)["A6C3T-BC9J-XS-BWI"]

    assert not [name for name in PORTAL_FIELDS if is_red(cells[name])]
    assert "MISSING" not in (cells["Notes"].value or "")


def test_blank_cbm_turns_the_volume_cell_red(sheet: Path, tmp_path: Path) -> None:
    result = prepare([sheet], work_root=tmp_path / "w", out_dir=tmp_path / "o")
    cells = rows_by_sku(result.data_sheet)["A6C3T-BC9J-S-BWI"]

    assert is_red(cells["Booked volume"])
    # and only that field - the row is otherwise bookable
    reds = [name for name in PORTAL_FIELDS if is_red(cells[name])]
    assert reds == ["Booked volume"]


def test_zero_cbm_is_treated_as_missing(sheet: Path, tmp_path: Path) -> None:
    """0 CBM would be rejected by the portal, so it must not pass as a value."""
    result = prepare([sheet], work_root=tmp_path / "w", out_dir=tmp_path / "o")
    cells = rows_by_sku(result.data_sheet)["A6C3T-BC9J-M-BWI"]

    assert cells["Booked volume"].value in (0, 0.0, None)
    assert is_red(cells["Booked volume"])


def test_notes_warn_which_field_is_missing(sheet: Path, tmp_path: Path) -> None:
    result = prepare([sheet], work_root=tmp_path / "w", out_dir=tmp_path / "o")
    cells = rows_by_sku(result.data_sheet)["A6C3T-BC9J-S-BWI"]

    notes = cells["Notes"].value
    assert notes.startswith("MISSING - cannot book until filled: Booked volume")
    assert is_red(cells["Notes"]), "the Notes cell is highlighted too"


def test_each_gap_is_named_and_only_the_gaps_are_red(tmp_path: Path) -> None:
    """Weights and CBM blank; quantity and packages present and therefore clean."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Packing list"
    for row in [
        ["J.M. FABRICS LIMITED"], ["ADDRESS: GAZIPUR"], ["GYMSHARK PACKING LIST"],
        ["STYLE NO", "", ":", "A6C3T"], ["SPLIT PO NO", "", ":", "4500060538"],
        ["SHIP QTY", "", ":", "63"],
        HEADER, SIZES,
        carton("1", 5, 5, "", "", ""),
        ["SUMMARY"],
    ]:
        ws.append(row)
    path = tmp_path / "empty figures.xlsx"
    wb.save(path)

    result = prepare([path], work_root=tmp_path / "w", out_dir=tmp_path / "o")
    cells = rows_by_sku(result.data_sheet)["A6C3T-BC9J-XS-BWI"]

    assert is_red(cells["Booked volume"])
    assert is_red(cells["Booked gross weight"])
    assert not is_red(cells["Booked quantity"]), "5 pcs is present"
    assert not is_red(cells["Booked packages"]), "1 carton is present"
    assert "Booked volume" in cells["Notes"].value
    assert "Booked gross weight" in cells["Notes"].value
