"""Tests for extraction against a fixture workbook."""

from __future__ import annotations

from pathlib import Path

import pytest

from autobook.extract import extract
from autobook.extract.profiles import ProfileError, load_profile, load_profiles
from autobook.paths import app_data_dir  # noqa: F401  (import check)

from .conftest import build_sample

PROFILE_DIR = Path(__file__).resolve().parents[1] / "profiles"


@pytest.fixture()
def sample(tmp_path: Path) -> Path:
    return build_sample(tmp_path / "JMF-26-GS-3844 SEA CA.xlsx")


def test_profiles_load() -> None:
    profiles = load_profiles(PROFILE_DIR)
    assert profiles, "the shipped profile must load"
    assert profiles[0].name == "gymshark_packing_list"
    assert profiles[0].carton is not None


def test_extracts_header_fields(sample: Path) -> None:
    pl = extract(sample, load_profiles(PROFILE_DIR))
    assert pl.supplier == "J.M. FABRICS LIMITED"
    assert pl.style_no == "A6C5J"
    assert pl.split_po_no == "4500036312"
    assert pl.order_qty == 306
    assert pl.ship_qty == 269
    assert pl.description == "Ribbed Vest"
    assert pl.supplier_address.startswith("SOUTH NAYAPARA")


def test_order_no_falls_back_to_filename_and_is_flagged(sample: Path) -> None:
    pl = extract(sample, load_profiles(PROFILE_DIR))
    assert pl.order_no == "3844"
    assert pl.confidence["order_no"] == "medium"
    assert any(i.field == "order_no" for i in pl.issues)


def test_carton_rows_and_forward_filled_colour(sample: Path) -> None:
    pl = extract(sample, load_profiles(PROFILE_DIR))
    assert len(pl.cartons) == 3
    assert [c.colour for c in pl.cartons] == ["BB2J-Gs Black", "BB2J-Gs Black", "WB57-Gs White"]
    assert [c.size for c in pl.cartons] == ["XS", "S", "XS"]
    assert sum(c.qty for c in pl.cartons) == 39


def test_summary_rows_skipped_not_counted(sample: Path) -> None:
    """TOTAL / GRAND TOTAL rows are inside the table and must not become cartons."""
    pl = extract(sample, load_profiles(PROFILE_DIR))
    assert "TOTAL" not in {c.carton_no for c in pl.cartons}
    assert pl.carton_count == 3


def test_mismatch_between_header_and_lines_is_reported(sample: Path) -> None:
    pl = extract(sample, load_profiles(PROFILE_DIR))
    problems = " ".join(i.problem for i in pl.issues)
    assert "does not match carton lines" in problems


def test_unknown_layout_never_guesses(tmp_path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["SOMETHING ELSE ENTIRELY"])
    wb.active.append(["a", "b", "c"])
    path = tmp_path / "other.xlsx"
    wb.save(path)

    pl = extract(path, load_profiles(PROFILE_DIR))
    assert pl.cartons == []
    assert any(i.severity == "error" for i in pl.issues)


def test_unsupported_type_reports_error(tmp_path: Path) -> None:
    path = tmp_path / "x.txt"
    path.write_text("nope", encoding="utf-8")
    pl = extract(path, load_profiles(PROFILE_DIR))
    assert any(i.severity == "error" for i in pl.issues)


def test_broken_profile_raises_profile_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: x\nfields:\n  a: {cast: nonsense}\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(bad)
