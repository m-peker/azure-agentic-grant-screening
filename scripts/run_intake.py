"""Run stage A (intake & shield) and compare with the golden set.

Usage:
  python scripts/run_intake.py MGA-2026-0147     # smoke test, one proposal
  python scripts/run_intake.py --all
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grant_screening.intake.pipeline import run_intake  # noqa: E402

PDF_DIR = ROOT / "scenario" / "proposals" / "pdf"
GOLDEN = json.loads((ROOT / "scenario" / "golden" / "expected_results.json").read_text(encoding="utf-8"))


def check(app_id: str) -> bool:
    result, mapping = run_intake(PDF_DIR / f"{app_id}.pdf")
    gold = GOLDEN[app_id]
    text = "\n".join(p["text"] for s in result.sections for p in s["paragraphs"])
    leaked = [v for v in gold["pii_to_mask"] if v in text]
    budget_ok = True
    if "budget" in gold:
        b = result.budget or {}
        budget_ok = (b.get("by_category") == gold["budget"]["rows"]
                     and b.get("rows_sum") == gold["budget"]["rows_sum"])
    integrity_ok = result.integrity["flag"] == gold["integrity_flag"]

    print(f"\n== {app_id}  ({result.page_count} pages)")
    print(f"   sections     : {result.section_titles()}")
    if result.budget:
        print(f"   budget       : rows_sum={result.budget['rows_sum']:,}  "
              f"table_total={result.budget['total_row_amount']:,}  fragments={result.budget['fragments']}")
    for f in result.integrity["findings"]:
        print(f"   integrity    : {f['layer']} p{f['page']} [{f['detail']}] shield={f['shield_attack']} :: {f['text'][:60]}...")
    print(f"   checked paras: {result.integrity['paragraphs_checked']}")
    print(f"   pseudonyms   : {result.pii_counts}")
    print(f"   golden       : budget={'OK' if budget_ok else 'FAIL'}  "
          f"integrity={'OK' if integrity_ok else 'FAIL'}  pii_leaks={leaked or 'none'}")
    return budget_ok and integrity_ok and not leaked


def main() -> int:
    ids = [k for k in GOLDEN if not k.startswith("_")] if "--all" in sys.argv else sys.argv[1:]
    if not ids:
        print(__doc__)
        return 2
    results = [check(i) for i in ids]
    print(f"\n{sum(results)}/{len(results)} proposals match the golden set")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
