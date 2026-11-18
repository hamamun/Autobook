"""Tests for the Prepare pipeline and the data sheet it writes."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook

from autobook.pipeline import PrepareError, prepare
from autobook.schema import HEADERS, SHEET_LINES, SHEET_REVIEW, SHEET_SUMMARY

from .conftest import build_multi_carton, build_sample

PROFILE_DIR = Path(__file__).resolve().parents[1] / "profiles"


@pytest.fixture()
def files(tmp_path: Path) -> list[Path]:
    one = build_sample(tmp_path / "in" / "JMF-26-GS-3844 SEA CA.xlsx")
    two = build_sample(tmp_path / "in" / "JMF-26-GS-3845 SEA CA.xlsx")
    return [one, two]


def test_prepare_creates_batch_dir_and_sheet(files: list[Path], tmp_path: Path) -> None:
    result = prepare(files, work_root=tmp_path / "work", out_dir=tmp_path / "out")

    assert result.batch_dir.is_dir()
    assert len(list(result.batch_dir.iterdir())) == 2, "both files copied in"
    assert result.data_sheet is not None and result.data_sheet.exists()
    assert len(result.results) == 2
    for original in files:
        assert original.exists(), "originals must be untouched"


def test_data_sheet_headers_are_predefined(files: list[Path], tmp_path: Path) -> None:
    result = prepare(files, work_root=tmp_path / "work", out_dir=tmp_path / "out")
    wb = load_workbook(result.data_sheet)
    try:
        ws = wb[SHEET_SUMMARY]
        headers = [c.value for c in ws[1]]
        assert tuple(headers) == HEADERS
        assert "Colour / size breakdown" not in headers, "column P was removed on request"
        assert len(headers) == 18
        assert ws.max_row == 3, "header + one row per file"
        assert ws.cell(row=2, column=1).value == "J.M. FABRICS LIMITED"
        assert SHEET_LINES in wb.sheetnames
        assert SHEET_REVIEW in wb.sheetnames
    finally:
        wb.close()


def test_sheet_has_detail_and_review_rows(files: list[Path], tmp_path: Path) -> None:
    result = prepare(files, work_root=tmp_path / "work", out_dir=tmp_path / "out")
    wb = load_workbook(result.data_sheet)
    try:
        assert wb[SHEET_LINES].max_row > 1
        assert wb[SHEET_REVIEW].max_row > 1
    finally:
        wb.close()


def test_bad_file_does_not_block_the_batch(tmp_path: Path) -> None:
    good = build_sample(tmp_path / "good.xlsx")
    bad = tmp_path / "bad.txt"
    bad.write_text("not a packing list", encoding="utf-8")

    result = prepare([good, bad], work_root=tmp_path / "work", out_dir=tmp_path / "out")

    assert len(result.results) == 1
    assert result.problems and "bad.txt" in result.problems[0]
    assert result.data_sheet is not None


def test_no_files_raises(tmp_path: Path) -> None:
    with pytest.raises(PrepareError):
        prepare([], work_root=tmp_path / "work", out_dir=tmp_path / "out")


def test_second_run_gets_its_own_folder(files: list[Path], tmp_path: Path) -> None:
    first = prepare(files, work_root=tmp_path / "work", out_dir=tmp_path / "out")
    second = prepare(files, work_root=tmp_path / "work", out_dir=tmp_path / "out")
    assert first.batch_dir != second.batch_dir
    assert first.data_sheet != second.data_sheet


def test_carton_lines_sheet_has_a_carton_count_column(tmp_path: Path) -> None:
    files = [build_multi_carton(tmp_path / "4500046108-1387-USA FINAL.xlsx")]
    result = prepare(files, work_root=tmp_path / "work", out_dir=tmp_path / "out")
    wb = load_workbook(result.data_sheet)
    try:
        ws = wb[SHEET_LINES]
        headers = [c.value for c in ws[1]]
        label = "Cartons (per source row)"
        assert label in headers
        counts = [row[headers.index(label)] for row in ws.iter_rows(min_row=2, values_only=True)
                  if row[headers.index(label)] is not None]
        assert sum(counts) == 5
        summary = wb[SHEET_SUMMARY]
        headers = [c.value for c in summary[1]]
        assert summary.cell(row=2, column=headers.index("Total cartons") + 1).value == 5
    finally:
        wb.close()
