"""Phase 10: turn officer decisions into rulebook proposals.

Reads the audit trail (Cosmos DB 'audit' if configured, else .cache/audit.jsonl),
keeps the latest record per application, and counts agent findings that were
  * trusted (evidence verified by code, conclusion supported by the F2 judge), and
  * accepted by an officer (APPROVE or CORRECT).
A call section confirmed this way is a candidate for a code rule: next time it
is checked deterministically, cheaper and without an agent.

Usage: python scripts/feedback_report.py   ->  docs/feedback_report.md
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import grant_screening.azure_clients  # noqa: E402,F401  (loads .env)
from grant_screening import corpus  # noqa: E402
from grant_screening.audit import AUDIT_FILE  # noqa: E402

REPORT = ROOT / "docs" / "feedback_report.md"


def load_records() -> list[dict]:
    if os.environ.get("COSMOS_ENDPOINT"):
        from grant_screening import store

        return list(store.container("audit").query_items("SELECT * FROM c", enable_cross_partition_query=True))
    return [json.loads(line) for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def latest_per_application(records: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for r in sorted(records, key=lambda r: r["recorded_at"]):
        latest[r["application_id"]] = r
    return list(latest.values())


def main() -> None:
    records = latest_per_application(load_records())
    by_section: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        accepted = (r.get("officer") or {}).get("action") in ("APPROVE", "CORRECT")
        for f in r.get("findings", []):
            if not (f.get("trusted") and accepted):
                continue
            sections = {f.get("call_section")} - {None}
            sections |= {e["source"].split("-")[-1].replace("_", ".") for e in f.get("evidence", [])
                         if e["source"].startswith("MGA-2026-CALL")}
            for s in sections:
                by_section[s].append({"application": r["application_id"], "finding": f["id"],
                                      "note": (r.get("officer") or {}).get("note", "")})

    lines = ["# Geri bildirim raporu", "",
             f"Kaynak: {len(records)} başvurunun son denetim kaydı. Komut: `python scripts/feedback_report.py`", "",
             "Aşağıdaki çağrı maddeleri, kural kitabında kod kuralı olmadığı halde agent'lar tarafından bulunup "
             "kanıtı doğrulanan ve Program Uzmanı tarafından onaylanan bulgulara konu oldu. "
             "Bunlar kod kuralına dönüştürülmeye adaydır.", "",
             "| Çağrı maddesi | Onaylanan bulgu | Başvurular | Uzman notu |", "|---|---|---|---|"]
    from datetime import date

    for section, items in sorted(by_section.items()):
        chunk = corpus.find_section(section, date(2026, 9, 30))
        title = f"§{section}" + (f" — {chunk.content[:70]}…" if chunk else "")
        notes = "; ".join(sorted({i["note"] for i in items if i["note"]}))
        lines.append(f"| {title} | {len(items)} | {', '.join(sorted({i['application'] for i in items}))} | {notes} |")
    if not by_section:
        lines.append("| - | 0 | - | - |")
    lines += ["", "## Önerilen kural kitabı değişikliği", "",
              "Her aday madde için kural kitabının bir sonraki sürümüne bir kural eklenir. "
              "Sayısal ön koşullar kodla, anlamsal kısım alıntı zorunlu bir LLM kontrolüyle değerlendirilir. "
              "Bkz. `scenario/rulebook/eligibility_rulebook_v3.yaml`."]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
