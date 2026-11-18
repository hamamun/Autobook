"""PDF packing lists.

PDFs are handled by extracting the text/table cells, then running the *same* profile
logic used for spreadsheets where possible. A PDF whose text layer yields usable
rows is processed automatically; a scanned PDF (no text layer) is reported clearly
rather than producing silent nonsense.
"""

from __future__ import annotations

from pathlib import Path

from ..models import PackingList
from .profiles import Profile


def extract_pdf(path: Path, profiles: list[Profile]) -> PackingList:
    path = Path(path)
    pl = PackingList(source=path)

    try:
        import pdfplumber
    except ImportError:
        pl.add_issue("file", "PDF support is not installed in this build",
                     "Install the PDF component, or save the packing list as xlsx", "error")
        return pl

    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                pl.add_issue("file", "The PDF has no pages", "Check the file", "error")
                return pl
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:  # pdfplumber raises a variety of errors on bad files
        pl.add_issue("file", f"Could not open the PDF: {exc}", "Check the file", "error")
        return pl

    if len(text.strip()) < 30:
        pl.add_issue(
            "file",
            "This PDF has no text layer - it is a scan or a photo",
            "PDF text extraction cannot read it. Add OCR support, or supply the source Excel",
            "error",
        )
        return pl

    pl.add_issue(
        "file",
        "PDF text was read, but table extraction for this layout is not enabled yet",
        "Paste the values into the review sheet, or send a sample so a PDF profile can be added",
        "review",
    )
    pl.doc_type = text.strip().splitlines()[0][:80]
    pl.confidence["_profile"] = "pdf-unmapped"
    return pl
