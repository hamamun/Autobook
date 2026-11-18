"""Fixed working directory management.

Selected packing lists are **copied** (never moved) into the work directory so the
operator's originals are untouched. Copying rules:

* the source file is never modified, moved or deleted;
* a file that is already inside the work directory is left alone;
* two different files with the same name both survive - the second becomes
  ``name (2).ext`` rather than overwriting the first;
* the same file selected twice is copied once;
* each Prepare run gets its own dated sub-folder, so yesterday's batch is still
  there and nothing is silently overwritten.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SUPPORTED_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".csv", ".pdf"}

#: Groups for the file dialog. Built from SUPPORTED_SUFFIXES so a newly supported
#: type can never be invisible in the picker.
DIALOG_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Packing lists", (".xlsx", ".xlsm", ".xls", ".csv", ".pdf")),
    ("Excel files", (".xlsx", ".xlsm", ".xls")),
    ("CSV files", (".csv",)),
    ("PDF files", (".pdf",)),
)


def dialog_filetypes() -> list[tuple[str, str]]:
    """Tk-style ``(label, pattern)`` list for the open dialog."""
    types = [(label, " ".join(f"*{s}" for s in suffixes))
             for label, suffixes in DIALOG_GROUPS]
    types.append(("All files", "*.*"))
    return types


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def file_digest(path: Path, chunk: int = 1 << 20) -> str:
    """SHA-256 of a file's contents - used to skip duplicates."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def make_batch_dir(root: Path, when: datetime | None = None) -> Path:
    """Create a unique dated sub-folder for one Prepare run."""
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M%S")
    candidate = root / stamp
    counter = 2
    while candidate.exists():
        candidate = root / f"{stamp}-{counter}"
        counter += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def safe_filename(name: str) -> str:
    """Strip characters Windows does not allow in a file name."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "unnamed"


@dataclass
class CopiedFile:
    """One packing list after it has been taken into the work directory."""

    source: Path
    stored: Path
    digest: str
    copied: bool  # False when the source was already inside the work directory

    @property
    def display_name(self) -> str:
        return self.stored.name


def copy_into_batch(sources: list[Path], batch_dir: Path) -> list[CopiedFile]:
    """Copy ``sources`` into ``batch_dir`` and describe what happened.

    Raises ``FileNotFoundError`` if a source vanished and ``ValueError`` for an
    unsupported extension, so the caller can report precisely which file failed.
    """
    batch_dir = batch_dir.resolve()
    results: list[CopiedFile] = []
    seen: dict[str, str] = {}  # digest -> stored name, dedupe within the batch

    for raw in sources:
        src = Path(raw).expanduser()
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(f"File no longer exists: {src}")
        if not is_supported(src):
            allowed = ", ".join(sorted(SUPPORTED_SUFFIXES))
            raise ValueError(f"Unsupported file type '{src.suffix}' (allowed: {allowed})")

        src_resolved = src.resolve()
        digest = file_digest(src_resolved)

        if digest in seen:
            # Same contents already copied in this batch - do not duplicate.
            results.append(CopiedFile(src_resolved, batch_dir / seen[digest], digest, True))
            continue

        if batch_dir in src_resolved.parents or src_resolved.parent == batch_dir:
            results.append(CopiedFile(src_resolved, src_resolved, digest, False))
            seen[digest] = src_resolved.name
            continue

        target = batch_dir / safe_filename(src_resolved.name)
        counter = 2
        while target.exists():
            target = batch_dir / f"{safe_filename(src_resolved.stem)} ({counter}){src_resolved.suffix}"
            counter += 1

        shutil.copy2(src_resolved, target)  # copy2 keeps timestamps for auditing
        results.append(CopiedFile(src_resolved, target, digest, True))
        seen[digest] = target.name

    return results


def is_work_dir_writable(path: Path) -> tuple[bool, str]:
    """Check the work directory can actually be written to, with a reason."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, ""
    except OSError as exc:
        return False, str(exc)
