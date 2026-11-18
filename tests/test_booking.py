"""Tests for turning carton lines into one portal row per SKU."""

from __future__ import annotations

from pathlib import Path

from autobook.booking import aggregate, build_sku, colour_code
from autobook.models import CartonLine, PackingList


def make_list(lines: list[tuple[str, str, str, int, int, float, float, float]],
              **kwargs) -> PackingList:
    """lines: (colour, size, carton_no, ctn_count, qty, net, gross, cbm)"""
    pl = PackingList(source=Path("4500046110-2563-USW FINAL.xlsx"), **kwargs)
    for i, (colour, size, ctn, count, qty, net, gross, cbm) in enumerate(lines):
        pl.cartons.append(CartonLine(carton_no=ctn, ctn_count=count, row_ref=i, colour=colour,
                                     size=size, qty=qty, net_kg=net, gross_kg=gross, cbm=cbm))
    return pl


def test_colour_code_is_the_first_token() -> None:
    assert colour_code("BC9J-GS BLACK/Wash") == "BC9J"
    assert colour_code("RCQX-GS PUMP BURGUNDY/Wash") == "RCQX"
    assert colour_code("WB57-Gs White") == "WB57"


def test_sku_number_matches_the_portal_format() -> None:
    # Portal screenshot shows A6C3T-BC9J-XL-BWI
    assert build_sku("A6C3T", "BC9J-GS BLACK/Wash", "XL", "BWI") == "A6C3T-BC9J-XL-BWI"
    assert build_sku("A6C3T", "BC9J-GS BLACK/Wash", "XL") == "A6C3T-BC9J-XL"


def test_two_cartons_of_one_size_become_one_line() -> None:
    """The exact case reported: carton 2 (65 pcs) + carton 3 (37 pcs) = one 102 pcs row."""
    pl = make_list([
        ("BC9J-GS BLACK/Wash", "S", "2", 1, 65, 11.43, 12.60, 0.0528),
        ("BC9J-GS BLACK/Wash", "S", "3", 1, 37, 6.23, 7.40, 0.0528),
    ], style_no="A6C3T", order_qty=2563, description="Power Washed Cut Off Tank")

    lines = aggregate(pl, sku_suffix="BWI")

    assert len(lines) == 1
    line = lines[0]
    assert line.booked_qty == 102
    assert line.booked_packages == 2
    assert line.qty_per_package == 51
    assert line.booked_volume == 0.1056
    assert line.booked_gross_kg == 20.0
    assert line.sku == "A6C3T-BC9J-S-BWI"
    assert line.carton_numbers == ["2", "3"]


def test_multiple_sizes_stay_separate() -> None:
    pl = make_list([
        ("BC9J-GS BLACK/Wash", "S", "2", 1, 65, 11.43, 12.60, 0.0528),
        ("BC9J-GS BLACK/Wash", "M", "4", 4, 240, 44.12, 56.12, 0.2112),
        ("RCQX-GS PUMP BURGUNDY/Wash", "S", "43", 2, 130, 22.86, 25.20, 0.1056),
    ], style_no="A6C3T", description="Tank")

    lines = aggregate(pl)

    assert [line.sku for line in lines] == [
        "A6C3T-BC9J-S", "A6C3T-BC9J-M", "A6C3T-RCQX-S"]
    assert lines[1].booked_packages == 4
    assert lines[1].qty_per_package == 60


def test_volume_and_weight_are_summed_not_taken_from_one_line() -> None:
    pl = make_list([
        ("BC9J-GS BLACK/Wash", "M", "4", 4, 240, 44.12, 56.12, 0.2112),
        ("BC9J-GS BLACK/Wash", "M", "8", 1, 13, 2.13, 3.30, 0.0528),
    ], style_no="A6C3T", description="Tank")

    line = aggregate(pl)[0]

    assert line.booked_packages == 5
    assert line.booked_qty == 253
    assert line.booked_volume == 0.264
    assert line.booked_gross_kg == 59.42


def test_a_row_covering_several_sizes_counts_packages_once() -> None:
    """One carton row with qty in two size columns must not double its carton count."""
    pl = PackingList(source=Path("x.xlsx"), style_no="A6C3T", description="Tank")
    pl.cartons = [
        CartonLine(carton_no="10", ctn_count=3, row_ref=8, colour="BC9J-GS BLACK", size="S", qty=40),
        CartonLine(carton_no="10", ctn_count=3, row_ref=8, colour="BC9J-GS BLACK", size="M", qty=20),
    ]

    lines = aggregate(pl)

    assert [line.booked_packages for line in lines] == [3, 3], "3 cartons, not 6"


def test_uneven_qty_per_package_is_flagged() -> None:
    """124 pcs over 3 cartons showed as 41 on the portal."""
    pl = make_list([("BC9J-GS BLACK/Wash", "L", "1", 3, 124, 10.0, 12.0, 0.15)],
                   style_no="A6C3T", description="Tank")

    line = aggregate(pl)[0]

    assert line.qty_per_package == 41
    assert any("does not divide evenly" in note for note in line.notes)


def test_missing_order_quantity_falls_back_and_is_flagged() -> None:
    pl = make_list([("BC9J-GS BLACK/Wash", "S", "1", 1, 50, 5.0, 6.0, 0.05)],
                   style_no="A6C3T", description="Tank", order_qty=None)

    line = aggregate(pl)[0]

    assert line.ordered_qty == 50
    assert any("order quantity not found" in note for note in line.notes)


def test_totals_are_conserved_across_the_aggregation() -> None:
    pl = make_list([
        ("BC9J-GS BLACK/Wash", "S", "2", 1, 65, 11.43, 12.60, 0.0528),
        ("BC9J-GS BLACK/Wash", "S", "3", 1, 37, 6.23, 7.40, 0.0528),
        ("RCQX-GS PUMP BURGUNDY/Wash", "M", "46", 6, 360, 66.18, 84.18, 0.3168),
    ], style_no="A6C3T", description="Tank")

    lines = aggregate(pl)

    assert sum(line.booked_qty for line in lines) == 462
    assert sum(line.booked_packages for line in lines) == 8
    assert round(sum(line.booked_gross_kg for line in lines), 2) == 104.18
