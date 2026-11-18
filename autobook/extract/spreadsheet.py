"""Turn a spreadsheet packing list into a :class:`PackingList` using a profile."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..models import CartonLine, PackingList
from .grid import (Grid, Sheet, cell, find_label_position, read_grid, read_sheets,
                   value_right_of)
from .profiles import FieldSpec, Profile, find_profile


def _cast(value: str, spec: FieldSpec) -> object:
    if value == "":
        return None
    if spec.cast == "int":
        try:
            return int(float(value.replace(",", "")))
        except ValueError:
            return None
    if spec.cast == "float":
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return value


def _apply_field(pl: PackingList, spec: FieldSpec, grid: Grid, path: Path) -> None:
    """Fill one field by cell reference, label lookup, or file-name fallback."""
    raw = ""

    if spec.cell is not None:
        raw = cell(grid, spec.cell[0], spec.cell[1])
        pl.sources[spec.key] = f"cell R{spec.cell[0] + 1}C{spec.cell[1] + 1}"

    if not raw and spec.label:
        position = find_label_position(grid, spec.label, end=min(len(grid), 60))
        if position:
            row, col = position
            if spec.label_value_offset is not None:
                raw = cell(grid, row, col + spec.label_value_offset)
            else:
                raw = value_right_of(grid, row, col)
            pl.sources[spec.key] = f"label '{spec.label}'"

    used_fallback = False
    if not raw and spec.fallback_filename_regex:
        # Try the stem first so an extension never hides an anchored pattern, then the
        # full name as a fallback (some profiles match the extension deliberately).
        match = (re.search(spec.fallback_filename_regex, path.stem)
                 or re.search(spec.fallback_filename_regex, path.name))
        if match:
            raw = match.group(1) if match.groups() else match.group(0)
            used_fallback = True
            pl.sources[spec.key] = "file name"
            pl.confidence[spec.key] = "medium"
            pl.add_issue(spec.key,
                         f"Value missing from the document; taken from the file name ('{raw}')",
                         "Confirm the value is correct")
        else:
            pl.confidence.setdefault(spec.key, "low")

    if spec.strip_prefix and raw.upper().startswith(spec.strip_prefix.upper()):
        raw = raw[len(spec.strip_prefix):].strip()

    value = _cast(raw, spec)
    if isinstance(value, str) and not value:
        value = None

    setattr(pl, spec.key, value)

    if value is None:
        pl.confidence.setdefault(spec.key, "low")
        if spec.required:
            pl.add_issue(spec.key, "Required value not found", "Enter it manually", "review")
    elif not used_fallback:
        pl.confidence.setdefault(spec.key, "high")


def _strip_units(value: str) -> float | None:
    """'51.60 KGS' -> 51.60, '0.7392 CBM' -> 0.7392."""
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    return float(match.group(0)) if match else None


def plan_sheets(path: Path, profiles: list[Profile]) -> list[tuple[str, Profile]]:
    """Which sheets of a workbook hold a packing list, and which profile to use.

    Every sheet is inspected; hidden ones are ignored and any sheet whose top rows do
    not match a profile is discarded. Returns ``[(sheet_name, profile), ...]``.
    """
    return [(entry.sheet_name, entry.profile)  # type: ignore[misc]
            for entry in survey_sheets(path, profiles) if entry.profile is not None]


@dataclass
class SheetSurvey:
    """What happened to one sheet during sheet selection."""

    sheet_name: str
    profile: Profile | None = None
    reason: str = ""


def survey_sheets(path: Path, profiles: list[Profile]) -> list[SheetSurvey]:
    """Inspect every sheet and say which ones qualify, and why the rest do not."""
    try:
        sheets = read_sheets(path)
    except ValueError:
        return []

    out: list[SheetSurvey] = []
    for sheet in sheets:
        if sheet.hidden:
            out.append(SheetSurvey(sheet.name, None, "hidden tab - ignored"))
            continue
        profile = find_profile(sheet.grid, profiles)
        if profile is None:
            out.append(SheetSurvey(
                sheet.name, None,
                "not a packing list (no title in the top rows and no carton table)"))
        else:
            out.append(SheetSurvey(sheet.name, profile, "packing list"))
    return out


def has_content(pl: PackingList) -> bool:
    """True when a sheet produced actual packing-list data.

    A tab can mention the words "packing list" without being one (a notes tab, a cover
    sheet, an index). Requiring at least one field value or one carton line discards
    those without relying on tab names or guesswork.
    """
    return bool(pl.cartons) or any(
        value not in (None, "")
        for key, value in vars(pl).items()
        if key in {"doc_type", "supplier", "order_no", "split_po_no", "style_no",
                   "description", "order_qty", "ship_qty", "total_cartons",
                   "total_net_kg", "total_gross_kg", "total_cbm"}
    )


def extract_with_profile(path: Path, profiles: list[Profile],
                         sheet_name: str | None = None,
                         profile: Profile | None = None) -> PackingList:
    """Extract one sheet (default: the first sheet that looks like a packing list)."""
    path = Path(path)
    pl = PackingList(source=path)

    try:
        sheets = read_sheets(path)
    except ValueError as exc:
        pl.add_issue("file", str(exc), "Re-save the file and add it again", "error")
        return pl

    if not sheets:
        pl.add_issue("file", "The document is empty", "Check the file", "error")
        return pl

    # Pick the sheet: an explicit name wins, otherwise the first one that matches.
    chosen: Sheet | None = None
    if sheet_name is not None:
        chosen = next((sh for sh in sheets if sh.name == sheet_name), None)
        if chosen is None:
            pl.add_issue("file", f"Sheet '{sheet_name}' no longer exists in {path.name}",
                         "Re-run Prepare", "error")
            return pl
    else:
        for sh in sheets:
            if sh.hidden:
                continue
            if find_profile(sh.grid, profiles) is not None:
                chosen = sh
                break

    if chosen is None:
        pl.add_issue(
            "file",
            "No extraction profile matches this layout",
            "Add a profile for this supplier, or fill the row manually",
            "error",
        )
        pl.confidence["_profile"] = "none"
        return pl

    grid = chosen.grid
    if not grid:
        pl.add_issue("file", f"Sheet '{chosen.name}' is empty", "Check the file", "error")
        return pl

    matched = profile if profile is not None else find_profile(grid, profiles)
    if matched is None:
        pl.add_issue(
            "file",
            f"Sheet '{chosen.name}' does not match any extraction profile",
            "Add a profile for this supplier, or fill the row manually",
            "error",
        )
        pl.confidence["_profile"] = "none"
        return pl

    pl.confidence["_profile"] = matched.name
    pl.sheet_name = chosen.name
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        pl.sources["sheet"] = chosen.name

    for spec in matched.fields.values():
        _apply_field(pl, spec, grid, path)

    if matched.carton is not None:
        _read_cartons(pl, matched, grid)

    _reconcile(pl)
    return pl


def _read_cartons(pl: PackingList, profile: Profile, grid: Grid) -> None:
    spec = profile.carton
    assert spec is not None

    header = find_label_position(grid, spec.header_label, end=min(len(grid), 80))
    if header is None:
        pl.add_issue("cartons", f"Carton table not found (looking for '{spec.header_label}')",
                     "Check the document, or add a profile for it", "error")
        return

    start_row = header[0] + 1
    # Size names often sit on a second header line (XXS, XS, S ...). Detect it so
    # those rows are not mistaken for data.
    sizes: list[str] = []
    probe = start_row
    while probe < len(grid) and probe < start_row + 3:
        labels = [cell(grid, probe, c) for c in range(spec.size_start_col, spec.size_end_col + 1)]
        found = [label for label in labels if label]
        if found and not any(label.replace(".", "").isdigit() for label in found):
            sizes = found
            start_row = probe + 1
            break
        probe += 1
    if not sizes:
        sizes = [f"SIZE{c + 1}" for c in range(spec.size_start_col, spec.size_end_col + 1)]

    colour = ""
    seen_data = False
    for r in range(start_row, min(len(grid), start_row + spec.max_rows)):
        tag = cell(grid, r, spec.carton_no_col)

        upper = tag.upper()
        if any(upper.startswith(prefix) for prefix in spec.skip_prefixes):
            # Subtotals inside the table are skipped; the stop label ends it.
            continue
        if spec.stop_label and upper.startswith(spec.stop_label.upper()):
            break
        if not upper:
            if seen_data and not any(cell(grid, r, c) for c in range(len(grid[r]))):
                continue
            continue
        if not tag.isdigit():
            continue

        seen_data = True
        if spec.colour_col is not None:
            colour_cell = cell(grid, r, spec.colour_col)
            if colour_cell:
                colour = colour_cell  # forward-fill: colour is written once per block

        # The figure that reconciles with the header total. When the profile does
        # not name one, assume each row is a single carton.
        ctn_count = 1
        if spec.ctn_count_col is not None:
            raw_count = cell(grid, r, spec.ctn_count_col)
            try:
                ctn_count = int(float(raw_count.replace(",", "")))
            except ValueError:
                ctn_count = 0
            if ctn_count <= 0:
                # A missing or unreadable count would silently undercount the batch, so
                # assume one carton and flag it instead of hiding the problem.
                ctn_count = 1
                if raw_count == "":
                    pl.add_issue("total_cartons",
                                 f"Carton row {tag}: the carton-count column is empty; "
                                 "counted as 1 carton",
                                 "Check this row in the packing list", "review")

        def number(col: int | None) -> float:
            if col is None:
                return 0.0
            try:
                return float(cell(grid, r, col).replace(",", ""))
            except ValueError:
                return 0.0

        for offset, size in enumerate(sizes):
            col = spec.size_start_col + offset
            qty_text = cell(grid, r, col)
            if not qty_text:
                continue
            try:
                qty = int(float(qty_text.replace(",", "")))
            except ValueError:
                continue
            if qty == 0:
                continue
            pl.cartons.append(CartonLine(
                carton_no=tag,
                ctn_count=ctn_count,
                row_ref=r,
                colour=colour,
                size=size,
                qty=qty,
                net_kg=number(spec.net_col),
                gross_kg=number(spec.gross_col),
                cbm=number(spec.cbm_col),
            ))

    if not pl.cartons:
        pl.add_issue("cartons", "Carton table found but no quantity rows were read",
                     "Check the document layout", "error")


def _reconcile(pl: PackingList) -> None:
    """Cross-check the header against the carton lines.

    These checks are the feature, not decoration: when three independent numbers in
    the document agree, an unattended run is defensible.
    """
    summed_qty = sum(line.qty for line in pl.cartons)
    summed_net = round(sum(line.net_kg for line in pl.cartons), 2)
    summed_gross = round(sum(line.gross_kg for line in pl.cartons), 2)
    summed_cbm = round(sum(line.cbm for line in pl.cartons), 3)

    if pl.ship_qty is not None and pl.cartons:
        if summed_qty != pl.ship_qty:
            pl.add_issue("ship_qty",
                         f"Header ship qty {pl.ship_qty} does not match carton lines ({summed_qty})",
                         "Check whether a carton row was missed or misread", "review")

    if pl.total_cartons is not None and pl.cartons:
        if pl.carton_count != pl.total_cartons:
            pl.add_issue("total_cartons",
                         f"Header says {pl.total_cartons} cartons, "
                         f"carton-count column totals {pl.carton_count}",
                         "Check the carton table", "review")

    if pl.total_gross_kg is not None and pl.cartons:
        if abs(summed_gross - pl.total_gross_kg) > 0.05:
            pl.add_issue("total_gross_kg",
                         f"Header gross {pl.total_gross_kg} vs lines {summed_gross}",
                         "Check weights", "review")

    if pl.total_net_kg is not None and pl.cartons:
        if abs(summed_net - pl.total_net_kg) > 0.05:
            pl.add_issue("total_net_kg",
                         f"Header net {pl.total_net_kg} vs lines {summed_net}",
                         "Check weights", "review")

    if pl.total_cbm is not None and pl.cartons:
        # Per-carton CBM is often rounded, so allow a wider tolerance here and
        # never treat a small difference as an error.
        if abs(summed_cbm - pl.total_cbm) > 0.02:
            pl.add_issue("total_cbm",
                         f"Header CBM {pl.total_cbm} vs lines {summed_cbm}",
                         "Check carton measurements", "info")

    if pl.order_qty is not None and pl.ship_qty is not None and pl.order_qty != pl.ship_qty:
        pl.add_issue("ship_qty",
                     f"Short shipment: ordered {pl.order_qty}, shipped {pl.ship_qty}",
                     "Confirm which quantity the booking should carry", "info")
