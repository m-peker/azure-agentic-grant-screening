"""Phase 6 lesson: the same Investigator, published to Foundry Agent Service.

Local agent (runner.py)        definition lives in Python; every run sends instructions + tool schemas.
Hosted prompt agent (this file) definition is versioned in the Foundry project (visible in the portal);
                                runs reference it by name + version.

Function tools stay client-side in both cases: the service tells the client
"call read_section(...)", the client runs the Python function and returns the
result. That is why the budget middleware and the audit trail still work.

The pipeline uses the local agent by default (cheaper to iterate, fully
cached). This module exists to show hosting, versioning and the portal view.
"""
from __future__ import annotations

import asyncio
from datetime import date

from agent_framework import Agent
from agent_framework.foundry import FoundryAgent, FoundryChatClient, to_prompt_agent

from grant_screening import azure_clients as az
from grant_screening.agents.runner import INVESTIGATOR_BUDGET, INVESTIGATOR_TOOLS, Verdict, _verify
from grant_screening.agents.tools import SearchFn, ToolRun, build_tools
from grant_screening.llm import load_prompt

AGENT_NAME = "sorusturmaci"


def _local_definition(intake: dict, deadline: date, search: SearchFn) -> tuple[Agent, dict]:
    version, instructions = load_prompt("investigator")
    tools = build_tools(intake, deadline, search)
    client = FoundryChatClient(project_endpoint=az.project_endpoint(), model=az.chat_deployment(),
                               credential=az.credential())
    agent = Agent(client=client, name=AGENT_NAME, instructions=instructions,
                  tools=[tools[t] for t in INVESTIGATOR_TOOLS], default_options={"response_format": Verdict})
    return agent, {"prompt_version": version, "tools": tools}


def publish(intake: dict, deadline: date, search: SearchFn) -> str:
    """Create a new version of the prompt agent in the Foundry project. Returns the version."""
    agent, meta = _local_definition(intake, deadline, search)
    definition = to_prompt_agent(agent)
    details = az.project_client().agents.create_version(
        agent_name=AGENT_NAME, definition=definition,
        description="Soruşturmacı: açık risk doğrulama (read-only araçlar, 5 adım bütçe)",
        metadata={"prompt_version": meta["prompt_version"], "project": "grant-screening"},
    )
    return details.version


async def _run_hosted(version: str, task: str, intake: dict, deadline: date, search: SearchFn) -> dict:
    tools = build_tools(intake, deadline, search)
    run = ToolRun(budget=INVESTIGATOR_BUDGET)
    agent = FoundryAgent(project_endpoint=az.project_endpoint(), agent_name=AGENT_NAME, agent_version=version,
                         credential=az.credential(), tools=[tools[t] for t in INVESTIGATOR_TOOLS],
                         middleware=[run.middleware()],
                         function_invocation_configuration={"max_function_calls": INVESTIGATOR_BUDGET + 2})
    # The output schema is part of the published definition. Sending it again at run time
    # fails with 400 "Not allowed when agent is specified" (param: text), so parse the text.
    resp = await agent.run(task)
    try:
        value = Verdict.model_validate_json(resp.text).model_dump(mode="json")
    except Exception:  # noqa: BLE001 - malformed output is an UNRESOLVED verdict, not a crash
        value = {"verdict": "UNRESOLVED", "rationale": "yapılandırılmış yanıt ayrıştırılamadı", "evidence": []}
    usage = resp.usage_details or {}
    return {"result": value, "tool_calls": run.calls, "budget": INVESTIGATOR_BUDGET,
            "input_tokens": usage.get("input_token_count", 0), "output_tokens": usage.get("output_token_count", 0)}


def investigate_hosted(version: str, task: str, intake: dict, deadline: date, search: SearchFn) -> dict:
    return _verify(asyncio.run(_run_hosted(version, task, intake, deadline, search)), intake)
