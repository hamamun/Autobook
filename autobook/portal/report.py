"""The booking report: one row per PO, success or failure.

Written as its own tab of the data sheet so a run can be read at a glance. Every PO the
automation touched gets exactly one row, even when nothing could be filled - a PO that
silently disappears is worse than one that failed loudly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Outcomes, in the order they are worth reading.
STATUS_DONE = "Booking done"
#: A SKU of ours had no portal row. Nothing is submitted - a booking missing goods is
#: worse than a booking not made, because only the second one is obvious.
STATUS_INCOMPLETE = "Not submitted - SKU missing"
STATUS_NOT_DONE = "Not done"
STATUS_SKIPPED = "Skipped"
STATUS_NOT_FOUND = "PO not found"
STATUS_FAILED = "Failed"
STATUS_ABANDONED = "Abandoned"
STATUS_LEFT = "Left for manual"


@dataclass
class PoResult:
    """What happened to one PO."""

    po_no: str
    booking_no: str = ""
    status: str = STATUS_NOT_DONE
    portal_status: str = ""          # the status read back from the list after submit
    #: Rows filled on the portal.
    matched: int = 0
    #: Our rows with no portal row. These are skipped and expected on the report.
    skipped: list[str] = field(default_factory=list)
    #: Anything that went wrong, in plain words.
    problems: list[str] = field(default_factory=list)
    submitted: bool = False

    @property
    def ok(self) -> bool:
        return self.status == STATUS_DONE

    @property
    def incomplete(self) -> bool:
        return self.status == STATUS_INCOMPLETE

    def finish(self) -> "PoResult":
        """Settle the status from the evidence, rather than trusting the caller."""
        if self.status in {STATUS_SKIPPED, STATUS_NOT_FOUND, STATUS_LEFT,
                           STATUS_INCOMPLETE}:
            return self
        if self.problems:
            self.status = STATUS_FAILED
            return self
        if not self.submitted:
            self.status = STATUS_ABANDONED
            return self
        good = {"pending for confirmation", "booking confirmed"}
        if self.portal_status.strip().lower() in good:
            self.status = STATUS_DONE
        else:
            self.status = STATUS_NOT_DONE
        return self


@dataclass
class BookingReport:
    """All the PO results from one run."""

    results: list[PoResult] = field(default_factory=list)

    def add(self, result: PoResult) -> PoResult:
        self.results.append(result.finish())
        return self.results[-1]

    @property
    def done(self) -> list[PoResult]:
        return [r for r in self.results if r.ok]

    @property
    def failed(self) -> list[PoResult]:
        return [r for r in self.results if not r.ok]

    @property
    def incomplete(self) -> list[PoResult]:
        return [r for r in self.results if r.incomplete]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for result in self.results:
            out[result.status] = out.get(result.status, 0) + 1
        return out

    def summary_line(self) -> str:
        parts = [f"{count} {status.lower()}" for status, count in self.counts().items()]
        return ", ".join(parts) if parts else "nothing to report"
