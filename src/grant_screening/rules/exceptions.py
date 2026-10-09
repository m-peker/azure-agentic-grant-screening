"""Stage D1: exception resolution by code.

The pre-approval registry is structured data, so it is queried, not searched.
Lookup uses the REAL ORCID from the pseudonym mapping: the model never sees it
and never needs to.

Claims that code cannot decide (an "other" claim, or a reference to a call
section that no code rule covers) are returned as `needs_agent` for stage D2.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from grant_screening import corpus
from grant_screening.rules.engine import COMPLIANT_EXC, VIOLATION, RuleResult

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "scenario" / "registry" / "preapproval_registry.json"


def load_registry() -> list[dict]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _real_orcid(pii_mapping: dict[str, str]) -> str | None:
    return next((v for k, v in pii_mapping.items() if k.startswith("[ORCID_")), None)


def resolve_equipment_exception(result: RuleResult, rule: dict, claims: list[dict],
                                pii_mapping: dict[str, str], call_id: str) -> RuleResult:
    """Apply Duyuru-2 pre-approvals to an R-BUD-03 violation."""
    if result.status != VIOLATION or "exception" not in rule:
        return result
    exc = rule["exception"]
    orcid = _real_orcid(pii_mapping)
    claimed = [c for c in claims if c["kind"] == "preapproval" and c["status"] == "ok"]
    claimed_ids = {c["cited_id"] for c in claimed if c["cited_id"]}
    registry = load_registry()

    valid = [e for e in registry if e["rule_id"] == rule["id"] and e["call_id"] == call_id
             and e["applicant_orcid"] == orcid]
    if valid:
        entry = valid[0]
        if result.value <= min(entry["max_equipment_percent"], exc["max_with_exception"]):
            result.status = COMPLIANT_EXC
            result.exception = {"status": "VALID", "preapproval_id": entry["preapproval_id"],
                                "claimed_ids": sorted(claimed_ids), "resolved_by": "D1-code"}
        else:
            result.exception = {"status": "INVALID", "preapproval_id": entry["preapproval_id"],
                                "reason": f"ön onay sınırı %{entry['max_equipment_percent']} aşılıyor",
                                "resolved_by": "D1-code"}
        return result

    reasons = []
    for cid in sorted(claimed_ids):
        entry = next((e for e in registry if e["preapproval_id"] == cid), None)
        if entry is None:
            reasons.append(f"{cid} sicilde yok")
        elif entry["call_id"] != call_id:
            reasons.append(f"{cid} başka bir çağrıya ({entry['call_id']}) ait; Duyuru-2 uyarınca geçersiz")
        elif entry["applicant_orcid"] != orcid:
            reasons.append(f"{cid} başka bir başvuru sahibine ait")
    result.exception = {"status": "INVALID" if claimed_ids else "NOT_CLAIMED",
                        "claimed_ids": sorted(claimed_ids), "reason": "; ".join(reasons),
                        "resolved_by": "D1-code"}
    return result


def triage_claims(claims: list[dict], rulebook: dict, on: date) -> list[dict]:
    """Decide for each non-preapproval claim whether code covers it or an agent must look.

    covered_by_rule  the cited section is the source of a rule that code evaluates;
                     the code result already decides it. Current text is attached.
    needs_agent      no code rule covers it (e.g. ethics exemption claims).
    """
    rule_sections: dict[str, str] = {}
    for r in rulebook["rules"]:
        for part in str(r["source"]["section"]).split("-"):
            rule_sections[part.strip()] = r["id"]
    announcement_rules = {r["exception"]["source"]["announcement"]: r["id"]
                          for r in rulebook["rules"] if "exception" in r}

    out = []
    for c in claims:
        if c["kind"] == "preapproval":
            continue
        cited = (c.get("cited_id") or "").strip()
        current = corpus.find_section(cited, on) or corpus.find_announcement(cited, on) if cited else None
        rule_id = rule_sections.get(cited)
        if current is not None and current.section in announcement_rules:
            rule_id = announcement_rules[current.section]
        item = dict(c)
        if rule_id and current is not None:
            item.update(route="covered_by_rule", rule_id=rule_id, current_source=current.id,
                        current_text=current.content)
        else:
            item.update(route="needs_agent")
        out.append(item)
    return out
