"""Phase 8: evaluate the Investigator agent with Foundry's built-in evaluators.

Three cases (two real risks, one false alarm that must be DISMISSED):
  MGA-2026-0147 / 4.6  service procurement without provider or quote  -> CONFIRMED
  MGA-2026-0388 / 6.2  retrospective patient data, "no ethics needed"  -> CONFIRMED
  MGA-2026-0213 / 6.2  plant-only project, flagged anyway              -> DISMISSED

The agent runs locally (same code as the pipeline); responses are sent to Foundry
evaluators (task adherence, tool call accuracy, intent resolution). The evaluation
run appears in the Foundry portal under Evaluations. Our own expected-verdict check
runs next to it, because generic evaluators cannot know the domain answer.

Usage: python eval/foundry_eval.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_framework import Agent, evaluate_agent  # noqa: E402
from agent_framework.foundry import FoundryChatClient, FoundryEvals  # noqa: E402

from grant_screening import azure_clients as az  # noqa: E402
from grant_screening.agents.runner import INVESTIGATOR_TOOLS, Verdict  # noqa: E402
from grant_screening.agents.tools import ToolRun, build_tools  # noqa: E402
from grant_screening.cache import CACHE_ROOT  # noqa: E402
from grant_screening.llm import load_prompt  # noqa: E402
from grant_screening.search.index import search_call_docs  # noqa: E402

DEADLINE = date(2026, 9, 30)
CASES = [
    ("MGA-2026-0147", "4.6", "180.000 TL hizmet alımında sağlayıcı belirtilmemiş ve teklif eklenmemiş olabilir.",
     "CONFIRMED"),
    ("MGA-2026-0388", "6.2", "Retrospektif hasta verisi kullanılıyor ama etik onay gerekmediği söyleniyor.",
     "CONFIRMED"),
    ("MGA-2026-0213", "6.2", "Projede insan kaynaklı veri kullanılıyor olabilir.", "DISMISSED"),
]
REPORT = ROOT / "docs" / "eval_foundry.md"


def task(section: str, concern: str) -> str:
    return (f"İşaretlenen risk — çağrı maddesi {section}.\nŞüpheler: {concern}\n"
            f"Bu riskin gerçek olup olmadığını araştır ve karar ver.")


async def main() -> int:
    _, instructions = load_prompt("investigator")
    client = FoundryChatClient(project_endpoint=az.project_endpoint(), model=az.chat_deployment(),
                               credential=az.credential())
    evals = FoundryEvals(client=client, evaluators=[FoundryEvals.TASK_ADHERENCE, FoundryEvals.TOOL_CALL_ACCURACY,
                                                    FoundryEvals.INTENT_RESOLUTION])
    lines = ["# Foundry değerlendirmesi — Soruşturmacı agent", "",
             "Komut: `python eval/foundry_eval.py`. Değerlendirme çalışmaları Foundry portalında, Evaluations altında görünür.",
             "", "| Başvuru | Madde | Beklenen | Agent | Araç çağrısı | Foundry sonucu |", "|---|---|---|---|---|---|"]
    ok_all = True
    for app, section, concern, expected in CASES:
        intake = json.loads((CACHE_ROOT / "intake" / f"{app}.json").read_text(encoding="utf-8"))
        tools = build_tools(intake, DEADLINE, search_call_docs)
        run = ToolRun(budget=5)
        agent = Agent(client=client, name="Sorusturmaci", instructions=instructions,
                      tools=[tools[t] for t in INVESTIGATOR_TOOLS], middleware=[run.middleware()],
                      default_options={"response_format": Verdict})
        query = task(section, concern)
        response = await agent.run(query)
        verdict = Verdict.model_validate_json(response.text).verdict
        results = await evaluate_agent(agent=agent, queries=[query], responses=[response], evaluators=evals,
                                       eval_name=f"sorusturmaci-{app}-{section}")
        r = results[0]
        summary = f"{r.passed}/{r.total} geçti"
        ok = verdict == expected
        ok_all &= ok
        lines.append(f"| {app} | {section} | {expected} | {verdict} {'✅' if ok else '❌'} | {len(run.calls)} | {summary} |")
        print(f"{app} {section}: expected {expected}, got {verdict} | tools={len(run.calls)} | foundry {summary}")
    lines += ["", "Foundry değerlendiricileri: task adherence, tool call accuracy, intent resolution (LLM-as-judge).",
              "Beklenen karar sütunu golden set'ten gelir ve kodla kontrol edilir."]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
