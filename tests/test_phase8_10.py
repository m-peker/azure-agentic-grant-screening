"""Regression tests for lessons learned in phases 8-10 (all offline)."""
from datetime import date

from grant_screening.agents.runner import _verify
from grant_screening.rules import engine
from grant_screening.rules.semantic import SemanticCheck, evaluate_semantic
from grant_screening.structure import extract as ex
from test_extract import load

DEADLINE = date(2026, 9, 30)
LEAVE_TEXT = "Doğum / ebeveyn izni: 2 adet (03.2019-09.2019; 01.2022-07.2022), belgeler ektedir"
INDEX = {"P1": {"section": "Beyan Formu", "text": LEAVE_TEXT}}


def leave(pid="P1", quote="Doğum / ebeveyn izni: 2 adet"):
    return ex.Leave(leave_type="parental", evidence=ex.Evidence(paragraph_id=pid, quote=quote))


# --- leave counting is code, not model ------------------------------------
def test_one_or_two_model_items_give_the_same_count():
    one = ex.count_leaves([leave()], INDEX, [])
    two = ex.count_leaves([leave(), leave(quote="01.2022-07.2022")], INDEX, [])
    assert len(one) == len(two) == 2
    assert {lv["months"] for lv in one} == {6}


def test_inconsistent_leave_count_is_reported():
    index = {"P1": {"section": "Beyan Formu", "text": "Doğum izni: 3 adet (03.2019-09.2019; 01.2022-07.2022)"}}
    problems: list[str] = []
    ex.count_leaves([leave(quote="Doğum izni: 3 adet")], index, problems)
    assert problems and "tutarsız" in problems[0]


# --- asymmetric trust ------------------------------------------------------
def test_model_omission_cannot_reject_eligible_pi():
    intake = load("intake", "MGA-2026-0213")
    rb = engine.load_rulebook("MGA-2026", DEADLINE, version=2)
    structured = {"phd_date": {"status": "ok", "value": "2017-06-20"},
                  "duration_months": {"status": "ok", "value": 24},
                  "declared_total": {"status": "ok", "value": 1_200_000},
                  "leaves": [], "leave_documents": {"status": "missing"}}  # model returned no leaves
    results, gate = engine.evaluate(intake, structured, rb)
    elg = results[0]
    assert not gate and elg.status == engine.UNRESOLVED


def test_real_ineligibility_still_exits_early():
    intake = load("intake", "MGA-2026-0402")  # form says "Yok"
    assert not engine.declared_leave_mentioned(intake)


# --- rulebook versions -----------------------------------------------------
def test_rulebook_selection_by_screening_date_and_pin():
    assert engine.load_rulebook("MGA-2026", DEADLINE)["version"] == 2
    assert engine.load_rulebook("MGA-2026", date(2026, 10, 1))["version"] == 3
    assert engine.load_rulebook("MGA-2026", date(2026, 10, 1), version=2)["version"] == 2


def test_v3_covers_feedback_sections_so_scan_scope_shrinks():
    from grant_screening.llm_stages.open_risk import uncovered_sections

    v2 = {c.section for c in uncovered_sections(engine.load_rulebook("MGA-2026", DEADLINE, 2), DEADLINE)}
    v3 = {c.section for c in uncovered_sections(engine.load_rulebook("MGA-2026", DEADLINE, 3), DEADLINE)}
    assert {"4.6", "6.2"} <= v2 and not ({"4.6", "6.2"} & v3)


def test_semantic_precondition_skips_llm(monkeypatch):
    import grant_screening.rules.semantic as sem

    calls = []
    monkeypatch.setattr(sem, "structured_call", lambda *a, **k: calls.append(a[0]) or SemanticCheck(
        applies=False, satisfied=None, reason="", evidence=[]))
    rb = engine.load_rulebook("MGA-2026", DEADLINE, version=3)
    intake = load("intake", "MGA-2026-0213")  # service line 30.000 TL < 100.000 TL
    pending = [engine.RuleResult("R-BUD-05", engine.UNRESOLVED, "MEDIUM", "x", detail=engine.SEMANTIC_PENDING)]
    out = evaluate_semantic(pending, rb, intake)
    assert out[0].status == engine.COMPLIANT and calls == []


def test_semantic_violation_needs_verified_quotes(monkeypatch):
    import grant_screening.rules.semantic as sem

    monkeypatch.setattr(sem, "structured_call", lambda *a, **k: SemanticCheck(
        applies=True, satisfied=False, reason="teklif yok",
        evidence=[ex.Evidence(paragraph_id="P1", quote="uydurma alıntı")]))
    rb = engine.load_rulebook("MGA-2026", DEADLINE, version=3)
    pending = [engine.RuleResult("R-ETH-01", engine.UNRESOLVED, "MEDIUM", "x", detail=engine.SEMANTIC_PENDING)]
    out = evaluate_semantic(pending, rb, load("intake", "MGA-2026-0388"))
    assert out[0].status == engine.UNRESOLVED  # fabricated quote -> human, not a violation


# --- tool results as evidence of absence -----------------------------------
def test_tool_result_evidence_is_checked_against_audit_trail():
    intake = load("intake", "MGA-2026-0147")
    out = {"result": {"verdict": "CONFIRMED", "rationale": "teklif yok",
                      "evidence": [{"source": "tool:find_term", "quote": "'fiyat teklifi' başvuruda geçmiyor."}]},
           "tool_calls": [{"tool": "find_term", "args": {}, "result": "'fiyat teklifi' başvuruda geçmiyor."}]}
    assert _verify(out, intake)["result"]["verdict"] == "CONFIRMED"
    forged = {"result": {"verdict": "CONFIRMED", "rationale": "x",
                         "evidence": [{"source": "tool:find_term", "quote": "hiç çağrılmamış sonuç"}]},
              "tool_calls": []}
    assert _verify(forged, intake)["result"]["verdict"] == "UNRESOLVED"
