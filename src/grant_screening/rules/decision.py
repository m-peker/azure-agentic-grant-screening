"""Stage F3: decision engine. A fixed order of rules; no model, no judgement.

The order comes from the rulebook (decision.order) and is implemented here
literally, so the code and the document can be read side by side.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from grant_screening.rules.engine import NOT_EVALUATED, PASSING, UNRESOLVED, VIOLATION

INTEGRITY_REVIEW = "INTEGRITY_REVIEW"
INELIGIBLE = "INELIGIBLE"
OFFICER_REVIEW = "OFFICER_REVIEW"
AUTO_PASS = "AUTO_PASS"


@dataclass
class Decision:
    decision: str
    risk_level: str
    reasons: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def decide(*, integrity_flag: bool, gate_failed: bool, rule_results: list[dict],
           cautions: list[dict], stage_problems: list[str]) -> Decision:
    """cautions: confirmed open risks / contradicted claims: [{id, label, template}]"""
    violations = [r for r in rule_results if r["status"] == VIOLATION]
    unresolved = [r for r in rule_results if r["status"] == UNRESOLVED]
    high = [r for r in violations if r["severity"] == "HIGH"]
    medium = [r for r in violations if r["severity"] == "MEDIUM"]

    templates = [r["template"] for r in violations if r.get("template")]
    templates += [c["template"] for c in cautions if c.get("template")]
    d = Decision(decision=AUTO_PASS, risk_level="LOW",
                 violations=[r["rule_id"] for r in violations],
                 cautions=[c["id"] for c in cautions],
                 templates=list(dict.fromkeys(templates)))

    if high or integrity_flag:
        d.risk_level = "HIGH"
    elif medium or cautions:
        d.risk_level = "MEDIUM"

    # decision.order, first match wins
    if integrity_flag:
        d.decision = INTEGRITY_REVIEW
        d.reasons.append("gizli metin veya prompt injection (çağrı 7.1)")
    elif gate_failed:
        d.decision = INELIGIBLE
        d.reasons.append("uygunluk kapısı: " + ", ".join(r["rule_id"] for r in violations))
        d.templates = [r["template"] for r in violations if r.get("template")]
    elif stage_problems or unresolved:
        d.decision = OFFICER_REVIEW
        d.reasons += stage_problems + [f"{r['rule_id']}: {r['detail']}" for r in unresolved]
    elif high:
        d.decision = OFFICER_REVIEW
        d.reasons.append("istisnasız HIGH aykırılık: " + ", ".join(r["rule_id"] for r in high))
    elif medium or cautions:
        d.decision = OFFICER_REVIEW
        d.reasons.append("MEDIUM aykırılık veya doğrulanmış açık risk")
    else:
        d.reasons.append("tüm kurallar geçti, açık risk yok")

    if gate_failed and integrity_flag:
        d.reasons.append("ayrıca uygunluk kapısı başarısız")
    assert all(r["status"] in PASSING | {VIOLATION, UNRESOLVED, NOT_EVALUATED} for r in rule_results)
    return d
