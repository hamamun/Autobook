"""Filesystem locations.

Every user-writable location is resolved from one place so the settings screen can
override them later without touching the rest of the code.

On Windows the default working directory is ``%LOCALAPPDATA%\\Autobook\\work``.
Elsewhere (development, CI) ``~/.local/share/autobook/work`` is used. The directory is
created on demand; nothing else in the app assumes it already exists.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Autobook"


def app_data_dir() -> Path:
    """Base directory for app data (settings, work dir, output)."""
    override = os.environ.get("AUTOBOOK_HOME")
    if override:
        return Path(override).expanduser().resolve()

    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Local" / APP_NAME

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME.lower()
    return Path.home() / ".local" / "share" / APP_NAME.lower()


def work_dir() -> Path:
    """Fixed working directory that selected packing lists are copied into."""
    override = os.environ.get("AUTOBOOK_WORK_DIR")
    path = Path(override).expanduser().resolve() if override else app_data_dir() / "work"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir() -> Path:
    """Where the populated data sheet is written."""
    override = os.environ.get("AUTOBOOK_OUTPUT_DIR")
    path = Path(override).expanduser().resolve() if override else app_data_dir() / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    """JSON settings file (last browse folder, work dir override)."""
    return app_data_dir() / "settings.json"


def ensure_dirs() -> None:
    """Create every directory the app expects."""
    app_data_dir().mkdir(parents=True, exist_ok=True)
    work_dir()
    output_dir()
