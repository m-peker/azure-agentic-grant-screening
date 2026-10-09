"""Stage A end to end: PDF -> IntakeResult (what every later stage consumes).

  A1 layout      sections + budget table (Document Intelligence, cached)
  A2 integrity   hidden text (local) + Prompt Shields on visible paragraphs
  A3 blind       pseudonymise identity (Language PII + regex), mapping kept local

Output files (git-ignored):
  .cache/intake/<application_id>.json      safe to hand to LLM stages (no PII)
  .cache/intake/<application_id>.pii.json  pseudonym -> real value, code only
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from grant_screening.cache import CACHE_ROOT
from grant_screening.intake import integrity, layout, pii

OUT_DIR = CACHE_ROOT / "intake"
APPLICANT_SECTION = "Yürütücü Bilgileri"


@dataclass
class IntakeResult:
    application_id: str
    source_sha256: str
    page_count: int
    sections: list[dict]          # [{title, paragraphs:[{text,page,offset}]}], pseudonymised
    budget: dict | None
    integrity: dict
    pii_counts: dict[str, int]
    document_number: str | None = None   # the number printed on the form (letters quote this)
    document_title: str | None = None
    pdf_page_count: int = 0
    problems: list[str] | None = None    # stage problems: the reading itself is in doubt -> human

    def section_titles(self) -> list[str]:
        return [s["title"] for s in self.sections]


def run_intake(pdf_path: str | Path, *, shield: integrity.ShieldFn = integrity.cached_shield,
               use_language_pii: bool = True, save: bool = True) -> tuple[IntakeResult, dict[str, str]]:
    pdf_path = Path(pdf_path)
    raw = layout.analyze_layout(pdf_path)
    pdf_pages = layout.pdf_page_count(pdf_path.read_bytes())
    problems = []
    if len(raw["pages"]) < pdf_pages:
        # never let an unread page turn into "section missing" for the applicant
        problems.append(f"belgenin yalnızca {len(raw['pages'])}/{pdf_pages} sayfası okunabildi")

    # A1
    sections = layout.parse_sections(raw)
    budget = layout.parse_budget_table(raw)

    # A2 (on original visible text: identity does not matter for attack detection)
    visible = [(s.title, p.page, p.text) for s in sections for p in s.paragraphs]
    report = integrity.check_integrity(pdf_path, visible, shield=shield)

    # A3
    applicant = next((s.text for s in sections if s.title == APPLICANT_SECTION), "")
    all_texts = [p.text for s in sections for p in s.paragraphs]
    ps = pii.build_pseudonymizer(applicant, all_texts, use_language=use_language_pii)
    for s in sections:
        for p in s.paragraphs:
            p.text = ps.apply(p.text)

    result = IntakeResult(
        application_id=pdf_path.stem,
        source_sha256=hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        page_count=len(raw["pages"]),
        sections=[asdict(s) for s in sections],
        budget=budget.to_dict() if budget else None,
        integrity=report.to_dict(),
        pii_counts=ps.counts(),
        document_number=layout.application_number(raw),
        document_title=layout.document_title(raw),
        pdf_page_count=pdf_pages,
        problems=problems,
    )
    if save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / f"{result.application_id}.json").write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
        (OUT_DIR / f"{result.application_id}.pii.json").write_text(
            json.dumps(ps.mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return result, ps.mapping
