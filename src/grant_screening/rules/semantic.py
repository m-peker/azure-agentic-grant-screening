"""Stage C-semantic (rulebook v3+): rules whose requirement needs reading, not arithmetic.

  precondition  code   e.g. "a service line above 100.000 TL exists"; if false, no LLM call
  requirement   LLM    one structured call: applies? satisfied? + verbatim quotes
  verification  code   every quote must exist in the application; otherwise UNRESOLVED

Compared with the agent path (E1 scan -> E2 investigation -> F2 judge) this is a
single, cheaper, repeatable call, because the question is known in advance.
That is the point of the feedback loop: known risks graduate from agents to rules.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from grant_screening.llm import Ledger, data_block, structured_call
from grant_screening.llm_stages.open_risk import budget_lines
from grant_screening.rules.engine import COMPLIANT, SEMANTIC_PENDING, UNRESOLVED, VIOLATION, RuleResult, tl
from grant_screening.structure.extract import Evidence, number_paragraphs, verify


class SemanticCheck(BaseModel):
    applies: bool = Field(description="Does the requirement apply to this application?")
    satisfied: bool | None = Field(description="If it applies: is it satisfied? null if it cannot be decided")
    reason: str = Field(description="One or two sentences in Turkish")
    evidence: list[Evidence] = Field(description="Verbatim quotes (P<n> or B<n>) supporting applies and satisfied")


def _precondition(rule: dict, intake: dict) -> tuple[bool, dict]:
    pre = rule.get("precondition")
    if not pre:
        return True, {}
    rows = [r for r in (intake.get("budget") or {}).get("rows", [])
            if r["category"] == pre["budget_category"] and (r["amount"] or 0) > pre["amount_gt"]]
    return bool(rows), {"amount": tl(sum(r["amount"] for r in rows))} if rows else {}


def evaluate_semantic(results: list[RuleResult], rulebook: dict, intake: dict,
                      ledger: Ledger | None = None) -> list[RuleResult]:
    rules = {r["id"]: r for r in rulebook["rules"]}
    text, index = number_paragraphs(intake)
    budget_text, budget_index = budget_lines(intake)
    index |= budget_index
    for r in results:
        if r.detail != SEMANTIC_PENDING:
            continue
        rule = rules[r.rule_id]
        ok, placeholders = _precondition(rule, intake)
        r.placeholders = placeholders
        if not ok:
            r.status, r.detail = COMPLIANT, "ön koşul sağlanmıyor (kod): kural uygulanmaz"
            continue
        question = rule.get("applicability", "Bu gereklilik başvuruya uygulanır mı?")
        doc = (data_block("KURAL", f"Uygulanabilirlik: {question}\nGereklilik: {rule['requirement']}")
               + "\n\n" + data_block("BAŞVURU", text) + "\n\n" + data_block("BÜTÇE_TABLOSU", budget_text))
        check = structured_call(f"C-semantic-{r.rule_id}", "semantic_rule", doc, SemanticCheck, ledger=ledger)
        verified = [verify(ev, index) for ev in check.evidence]
        r.exception = None
        r.value = {"applies": check.applies, "satisfied": check.satisfied, "reason": check.reason,
                   "evidence": [{"paragraph_id": v.paragraph_id, "quote": v.quote, "status": v.status} for v in verified]}
        if not check.applies:
            r.status, r.detail = COMPLIANT, "kural uygulanmaz (LLM, alıntılı)"
            if verified and any(v.status != "ok" for v in verified):
                r.status, r.detail = UNRESOLVED, "uygulanmazlık kanıtı doğrulanamadı"
        elif not verified or any(v.status != "ok" for v in verified) or check.satisfied is None:
            r.status, r.detail = UNRESOLVED, "anlamsal kural: kanıt doğrulanamadı veya karar verilemedi"
        else:
            r.status = COMPLIANT if check.satisfied else VIOLATION
            r.detail = check.reason
    return results
