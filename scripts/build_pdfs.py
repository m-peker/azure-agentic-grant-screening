"""Render scenario proposals (Markdown) into PDFs for the intake stage (A).

Lines starting with '::hidden::' are rendered as white 1pt text: invisible to a
human reader but present in the PDF text layer. This simulates hidden prompt
injection aimed at AI reviewers (call section 7.1). '::pagebreak::' starts a new page.

Usage: python scripts/build_pdfs.py [file.md ...]   (no files: every MGA-*.md)
Output: scenario/proposals/pdf/<application_id>.pdf
Rebuilding an existing PDF changes its bytes, so its cached service results no longer apply.
"""
from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scenario" / "proposals"
OUT = SRC / "pdf"
FONT_DIR = Path("C:/Windows/Fonts")
HIDDEN = "::hidden::"
PAGEBREAK = "::pagebreak::"

pdfmetrics.registerFont(TTFont("Arial", str(FONT_DIR / "arial.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Bold", str(FONT_DIR / "arialbd.ttf")))

STYLES = {
    "h1": ParagraphStyle("h1", fontName="Arial-Bold", fontSize=14, leading=18, spaceAfter=8, alignment=1),
    "h2": ParagraphStyle("h2", fontName="Arial-Bold", fontSize=11, leading=14, spaceBefore=8, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Arial", fontSize=10, leading=13.5, spaceAfter=3),
    "hidden": ParagraphStyle("hidden", fontName="Arial", fontSize=1, leading=1.2, textColor="#FFFFFF"),
}


def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def split_front_matter(md: str) -> tuple[dict, str]:
    meta = {}
    if md.startswith("---"):
        _, head, body = md.split("---", 2)
        for line in head.strip().splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
        return meta, body
    return meta, md


def build(md_path: Path) -> Path:
    meta, body = split_front_matter(md_path.read_text(encoding="utf-8"))
    story, table_rows = [], []

    def flush_table():
        if not table_rows:
            return
        t = Table([[Paragraph(inline(c), STYLES["body"]) for c in r] for r in table_rows])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, "#888888"),
                               ("BACKGROUND", (0, 0), (-1, 0), "#EEEEEE")]))
        story.extend([t, Spacer(1, 6)])
        table_rows.clear()

    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                table_rows.append(cells)
            continue
        flush_table()
        if not line or line == "---":
            story.append(Spacer(1, 4))
        elif line == PAGEBREAK:
            story.append(PageBreak())
        elif line.startswith(HIDDEN):
            story.append(Paragraph(inline(line[len(HIDDEN):].strip()), STYLES["hidden"]))
        elif line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), STYLES["h1"]))
        elif line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), STYLES["h2"]))
        else:
            story.append(Paragraph(inline(line), STYLES["body"]))
    flush_table()

    OUT.mkdir(parents=True, exist_ok=True)
    app_id = meta.get("application_id", md_path.stem)
    out = OUT / f"{app_id}.pdf"
    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm,
                      topMargin=2 * cm, bottomMargin=2 * cm, title=app_id).build(story)
    return out


SAMPLES = ROOT / "scenario" / "upload_samples"

if __name__ == "__main__":
    import sys

    if "--samples" in sys.argv:  # PDFs for trying the upload feature
        OUT = SAMPLES
        for md in sorted(SAMPLES.glob("ornek-*.md")):
            print("built", build(md).relative_to(ROOT))
    else:
        files = [Path(a) for a in sys.argv[1:] if a.endswith(".md")] or sorted(SRC.glob("MGA-*.md"))
        for md in files:
            print("built", build(md.resolve()).relative_to(ROOT))
