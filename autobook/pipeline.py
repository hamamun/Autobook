"""The Prepare pipeline: copy files in, extract, write the data sheet.

This module is UI-agnostic and has no knowledge of tkinter, so it can be driven from
the window, from a test, or later from a command line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .booking import DEFAULT_SKU_SUFFIX
from .extract import extract_all
from .extract.profiles import load_profiles
from .models import PackingList, SkippedSheet
from .paths import output_dir, work_dir
from .workdir import CopiedFile, copy_into_batch, is_work_dir_writable, make_batch_dir
from .writer import write_workbook


class PrepareError(RuntimeError):
    """A failure the operator needs to read and act on."""


@dataclass
class PrepareResult:
    """Everything one Prepare click produced."""

    batch_dir: Path
    data_sheet: Path | None
    results: list[PackingList] = field(default_factory=list)
    copied: list[CopiedFile] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    #: Sheets that were looked at and not used. Reported only on the About tab.
    skipped: list[SkippedSheet] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for pl in self.results if not any(i.severity == "error" for i in pl.issues))

    @property
    def issue_count(self) -> int:
        return sum(len(pl.issues) for pl in self.results)


def prepare(files: list[Path],
            work_root: Path | None = None,
            out_dir: Path | None = None,
            profiles=None,
            sku_suffix: str = DEFAULT_SKU_SUFFIX,
            commodity_code: str = "",
            country_of_origin: str = "") -> PrepareResult:
    """Run the whole Prepare step for ``files``.

    Raises :class:`PrepareError` only when nothing at all can be done (no files,
    unwritable work directory). Per-file problems are collected as issues so one bad
    file never blocks the rest of the batch.
    """
    if not files:
        raise PrepareError("No packing lists were selected.")

    root = Path(work_root) if work_root else work_dir()
    writable, reason = is_work_dir_writable(root)
    if not writable:
        raise PrepareError(f"The working directory cannot be written to:\n{root}\n\n{reason}")

    batch_dir = make_batch_dir(root)

    copied: list[CopiedFile] = []
    problems: list[str] = []
    usable: list[Path] = []

    for item in files:
        try:
            batch = copy_into_batch([item], batch_dir)
            copied.extend(batch)
            usable.append(batch[0].stored)
        except (FileNotFoundError, ValueError, OSError) as exc:
            problems.append(f"{Path(item).name}: {exc}")

    results: list[PackingList] = []
    skipped: list[SkippedSheet] = []
    active_profiles = profiles if profiles is not None else load_profiles()
    for stored in usable:
        try:
            # A workbook may hold several packing-list tabs; each becomes its own row.
            results.extend(extract_all(stored, active_profiles, skipped))
        except Exception as exc:  # never let one malformed file abort the batch
            failed = PackingList(source=stored)
            failed.add_issue("file", f"Unexpected error while reading: {exc}",
                             "Check the file opens in Excel", "error")
            results.append(failed)

    data_sheet: Path | None = None
    if results:
        target_dir = Path(out_dir) if out_dir else output_dir()
        template = "data_sheet_{stamp}.xlsx"
        out_path = target_dir / template.format(stamp=datetime.now().strftime("%Y%m%d-%H%M%S"))
        counter = 2
        while out_path.exists():
            out_path = target_dir / template.format(
                stamp=f"{datetime.now():%Y%m%d-%H%M%S}-{counter}")
            counter += 1
        data_sheet = write_workbook(results, out_path,
                                    sku_suffix=sku_suffix,
                                    commodity_code=commodity_code,
                                    country_of_origin=country_of_origin,
                                    skipped=skipped)

    return PrepareResult(batch_dir=batch_dir, data_sheet=data_sheet,
                         results=results, copied=copied, problems=problems,
                         skipped=skipped)
