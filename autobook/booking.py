"""Aggregate carton lines into the rows the Maersk booking page expects.

The portal wants **one row per SKU**, and a SKU number is
``<style>-<colour code>-<size>-<suffix>`` (e.g. ``A6C3T-BC9J-XL-BWI``). A packing list
gives us carton lines, so several lines can belong to one SKU:

    carton 2  BC9J-GS BLACK/Wash  S  65 pcs  1 ctn  12.60 kg
    carton 3  BC9J-GS BLACK/Wash  S  37 pcs  1 ctn   7.40 kg
    ------------------------------------------------------
    one portal row: 102 pcs, 2 packages, 51 qty/pkg, 20.00 kg

Rules applied here, each one deliberate:

* **Quantities, packages, volume and weights are summed.**
* **Qty per package is derived** as ``qty // packages`` and reported when it does not
  divide evenly - the portal showed 124 pcs over 3 cartons as 41.
* **Volume is summed per carton** rather than taken from one line, so a line covering
  several cartons (e.g. 6 cartons x 0.0528) is not understated.
* **Ordered quantity** comes from the packing list's order figure, which is not in the
  carton rows; where it is unavailable the shipped quantity is used and the row is
  flagged rather than silently filled.

The output is ordered by the packing list's own sequence (colour block, then size), so
the rows appear on the portal in the same order as the document.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import PackingList


@dataclass
class BookingLine:
    """One row of the Maersk booking-details grid."""

    source_file: str
    order_no: str
    style_no: str
    colour: str
    colour_code: str
    size: str
    sku: str
    ordered_qty: int
    booked_qty: int
    booked_packages: int
    qty_per_package: int
    booked_volume: float
    booked_gross_kg: float
    description: str
    carton_numbers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def colour_code(colour: str) -> str:
    """``BC9J-GS BLACK/Wash`` -> ``BC9J``.

    The first token of the colour field is the buyer's colour code in every packing
    list seen so far; the rest is a human description.
    """
    token = colour.strip().split("-")[0].split("/")[0].split(" ")[0]
    return token.strip().upper()


def build_sku(style_no: str, colour: str, size: str, suffix: str = "") -> str:
    """Assemble a portal SKU number.

    ``suffix`` is site-specific (``BWI`` appears on the live portal and is not present
    in any packing list), so it is supplied by configuration rather than guessed.
    """
    parts = [style_no.strip().upper(), colour_code(colour), size.strip().upper()]
    if suffix:
        parts.append(suffix.strip().upper())
    return "-".join(p for p in parts if p)


def aggregate(pl: PackingList, sku_suffix: str = "",
              description_template: str = "{description}, {colour}, {size}") -> list[BookingLine]:
    """Collapse a packing list's carton lines into one :class:`BookingLine` per SKU."""
    grouped: dict[tuple[str, str], list] = {}
    order: list[tuple[str, str]] = []

    for line in pl.cartons:
        key = (line.colour, line.size)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(line)

    lines: list[BookingLine] = []
    for colour, size in order:
        items = grouped[(colour, size)]
        qty = sum(i.qty for i in items)
        # Carton counts belong to source rows; sum once per row so a row carrying
        # several sizes does not multiply its count across them.
        packages = sum({i.row_ref: i.ctn_count for i in items}.values())
        volume = round(sum(i.cbm for i in items), 4)
        gross = round(sum(i.gross_kg for i in items), 2)

        notes: list[str] = []
        qty_per_package = qty // packages if packages else qty
        if packages and qty % packages:
            notes.append(f"{qty} pcs over {packages} cartons does not divide evenly "
                         f"(portal would show {qty / packages:.2f}, rounded down to "
                         f"{qty_per_package})")

        ordered = pl.order_qty
        if ordered is None:
            ordered = qty
            notes.append("order quantity not found in the document; used shipped quantity")

        lines.append(BookingLine(
            source_file=pl.source.name,
            order_no=pl.order_no or "",
            style_no=pl.style_no or "",
            colour=colour,
            colour_code=colour_code(colour),
            size=size,
            sku=build_sku(pl.style_no or "", colour, size, sku_suffix),
            ordered_qty=ordered,
            booked_qty=qty,
            booked_packages=packages,
            qty_per_package=qty_per_package,
            booked_volume=volume,
            booked_gross_kg=gross,
            description=description_template.format(
                description=pl.description or "", colour=colour, size=size).strip(", "),
            carton_numbers=[i.carton_no for i in items],
            notes=notes,
        ))
    return lines


def build_all(packing_lists: list[PackingList], sku_suffix: str = "") -> list[BookingLine]:
    """Aggregate every packing list in a batch."""
    out: list[BookingLine] = []
    for pl in packing_lists:
        out.extend(aggregate(pl, sku_suffix=sku_suffix))
    return out
