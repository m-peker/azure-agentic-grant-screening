"""Phase 8 evaluation: run the pipeline N times against the golden set and write a report.

Usage:
  python eval/run_eval.py --trials 3
  python eval/run_eval.py --trials 1 --report-only   # rebuild report from cached trials

Each trial uses a different GRANT_TRIAL salt, so model calls are sampled again while
deterministic services (Layout, Prompt Shields, PII, embeddings) are reused from cache.
Report: docs/eval_report.md (Markdown) and eval/results.json (raw).
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grant_screening import screening as S  # noqa: E402

GOLDEN = json.loads((ROOT / "scenario" / "golden" / "expected_results.json").read_text(encoding="utf-8"))
APP_IDS = [k for k in GOLDEN if not k.startswith("_")]
RULEBOOK = int(sys.argv[sys.argv.index("--rulebook") + 1]) if "--rulebook" in sys.argv else None
SUFFIX = f"_v{RULEBOOK}" if RULEBOOK else ""
REPORT = ROOT / "docs" / f"eval_report{SUFFIX}.md"
RAW = ROOT / "eval" / f"results{SUFFIX}.json"
if RULEBOOK:
    os.environ["GRANT_RULEBOOK"] = str(RULEBOOK)


def score(case: dict) -> dict:
    app = case["application_id"]
    gold = GOLDEN[app]
    view = S.public_view(case)
    d = view["decision"]
    exp, got = set(gold["deficiency_templates"]), set(d["templates"])
    text = "\n".join(p["text"] for s in view["intake"]["sections"] for p in s["paragraphs"])
    gr = gold["rule_results"]
    rules = [r for r in view["rule_results"] if r["rule_id"] in gr and r["status"] != "NOT_EVALUATED"]
    findings = view.get("findings", [])
    return {
        "application_id": app,
        "decision": d["decision"], "decision_ok": d["decision"] == gold["decision"].split(" ")[0],
        "templates_exact": exp == got,
        "tp": len(exp & got), "fp": len(got - exp), "fn": len(exp - got),
        "missed": sorted(exp - got), "extra": sorted(got - exp),
        "rules_ok": sum(r["status"] == gr[r["rule_id"]]["status"] for r in rules), "rules_total": len(rules),
        "rule_mismatches": [f"{r['rule_id']}: {r['status']} (golden {gr[r['rule_id']]['status']})"
                            for r in rules if r["status"] != gr[r["rule_id"]]["status"]],
        "integrity_ok": view["intake"]["integrity"]["flag"] == gold["integrity_flag"],
        "pii_leaks": [v for v in gold["pii_to_mask"] if v in text],
        "early_exit": view["gate_failed"],
        "llm_calls": view["cost"]["llm_calls"], "usd": view["cost"]["usd_if_uncached"],
        "rulebook": view["rulebook"]["version"],
        "agent_runs": len(findings),
        "agent_tool_calls": sum(len(f.get("tool_calls", [])) for f in findings),
        "critic_revisions": sum(max(len(f.get("rounds", [])) - 1, 0) for f in findings),
        "untrusted_findings": sum(1 for f in findings if not f["trusted"] and f["status"] not in ("DISMISSED", "SUPPORTED")),
    }


def run(trials: int) -> list[dict]:
    rows = []
    for t in range(trials):
        os.environ["GRANT_TRIAL"] = f"eval-{t}"
        for app in APP_IDS:
            row = score(S.run_sequential(app))
            row["trial"] = t
            rows.append(row)
            print(f"trial {t} {app}: {row['decision']:17} ok={row['decision_ok']} templates_exact={row['templates_exact']} "
                  f"${row['usd']:.4f}")
    os.environ.pop("GRANT_TRIAL", None)
    return rows


def pct(n: float, d: float) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def write_report(rows: list[dict]) -> str:
    trials = len({r["trial"] for r in rows})
    n = len(rows)
    tp, fp, fn = (sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))
    lines = [
        "# Değerlendirme raporu",
        "",
        f"Üretildi: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"Model: `{os.environ.get('CHAT_DEPLOYMENT', '?')}` · Kural kitabı: v{rows[0]['rulebook']} · Deneme: {trials} · Başvuru: {len(APP_IDS)}",
        "",
        "Komut: `python eval/run_eval.py --trials " + str(trials) + (f" --rulebook {RULEBOOK}" if RULEBOOK else "") + "`",
        "",
        "## Özet",
        "",
        "| Ölçüt | Sonuç |",
        "|---|---|",
        f"| Nihai karar doğru | {sum(r['decision_ok'] for r in rows)}/{n} ({pct(sum(r['decision_ok'] for r in rows), n)}) |",
        f"| Eksiklik şablonları birebir doğru | {sum(r['templates_exact'] for r in rows)}/{n} ({pct(sum(r['templates_exact'] for r in rows), n)}) |",
        f"| Şablon kesinliği (precision) | {pct(tp, tp + fp)} |",
        f"| Şablon duyarlılığı (recall) | {pct(tp, tp + fn)} |",
        f"| Kural sonucu doğru | {sum(r['rules_ok'] for r in rows)}/{sum(r['rules_total'] for r in rows)} |",
        f"| Bütünlük bayrağı doğru | {sum(r['integrity_ok'] for r in rows)}/{n} |",
        f"| Kimlik sızıntısı | {sum(len(r['pii_leaks']) for r in rows)} |",
        f"| Doğrulanamayan agent bulgusu (insana gitti) | {sum(r['untrusted_findings'] for r in rows)} |",
        f"| Eleştirmen düzeltme turu | {sum(r['critic_revisions'] for r in rows)} |",
        f"| Agent çalıştırması (toplam) | {sum(r['agent_runs'] for r in rows)} |",
        "",
        "## Başvuru bazında",
        "",
        "| Başvuru | Karar doğru | Şablon birebir | Kaçırılan şablon | Fazla şablon | Ort. model çağrısı | Ort. maliyet |",
        "|---|---|---|---|---|---|---|",
    ]
    for app in APP_IDS:
        rs = [r for r in rows if r["application_id"] == app]
        missed = sorted({m for r in rs for m in r["missed"]})
        extra = sorted({m for r in rs for m in r["extra"]})
        lines.append(
            f"| {app} | {sum(r['decision_ok'] for r in rs)}/{len(rs)} | {sum(r['templates_exact'] for r in rs)}/{len(rs)} | "
            f"{', '.join(missed) or '-'} | {', '.join(extra) or '-'} | "
            f"{statistics.mean(r['llm_calls'] for r in rs):.1f} | ${statistics.mean(r['usd'] for r in rs):.4f} |")
    early = [r["usd"] for r in rows if r["early_exit"]]
    full = [r["usd"] for r in rows if not r["early_exit"]]
    lines += [
        "",
        "## Maliyet",
        "",
        "| | Ortalama maliyet / başvuru |",
        "|---|---|",
        f"| Erken çıkış | ${statistics.mean(early):.4f} |" if early else "| Erken çıkış | - |",
        f"| Tam akış | ${statistics.mean(full):.4f} |" if full else "| Tam akış | - |",
        f"| Tüm başvurular | ${statistics.mean(r['usd'] for r in rows):.4f} |",
        "",
        "Maliyet, önbellek olmadan ödenecek tutardır (gpt-5.4-mini Global Standard fiyatlarıyla).",
        "Document Intelligence, Language ve Content Safety F0 kotasından karşılandığı için dahil değildir.",
    ]
    text = "\n".join(lines) + "\n"
    REPORT.write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    trials = int(sys.argv[sys.argv.index("--trials") + 1]) if "--trials" in sys.argv else 1
    if "--report-only" in sys.argv and RAW.exists():
        rows = json.loads(RAW.read_text(encoding="utf-8"))
    else:
        rows = run(trials)
        RAW.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + write_report(rows))
