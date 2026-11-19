"""Values the portal pre-fills, which must therefore be written on every row.

Cargo type, commodity code and country of origin are fixed for this site: cargo type is
a dropdown whose only value is "Flat pack", and the portal pre-fills the other two. They
live in settings so they can be changed without touching code, and they must reach the
Booking_lines columns even when the rest of the call is left at its defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from autobook.pipeline import prepare
from autobook.settings import Settings

#: Booking_lines column letter -> heading, as the operator sees them.
EXPECTED = {"O": "Cargo type", "P": "Commodity code", "Q": "Country of origin"}


@pytest.fixture()
def packing_list(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Packing list"
    for row in [
        ["J.M. FABRICS LIMITED"],
        ["ADDRESS: GAZIPUR"],
        ["GYMSHARK PACKING LIST"],
        ["STYLE NO", "", ":", "A6C3T"],
        ["SPLIT PO NO", "", ":", "4500060538"],
        ["SHIP QTY", "", ":", "5"],
        ["CTN NO", "", "CTN QTY", "COLOUR", "", "SIZE", "", "", "", "", "", "", "",
         "", "", "", "", "TTL N.W", "TTL G.W", "", "CBM"],
        ["", "", "", "", "", "XS", "S", "M"],
    ]:
        ws.append(row)
    line: list[object] = [""] * 21
    line[0] = "1"
    line[2] = "1"
    line[3] = "BC9J-GS Black/Wash"
    line[5] = "5"
    line[17] = "3.0"
    line[18] = "3.6"
    line[20] = 0.0528
    ws.append(line)
    ws.append(["SUMMARY"])
    path = tmp_path / "one.xlsx"
    wb.save(path)
    return path


def first_booking_row(path: Path) -> dict[str, object]:
    wb = load_workbook(path)
    try:
        ws = wb["Booking_lines"]
        headers = [cell.value for cell in ws[1]]
        return {headers[cell.column - 1]: cell.value
                for cell in ws[2] if cell.value is not None}
    finally:
        wb.close()


def test_the_columns_are_where_the_operator_expects_them(packing_list: Path,
                                                         tmp_path: Path) -> None:
    """Read the real sheet: O, P and Q must be the three fields that were asked for."""
    result = prepare([packing_list], work_root=tmp_path / "w", out_dir=tmp_path / "o")
    wb = load_workbook(result.data_sheet)
    try:
        ws = wb["Booking_lines"]
        for letter, heading in EXPECTED.items():
            assert ws[f"{letter}1"].value == heading, f"column {letter}"
    finally:
        wb.close()


def test_commodity_code_is_left_blank(packing_list: Path, tmp_path: Path) -> None:
    """The portal pre-fills it and there is no fixed code, so we must not state one."""
    result = prepare([packing_list], work_root=tmp_path / "w", out_dir=tmp_path / "o")

    row = first_booking_row(result.data_sheet)
    assert "Commodity code" not in row, "the cell must be empty, not carry a value"


def test_country_of_origin_is_always_bd(packing_list: Path, tmp_path: Path) -> None:
    settings = Settings.load()
    assert settings.country_of_origin == "BD"

    result = prepare([packing_list], work_root=tmp_path / "w", out_dir=tmp_path / "o",
                     country_of_origin=settings.country_of_origin)

    assert first_booking_row(result.data_sheet)["Country of origin"] == "BD"


def test_commodity_code_and_cargo_type_are_not_settings_any_more() -> None:
    """Neither is a free-text value: one is blank, the other is forced."""
    fields = set(Settings.__dataclass_fields__)
    assert "commodity_code" not in fields
    assert "cargo_type" not in fields


def test_cargo_type_is_never_left_blank(packing_list: Path, tmp_path: Path) -> None:
    """The portal rejects a blank dropdown, so every row must carry a value."""
    result = prepare([packing_list], work_root=tmp_path / "w", out_dir=tmp_path / "o")

    wb = load_workbook(result.data_sheet)
    try:
        ws = wb["Booking_lines"]
        headers = [cell.value for cell in ws[1]]
        column = headers.index("Cargo type") + 1
        for row_index in range(2, ws.max_row + 1):
            assert ws.cell(row=row_index, column=column).value == "Flat pack"
    finally:
        wb.close()


def test_a_stale_commodity_code_in_settings_is_dropped(tmp_path: Path) -> None:
    """An older settings.json held a commodity code; it must not come back."""
    path = tmp_path / "settings.json"
    path.write_text('{"commodity_code": "6109100018", "cargo_type": "Dry", '
                    '"country_of_origin": "BD", "sku_suffix": "BWI"}', encoding="utf-8")

    loaded = Settings.load(path)

    assert not hasattr(loaded, "commodity_code")
    assert not hasattr(loaded, "cargo_type")
    assert loaded.country_of_origin == "BD"

    loaded.save(path)
    assert "commodity_code" not in path.read_text(encoding="utf-8")
    assert "cargo_type" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("source_value", ["Flat pack", "Dry", "dry", "None", "", None,
                                          "  "])
def test_cargo_type_is_always_flat_pack(source_value: object) -> None:
    """Whatever the source says, the portal line must read "Flat pack"."""
    from autobook.booking import normalise_cargo_type

    assert normalise_cargo_type(source_value) == "Flat pack"


def test_country_of_origin_defaults_to_bd_with_no_arguments(packing_list: Path,
                                                            tmp_path: Path) -> None:
    """A bare prepare() call must still write BD - it is not opt-in."""
    result = prepare([packing_list], work_root=tmp_path / "w", out_dir=tmp_path / "o")

    assert first_booking_row(result.data_sheet)["Country of origin"] == "BD"
