"""Tests for the work-directory copy rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from autobook.workdir import (
    SUPPORTED_SUFFIXES,
    copy_into_batch,
    file_digest,
    is_work_dir_writable,
    make_batch_dir,
    safe_filename,
)


def test_copy_keeps_original_and_copies_content(tmp_path: Path) -> None:
    src = tmp_path / "in" / "a.csv"
    src.parent.mkdir()
    src.write_text("hello", encoding="utf-8")

    batch = make_batch_dir(tmp_path / "work")
    result = copy_into_batch([src], batch)

    assert src.exists(), "the original must never be removed"
    assert result[0].copied is True
    assert result[0].stored.read_text(encoding="utf-8") == "hello"
    assert result[0].stored.parent == batch


def test_same_name_different_content_does_not_overwrite(tmp_path: Path) -> None:
    one = tmp_path / "one" / "packing.csv"
    two = tmp_path / "two" / "packing.csv"
    one.parent.mkdir()
    two.parent.mkdir()
    one.write_text("first", encoding="utf-8")
    two.write_text("second", encoding="utf-8")

    batch = make_batch_dir(tmp_path / "work")
    a = copy_into_batch([one], batch)[0]
    b = copy_into_batch([two], batch)[0]

    assert a.stored != b.stored
    assert a.stored.read_text(encoding="utf-8") == "first"
    assert b.stored.read_text(encoding="utf-8") == "second"
    assert b.stored.name == "packing (2).csv"


def test_identical_file_is_copied_once(tmp_path: Path) -> None:
    src = tmp_path / "a.csv"
    src.write_text("same", encoding="utf-8")
    batch = make_batch_dir(tmp_path / "work")

    first = copy_into_batch([src, src], batch)

    assert len(first) == 2
    assert first[0].digest == first[1].digest
    assert first[0].stored == first[1].stored
    assert len(list(batch.iterdir())) == 1


def test_file_already_in_work_dir_is_not_copied(tmp_path: Path) -> None:
    batch = make_batch_dir(tmp_path / "work")
    inside = batch / "already.csv"
    inside.write_text("x", encoding="utf-8")

    result = copy_into_batch([inside], batch)[0]

    assert result.copied is False
    assert result.stored == inside


def test_unsupported_extension_rejected(tmp_path: Path) -> None:
    src = tmp_path / "notes.txt"
    src.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file type"):
        copy_into_batch([src], make_batch_dir(tmp_path / "work"))


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        copy_into_batch([tmp_path / "nope.xlsx"], make_batch_dir(tmp_path / "work"))


def test_batch_dirs_are_unique(tmp_path: Path) -> None:
    root = tmp_path / "work"
    first = make_batch_dir(root)
    second = make_batch_dir(root)
    assert first != second and first.exists() and second.exists()


def test_digest_changes_with_content(tmp_path: Path) -> None:
    a = tmp_path / "a.csv"
    a.write_text("one", encoding="utf-8")
    first = file_digest(a)
    a.write_text("two", encoding="utf-8")
    assert file_digest(a) != first


def test_safe_filename_strips_windows_reserved_chars() -> None:
    assert safe_filename('a<b>c:d"e/f\\g|h?i*j.csv') == "a_b_c_d_e_f_g_h_i_j.csv"


def test_writable_probe(tmp_path: Path) -> None:
    ok, reason = is_work_dir_writable(tmp_path / "new" / "dir")
    assert ok and reason == ""


def test_every_supported_type_appears_in_the_file_dialog() -> None:
    from autobook.workdir import dialog_filetypes

    groups = dialog_filetypes()[:-1]  # the last entry is "All files"
    covered = {suffix for _label, pattern in groups for suffix in pattern.replace("*", "").split()}
    assert SUPPORTED_SUFFIXES <= covered
