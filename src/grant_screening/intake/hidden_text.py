"""Stage A2 (local half): detect text a human reader cannot see.

Hidden text is the classic carrier for prompt injection against AI reviewers:
white-on-white, microscopic font size, or text placed outside the page box.
This detector inspects every character in the PDF text layer. It runs before any
model call and costs nothing. Its findings are combined with Azure AI Content
Safety Prompt Shields (the cloud half of A2), which judges *what* the text says.

Rule of thumb: this module answers "is it visible?", Prompt Shields answers
"is it an attack?". Either one is enough to raise the integrity flag.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pdfplumber

MIN_VISIBLE_FONT_SIZE = 4.0   # points; body text is ~10pt
NEAR_WHITE_THRESHOLD = 0.92   # 0 = black, 1 = white (per channel)
MIN_SPAN_CHARS = 8            # ignore isolated stray glyphs


@dataclass(frozen=True)
class HiddenSpan:
    page: int
    reasons: tuple[str, ...]
    text: str


def _is_near_white(color) -> bool:
    """pdfplumber colors: None, gray (g,), RGB (r,g,b) or CMYK (c,m,y,k)."""
    if color is None:
        return False
    if isinstance(color, (int, float)):
        color = (color,)
    values = tuple(float(v) for v in color)
    if len(values) in (1, 3):
        return min(values) >= NEAR_WHITE_THRESHOLD
    if len(values) == 4:  # CMYK: white means no ink at all
        return max(values) <= 1 - NEAR_WHITE_THRESHOLD
    return False


def _char_reasons(char: dict, page_width: float, page_height: float) -> tuple[str, ...]:
    reasons = []
    if char.get("size", 99) < MIN_VISIBLE_FONT_SIZE:
        reasons.append("tiny_font")
    if _is_near_white(char.get("non_stroking_color")):
        reasons.append("near_white_color")
    if char["x1"] < 0 or char["x0"] > page_width or char["bottom"] < 0 or char["top"] > page_height:
        reasons.append("outside_page")
    return tuple(reasons)


def find_hidden_text(pdf_path: str | Path) -> list[HiddenSpan]:
    """Return contiguous runs of invisible characters, grouped per page."""
    spans: list[HiddenSpan] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            run_text: list[str] = []
            run_reasons: set[str] = set()

            def flush():
                text = "".join(run_text).strip()
                if len(text) >= MIN_SPAN_CHARS:
                    spans.append(HiddenSpan(page_no, tuple(sorted(run_reasons)), text))
                run_text.clear()
                run_reasons.clear()

            for char in page.chars:
                reasons = _char_reasons(char, page.width, page.height)
                if reasons:
                    run_text.append(char["text"])
                    run_reasons.update(reasons)
                elif char["text"].isspace() and run_text:
                    run_text.append(char["text"])
                else:
                    flush()
            flush()
    return spans


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        found = find_hidden_text(path)
        print(f"{Path(path).name}: {len(found)} hidden span(s)")
        for s in found:
            print(f"  page {s.page} {list(s.reasons)}: {s.text[:90]}...")
