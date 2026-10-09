"""Stage E1: open risk scan — what the rulebook does NOT check.

Coverage gap is computed by CODE: call sections in force on the deadline minus
the sections the rulebook already evaluates. The model only compares the
application against those uncovered sections. This keeps the scan focused
(cheap, few false positives) and makes the gap explicit and auditable.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from grant_screening import corpus
from grant_screening.llm import Ledger, data_block, structured_call
from grant_screening.rules.citations import budget_line_text
from grant_screening.structure.extract import number_paragraphs, verify, Evidence

# Sections that are procedural / about the funder, not about the application.
NON_APPLICANT_SECTIONS = {"1.1", "8.1", "8.2", "7.1"}  # 7.1 is handled by stage A2
SAMPLES = 2


class RiskFlag(BaseModel):
    call_section: str = Field(description="Uncovered call section the application may conflict with, e.g. 6.2")
    concern: str = Field(description="One sentence")
    evidence: Evidence


class RiskScan(BaseModel):
    flags: list[RiskFlag]


def uncovered_sections(rulebook: dict, on: date) -> list[corpus.Chunk]:
    covered: set[str] = set()
    for r in rulebook["rules"]:
        covered |= {p.strip() for p in str(r["source"]["section"]).split("-")}
    return [c for c in corpus.load_corpus()
            if c.doc_id == "MGA-2026-CALL" and c.in_force(on)
            and c.section not in covered and c.section not in NON_APPLICANT_SECTIONS]


def budget_lines(intake: dict) -> tuple[str, dict[str, dict]]:
    """Budget rows as citable lines [B<n>]. Values come from Layout cells, not from a model."""
    lines, index = [], {}
    for i, r in enumerate((intake.get("budget") or {}).get("rows", []), start=1):
        bid = f"B{i}"
        text = budget_line_text(r)
        index[bid] = {"section": "Bütçe tablosu", "text": text}
        lines.append(f"[{bid}] {text}")
    return "\n".join(lines), index


def scan(intake: dict, rulebook: dict, ledger: Ledger | None = None) -> list[dict]:
    on = rulebook["application_deadline"]
    gap = uncovered_sections(rulebook, on)
    text, index = number_paragraphs(intake)
    budget_text, budget_index = budget_lines(intake)
    index |= budget_index
    # Lesson: the first version omitted the budget table (cells are not paragraphs)
    # and the scan could not see that a service line exceeded 100.000 TL.
    document = (data_block("KONTROL_EDILECEK_MADDELER", "\n".join(c.content for c in gap))
                + "\n\n" + data_block("BAŞVURU", text)
                + "\n\n" + data_block("BÜTÇE_TABLOSU", budget_text))
    # High-recall scanner, precise verifier: E1 runs SAMPLES independent samples and the
    # union of flags goes to the E2 agent + F2 judge, which filter false positives.
    # Lesson (phase 8): with one sample the ethics risk was missed in 1 of 3 trials.
    raw_flags = []
    for s in range(SAMPLES):
        raw_flags += structured_call("E1-open-risk", "open_risk", document, RiskScan, ledger=ledger, sample=s).flags

    gap_ids = {c.section for c in gap}
    flags, seen = [], set()
    for f in raw_flags:
        v = verify(f.evidence, index)
        if v.status != "ok" or f.call_section not in gap_ids:
            continue  # unverifiable quote or out-of-scope section: dropped, not trusted
        if (f.call_section, v.quote) in seen:
            continue
        seen.add((f.call_section, v.quote))
        flags.append({"call_section": f.call_section, "concern": f.concern,
                      "paragraph_id": v.paragraph_id, "quote": v.quote,
                      "section": index[v.paragraph_id]["section"]})
    return flags
