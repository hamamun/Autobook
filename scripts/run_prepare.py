"""End-to-end run of the Prepare step against real sample files.

Usage::

    python scripts/run_prepare.py <file> [<file> ...] [--out DIR]

This is how the pipeline can be exercised without opening the window - useful for
testing on a machine where the GUI cannot run (CI, a server, this sandbox).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autobook.pipeline import PrepareError, prepare  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare packing lists into a data sheet")
    parser.add_argument("files", nargs="+", type=Path, help="packing list files")
    parser.add_argument("--work", type=Path, default=None, help="override work directory")
    parser.add_argument("--out", type=Path, default=None, help="override output directory")
    args = parser.parse_args(argv)

    try:
        result = prepare(args.files, work_root=args.work, out_dir=args.out)
    except PrepareError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Batch folder  : {result.batch_dir}")
    for item in result.copied:
        print(f"  copied      : {item.display_name}")
    for problem in result.problems:
        print(f"  not used    : {problem}")
    print(f"Files read    : {len(result.results)}  (clean: {result.ok_count})")
    for pl in result.results:
        print(f"  {pl.source.name}: {len(pl.cartons)} carton lines, {len(pl.issues)} note(s)")
        for issue in pl.issues:
            print(f"     [{issue.severity}] {issue.field}: {issue.problem}")
    print(f"Data sheet    : {result.data_sheet}")
    return 0 if result.data_sheet else 1


if __name__ == "__main__":
    raise SystemExit(main())
