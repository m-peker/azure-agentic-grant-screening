"""Screen proposals end to end (sequential orchestration) and compare with the golden set.

Usage:
  python scripts/screen.py MGA-2026-0147
  python scripts/screen.py --all
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grant_screening.screening import public_view, run_sequential, save  # noqa: E402

GOLDEN = json.loads((ROOT / "scenario" / "golden" / "expected_results.json").read_text(encoding="utf-8"))


def report(case: dict) -> bool:
    app = case["application_id"]
    gold = GOLDEN[app]
    view = public_view(case)
    d = view["decision"]
    exp_templates = set(gold["deficiency_templates"])
    got_templates = set(d["templates"])
    ok_decision = d["decision"] == gold["decision"].split(" ")[0]
    ok_templates = got_templates == exp_templates
    print(f"\n== {app}")
    print(f"   decision : {d['decision']:18} golden {gold['decision']:18} {'OK' if ok_decision else 'FAIL'}")
    print(f"   templates: {sorted(got_templates)}  {'OK' if ok_templates else 'FAIL, golden ' + str(sorted(exp_templates))}")
    for f in view.get("findings", []):
        print(f"   finding  : {f['id']:28} {f['status']:12} trusted={f['trusted']} template={f.get('template')}")
    print(f"   letter   : {view['letter']['mode']} (lock: {view['letter']['lock']})")
    c = view["cost"]
    print(f"   cost     : {c['llm_calls']} model calls, {c['input_tokens']}+{c['output_tokens']} tokens, "
          f"${c['usd_if_uncached']:.4f} uncached (${c['usd_billed']:.4f} billed now)")
    print(f"   saved    : {save(case).relative_to(ROOT)}")
    return ok_decision and ok_templates


def main() -> int:
    from grant_screening import telemetry

    ids = [k for k in GOLDEN if not k.startswith("_")] if "--all" in sys.argv else \
        [a for a in sys.argv[1:] if not a.startswith("--")]
    if not ids:
        print(__doc__)
        return 2
    if telemetry.setup():
        print("telemetry: Application Insights")
    results = [report(run_sequential(i)) for i in ids]
    telemetry.flush()
    print(f"\n{sum(results)}/{len(results)} proposals match the golden set (decision + templates)")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
