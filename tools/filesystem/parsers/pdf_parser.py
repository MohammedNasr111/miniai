"""Parses PDF files into per-page text, so chunks can carry accurate
page numbers for citation. Text-layer extraction only - scanned image
PDFs with no text layer will return empty strings per page; OCR is out
of scope for now.
"""

from pypdf import PdfReader


def parse_pdf(path: str) -> list[tuple[int, str]]:
    """Returns a list of (page_number, text) tuples, 1-indexed pages."""
    reader = PdfReader(path)
    return [
        (i + 1, page.extract_text() or "")
        for i, page in enumerate(reader.pages)
    ]
