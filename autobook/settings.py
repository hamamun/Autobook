"""Persisted user settings.

Deliberately a tiny JSON file rather than a config framework: one key today
(``last_browse_dir``), a settings screen later. Unknown keys are preserved so a
downgrade never destroys someone's configuration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import settings_path


@dataclass
class Settings:
    """User-mutable settings."""

    last_browse_dir: str = ""
    work_dir_override: str = ""
    output_dir_override: str = ""
    # Site-specific values for the booking page. They cannot be derived from a packing
    # list, so they live in settings rather than in the extraction profile.
    sku_suffix: str = "BWI"
    commodity_code: str = ""
    country_of_origin: str = "BD"
    extra: dict[str, Any] = field(default_factory=dict)

    # -- persistence ---------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or settings_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt settings file must never stop the app from starting.
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        extra = {k: v for k, v in raw.items() if k not in known}
        return cls(
            last_browse_dir=str(raw.get("last_browse_dir") or ""),
            work_dir_override=str(raw.get("work_dir_override") or ""),
            output_dir_override=str(raw.get("output_dir_override") or ""),
            sku_suffix=str(raw.get("sku_suffix") or "BWI"),
            commodity_code=str(raw.get("commodity_code") or ""),
            country_of_origin=str(raw.get("country_of_origin") or "BD"),
            extra=extra,
        )

    def save(self, path: Path | None = None) -> None:
        path = path or settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "last_browse_dir": self.last_browse_dir,
            "work_dir_override": self.work_dir_override,
            "output_dir_override": self.output_dir_override,
            "sku_suffix": self.sku_suffix,
            "commodity_code": self.commodity_code,
            "country_of_origin": self.country_of_origin,
            **self.extra,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic: never leaves a half-written settings file

    # -- helpers -------------------------------------------------------------
    def initial_browse_dir(self) -> str:
        """Folder the file dialog should open in.

        Falls back to the user's home directory when nothing usable is stored,
        so the dialog never opens somewhere unhelpful or on a missing drive.
        """
        candidate = self.last_browse_dir
        if candidate and Path(candidate).is_dir():
            return candidate
        return str(Path.home())

    def remember_browse_dir(self, files: list[str] | list[Path]) -> None:
        """Store the folder of the first selected file."""
        for item in files:
            parent = Path(item).expanduser().parent
            if parent.is_dir():
                self.last_browse_dir = str(parent.resolve())
                return
