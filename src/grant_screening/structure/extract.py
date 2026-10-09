"""Stage B: structuring.

B1 (LLM)  locates information: for every field, a paragraph id and a verbatim quote.
B2 (code) verifies every quote exists verbatim in that paragraph, then parses
          values (dates, months, amounts) FROM THE QUOTE. The model never
          produces a number that the rules use.

A field whose quote fails verification is marked `unverified` and its value is
dropped; the decision engine routes such proposals to a human (safe default).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from grant_screening.intake.layout import parse_amount
from grant_screening.llm import Ledger, data_block, structured_call

EXCLUDED_SECTIONS: set[str] = set()
# Text before the first heading (title, form table) is shown under this name. Lesson (real upload):
# excluding it hid the info table, so the model never saw the duration printed there.
PREAMBLE_LABEL = "Form bilgileri"


# ---------------------------------------------------------------------------
# B1 schema (what the model returns)
# ---------------------------------------------------------------------------
class Evidence(BaseModel):
    paragraph_id: str = Field(description="Paragraph id such as P12")
    quote: str = Field(description="Short verbatim quote from that paragraph")


class Leave(BaseModel):
    leave_type: Literal["parental", "long_term_sick"]
    evidence: Evidence


class ExceptionClaim(BaseModel):
    kind: Literal["preapproval", "call_reference", "other"]
    cited_id: str | None = Field(description="Pre-approval number, call section or announcement name")
    summary: str = Field(description="One sentence, what is claimed")
    evidence: Evidence


class Extraction(BaseModel):
    phd_date: Evidence | None
    duration: Evidence | None
    declared_total: Evidence | None
    leaves: list[Leave]
    leave_documents: Evidence | None
    exception_claims: list[ExceptionClaim]
    attachments: Evidence | None


# ---------------------------------------------------------------------------
# B2 result (what later stages use)
# ---------------------------------------------------------------------------
@dataclass
class VerifiedField:
    status: Literal["ok", "missing", "unverified", "unparsed"]
    value: object = None
    paragraph_id: str | None = None
    quote: str | None = None


@dataclass
class Structured:
    phd_date: VerifiedField
    duration_months: VerifiedField
    declared_total: VerifiedField
    leaves: list[dict] = field(default_factory=list)          # [{leave_type, months, status, quote}]
    leave_documents: VerifiedField | None = None
    exception_claims: list[dict] = field(default_factory=list)
    attachments: VerifiedField | None = None
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Paragraph numbering
# ---------------------------------------------------------------------------
def number_paragraphs(intake: dict) -> tuple[str, dict[str, dict]]:
    """Return the LLM-facing text and an index {P<n>: {section, text}}."""
    index: dict[str, dict] = {}
    lines: list[str] = []
    n = 0
    for s in intake["sections"]:
        if s["title"] in EXCLUDED_SECTIONS:
            continue
        lines.append(f"## {PREAMBLE_LABEL if s['title'] == '_preamble' else s['title']}")
        for p in s["paragraphs"]:
            n += 1
            pid = f"P{n}"
            index[pid] = {"section": s["title"], "text": p["text"]}
            lines.append(f"[{pid}] {p['text']}")
    return "\n".join(lines), index


# ---------------------------------------------------------------------------
# Parsers (code reads values from verified quotes)
# ---------------------------------------------------------------------------
DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
MONTH_YEAR_RANGE_RE = re.compile(r"(\d{1,2})[./](\d{4})\s*[–\-]\s*(\d{1,2})[./](\d{4})")
MONTHS_RE = re.compile(r"\b(\d{1,3})\s*ay\b", re.IGNORECASE)
AMOUNT_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?\s*(?:TL|₺)")


def parse_date(text: str) -> date | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    d, mth, y = map(int, m.groups())
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def parse_months(text: str) -> int | None:
    m = MONTHS_RE.search(text)
    return int(m.group(1)) if m else None


def parse_total(text: str) -> int | None:
    m = AMOUNT_RE.search(text)
    return parse_amount(m.group(0)) if m else None


def parse_leave_months(text: str) -> int | None:
    """'03.2019–09.2019' -> 6. Used for long-term sick leave (extension = duration)."""
    m = MONTH_YEAR_RANGE_RE.search(text)
    if not m:
        return None
    m1, y1, m2, y2 = map(int, m.groups())
    return (y2 - y1) * 12 + (m2 - m1)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def verify(ev: Evidence | None, index: dict[str, dict], parser=None) -> VerifiedField:
    if ev is None:
        return VerifiedField("missing")
    para = index.get(ev.paragraph_id)
    if para is None or _norm(ev.quote) not in _norm(para["text"]):
        # Accept the quote if it exists verbatim in ANY paragraph (wrong id is a minor error).
        hit = next((pid for pid, p in index.items() if _norm(ev.quote) in _norm(p["text"])), None)
        if hit is None:
            return VerifiedField("unverified", None, ev.paragraph_id, ev.quote)
        ev = Evidence(paragraph_id=hit, quote=ev.quote)
        para = index[hit]
    if parser is None:
        return VerifiedField("ok", None, ev.paragraph_id, ev.quote)
    # Parse from the quote first, then from the full paragraph (quote may be too short).
    value = parser(ev.quote)
    if value is None:
        value = parser(para["text"])
    status = "ok" if value is not None else "unparsed"
    return VerifiedField(status, value, ev.paragraph_id, ev.quote)


COUNT_RE = re.compile(r"\b(\d+)\s*adet\b", re.IGNORECASE)


def count_leaves(items: list[Leave], index: dict[str, dict], problems: list[str]) -> list[dict]:
    """The model says WHERE leaves are declared; code decides HOW MANY.

    Lesson (phase 8 evaluation): for "2 adet (03.2019–09.2019; 01.2022–07.2022)" the model
    returned one item in some trials and two in others, so the extension flipped between
    18 and 36 months and an eligible PI was rejected. Counting is arithmetic, so it is code:
    distinct date ranges in the cited paragraphs, cross-checked with an explicit "N adet".
    """
    leaves: list[dict] = []
    for leave_type in ("parental", "long_term_sick"):
        evid = [verify(lv.evidence, index) for lv in items if lv.leave_type == leave_type]
        if not evid:
            continue
        if any(v.status != "ok" for v in evid):
            leaves.append({"leave_type": leave_type, "months": None, "status": "unverified",
                           "paragraph_id": evid[0].paragraph_id, "quote": evid[0].quote})
            continue
        paragraphs = {v.paragraph_id: index[v.paragraph_id]["text"] for v in evid}
        ranges = sorted({m.group(0) for t in paragraphs.values() for m in MONTH_YEAR_RANGE_RE.finditer(t)})
        explicit = [int(m.group(1)) for t in paragraphs.values() for m in COUNT_RE.finditer(t)]
        count = len(ranges) or (explicit[0] if explicit else len(evid))
        if explicit and ranges and explicit[0] != len(ranges):
            problems.append(f"{leave_type} izin sayısı tutarsız: '{explicit[0]} adet' ama {len(ranges)} tarih aralığı")
        pid = evid[0].paragraph_id
        for i in range(count):
            period = ranges[i] if i < len(ranges) else None
            leaves.append({"leave_type": leave_type, "months": parse_leave_months(period) if period else None,
                           "status": "ok", "paragraph_id": pid, "quote": period or evid[0].quote,
                           "counted_by": "code"})
    return leaves


# ---------------------------------------------------------------------------
# Stage B entry point
# ---------------------------------------------------------------------------
def structure(intake: dict, ledger: Ledger | None = None) -> Structured:
    text, index = number_paragraphs(intake)
    raw = structured_call("B1-extract", "extract", data_block("BAŞVURU", text), Extraction, ledger=ledger)

    out = Structured(
        phd_date=verify(raw.phd_date, index, parse_date),
        duration_months=verify(raw.duration, index, parse_months),
        declared_total=verify(raw.declared_total, index, parse_total),
        leave_documents=verify(raw.leave_documents, index),
        attachments=verify(raw.attachments, index),
    )
    if isinstance(out.phd_date.value, date):
        out.phd_date.value = out.phd_date.value.isoformat()

    out.leaves = count_leaves(raw.leaves, index, out.problems)

    for c in raw.exception_claims:
        v = verify(c.evidence, index)
        out.exception_claims.append({"kind": c.kind, "cited_id": c.cited_id, "summary": c.summary,
                                     "status": v.status, "paragraph_id": v.paragraph_id, "quote": v.quote,
                                     "section": index.get(v.paragraph_id or "", {}).get("section")})

    for name in ("phd_date", "duration_months", "declared_total"):
        f = getattr(out, name)
        if f.status != "ok":
            out.problems.append(f"{name}: {f.status}")
    out.problems += [f"leave: {lv['status']}" for lv in out.leaves if lv["status"] not in ("ok", "unparsed")]
    out.problems += [f"claim {c['cited_id']}: {c['status']}" for c in out.exception_claims if c["status"] != "ok"]
    return out
