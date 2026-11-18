"""Extraction entry point.

Turn one packing list file into a :class:`~autobook.models.PackingList`. Which
profile to apply is decided by matching text found in the document against the
profile's ``match`` rules, never by the file name alone.
"""

from __future__ import annotations

from pathlib import Path

from ..models import PackingList
from ..models import SkippedSheet
from .profiles import Profile, load_profiles
from .spreadsheet import extract_with_profile, has_content, survey_sheets


def sniff_kind(path: Path) -> str:
    """Coarse file kind used for dispatch: 'spreadsheet' or 'pdf'."""
    suffix = path.suffix.lower()
    if suffix in {".csv", ".xlsx", ".xlsm", ".xls"}:
        return "spreadsheet"
    if suffix == ".pdf":
        return "pdf"
    return "unknown"


def extract_all(path: Path, profiles: list[Profile] | None = None,
                skipped: list[SkippedSheet] | None = None) -> list[PackingList]:
    """Extract **every** packing list held in one file.

    A workbook can contain several packing-list tabs (one per style or PO) plus tabs
    that have nothing to do with packing lists. Each qualifying tab becomes its own
    :class:`PackingList` so totals are never merged across tabs. Hidden tabs are
    ignored and non-matching tabs are discarded.

    Always returns at least one object: if nothing qualifies, the single result
    carries the reason so the operator sees the file was not used.
    """
    path = Path(path)
    kind = sniff_kind(path)

    if kind == "unknown":
        result = PackingList(source=path)
        result.add_issue("file", f"Unsupported file type '{path.suffix}'",
                         "Save as xlsx or pdf and add it again", "error")
        return [result]

    profiles = profiles if profiles is not None else load_profiles()

    if kind == "pdf":
        from .pdf import extract_pdf

        return [extract_pdf(path, profiles)]

    report = skipped if skipped is not None else []

    survey = survey_sheets(path, profiles)
    if survey:
        for entry in survey:
            if entry.profile is None:
                report.append(SkippedSheet(path.name, entry.sheet_name, entry.reason))

    plan = [(entry.sheet_name, entry.profile) for entry in survey if entry.profile is not None]
    if not plan:
        # Nothing qualifies: one row explaining the file was not used.
        return [extract_with_profile(path, profiles)]

    results: list[PackingList] = []
    for name, profile in plan:
        pl = extract_with_profile(path, profiles, sheet_name=name, profile=profile)
        if has_content(pl):
            results.append(pl)
        else:
            # Matched on words alone but held no data - not a packing list.
            report.append(SkippedSheet(path.name, name,
                                       "matched the layout words but contained no "
                                       "packing-list data"))

    if not results:
        empty = extract_with_profile(path, profiles)
        empty.add_issue("file", "No sheet contained packing-list data",
                        "Check this is a packing list workbook", "error")
        return [empty]

    return results


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
