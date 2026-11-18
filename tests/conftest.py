"""Fixture: build a couple of sample packing-list workbooks for tests."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

# Row/col layout mirrors the real Gymshark packing list (0-based, as read by openpyxl).
SAMPLE = [
    ["J.M. FABRICS LIMITED"],
    ["ADDRESS: SOUTH NAYAPARA, 6 NO. DOGRI, PO. BHAWAL MIRZAPUR, GAZIPUR-1703, BANGLADESH"],
    ["GYMSHARK PACKING LIST"],
    ["ORDER NO", "", ":", "", "", "", "", "", "", "", "CA"],
    ["STYLE NO", "", ":", "A6C5J"],
    ["SPLIT PO NO", "", ":", "4500036312"],
    ["ORDER QTY", "", ":", "306", "PCS"],
    ["SHIP QTY", "", ":", "269", "PCS"],
    ["DESCRIPTION", "", ":", "Ribbed Vest"],
    [],
    [],
    ["CTN NO", "", "CTN QTY", "COLOUR", "", "SIZE"],
    ["", "", "", "", "", "XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL"],
    ["1", "1", "1", "BB2J-Gs Black", "", "", "6"],
    ["2", "2", "1", "", "", "", "", "28"],
    ["TOTAL", "", "2", "", "", "0", "6", "28"],
    ["3", "3", "1", "WB57-Gs White", "", "", "5"],
    ["GRAND TOTAL", "", "3", "", "", "0", "6", "33"],
    ["SUMMARY"],
]


# A row that covers SEVERAL cartons (CTN NO 10, QTY 3). The header total can only be
# reconciled by summing the CTN QTY column, not by counting rows.
MULTI_CTN = [
    ["J.M. FABRICS LIMITED"],
    ["ADDRESS: SOUTH NAYAPARA, GAZIPUR, BANGLADESH"],
    ["GYMSHARK PACKING LIST"],
    ["STYLE NO", "", ":", "A6C3T"],
    ["SHIP QTY", "", ":", "120", "PCS"],
    [],
    ["CTN NO", "", "CTN QTY", "COLOUR", "", "SIZE"],
    ["", "", "", "", "", "XS", "S", "M"],
    ["10", "10", "3", "BC9J-GS BLACK", "", "", "40", "20"],
    ["11", "11", "2", "", "", "10", "", ""],
    ["TOTAL", "", "5", "", "", "10", "40", "20"],
    ["SUMMARY"],
]


def build_multi_carton(path: Path) -> Path:
    """Workbook where carton rows cover multiple cartons each."""
    wb = Workbook()
    ws = wb.active
    for row in MULTI_CTN:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def build_sample(path: Path) -> Path:
    """Write the fixture workbook to ``path``."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Packing list"
    for row in SAMPLE:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
