"""One-off dev script: generates a small, known-content PDF fixture
for testing pdf_parser.py. Run once; the output is committed so the
test is reproducible without reportlab being needed again later.
"""

from pathlib import Path

from reportlab.pdfgen import canvas

FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "sample.pdf"


def main() -> None:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(FIXTURE_PATH))
    c.drawString(100, 750, "PAGE ONE MARKER: The mitochondria is the powerhouse of the cell.")
    c.showPage()
    c.drawString(100, 750, "PAGE TWO MARKER: Local AI agents should ask permission before deleting files.")
    c.showPage()
    c.save()
    print(f"Fixture written to {FIXTURE_PATH}")


if __name__ == "__main__":
    main()
