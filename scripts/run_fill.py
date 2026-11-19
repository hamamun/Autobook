"""Run the portal fill against a prepared data sheet.

Usage::

    python scripts/run_fill.py data_sheet_20261118-165648.xlsx [--submit]

Submits by default, like the window does. Use ``--dry-run`` to stop at the Review page
and book nothing, which is how to watch a fill work before trusting it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autobook.portal.session import fill_from_data_sheet  # noqa: E402
from autobook.settings import Settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fill the Maersk portal from a data sheet")
    parser.add_argument("data_sheet", type=Path)
    parser.add_argument("--dry-run", action="store_true",
                        help="stop at the Review page and submit nothing")
    parser.add_argument("--channel", default="msedge",
                        help="installed browser to drive (msedge, chrome)")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    settings = Settings.load()
    summary = fill_from_data_sheet(
        args.data_sheet,
        profile_dir=settings.browser_profile_dir(),
        stop_before_submit=args.dry_run,
        channel=args.channel,
        headless=args.headless,
    )
    for line in summary.lines:
        print(line)
    return 0 if not summary.report.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
