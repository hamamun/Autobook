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
    colour: str = ""
    size: str = ""
    qty: int = 0
    net_kg: float = 0.0
    gross_kg: float = 0.0
    cbm: float = 0.0


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

    @property
    def carton_count(self) -> int:
        return len({line.carton_no for line in self.cartons})

    def add_issue(self, field_name: str, problem: str, action: str, severity: str = "review") -> None:
        self.issues.append(Issue(field_name, problem, action, severity))
