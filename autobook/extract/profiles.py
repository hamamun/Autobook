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


@dataclass
class Profile:
    """One document family."""

    name: str
    match_any: tuple[str, ...]
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    carton: CartonSpec | None = None
    path: Path | None = None

    def matches(self, grid: list[list[str]], head_rows: int = 8) -> bool:
        """True when any match string appears in the first ``head_rows`` rows."""
        if not self.match_any:
            return False
        head = " ".join(" ".join(row) for row in grid[:head_rows]).upper()
        return any(token.upper() in head for token in self.match_any)


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

    return Profile(
        name=name,
        match_any=tuple(str(m) for m in (match_any or [])),
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
