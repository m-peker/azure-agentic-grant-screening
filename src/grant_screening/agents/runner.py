"""Stages D2 and E2: the two budgeted, read-only agents.

  D2 Kayıt Araştırmacı  claims that code could not decide   tools: search, announcement, registry   budget 3
  E2 Soruşturmacı       open-risk flags from E1             tools: section, term, attachments,
                                                                   budget line, search                  budget 5

Both return a structured verdict with evidence. Evidence quotes are verified
by code (stage F1) before the verdict is trusted; an unverifiable verdict is
downgraded to UNRESOLVED and the proposal goes to a human.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient

from grant_screening import azure_clients as az
from grant_screening.agents.tools import SearchFn, ToolRun, build_tools
from grant_screening.cache import cached_json, digest, trial_salt
from grant_screening.llm import Ledger, Usage, load_prompt
from grant_screening.rules.citations import check_evidence

INVESTIGATOR_TOOLS = ["read_section", "find_term", "list_attachments", "get_budget_line", "search_call_docs"]
RESEARCHER_TOOLS = ["search_call_docs", "get_announcement", "get_registry_entry"]
INVESTIGATOR_BUDGET = 5
RESEARCHER_BUDGET = 3


class EvidenceItem(BaseModel):
    source: str = Field(description="'application' for application text; the chunk id in [brackets] from "
                                    "search_call_docs, e.g. MGA-2026-CALL-v2-6_2; or 'tool:<tool_name>' to cite a "
                                    "tool result, e.g. a find_term result showing that a term does not occur")
    quote: str = Field(description="Verbatim quote from that source")


class Verdict(BaseModel):
    verdict: Literal["CONFIRMED", "DISMISSED", "UNRESOLVED"]
    rationale: str = Field(description="Two or three sentences in Turkish")
    evidence: list[EvidenceItem]


class ClaimVerdict(BaseModel):
    verdict: Literal["SUPPORTED", "CONTRADICTED", "UNRESOLVED"]
    rationale: str = Field(description="Two or three sentences in Turkish")
    evidence: list[EvidenceItem]


def _client(max_calls: int) -> FoundryChatClient:
    return FoundryChatClient(
        project_endpoint=az.project_endpoint(), model=az.chat_deployment(), credential=az.credential(),
        function_invocation_configuration={"max_function_calls": max_calls + 2, "max_iterations": max_calls + 3},
    )


async def _run_agent(name: str, prompt_name: str, task: str, tool_names: list[str], budget: int,
                     schema: type[BaseModel], intake: dict, deadline: date, search: SearchFn) -> dict:
    version, instructions = load_prompt(prompt_name)
    tools = build_tools(intake, deadline, search)
    run = ToolRun(budget=budget)
    agent = Agent(client=_client(budget), name=name, instructions=instructions,
                  tools=[tools[t] for t in tool_names], middleware=[run.middleware()])
    response = await agent.run(task, options={"response_format": schema})
    usage = response.usage_details or {}
    value = response.value.model_dump(mode="json") if response.value is not None else {
        "verdict": "UNRESOLVED", "rationale": "agent yapılandırılmış yanıt üretmedi", "evidence": []}
    return {"result": value, "tool_calls": run.calls, "budget": budget,
            "input_tokens": usage.get("input_token_count", 0), "output_tokens": usage.get("output_token_count", 0),
            "prompt_version": version}


def _run_cached(stage: str, name: str, prompt_name: str, task: str, tool_names: list[str], budget: int,
                schema: type[BaseModel], intake: dict, deadline: date, search: SearchFn,
                ledger: Ledger | None) -> dict:
    version, _ = load_prompt(prompt_name)
    key = digest("agent", trial_salt(), stage, az.chat_deployment(), prompt_name, version, str(budget), task,
                 json.dumps(intake["sections"], ensure_ascii=False, sort_keys=True))
    fresh = {"hit": True}

    def call() -> dict:
        fresh["hit"] = False
        return asyncio.run(_run_agent(name, prompt_name, task, tool_names, budget, schema, intake, deadline, search))

    out = cached_json("agents", key, call)
    if ledger is not None:
        ledger.add(Usage(stage, out["input_tokens"], out["output_tokens"], cached=fresh["hit"]))
    return out


def _norm(s: str) -> str:
    return " ".join(s.split())


def _verify(out: dict, intake: dict, fail_verdict: str = "UNRESOLVED") -> dict:
    """F1 for agent output. Sources: application text, a corpus chunk, or a recorded tool result.

    A tool result is valid evidence of ABSENCE ("'fiyat teklifi' başvuruda geçmiyor."): it is
    checked against the audit record of that run's tool calls, not against the application.
    """
    res = out["result"]
    items = [{"source": e["source"].strip("[] "), "quote": e["quote"]} for e in res["evidence"]]
    tool_items = [e for e in items if e["source"].startswith("tool:")]
    doc_items = [e for e in items if not e["source"].startswith("tool:")]
    problems = check_evidence([{"id": "agent", "evidence": doc_items}], intake)
    for e in tool_items:
        name = e["source"].split(":", 1)[1]
        if not any(c["tool"] == name and _norm(e["quote"]) in _norm(c["result"]) for c in out["tool_calls"]):
            problems.append(f"agent: alıntı araç sonucunda yok ({e['source']}): {e['quote'][:60]}")
    res["evidence"] = items
    res["evidence_problems"] = problems
    if problems or (not items and res["verdict"] not in ("UNRESOLVED",)):
        res["original_verdict"] = res["verdict"]
        res["verdict"] = fail_verdict  # safe default: an unproven verdict is not trusted
    return out


def _with_feedback(task: str, feedback: str | None) -> str:
    return task if not feedback else f"{task}\n\nDenetçi notu (önceki kararın kanıtları yetersiz bulundu): {feedback}"


def investigate(flag_group: dict, intake: dict, deadline: date, search: SearchFn,
                ledger: Ledger | None = None, feedback: str | None = None) -> dict:
    """flag_group: {call_section, concerns:[...], quotes:[...]}"""
    task = (f"İşaretlenen risk — çağrı maddesi {flag_group['call_section']}.\n"
            f"Şüpheler: " + " | ".join(flag_group["concerns"]) + "\n"
            f"Başvurudan alıntılar: " + " | ".join(flag_group["quotes"]) + "\n"
            f"Bu riskin gerçek olup olmadığını araştır ve karar ver.")
    out = _run_cached("E2-investigator", "Sorusturmaci", "investigator", _with_feedback(task, feedback),
                      INVESTIGATOR_TOOLS, INVESTIGATOR_BUDGET, Verdict, intake, deadline, search, ledger)
    return _verify(out, intake)


def research_claim(claim: dict, intake: dict, deadline: date, search: SearchFn,
                   ledger: Ledger | None = None, feedback: str | None = None) -> dict:
    task = (f"Başvurudaki iddia ({claim['section']} bölümü): \"{claim['quote']}\"\n"
            f"Özet: {claim['summary']}\n"
            f"Bu iddia, son başvuru tarihinde yürürlükte olan çağrı metni ve duyurularla destekleniyor mu?")
    out = _run_cached("D2-registry-researcher", "KayitArastirmaci", "registry_researcher",
                      _with_feedback(task, feedback), RESEARCHER_TOOLS, RESEARCHER_BUDGET, ClaimVerdict,
                      intake, deadline, search, ledger)
    return _verify(out, intake)
