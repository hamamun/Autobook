"""Declarative extraction profiles.

A profile describes *where* information sits in one document family, so supporting a
new supplier is a YAML file, not a code change. Everything is optional: a field the
profile does not define simply comes back empty and is reported in the Review sheet.

Example::

    name: gymshark_packing_list
    match:
      any_of: ["PACKING LIST"]
    fields:
      supplier:   {cell: [0, 0]}
      style_no:   {label: "STYLE NO"}
      order_no:   {label: "ORDER NO", fallback_filename_regex: '-(\\d+)\\s+[A-Z]'}
    cartons:
      header_label: "CTN NO"
      stop_label: "SUMMARY"
      ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROFILE_DIR = Path(__file__).resolve().parents[2] / "profiles"


class ProfileError(ValueError):
    """A profile file is malformed - surfaced to the operator, not swallowed."""


@dataclass
class FieldSpec:
    """How to obtain one scalar field from the grid."""

    key: str
    cell: tuple[int, int] | None = None
    label: str | None = None
    label_value_offset: int | None = None
    strip_prefix: str | None = None
    fallback_filename_regex: str | None = None
    fallback_severity: str = "info"  # review | info
    cast: str = "str"
    required: bool = False


@dataclass
class CartonSpec:
    """How to read the carton grid."""

    header_label: str
    stop_label: str | None = None
    carton_no_col: int = 0
    ctn_count_col: int | None = None
    colour_col: int | None = None
    size_start_col: int = 5
    size_end_col: int = 12
    per_ctn_col: int | None = None
    total_pcs_col: int | None = None
    net_col: int | None = None
    gross_col: int | None = None
    cbm_col: int | None = None
    skip_prefixes: tuple[str, ...] = ("TOTAL", "GRAND")
    max_rows: int = 500


#: How many leading rows are searched for the match text. The packing-list title is
#: rarely in row 1 - it sits under a logo, address block or blank rows.
DEFAULT_MATCH_ROWS = 5

#: How far down a sheet the structural signature is looked for. Header rows usually sit
#: within the first few dozen rows, but trailers can push them further down.
DEFAULT_SIGNATURE_ROWS = 100


@dataclass
class Profile:
    """One document family."""

    name: str
    match_any: tuple[str, ...]
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    carton: CartonSpec | None = None
    path: Path | None = None
    match_rows: int = DEFAULT_MATCH_ROWS
    #: Labels that must also exist somewhere in the sheet. Words alone are not enough:
    #: a notes tab can say "PACKING LIST" without being one, but it will not contain
    #: the carton-table heading.
    require_any: tuple[str, ...] = ()
    #: Structural signature: label sets that identify the document even when the title
    #: is missing. Each group is a set of labels that must all appear in the *same*
    #: header row - a carton table has carton no, carton qty, net and gross weight on
    #: one line, which a note or cover tab will never have.
    signature: tuple[tuple[str, ...], ...] = ()
    signature_rows: int = DEFAULT_SIGNATURE_ROWS

    def matches(self, grid: list[list[str]], head_rows: int | None = None) -> bool:
        """True when the sheet looks like this document family.

        Two ways in, either is enough:

        1. the title text appears in the top ``match_rows`` rows **and** one of the
           ``require_any`` labels exists somewhere in the sheet; or
        2. the structural signature is present: one header row carries every label of
           a signature group (used when the words "packing list" are missing).
        """
        if self.matches_signature(grid):
            return True
        if not self.match_any:
            return False
        rows = head_rows if head_rows is not None else self.match_rows
        head = " ".join(" ".join(row) for row in grid[:rows]).upper()
        if not any(token.upper() in head for token in self.match_any):
            return False
        if self.require_any:
            whole = " ".join(" ".join(row) for row in grid).upper()
            if not any(token.upper() in whole for token in self.require_any):
                return False
        return True

    def matches_signature(self, grid: list[list[str]]) -> bool:
        """True when one header row carries every label of a signature group.

        Cells are compared individually (see :func:`~.grid.label_cells`), so ``CTN`` in
        one cell and ``NO`` in the next do not accidentally spell ``CTN NO``.
        """
        if not self.signature:
            return False
        from .grid import label_cells

        for row_index in range(min(len(grid), self.signature_rows)):
            cells = label_cells(grid, row_index)
            if not cells:
                continue
            joined = " | ".join(cells)
            for group in self.signature:
                if group and all(
                        label.upper() in cells or label.upper() in joined
                        for label in group):
                    return True
        return False


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ProfileError(f"{where}: missing required key '{key}'")
    return mapping[key]


def _parse_field(key: str, raw: dict[str, Any], where: str) -> FieldSpec:
    if not isinstance(raw, dict):
        raise ProfileError(f"{where}.{key}: expected a mapping")

    cell = raw.get("cell")
    if cell is not None:
        if not (isinstance(cell, (list, tuple)) and len(cell) == 2):
            raise ProfileError(f"{where}.{key}.cell: expected [row, column]")
        cell = (int(cell[0]), int(cell[1]))

    severity = str(raw.get("fallback_severity", "info")).lower()
    if severity not in {"review", "info"}:
        raise ProfileError(f"{where}.{key}.fallback_severity: expected review or info")

    cast = str(raw.get("cast", "str")).lower()
    if cast not in {"str", "int", "float"}:
        raise ProfileError(f"{where}.{key}.cast: expected str, int or float")

    spec = FieldSpec(
        key=key,
        cell=cell,
        label=raw.get("label"),
        label_value_offset=(int(raw["label_value_offset"])
                            if raw.get("label_value_offset") is not None else None),
        strip_prefix=raw.get("strip_prefix"),
        fallback_filename_regex=raw.get("fallback_filename_regex"),
        fallback_severity=str(raw.get("fallback_severity", "info")).lower(),
        cast=cast,
        required=bool(raw.get("required", False)),
    )
    if spec.cell is None and spec.label is None and spec.fallback_filename_regex is None:
        raise ProfileError(f"{where}.{key}: needs one of cell, label or fallback_filename_regex")
    return spec


def _parse_carton(raw: dict[str, Any], where: str) -> CartonSpec:
    if not isinstance(raw, dict):
        raise ProfileError(f"{where}.cartons: expected a mapping")
    spec = CartonSpec(
        header_label=_require(raw, "header_label", f"{where}.cartons"),
        stop_label=raw.get("stop_label"),
        carton_no_col=int(raw.get("carton_no_col", 0)),
        ctn_count_col=(int(raw["ctn_count_col"]) if raw.get("ctn_count_col") is not None else None),
        colour_col=(int(raw["colour_col"]) if raw.get("colour_col") is not None else None),
        size_start_col=int(raw.get("size_start_col", 5)),
        size_end_col=int(raw.get("size_end_col", 12)),
        per_ctn_col=(int(raw["per_ctn_col"]) if raw.get("per_ctn_col") is not None else None),
        total_pcs_col=(int(raw["total_pcs_col"]) if raw.get("total_pcs_col") is not None else None),
        net_col=(int(raw["net_col"]) if raw.get("net_col") is not None else None),
        gross_col=(int(raw["gross_col"]) if raw.get("gross_col") is not None else None),
        cbm_col=(int(raw["cbm_col"]) if raw.get("cbm_col") is not None else None),
        skip_prefixes=tuple(str(p).upper() for p in raw.get("skip_prefixes", ["TOTAL", "GRAND"])),
        max_rows=int(raw.get("max_rows", 500)),
    )
    if spec.size_end_col < spec.size_start_col:
        raise ProfileError(f"{where}.cartons: size_end_col is before size_start_col")
    return spec


def load_profile(path: Path) -> Profile:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path.name}: invalid YAML - {exc}") from exc
    if not isinstance(raw, dict):
        raise ProfileError(f"{path.name}: expected a mapping at the top level")

    where = path.stem
    name = str(raw.get("name") or path.stem)
    match = raw.get("match") or {}
    match_any = match.get("any_of") if isinstance(match, dict) else match
    fields_raw = raw.get("fields") or {}
    if not isinstance(fields_raw, dict):
        raise ProfileError(f"{where}.fields: expected a mapping of key -> spec")

    match_block = raw.get("match") if isinstance(raw.get("match"), dict) else {}
    match_rows = int(match_block.get("rows", DEFAULT_MATCH_ROWS))
    if match_rows < 1:
        raise ProfileError(f"{where}.match.rows: must be 1 or more")

    require_any = match_block.get("require_any") or []
    if isinstance(require_any, str):
        require_any = [require_any]

    signature_raw = match_block.get("signature") or []
    signature: list[tuple[str, ...]] = []
    for group in signature_raw:
        if isinstance(group, str):
            group = [group]
        if not isinstance(group, (list, tuple)) or not group:
            raise ProfileError(
                f"{where}.match.signature: each group must be a list of labels that "
                "must appear together in one header row")
        signature.append(tuple(str(g) for g in group))
    signature_rows = int(match_block.get("signature_rows", DEFAULT_SIGNATURE_ROWS))
    if signature_rows < 1:
        raise ProfileError(f"{where}.match.signature_rows: must be 1 or more")

    return Profile(
        name=name,
        match_any=tuple(str(m) for m in (match_any or [])),
        match_rows=match_rows,
        require_any=tuple(str(r) for r in require_any),
        signature=tuple(signature),
        signature_rows=signature_rows,
        fields={k: _parse_field(k, v, where) for k, v in fields_raw.items()},
        carton=_parse_carton(raw["cartons"], where) if raw.get("cartons") else None,
        path=path,
    )


def load_profiles(directory: Path | None = None) -> list[Profile]:
    """Load every ``*.yaml`` profile. A broken profile is skipped, not fatal."""
    directory = Path(directory or PROFILE_DIR)
    if not directory.is_dir():
        return []
    profiles: list[Profile] = []
    for file in sorted(directory.glob("*.y*ml")):
        try:
            profiles.append(load_profile(file))
        except ProfileError:
            continue
    return profiles


def find_profile(grid: list[list[str]], profiles: list[Profile]) -> Profile | None:
    """First profile whose match rule fires on this document."""
    for profile in profiles:
        if profile.matches(grid):
            return profile
    return None
