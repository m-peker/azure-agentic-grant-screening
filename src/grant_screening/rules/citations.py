"""Stage F1: citation check. Fake or stale sources are caught here, by code.

Two checks:
  * every rule result cites a call section that exists AND is in force on the
    deadline (protects against a rulebook pointing at superseded text);
  * every quote attached to a finding exists verbatim in its claimed source
    (the application text or a corpus chunk).
"""
from __future__ import annotations

import re
from datetime import date

from grant_screening import corpus


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def check_rule_sources(results: list[dict], on: date) -> list[str]:
    problems = []
    for r in results:
        m = re.search(r"§(.+)$", r["source"])
        if not m:
            problems.append(f"{r['rule_id']}: kaynak biçimi okunamadı ({r['source']})")
            continue
        for section in m.group(1).split("-"):
            if corpus.find_section(section.strip(), on) is None:
                problems.append(f"{r['rule_id']}: §{section} son başvuru tarihinde yürürlükte değil")
    return problems


def budget_line_text(row: dict) -> str:
    """Canonical text of a budget row. The same string is shown to E1 and returned by agent tools,
    so a quote of a budget row can be verified like any paragraph."""
    amount = f"{row['amount']:,}".replace(",", ".") if row.get("amount") is not None else "?"
    return f"{row['label']} | {amount} TL | {row['justification']}"


def application_texts(intake: dict) -> list[str]:
    texts = [p["text"] for s in intake["sections"] for p in s["paragraphs"]]
    texts += [budget_line_text(r) for r in (intake.get("budget") or {}).get("rows", [])]
    return texts


def quote_in_application(quote: str, intake: dict) -> bool:
    q = _norm(quote)
    return bool(q) and any(q in _norm(t) for t in application_texts(intake))


def quote_in_corpus(quote: str, chunk_id: str) -> bool:
    chunk = next((c for c in corpus.load_corpus() if c.id == chunk_id), None)
    return chunk is not None and _norm(quote) in _norm(chunk.content)


def check_evidence(findings: list[dict], intake: dict) -> list[str]:
    """findings: [{id, evidence:[{source: 'application'|<chunk_id>, quote}]}]"""
    problems = []
    for f in findings:
        for ev in f.get("evidence", []):
            ok = (quote_in_application(ev["quote"], intake) if ev["source"] == "application"
                  else quote_in_corpus(ev["quote"], ev["source"]))
            if not ok:
                problems.append(f"{f['id']}: alıntı kaynakta yok ({ev['source']}): {ev['quote'][:60]}")
    return problems
