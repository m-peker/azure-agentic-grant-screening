"""Shared fixtures. All tests run offline: no Azure calls, no credentials.

Layout results captured from Document Intelligence live in tests/fixtures/layout/.
Network-bound functions are replaced with deterministic fakes.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "layout"
PDF_DIR = ROOT / "scenario" / "proposals" / "pdf"
GOLDEN = json.loads((ROOT / "scenario" / "golden" / "expected_results.json").read_text(encoding="utf-8"))
APP_IDS = [k for k in GOLDEN if not k.startswith("_")]

INJECTION_MARKERS = ("yapay zekâ sistemi", "önceki tüm talimatları")


def load_layout(app_id: str) -> dict:
    return json.loads((FIXTURES / f"{app_id}.json").read_text(encoding="utf-8"))


def fake_shield(texts: list[str]) -> list[bool]:
    """Stand-in for Prompt Shields: flags text containing the known injection."""
    return [any(m in t.lower() for m in INJECTION_MARKERS) for t in texts]


def fake_language_entities(texts: list[str]) -> list[tuple[str, str]]:
    """Stand-in for Language PII: returns the applicant name from the form line."""
    found = []
    for t in texts:
        m = re.search(r"(?:Ad Soyad|Proje yürütücüsü):\s*(?:Dr\.\s*)?(.+)", t)
        if m:
            found.append(("KISI", m.group(1).strip()))
    return found


@pytest.fixture
def offline(monkeypatch):
    """Patch every network call used by stage A."""
    from grant_screening.intake import layout, pii

    monkeypatch.setattr(layout, "analyze_layout", lambda pdf: load_layout(Path(pdf).stem))
    monkeypatch.setattr(pii, "language_entities", fake_language_entities)
    return fake_shield
