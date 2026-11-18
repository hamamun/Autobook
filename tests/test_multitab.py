"""Multi-tab workbooks: find the packing lists, ignore everything else."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from autobook.extract import extract_all
from autobook.extract.profiles import load_profiles
from autobook.pipeline import prepare

PROFILE_DIR = Path(__file__).resolve().parents[1] / "profiles"


def fill_packing_list(ws, style: str = "A6C3T", ship_qty: str = "150") -> None:
    """A packing list whose title sits in row 3 - not row 1."""
    ws.append(["J.M. FABRICS LIMITED"])
    ws.append(["ADDRESS: SOUTH NAYAPARA, 6 NO. DOGRI, GAZIPUR-1703, BANGLADESH"])
    ws.append(["GYMSHARK PACKING LIST"])
    ws.append(["STYLE NO", "", ":", style])
    ws.append(["SPLIT PO NO", "", ":", "4500060538"])
    ws.append(["DESCRIPTION", "", ":", "Power Washed Cut Off Tank"])
    ws.append(["SHIP QTY", "", ":", ship_qty])
    ws.append(["CTN NO", "", "CTN QTY", "COLOUR", "", "SIZE"])
    ws.append(["", "", "", "", "", "XS", "S", "M"])
    ws.append(["1", "1", "1", "BC9J-GS BLACK/Wash", "", "5", "43", "15"])
    ws.append(["SUMMARY"])


@pytest.fixture()
def workbook(tmp_path: Path) -> Path:
    wb = Workbook()

    cover = wb.active
    cover.title = "Cover"
    cover.append(["SHIPMENT DOCUMENTS"])
    cover.append(["Prepared by: Logistics"])
    for row in range(3, 30):
        cover.append([f"note {row}"])

    fill_packing_list(wb.create_sheet("Style A6C3T"))

    notes = wb.create_sheet("Notes")
    notes.append(["INTERNAL NOTES"])
    notes.append(["PACKING LIST must not be filed here"])

    fill_packing_list(wb.create_sheet("Style B2X"), style="B2X", ship_qty="95")

    hidden = wb.create_sheet("Old copy")
    fill_packing_list(hidden)
    hidden.sheet_state = "hidden"

    path = tmp_path / "multi tab shipment.xlsx"
    wb.save(path)
    return path


def test_each_packing_list_tab_becomes_its_own_row(workbook: Path) -> None:
    results = extract_all(workbook, load_profiles(PROFILE_DIR))

    assert [pl.sheet_name for pl in results] == ["Style A6C3T", "Style B2X"]
    assert [pl.style_no for pl in results] == ["A6C3T", "B2X"]
    assert [pl.ship_qty for pl in results] == [150, 95]


def test_tabs_that_are_not_packing_lists_are_discarded(workbook: Path) -> None:
    results = extract_all(workbook, load_profiles(PROFILE_DIR))
    names = {pl.sheet_name for pl in results}
    assert "Cover" not in names
    assert "Notes" not in names, "a tab that merely says 'PACKING LIST' is not one"


def test_hidden_tabs_are_ignored(workbook: Path) -> None:
    results = extract_all(workbook, load_profiles(PROFILE_DIR))
    assert "Old copy" not in {pl.sheet_name for pl in results}


def test_title_below_the_first_row_is_still_found(workbook: Path) -> None:
    """The title sits in row 3; matching looks at the top 5 rows."""
    results = extract_all(workbook, load_profiles(PROFILE_DIR))
    assert len(results) == 2


def test_title_outside_the_match_window_is_not_found(tmp_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    for _ in range(8):
        ws.append(["filler"])
    ws.append(["GYMSHARK PACKING LIST"])
    ws.append(["STYLE NO", "", ":", "A6C3T"])
    ws.append(["CTN NO", "", "CTN QTY", "COLOUR", "", "SIZE"])
    path = tmp_path / "late title.xlsx"
    wb.save(path)

    results = extract_all(path, load_profiles(PROFILE_DIR))

    assert len(results) == 1
    assert any(i.severity == "error" for i in results[0].issues)


def test_single_tab_workbook_is_unchanged(tmp_path: Path) -> None:
    wb = Workbook()
    fill_packing_list(wb.active)
    wb.active.title = "Packing list"
    path = tmp_path / "single.xlsx"
    wb.save(path)

    results = extract_all(path, load_profiles(PROFILE_DIR))

    assert len(results) == 1
    assert results[0].style_no == "A6C3T"


def test_workbook_with_no_packing_list_reports_once(tmp_path: Path) -> None:
    wb = Workbook()
    wb.active.title = "Cover"
    wb.active.append(["SOMETHING ELSE"])
    path = tmp_path / "nothing.xlsx"
    wb.save(path)

    results = extract_all(path, load_profiles(PROFILE_DIR))

    assert len(results) == 1
    assert any(i.severity == "error" for i in results[0].issues)


def test_data_sheet_shows_the_tab_name(workbook: Path, tmp_path: Path) -> None:
    result = prepare([workbook], work_root=tmp_path / "work", out_dir=tmp_path / "out")
    assert result.data_sheet is not None

    from openpyxl import load_workbook

    wb = load_workbook(result.data_sheet)
    try:
        ws = wb["Packing_lists"]
        headers = [c.value for c in ws[1]]
        column = headers.index("Source file") + 1
        sources = [ws.cell(row=r, column=column).value for r in range(2, ws.max_row + 1)]
        assert "multi tab shipment.xlsx [Style A6C3T]" in sources
        assert "multi tab shipment.xlsx [Style B2X]" in sources
    finally:
        wb.close()


# --------------------------------------------------------------------------
# Recognition without the words "PACKING LIST"
# --------------------------------------------------------------------------

def build_sheet(tmp_path: Path, *, title: bool, table: bool, name: str) -> Path:
    """Workbook with or without the title line and/or the carton table."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["J.M. FABRICS LIMITED"])
    ws.append(["ADDRESS: SOUTH NAYAPARA, GAZIPUR-1703, BANGLADESH"])
    ws.append(["GYMSHARK PACKING LIST"] if title else [])
    ws.append(["STYLE NO", "", ":", "A6C3T"])
    ws.append(["SPLIT PO NO", "", ":", "4500060538"])
    ws.append(["SHIP QTY", "", ":", "63"])
    if table:
        ws.append(["CTN NO", "", "CTN QTY", "COLOUR", "", "SIZE", "", "", "", "", "",
                   "", "", "", "", "", "", "N.W", "G.W"])
        ws.append(["", "", "", "", "", "XS", "S", "M"])
        ws.append(["1", "1", "1", "BC9J-GS BLACK/Wash", "", "5", "43", "15",
                   "", "", "", "", "", "", "", "", "", "3.0", "3.6"])
    else:
        for index in range(5):
            ws.append([f"note {index}"])
    ws.append(["GRAND TOTAL"])
    path = tmp_path / name
    wb.save(path)
    return path


def test_carton_table_alone_identifies_a_packing_list(tmp_path: Path) -> None:
    """No title anywhere, but carton no/qty and net/gross weight on one row."""
    path = build_sheet(tmp_path, title=False, table=True, name="no title.xlsx")

    results = extract_all(path, load_profiles(PROFILE_DIR))

    assert len(results) == 1
    assert results[0].style_no == "A6C3T"
    assert len(results[0].cartons) == 3
    assert not any(i.severity == "error" for i in results[0].issues)


def test_title_without_a_carton_table_is_not_a_packing_list(tmp_path: Path) -> None:
    path = build_sheet(tmp_path, title=True, table=False, name="cover.xlsx")

    results = extract_all(path, load_profiles(PROFILE_DIR))

    assert results[0].cartons == []
    assert any(i.severity == "error" for i in results[0].issues)


def test_neither_title_nor_table_is_discarded(tmp_path: Path) -> None:
    path = build_sheet(tmp_path, title=False, table=False, name="nothing.xlsx")

    results = extract_all(path, load_profiles(PROFILE_DIR))

    assert any(i.severity == "error" for i in results[0].issues)


def test_signature_labels_must_share_one_header_row(tmp_path: Path) -> None:
    """Carton labels scattered over different rows must not count as a signature."""
    wb = Workbook()
    ws = wb.active
    ws.append(["CTN NO"])            # carton no alone
    ws.append(["N.W", "G.W"])        # weights on a different row, no carton qty
    ws.append(["1", "2", "3"])
    path = tmp_path / "scattered.xlsx"
    wb.save(path)

    results = extract_all(path, load_profiles(PROFILE_DIR))

    assert any(i.severity == "error" for i in results[0].issues)


# --------------------------------------------------------------------------
# Skipped sheets are recorded on the About tab only
# --------------------------------------------------------------------------

def test_skipped_sheets_appear_only_on_the_about_tab(workbook: Path, tmp_path: Path) -> None:
    from openpyxl import load_workbook

    result = prepare([workbook], work_root=tmp_path / "work", out_dir=tmp_path / "out")
    wb = load_workbook(result.data_sheet)
    try:
        # Nothing about Cover / Notes / Old copy on the data tabs. Columns headed
        # "Notes" (issues, notes) are legitimate, so match the source-file pattern
        # "file.xlsx [Sheet]" and exact-cell sheet names rather than bare words.
        tab_names = {"Cover", "Old copy"}  # "Notes" is also a legitimate header
        for sheet in ("Packing_lists", "Carton_lines", "Booking_lines", "Review"):
            cells = [str(value) for row in wb[sheet].iter_rows(values_only=True)
                     for value in row if value is not None]
            for skipped in tab_names:
                assert not any(f"[{skipped}]" in cell for cell in cells), (
                    f"{sheet} references the skipped sheet '{skipped}'")
                assert skipped not in cells, (
                    f"{sheet} contains a cell naming the skipped sheet '{skipped}'")
            # The Notes tab must not appear as a source (its name doubles as a header,
            # so look for it in the bracketed sheet position only).
            assert not any("[Notes]" in cell for cell in cells)

        # ...but all three are listed on About with a reason
        about = " ".join(
            str(value)
            for row in wb["About"].iter_rows(values_only=True)
            for value in row if value is not None)
        for skipped in ("Cover", "Notes", "Old copy"):
            assert skipped in about
        assert "hidden tab" in about
    finally:
        wb.close()


def test_about_counts_the_skipped_sheets(workbook: Path, tmp_path: Path) -> None:
    from openpyxl import load_workbook

    result = prepare([workbook], work_root=tmp_path / "work", out_dir=tmp_path / "out")
    assert len(result.skipped) == 3, "Cover, Notes and the hidden tab"

    wb = load_workbook(result.data_sheet)
    try:
        values = {row[0]: row[1] for row in wb["About"].iter_rows(values_only=True)
                  if row and row[0]}
        assert values["Sheets skipped"] == 3
    finally:
        wb.close()


def test_clean_single_tab_workbook_lists_no_skips(tmp_path: Path) -> None:
    wb = Workbook()
    fill_packing_list(wb.active)
    wb.active.title = "Packing list"
    path = tmp_path / "clean.xlsx"
    wb.save(path)

    result = prepare([path], work_root=tmp_path / "work", out_dir=tmp_path / "out")

    assert result.skipped == []
