import json
from pathlib import Path

import pytest

from grant_screening.intake.hidden_text import _is_near_white, find_hidden_text

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "scenario" / "proposals" / "pdf"
GOLDEN = json.loads((ROOT / "scenario" / "golden" / "expected_results.json").read_text(encoding="utf-8"))
APP_IDS = [k for k in GOLDEN if not k.startswith("_")]


@pytest.mark.parametrize("app_id", APP_IDS)
def test_integrity_flag_matches_golden(app_id):
    spans = find_hidden_text(PDF_DIR / f"{app_id}.pdf")
    assert bool(spans) == GOLDEN[app_id]["integrity_flag"]


def test_hidden_span_content_and_reasons():
    spans = find_hidden_text(PDF_DIR / "MGA-2026-0388.pdf")
    assert len(spans) == 1
    span = spans[0]
    assert "yapay zekâ sistemi" in span.text
    assert set(span.reasons) == {"near_white_color", "tiny_font"}


@pytest.mark.parametrize(
    "color, expected",
    [
        (None, False),
        ((0.0, 0.0, 0.0), False),
        ((1.0, 1.0, 1.0), True),
        ((0.95,), True),
        ((0.5,), False),
        ((0.0, 0.0, 0.0, 0.0), True),   # CMYK no ink = white
        ((0.0, 0.0, 0.0, 1.0), False),  # CMYK full black
    ],
)
def test_near_white(color, expected):
    assert _is_near_white(color) is expected
