"""Tests for the remembered-file-dialog behaviour."""

from __future__ import annotations

from pathlib import Path

from autobook.settings import Settings


def test_defaults_when_no_file(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path / "missing.json")
    assert settings.last_browse_dir == ""
    assert Path(settings.initial_browse_dir()) == Path.home()


def test_roundtrip(tmp_path: Path) -> None:
    folder = tmp_path / "a"
    folder.mkdir()
    path = tmp_path / "settings.json"
    settings = Settings.load(path)
    settings.remember_browse_dir([folder / "x.xlsx"])
    settings.save(path)

    reloaded = Settings.load(path)
    assert reloaded.last_browse_dir == str((tmp_path / "a").resolve())


def test_corrupt_settings_does_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json", encoding="utf-8")
    settings = Settings.load(path)
    assert settings.last_browse_dir == ""


def test_missing_folder_falls_back_to_home(tmp_path: Path) -> None:
    settings = Settings(last_browse_dir=str(tmp_path / "deleted" / "drive"))
    assert Path(settings.initial_browse_dir()) == Path.home()


def test_unknown_keys_are_preserved(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"last_browse_dir": "", "future_option": 42}', encoding="utf-8")
    settings = Settings.load(path)
    settings.save(path)

    assert '"future_option": 42' in path.read_text(encoding="utf-8")
