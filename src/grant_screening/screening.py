"""All pipeline stages as small functions over one shared case dict.

The Agent Framework workflow (workflow/graph.py) wraps each function in an
executor; `run_sequential` runs the same functions in order for tests and
evaluation. One implementation, two orchestrations.

case keys
  application_id, pdf, deadline, rulebook, ledger
  intake            stage A output (pseudonymised)       -> LLM-safe
  pii               pseudonym -> real value               -> code only, never in prompts
  structured        stage B
  rule_results, gate_failed                               stage C (+ D1)
  claims            triaged claims (+ D2 verdicts)
  risk_flags, investigations                              stage E
  findings          verified agent findings (F1 + F2)
  decision          stage F3
  letter            stage G1
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from grant_screening.cache import CACHE_ROOT
from grant_screening.llm import Ledger
from grant_screening.rules import citations, decision, engine, exceptions
from grant_screening.telemetry import span, traced_stage

ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = ROOT / "scenario" / "proposals" / "pdf"
UPLOAD_DIR = ROOT / "data" / "uploads"   # proposals uploaded through the UI (git-ignored)


def pdf_path(application_id: str) -> Path:
    """Where the submitted PDF lives: an uploaded file first, then the scenario sample."""
    uploaded = UPLOAD_DIR / f"{application_id}.pdf"
    return uploaded if uploaded.exists() else PDF_DIR / f"{application_id}.pdf"
RESULT_DIR = CACHE_ROOT / "results"
CALL_ID = "MGA-2026"


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------
def new_case(application_id: str, screening_date: date | None = None, rulebook_version: int | None = None) -> dict:
    """Rulebook = highest version in force on the screening date (default: today).
    GRANT_RULEBOOK=<n> pins a version (evaluation compares v2 and v3)."""
    import os

    version = rulebook_version or (int(os.environ["GRANT_RULEBOOK"]) if os.environ.get("GRANT_RULEBOOK") else None)
    rb = engine.load_rulebook(CALL_ID, screening_date or date.today(), version)
    return {"application_id": application_id, "pdf": str(pdf_path(application_id)),
            "deadline": rb["application_deadline"], "rulebook": rb, "rulebook_version": rb["version"],
            "ledger": Ledger(), "trace": []}


def _trace(case: dict, stage: str, note: str = "") -> None:
    case["trace"].append({"stage": stage, "note": note})


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
@traced_stage("A")
def stage_intake(case: dict, **kw) -> dict:
    from grant_screening.intake.pipeline import run_intake

    result, mapping = run_intake(case["pdf"], **kw)
    case["intake"] = json.loads(json.dumps(result.__dict__, default=str))
    case["pii"] = mapping
    _trace(case, "A", f"integrity={result.integrity['flag']}")
    return case


@traced_stage("B")
def stage_structure(case: dict) -> dict:
    from grant_screening.structure.extract import structure

    case["structured"] = structure(case["intake"], case["ledger"]).to_dict()
    _trace(case, "B", f"problems={case['structured']['problems']}")
    return case


@traced_stage("C+D1")
def stage_rules(case: dict) -> dict:
    rb = case["rulebook"]
    results, gate_failed = engine.evaluate(case["intake"], case["structured"], rb)
    rules = {r["id"]: r for r in rb["rules"]}
    results = [exceptions.resolve_equipment_exception(r, rules[r.rule_id], case["structured"]["exception_claims"],
                                                      case["pii"], CALL_ID) for r in results]
    if not gate_failed:
        from grant_screening.rules.semantic import evaluate_semantic

        results = evaluate_semantic(results, rb, case["intake"], case["ledger"])
    results = engine.describe_all(results, rb)
    case["rule_results"] = [r.to_dict() for r in results]
    case["gate_failed"] = gate_failed
    case["claims"] = exceptions.triage_claims(case["structured"]["exception_claims"], rb, case["deadline"])
    _trace(case, "C+D1", f"rulebook=v{rb['version']} gate_failed={gate_failed}")
    return case


@traced_stage("D2")
def stage_claim_agent(case: dict, search=None) -> dict:
    from grant_screening.agents.runner import research_claim
    from grant_screening.search.index import search_call_docs

    for c in case["claims"]:
        if c["route"] == "needs_agent":
            out = research_claim(c, case["intake"], case["deadline"], search or search_call_docs, case["ledger"])
            c["agent"] = out
    _trace(case, "D2", f"claims_to_agent={sum(c['route'] == 'needs_agent' for c in case['claims'])}")
    return case


@traced_stage("E")
def stage_open_risk(case: dict, search=None) -> dict:
    from grant_screening.agents.runner import investigate
    from grant_screening.llm_stages.open_risk import scan
    from grant_screening.search.index import search_call_docs

    flags = scan(case["intake"], case["rulebook"], case["ledger"])
    groups: dict[str, dict] = {}
    for f in flags:
        g = groups.setdefault(f["call_section"], {"call_section": f["call_section"], "concerns": [], "quotes": []})
        g["concerns"].append(f["concern"])
        g["quotes"].append(f["quote"])
    case["risk_flags"] = flags
    case["investigations"] = [
        {"group": g, **investigate(g, case["intake"], case["deadline"], search or search_call_docs, case["ledger"])}
        for g in groups.values()
    ]
    _trace(case, "E", f"flags={len(flags)} investigations={len(groups)}")
    return case


MAX_CRITIC_ROUNDS = 1  # one revision after a NOT_SUPPORTED judgement, then a human decides


@traced_stage("F1+F2")
def stage_verify(case: dict, search=None) -> dict:
    """F1 (sources of code rules) + F2 (support of every agent conclusion), with one critic round."""
    from grant_screening.agents.runner import investigate, research_claim
    from grant_screening.llm_stages.claim_support import check_support
    from grant_screening.llm_stages.letter import load_templates
    from grant_screening.search.index import search_call_docs

    search = search or search_call_docs
    templates_by_section = {t["call_section"]: t["id"] for t in load_templates().values() if t.get("call_section")}
    case["source_problems"] = citations.check_rule_sources(case["rule_results"], case["deadline"])
    findings = []

    def judge(kind: str, positive: str, out: dict, call_section: str | None, origin: str, rerun) -> None:
        rounds = []
        for attempt in range(MAX_CRITIC_ROUNDS + 1):
            res = out["result"]
            if res["verdict"] != positive:
                rounds.append({"verdict": res["verdict"], "support": None,
                               "evidence_problems": res.get("evidence_problems", [])})
                # F1 rejected the evidence of an otherwise positive verdict: give one chance to fix it
                if res.get("original_verdict") == positive and res.get("evidence_problems") \
                        and attempt < MAX_CRITIC_ROUNDS:
                    out = rerun("Şu kanıtlar kaynakta birebir doğrulanamadı: " + " | ".join(res["evidence_problems"]))
                    continue
                break
            support = check_support(res["rationale"], res["evidence"], case["ledger"])
            rounds.append({"verdict": res["verdict"], "support": support})
            if support["supported"] == "SUPPORTED" or attempt == MAX_CRITIC_ROUNDS:
                break
            out = rerun(support["reason"])  # critic -> revise
        res = out["result"]
        trusted = res["verdict"] == positive and rounds[-1]["support"] is not None \
            and rounds[-1]["support"]["supported"] == "SUPPORTED"
        sections = {call_section} if call_section else set()
        sections |= {e["source"].split("-")[-1].replace("_", ".") for e in res["evidence"] if e["source"] != "application"}
        template = next((templates_by_section[s] for s in sorted(sections) if s in templates_by_section), None)
        findings.append({"id": origin, "kind": kind, "status": res["verdict"], "trusted": trusted,
                         "rounds": rounds, "template": template if trusted else None,
                         "call_section": call_section, "rationale": res["rationale"],
                         "evidence": res["evidence"], "tool_calls": out.get("tool_calls", [])})

    for c in case.get("claims", []):
        if "agent" in c:
            judge("claim", "CONTRADICTED", c["agent"], None, f"claim:{c['section']}",
                  lambda fb, c=c: research_claim(c, case["intake"], case["deadline"], search, case["ledger"], fb))
    for inv in case.get("investigations", []):
        g = inv["group"]
        judge("open_risk", "CONFIRMED", inv, g["call_section"], f"risk:{g['call_section']}",
              lambda fb, g=g: investigate(g, case["intake"], case["deadline"], search, case["ledger"], fb))
    case["findings"] = findings
    _trace(case, "F1+F2", f"findings={len(findings)} source_problems={len(case['source_problems'])}")
    return case


@traced_stage("F3")
def stage_decide(case: dict) -> dict:
    cautions, seen = [], set()
    unresolved = []
    for f in case.get("findings", []):
        if f["status"] in ("DISMISSED", "SUPPORTED"):
            continue  # agent cleared it
        if not f["trusted"]:
            unresolved.append(f"{f['id']}: agent sonucu doğrulanamadı ({f['status']})")
        elif f.get("template") and f["template"] not in seen:
            seen.add(f["template"])
            cautions.append({"id": f["id"], "label": "DİKKAT", "template": f["template"]})
    problems = (case["intake"].get("problems") or []) + case["structured"]["problems"] \
        + case.get("source_problems", []) + unresolved
    d = decision.decide(integrity_flag=case["intake"]["integrity"]["flag"], gate_failed=case["gate_failed"],
                        rule_results=case["rule_results"], cautions=cautions, stage_problems=problems)
    case["cautions"] = cautions
    case["decision"] = d.to_dict()
    _trace(case, "F3", d.decision)
    return case


def _placeholders(case: dict, template_id: str) -> dict:
    for r in case["rule_results"]:
        if r.get("template") == template_id:
            return r["placeholders"]
    if template_id == "TPL-SERVICE-QUOTE":
        row = next((r for r in (case["intake"].get("budget") or {}).get("rows", []) if r["category"] == "hizmet"), None)
        return {"amount": engine.tl(row["amount"]) if row else "?"}
    return {}


@traced_stage("G1")
def stage_letter(case: dict) -> dict:
    from grant_screening.llm_stages.letter import render, write_letter

    if case["decision"]["decision"] == decision.INTEGRITY_REVIEW:
        # A manipulated document is not answered with a deficiency list: the officer handles
        # it under call section 7.1. Writing one would also tell the sender what got through.
        case["letter"] = {"text": None, "mode": "withheld", "lock": "n/a", "sentences": []}
        _trace(case, "G1", "withheld")
        return case
    sentences = [render(t, _placeholders(case, t)) for t in case["decision"]["templates"]]
    use_llm = not case["gate_failed"]  # early exit: code-only letter, no LLM spend
    # the applicant knows their proposal by the number printed on the form, not our upload id
    number = case["intake"].get("document_number") or case["application_id"]
    case["letter"] = write_letter(number, sentences, use_llm, case["ledger"])
    _trace(case, "G1", case["letter"]["mode"])
    return case


# ---------------------------------------------------------------------------
# Sequential orchestration (tests, evaluation)
# ---------------------------------------------------------------------------
def run_sequential(application_id: str, intake_kw: dict | None = None, search=None) -> dict:
    case = new_case(application_id)
    with span(f"screen {application_id}", **{"grant.application_id": application_id}) as root:
        stage_intake(case, **(intake_kw or {}))
        stage_structure(case)
        stage_rules(case)
        if not case["gate_failed"]:
            stage_claim_agent(case, search)
            stage_open_risk(case, search)
            stage_verify(case, search)
        stage_decide(case)
        stage_letter(case)
        cost = case["ledger"].summary()
        root.set_attribute("grant.decision", case["decision"]["decision"])
        root.set_attribute("grant.early_exit", case["gate_failed"])
        root.set_attribute("grant.llm_calls", cost["llm_calls"])
        root.set_attribute("grant.usd_if_uncached", cost["usd_if_uncached"])
    return case


def public_view(case: dict) -> dict:
    """What is stored and shown: everything except the PII mapping and live objects."""
    out = {k: v for k, v in case.items() if k not in ("pii", "ledger", "rulebook")}
    out["rulebook"] = {"id": case["rulebook"]["rulebook_id"], "version": case["rulebook"]["version"],
                       "file": case["rulebook"].get("_file")}
    out["deadline"] = case["deadline"].isoformat()
    out["cost"] = case["ledger"].summary()
    return json.loads(json.dumps(out, default=str, ensure_ascii=False))


def save(case: dict) -> Path:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULT_DIR / f"{case['application_id']}.json"
    path.write_text(json.dumps(public_view(case), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
