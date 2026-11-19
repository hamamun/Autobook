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

#: Fixed for this operation: goods are always shipped from Bangladesh.
DEFAULT_COUNTRY_OF_ORIGIN = "BD"


@dataclass
class Settings:
    """User-mutable settings."""

    last_browse_dir: str = ""
    work_dir_override: str = ""
    output_dir_override: str = ""
    # Site-specific values for the booking page. They cannot be derived from a packing
    # list, so they live in settings rather than in the extraction profile.
    sku_suffix: str = "BWI"
    #: The portal pre-fills commodity code, so it is deliberately left blank here rather
    #: than written on every row - there is no fixed code to state. Country of origin is
    #: always BD and is written for the operator to check against the page.
    country_of_origin: str = DEFAULT_COUNTRY_OF_ORIGIN
    #: Stop at the Review page instead of submitting. **Off by default**: a run is meant
    #: to book. Set it to true to rehearse a fill without submitting anything.
    stop_before_submit: bool = False
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
        # Keys that used to be settings but are now fixed or blank by design. Dropped
        # rather than kept in `extra`, so a stale value cannot reappear on save.
        obsolete = {"commodity_code", "cargo_type"}
        extra = {k: v for k, v in raw.items() if k not in known and k not in obsolete}
        return cls(
            last_browse_dir=str(raw.get("last_browse_dir") or ""),
            work_dir_override=str(raw.get("work_dir_override") or ""),
            output_dir_override=str(raw.get("output_dir_override") or ""),
            sku_suffix=str(raw.get("sku_suffix") or "BWI"),
            country_of_origin=str(raw.get("country_of_origin")
                                  or DEFAULT_COUNTRY_OF_ORIGIN),
            stop_before_submit=bool(raw.get("stop_before_submit", False)),
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
            "country_of_origin": self.country_of_origin,
            "stop_before_submit": self.stop_before_submit,
            **self.extra,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic: never leaves a half-written settings file

    # -- helpers -------------------------------------------------------------
    def browser_profile_dir(self) -> Path:
        """Where the portal session lives.

        A dedicated folder, because current Chrome and Edge refuse remote debugging on
        the default profile. The operator logs in here once.
        """
        from .paths import app_data_dir

        return app_data_dir() / "browser-profile"

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
