import json
from pathlib import Path

import pytest

from conftest import APP_IDS, GOLDEN, ROOT
from grant_screening.structure import extract as ex

FIX = ROOT / "tests" / "fixtures"


def load(kind: str, app_id: str) -> dict:
    return json.loads((FIX / kind / f"{app_id}.json").read_text(encoding="utf-8"))


@pytest.fixture
def offline_llm(monkeypatch):
    """Replay the recorded model output instead of calling Foundry."""
    by_text = {ex.number_paragraphs(load("intake", a))[0]: a for a in APP_IDS}

    def fake_call(stage, prompt_name, document, schema, ledger=None, effort="low"):
        app_id = next(a for text, a in by_text.items() if text in document)
        return schema.model_validate(load("extraction", app_id))
    monkeypatch.setattr(ex, "structured_call", fake_call)


@pytest.mark.parametrize("app_id", APP_IDS)
def test_values_parsed_by_code_match_golden(offline_llm, app_id):
    s = ex.structure(load("intake", app_id))
    gold = GOLDEN[app_id]["rule_results"]
    assert s.phd_date.value == gold["R-ELG-01"]["phd_date"]
    if "R-DUR-01" in gold:
        assert s.duration_months.value == gold["R-DUR-01"]["value"]
    if "budget" in GOLDEN[app_id]:
        assert s.declared_total.value == GOLDEN[app_id]["budget"]["declared_total"]
    assert s.problems == []


def test_parental_leaves_found(offline_llm):
    s = ex.structure(load("intake", "MGA-2026-0213"))
    assert [lv["leave_type"] for lv in s.leaves] == ["parental", "parental"]
    assert s.leave_documents.status == "ok"


def test_claims_found(offline_llm):
    ids = {c["cited_id"] for c in ex.structure(load("intake", "MGA-2026-0147")).exception_claims}
    assert {"4.3", "ON-2025-031"} <= ids


def test_fabricated_quote_is_rejected():
    index = {"P1": {"section": "Beyan Formu", "text": "Proje süresi: 18 ay"}}
    v = ex.verify(ex.Evidence(paragraph_id="P1", quote="Proje süresi: 12 ay"), index, ex.parse_months)
    assert v.status == "unverified" and v.value is None


def test_wrong_paragraph_id_is_recovered():
    index = {"P1": {"section": "x", "text": "başka"}, "P2": {"section": "y", "text": "Proje süresi: 18 ay"}}
    v = ex.verify(ex.Evidence(paragraph_id="P1", quote="Proje süresi: 18 ay"), index, ex.parse_months)
    assert v.status == "ok" and v.paragraph_id == "P2" and v.value == 18


@pytest.mark.parametrize("text, expected", [
    ("Doktora derecesi alış tarihi: 11.02.2021", "2021-02-11"),
    ("tarih 31.02.2021", None),
    ("yok", None),
])
def test_parse_date(text, expected):
    d = ex.parse_date(text)
    assert (d.isoformat() if d else None) == expected


def test_parse_leave_months_and_total():
    assert ex.parse_leave_months("03.2019–09.2019") == 6
    assert ex.parse_total("Beyan edilen toplam bütçe: 1.449.000 TL") == 1_449_000
