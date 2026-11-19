"""Values, not browser actions: what the Maersk portal line must contain.

The portal side (Playwright) is a thin shell around this module. Everything that can be
decided without a browser lives here, so it can be tested without one.

Three jobs:

* :func:`compared_key` - the match key. **PO number + SKU core**, with the size suffix
  dropped on both sides. The portal appends its own suffix (`BW1`) which appears nowhere
  in the source document, so comparing full SKU strings would fail on every row.
* :func:`compare_number` - the portal renders values at display precision (`0.053` for
  our `0.0528`, `3` for our `3.00`). Comparing raw floats would report every row as a
  mismatch.
* :class:`PoTotals` - the four reconciliation figures, built from the rows that were
  **actually matched**, never from the whole packing list: an unmatched SKU is skipped
  and reported, so the portal can never total the whole list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

#: The portal displays volume and weight to three decimals.
DISPLAY_PLACES = 3


def sku_core(sku: str) -> str:
    """``A6C3T-BC9J-XS-BWI`` -> ``A6C3T-BC9J-XS``.

    The last hyphen-separated group is the size suffix the portal generates. Everything
    before it is what identifies the line.
    """
    text = (sku or "").strip().upper()
    if text.endswith(")"):
        # portal style "A6C3T-BC9J-XS-BW1 (4500046108-6-60)"
        text = text.split("(", 1)[0].strip()
    if "-" not in text:
        return text
    return text.rsplit("-", 1)[0]


def compared_key(po_no: str, sku: str) -> tuple[str, str]:
    """The match key: ``(PO number, SKU core)``, both normalised.

    This is the only thing used to pair one of our rows with one portal row.
    """
    return ((po_no or "").strip().upper(), sku_core(sku))


def portal_text_to_key(text: str) -> tuple[str, str]:
    """Parse a portal SKU cell into the same key.

    The cell reads ``A6C3T-BC9J-XS-BW1 (4500046108-6-60)``: the SKU, then the row key in
    brackets. The PO comes from the bracketed key so the two sides are built the same way.
    """
    raw = (text or "").strip()
    po = ""
    if "(" in raw and raw.endswith(")"):
        inner = raw[raw.index("(") + 1:-1]
        po = inner.split("-", 1)[0].strip()
    return compared_key(po, raw)


def to_decimal(value: object) -> Decimal | None:
    """Parse a portal or spreadsheet value, returning ``None`` when it is not a number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def round_for_portal(value: object, places: int = DISPLAY_PLACES) -> Decimal | None:
    """Round our value the way the portal displays it, before comparing."""
    number = to_decimal(value)
    if number is None:
        return None
    quant = Decimal(1).scaleb(-places)
    return number.quantize(quant, rounding=ROUND_HALF_UP)


def compare_number(ours: object, portal: object,
                   places: int = DISPLAY_PLACES) -> bool:
    """True when the portal's displayed value equals ours at that precision.

    ``0.0528`` vs ``0.053`` -> True. ``3.00`` vs ``3`` -> True. This is rounding, not a
    tolerance: the portal stores and shows three decimals.
    """
    left = round_for_portal(ours, places)
    right = to_decimal(portal)
    if left is None or right is None:
        return False
    # The portal may show fewer decimals (3 rather than 3.000); compare numerically.
    return left.normalize() == right.normalize()


def compare_whole(ours: object, portal: object) -> bool:
    """Quantity and package counts are whole numbers on both sides."""
    left = to_decimal(ours)
    right = to_decimal(portal)
    if left is None or right is None:
        return False
    return int(left) == int(right)


@dataclass
class LineComparison:
    """One row: what was expected, what the portal showed, and whether they agree."""

    key: tuple[str, str]
    label: str  # the SKU core, for the report
    checks: dict[str, tuple[object, object, bool]] = field(default_factory=dict)

    def add(self, name: str, ours: object, portal: object, ok: bool) -> None:
        self.checks[name] = (ours, portal, ok)

    @property
    def ok(self) -> bool:
        return all(ok for _, _, ok in self.checks.values())

    @property
    def failures(self) -> list[str]:
        return [f"{name}: ours {ours}, portal {portal}"
                for name, (ours, portal, ok) in self.checks.items() if not ok]


@dataclass
class PoTotals:
    """The four reconciliation figures for one PO."""

    quantity: int = 0
    packages: int = 0
    gross_kg: Decimal = Decimal("0")
    volume: Decimal = Decimal("0")

    def add(self, *, quantity: int, packages: int, gross_kg: object, volume: object) -> None:
        self.quantity += int(quantity)
        self.packages += int(packages)
        self.gross_kg += to_decimal(gross_kg) or Decimal("0")
        self.volume += round_for_portal(volume) or Decimal("0")

    @classmethod
    def from_lines(cls, lines) -> "PoTotals":
        """Totals for the rows that were matched, not the whole packing list.

        Volume is summed **per row, rounded first**, because that is what the portal
        does: our ``0.0528`` is held as ``0.053`` and the portal sums the rounded values.
        Summing our raw figures and rounding at the end drifts by up to half a unit in
        the third decimal per row.
        """
        totals = cls()
        for line in lines:
            totals.add(quantity=line.booked_qty,
                       packages=line.booked_packages,
                       gross_kg=line.booked_gross_kg,
                       volume=line.booked_volume)
        return totals

    def compare(self, *, quantity: object, packages: object,
                gross_kg: object, volume: object) -> dict[str, tuple[object, object, bool]]:
        """Compare against the portal's displayed totals."""
        return {
            "Total quantity": (self.quantity, quantity,
                               compare_whole(self.quantity, quantity)),
            "Total packages": (self.packages, packages,
                               compare_whole(self.packages, packages)),
            "Total gross weight": (self.gross_kg, gross_kg,
                                   compare_number(self.gross_kg, gross_kg)),
            "Total volume": (self.volume, volume,
                             compare_number(self.volume, volume)),
        }
