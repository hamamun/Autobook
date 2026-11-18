"""Shared data model for one extracted packing list.

Everything the extractors produce is a :class:`PackingList`; everything the writer
consumes is a :class:`PackingList`. Keeping one neutral shape in the middle means a
new document layout is a new extractor, not a change to the writer or the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CartonLine:
    """One carton within a packing list."""

    carton_no: str
    ctn_count: int = 1
    row_ref: int = 0  # source grid row: one row can yield several size lines
    colour: str = ""
    size: str = ""
    qty: int = 0
    net_kg: float = 0.0
    gross_kg: float = 0.0
    cbm: float = 0.0


@dataclass
class SkippedSheet:
    """A sheet that was looked at and deliberately not turned into data."""

    source_file: str
    sheet_name: str
    reason: str


@dataclass
class Issue:
    """A problem worth a human's attention."""

    field: str
    problem: str
    action: str
    severity: str = "review"  # review | info | error


@dataclass
class PackingList:
    """Normalised contents of one packing list document."""

    source: Path
    sheet_name: str = ""  # which tab of the workbook this row came from
    doc_type: str = ""
    supplier: str = ""
    supplier_address: str = ""
    buyer: str = ""
    order_no: str = ""
    split_po_no: str = ""
    style_no: str = ""
    description: str = ""
    destination: str = ""
    order_qty: int | None = None
    ship_qty: int | None = None
    total_cartons: int | None = None
    total_net_kg: float | None = None
    total_gross_kg: float | None = None
    total_cbm: float | None = None
    cartons: list[CartonLine] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    discarded_sheets: list[str] = field(default_factory=list)
    confidence: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    # -- derived -------------------------------------------------------------
    def colour_size_totals(self) -> list[tuple[str, str, int]]:
        """Aggregate pieces per (colour, size), preserving first-seen order."""
        totals: dict[tuple[str, str], int] = {}
        for line in self.cartons:
            key = (line.colour, line.size)
            totals[key] = totals.get(key, 0) + line.qty
        return [(c, s, q) for (c, s), q in totals.items()]

    def carton_count_by_row(self) -> list[int]:
        """Carton count for each source row, in first-seen order.

        A single carton row can carry quantities in several size columns, producing
        several :class:`CartonLine` entries. The carton count belongs to the row, so
        it must be counted once - summing it per size line multiplies it.
        """
        per_row: dict[int, int] = {}
        for line in self.cartons:
            per_row.setdefault(line.row_ref, line.ctn_count)
        return list(per_row.values())

    @property
    def carton_count(self) -> int:
        """Total cartons shipped.

        Sums the "CTN QTY" column once per carton row. In these documents "CTN NO" is
        a label and the figure that reconciles with the header total is the adjacent
        count column, so counting distinct carton numbers would undercount.
        """
        return sum(self.carton_count_by_row())

    def add_issue(self, field_name: str, problem: str, action: str, severity: str = "review") -> None:
        self.issues.append(Issue(field_name, problem, action, severity))
