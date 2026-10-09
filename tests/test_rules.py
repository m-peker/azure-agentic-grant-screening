from datetime import date

import pytest

from conftest import APP_IDS, GOLDEN
from grant_screening.rules import citations, decision, engine, exceptions
from grant_screening.structure import extract as ex
from test_extract import load

DEADLINE = date(2026, 9, 30)


@pytest.fixture(scope="module")
def rulebook():
    return engine.load_rulebook("MGA-2026", DEADLINE)


def structured_for(app_id, monkeypatch):
    monkeypatch.setattr(ex, "structured_call",
                        lambda *a, **k: ex.Extraction.model_validate(load("extraction", app_id)))
    return ex.structure(load("intake", app_id)).to_dict()


def evaluate(app_id, rulebook, monkeypatch):
    intake = load("intake", app_id)
    s = structured_for(app_id, monkeypatch)
    results, gate = engine.evaluate(intake, s, rulebook)
    rules = {r["id"]: r for r in rulebook["rules"]}
    pii = {"[ORCID_1]": f"0000-0000-0000-{app_id[-4:]}"}  # synthetic ORCIDs follow this pattern
    results = [exceptions.resolve_equipment_exception(r, rules[r.rule_id], s["exception_claims"], pii, "MGA-2026")
               for r in results]
    return intake, s, [r.to_dict() for r in results], gate


@pytest.mark.parametrize("app_id", APP_IDS)
def test_rule_statuses_match_golden(app_id, rulebook, monkeypatch):
    _, _, results, _ = evaluate(app_id, rulebook, monkeypatch)
    gold = GOLDEN[app_id]["rule_results"]
    for r in results:
        if r["rule_id"] in gold:
            assert r["status"] == gold[r["rule_id"]]["status"], r["rule_id"]


def test_percentages_computed_by_code(rulebook, monkeypatch):
    _, _, results, _ = evaluate("MGA-2026-0147", rulebook, monkeypatch)
    by_id = {r["rule_id"]: r for r in results}
    assert by_id["R-BUD-02"]["value"] == 15.0
    assert by_id["R-BUD-02"]["placeholders"]["max_amount"] == "126.000"
    assert by_id["R-BUD-03"]["value"] == 33.13


def test_preapproval_from_other_call_is_rejected(rulebook, monkeypatch):
    _, _, results, _ = evaluate("MGA-2026-0147", rulebook, monkeypatch)
    exc = next(r for r in results if r["rule_id"] == "R-BUD-03")["exception"]
    assert exc["status"] == "INVALID" and "MGA-2025" in exc["reason"]


def test_leave_extension_makes_pi_eligible(rulebook, monkeypatch):
    _, _, results, _ = evaluate("MGA-2026-0213", rulebook, monkeypatch)
    elg = next(r for r in results if r["rule_id"] == "R-ELG-01")
    assert elg["status"] == engine.COMPLIANT_EXT and elg["limit"] == "2027-06-20"


def test_gate_failure_skips_remaining_rules(rulebook, monkeypatch):
    _, _, results, gate = evaluate("MGA-2026-0402", rulebook, monkeypatch)
    assert gate
    assert all(r["status"] == engine.NOT_EVALUATED for r in results[1:])


@pytest.mark.parametrize("app_id, cautions", [
    ("MGA-2026-0147", [{"id": "risk:4.6", "template": "TPL-SERVICE-QUOTE"}]),
    ("MGA-2026-0213", []),
    ("MGA-2026-0388", [{"id": "risk:6.2", "template": "TPL-ETHICS"}]),
    ("MGA-2026-0402", []),
    # R-ETH-01 is a semantic (model) rule, pending offline; its recorded outcome stands in as a caution
    ("MGA-2026-0519", [{"id": "R-ETH-01", "template": "TPL-ETHICS"}]),
    ("MGA-2026-0520", [{"id": "R-ETH-01", "template": "TPL-ETHICS"}]),
])
def test_decision_and_templates_match_golden(app_id, cautions, rulebook, monkeypatch):
    intake, s, results, gate = evaluate(app_id, rulebook, monkeypatch)
    d = decision.decide(integrity_flag=GOLDEN[app_id]["integrity_flag"], gate_failed=gate,
                        rule_results=results, cautions=cautions, stage_problems=s["problems"])
    assert d.decision == GOLDEN[app_id]["decision"].split(" ")[0]
    assert set(d.templates) == set(GOLDEN[app_id]["deficiency_templates"])


def test_claim_triage(rulebook, monkeypatch):
    claims = structured_for("MGA-2026-0147", monkeypatch)["exception_claims"]
    routes = {c["cited_id"]: c["route"] for c in exceptions.triage_claims(claims, rulebook, DEADLINE)}
    assert routes["4.3"] == "covered_by_rule"
    ethics = structured_for("MGA-2026-0388", monkeypatch)["exception_claims"]
    assert [c["route"] for c in exceptions.triage_claims(ethics, rulebook, DEADLINE)] == ["needs_agent"]


def test_rule_sources_are_in_force(rulebook, monkeypatch):
    _, _, results, _ = evaluate("MGA-2026-0147", rulebook, monkeypatch)
    assert citations.check_rule_sources(results, DEADLINE) == []
    stale = [{"rule_id": "X", "source": "MGA-2026-CALL v1 §9.9"}]
    assert citations.check_rule_sources(stale, DEADLINE)


def test_fabricated_corpus_quote_is_caught():
    f = [{"id": "agent", "evidence": [{"source": "MGA-2026-CALL-v2-4_3", "quote": "doğrudan giderlerin %15'ini"}]}]
    assert citations.check_evidence(f, load("intake", "MGA-2026-0147"))


def test_add_months_clips_to_month_end():
    assert engine.add_months(date(2020, 1, 31), 1) == date(2020, 2, 29)
