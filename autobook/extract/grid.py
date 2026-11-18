"""Reading a document as a rectangular grid of strings.

Both CSV and xlsx are reduced to the same shape - a list of rows, each a list of
strings - so an extraction profile can describe a layout once and work against
either file type. Nothing here knows what a packing list is.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

Grid = list[list[str]]


class Sheet:
    """One worksheet (or the single grid of a CSV) ready for profile matching."""

    def __init__(self, name: str, grid: Grid, hidden: bool = False):
        self.name = name
        self.grid = grid
        self.hidden = hidden

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Sheet({self.name!r}, {len(self.grid)} rows, hidden={self.hidden})"

_WS = re.compile(r"\s+")


def normalise(value: object) -> str:
    """Trim, collapse whitespace and upper-case for label comparisons."""
    if value is None:
        return ""
    text = _WS.sub(" ", str(value)).strip()
    return text.upper()


def cell(grid: Grid, row: int, col: int) -> str:
    """Safe cell access - out-of-range coordinates return an empty string."""
    if row < 0 or row >= len(grid):
        return ""
    line = grid[row]
    if col < 0 or col >= len(line):
        return ""
    return line[col].strip()


def label_cells(grid: Grid, row: int) -> list[str]:
    """Normalised, non-empty cells of one row - for label comparisons.

    Returns ``["CTN NO", "CTN QTY", "COLOUR", "SIZE", ...]``: each cell upper-cased with
    internal whitespace collapsed, empty cells dropped. Two adjacent headings such as
    ``CTN`` and ``NO`` stay separate rather than merging into ``CTN | NO``.
    """
    if row < 0 or row >= len(grid):
        return []
    return [normalise(value) for value in grid[row] if normalise(value)]


def numbers_in(row: list[str]) -> list[float]:
    """Every numeric value in a row, in order - handy for carton rows."""
    out: list[float] = []
    for value in row:
        try:
            out.append(float(value.replace(",", "")))
        except (ValueError, AttributeError):
            continue
    return out


def find_label_row(grid: Grid, label: str, start: int = 0, end: int | None = None) -> int | None:
    """First row index containing ``label`` in any cell."""
    target = normalise(label)
    for r in range(start, end if end is not None else len(grid)):
        for value in grid[r]:
            if normalise(value) == target:
                return r
    return None


def find_label_position(grid: Grid, label: str, start: int = 0,
                        end: int | None = None) -> tuple[int, int] | None:
    """(row, col) of the first exact match of ``label``."""
    target = normalise(label)
    for r in range(start, end if end is not None else len(grid)):
        for c, value in enumerate(grid[r]):
            if normalise(value) == target:
                return r, c
    return None


def value_right_of(grid: Grid, row: int, col: int, max_offset: int = 6) -> str:
    """First non-empty value to the right of a label, skipping ':' separators."""
    for offset in range(1, max_offset + 1):
        value = cell(grid, row, col + offset)
        if value and value != ":":
            # Stop if we run into another label (left-hand column of another field).
            return value
    return ""


def read_grid(path: Path) -> Grid:
    """Load the first worksheet of a csv/xlsx/xlsm file into a grid of strings."""
    return read_sheets(path)[0].grid


def read_sheets(path: Path) -> list[Sheet]:
    """Load every worksheet of a csv/xlsx/xlsm file.

    Hidden and very-hidden tabs are still read (callers decide whether to use them,
    and the operator is told about them); the ``hidden`` flag carries that state.
    """
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return [Sheet(path.stem, _read_csv(path))]
    if suffix in {".xlsx", ".xlsm"}:
        return _read_xlsx_sheets(path)
    if suffix == ".xls":
        raise ValueError(
            "Legacy .xls files are not readable. Open the file in Excel and save as "
            ".xlsx, then add it again."
        )
    raise ValueError(f"Not a spreadsheet: {path.name}")


def _read_csv(path: Path) -> Grid:
    # utf-8-sig strips the BOM these files often start with; cp1252 is a common
    # fallback for exports from older Windows systems.
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open(newline="", encoding=encoding) as fh:
                sample = fh.read(8192)
                fh.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                except csv.Error:
                    dialect = csv.excel
                rows = [[c.strip() for c in row] for row in csv.reader(fh, dialect)]
            return rows
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode {path.name} - save it as UTF-8 or xlsx.")


def _read_xlsx_sheets(path: Path) -> list[Sheet]:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        sheets: list[Sheet] = []
        for name in wb.sheetnames:
            ws = wb[name]
            hidden = ws.sheet_state in {"hidden", "veryHidden"}
            grid: Grid = []
            for row in ws.iter_rows(values_only=True):
                grid.append(["" if v is None else str(v).strip() for v in row])
            sheets.append(Sheet(name, grid, hidden))
        return sheets
    finally:
        wb.close()
