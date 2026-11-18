"""Extraction entry point.

Turn one packing list file into a :class:`~autobook.models.PackingList`. Which
profile to apply is decided by matching text found in the document against the
profile's ``match`` rules, never by the file name alone.
"""

from __future__ import annotations

from pathlib import Path

from ..models import PackingList
from .profiles import Profile, load_profiles
from .spreadsheet import extract_with_profile


def sniff_kind(path: Path) -> str:
    """Coarse file kind used for dispatch: 'spreadsheet' or 'pdf'."""
    suffix = path.suffix.lower()
    if suffix in {".csv", ".xlsx", ".xlsm", ".xls"}:
        return "spreadsheet"
    if suffix == ".pdf":
        return "pdf"
    return "unknown"


def extract(path: Path, profiles: list[Profile] | None = None) -> PackingList:
    """Extract one file. Never raises for a layout mismatch - it reports it.

    The returned object always exists, so the caller can show the operator exactly
    why a file could not be used instead of dropping the file silently.
    """
    path = Path(path)
    kind = sniff_kind(path)

    if kind == "unknown":
        result = PackingList(source=path)
        result.add_issue("file", f"Unsupported file type '{path.suffix}'",
                         "Save as xlsx or pdf and add it again", "error")
        return result

    profiles = profiles if profiles is not None else load_profiles()

    if kind == "pdf":
        from .pdf import extract_pdf

        return extract_pdf(path, profiles)

    return extract_with_profile(path, profiles)
