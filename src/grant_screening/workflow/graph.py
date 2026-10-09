"""Phase 7: the screening pipeline as a Microsoft Agent Framework workflow.

                       ┌──────────────► claims (D2 agent) ─┐
 intake ─► structure ─► rules ─┤ gate ok                           ├─► verify ─► decide ─► letter ─► officer
                       │       └──────────────► open risk (E1+E2) ─┘     (F1+F2)    (F3)     (G1)     (G2, HITL)
                       └── gate failed ─────────────────────────────────────────────► decide

Concepts shown here
  * executors and edges: each stage is an Executor; edges define the graph
  * conditional routing: the gate decides the next edge (early exit)
  * fan-out / fan-in: D2 and E run in parallel, then merge
  * checkpointing: FileCheckpointStorage after every superstep (resume after a crash)
  * human-in-the-loop: the officer step calls ctx.request_info and the run pauses
    until a response arrives, possibly in another process, days later

Workflow state is JSON (checkpointable) and never contains the PII mapping:
executors that need real identity reload it from the local intake cache.
"""
from __future__ import annotations

import asyncio
import copy
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from agent_framework import (
    Executor,
    FileCheckpointStorage,
    WorkflowBuilder,
    WorkflowContext,
    handler,
    response_handler,
)

from grant_screening import screening as S
from grant_screening.cache import CACHE_ROOT
from grant_screening.llm import Ledger, Usage
from grant_screening.rules import engine

CHECKPOINT_DIR = CACHE_ROOT / "checkpoints"
PII_DIR = CACHE_ROOT / "intake"


# ---------------------------------------------------------------------------
# State <-> case (JSON in the workflow, rich objects inside a stage)
# ---------------------------------------------------------------------------
def to_state(case: dict) -> dict:
    state = {k: v for k, v in case.items() if k not in ("pii", "ledger", "rulebook")}
    state["deadline"] = case["deadline"].isoformat()
    state["ledger"] = [asdict(u) for u in case["ledger"].entries]
    return json.loads(json.dumps(state, default=str, ensure_ascii=False))


def to_case(state: dict) -> dict:
    # Deep copy: parallel branches (D2 and E) receive the SAME state object. A shallow copy
    # let both append to one shared trace list, so each branch's steps were recorded twice.
    case = copy.deepcopy(state)
    case["deadline"] = date.fromisoformat(state["deadline"])
    case["rulebook"] = engine.load_rulebook(S.CALL_ID, case["deadline"], version=state["rulebook_version"])
    case["ledger"] = Ledger([Usage(**u) for u in state.get("ledger", [])])
    pii_file = PII_DIR / f"{state['application_id']}.pii.json"
    case["pii"] = json.loads(pii_file.read_text(encoding="utf-8")) if pii_file.exists() else {}
    return case


async def run_stage(state: dict, fn, **kw) -> dict:
    """Stages are synchronous (they call asyncio.run for agents), so run them in a worker thread."""
    def work():
        case = to_case(state)
        fn(case, **kw)
        return to_state(case)
    return await asyncio.to_thread(work)


# ---------------------------------------------------------------------------
# Human-in-the-loop messages
# ---------------------------------------------------------------------------
@dataclass
class ReviewRequest:
    application_id: str
    system_decision: str
    risk_level: str
    reasons: list[str]
    templates: list[str]
    letter: str | None


@dataclass
class OfficerDecision:
    officer: str
    action: str          # APPROVE | CORRECT | REJECT
    final_decision: str  # what the officer decides, e.g. OFFICER_REVIEW -> "RETURN_FOR_REVISION"
    note: str = ""


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------
class Intake(Executor):
    def __init__(self, intake_kw: dict | None = None):
        super().__init__(id="A_intake")
        self.intake_kw = intake_kw or {}

    @handler
    async def run(self, application_id: str, ctx: WorkflowContext[dict]) -> None:
        def work():
            case = S.new_case(application_id)
            S.stage_intake(case, **self.intake_kw)
            return to_state(case)
        await ctx.send_message(await asyncio.to_thread(work))


class Structure(Executor):
    def __init__(self):
        super().__init__(id="B_structure")

    @handler
    async def run(self, state: dict, ctx: WorkflowContext[dict]) -> None:
        await ctx.send_message(await run_stage(state, S.stage_structure))


class Rules(Executor):
    def __init__(self):
        super().__init__(id="C_rules")

    @handler
    async def run(self, state: dict, ctx: WorkflowContext[dict]) -> None:
        await ctx.send_message(await run_stage(state, S.stage_rules))


class ClaimAgent(Executor):
    def __init__(self, search=None):
        super().__init__(id="D2_claims")
        self.search = search

    @handler
    async def run(self, state: dict, ctx: WorkflowContext[dict]) -> None:
        out = await run_stage(state, S.stage_claim_agent, search=self.search)
        await ctx.send_message({"branch": "claims", "claims": out["claims"], "ledger": out["ledger"],
                                "trace": out["trace"][-1:]})


class OpenRisk(Executor):
    def __init__(self, search=None):
        super().__init__(id="E_open_risk")
        self.search = search

    @handler
    async def run(self, state: dict, ctx: WorkflowContext[dict]) -> None:
        out = await run_stage(state, S.stage_open_risk, search=self.search)
        await ctx.send_message({"branch": "risk", "base": state, "risk_flags": out["risk_flags"],
                                "investigations": out["investigations"], "ledger": out["ledger"],
                                "trace": out["trace"][-1:]})


class Verify(Executor):
    """Fan-in: merges the two parallel branches, then runs F1 + F2."""

    def __init__(self, search=None):
        super().__init__(id="F_verify")
        self.search = search

    @handler
    async def run(self, branches: list[dict], ctx: WorkflowContext[dict]) -> None:
        risk = next(b for b in branches if b["branch"] == "risk")
        claims = next(b for b in branches if b["branch"] == "claims")
        state = dict(risk["base"])
        base_len = len(state["ledger"])
        state["claims"] = claims["claims"]
        state["risk_flags"] = risk["risk_flags"]
        state["investigations"] = risk["investigations"]
        # each branch started from the same base ledger; keep base + both branches' new entries
        state["ledger"] = state["ledger"] + claims["ledger"][base_len:] + risk["ledger"][base_len:]
        state["trace"] = state["trace"] + claims["trace"] + risk["trace"]
        await ctx.send_message(await run_stage(state, S.stage_verify, search=self.search))


class Decide(Executor):
    def __init__(self):
        super().__init__(id="F3_decide")

    @handler
    async def run(self, state: dict, ctx: WorkflowContext[dict]) -> None:
        await ctx.send_message(await run_stage(state, S.stage_decide))


class Letter(Executor):
    def __init__(self):
        super().__init__(id="G1_letter")

    @handler
    async def run(self, state: dict, ctx: WorkflowContext[dict]) -> None:
        await ctx.send_message(await run_stage(state, S.stage_letter))


class Officer(Executor):
    """G2: AUTO_PASS goes straight through (spot-check later); everything else waits for a human.

    on_pending(state, request_id) publishes the case for the officer UI before pausing;
    on_final(state) writes the audit record and the final status.
    """

    def __init__(self, on_final=None, on_pending=None):
        super().__init__(id="G2_officer")
        self.on_final = on_final
        self.on_pending = on_pending

    @handler
    async def run(self, state: dict, ctx: WorkflowContext[Any, dict]) -> None:
        ctx.set_state("pending_case", state)
        if state["decision"]["decision"] == "AUTO_PASS":
            await self._finish(state, None, ctx)
            return
        d = state["decision"]
        request_id = f"review-{state['application_id']}-{uuid.uuid4().hex[:8]}"
        if self.on_pending:
            await asyncio.to_thread(self.on_pending, state, request_id)
        await ctx.request_info(
            ReviewRequest(state["application_id"], d["decision"], d["risk_level"], d["reasons"], d["templates"],
                          (state.get("letter") or {}).get("text")),
            OfficerDecision,
            request_id=request_id,
        )

    @response_handler
    async def on_review(self, original_request: ReviewRequest, response: OfficerDecision,
                        ctx: WorkflowContext[Any, dict]) -> None:
        await self._finish(ctx.get_state("pending_case"), response, ctx)

    async def _finish(self, state: dict, officer: OfficerDecision | None, ctx: WorkflowContext) -> None:
        state["officer"] = asdict(officer) if officer else {"action": "AUTO", "final_decision": "AUTO_PASS",
                                                            "officer": "system", "note": "örneklem denetimine açık"}
        if self.on_final:
            await asyncio.to_thread(self.on_final, state)
        await ctx.yield_output(state)


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
def view_from_state(state: dict) -> dict:
    """Public (PII-free) view of a workflow state, same shape as screening.public_view."""
    view = S.public_view(to_case(state))
    view["officer"] = state.get("officer")
    return view


def build(search=None, intake_kw: dict | None = None, on_final=None, on_pending=None,
          checkpoint_dir=CHECKPOINT_DIR):
    intake, structure, rules = Intake(intake_kw), Structure(), Rules()
    claims, risk, verify = ClaimAgent(search), OpenRisk(search), Verify(search)
    decide, letter, officer = Decide(), Letter(), Officer(on_final, on_pending)

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    # Checkpoints are deserialised only for allow-listed types (protection against
    # arbitrary-object deserialisation). Our HITL message types must be listed explicitly.
    storage = FileCheckpointStorage(checkpoint_dir, allowed_checkpoint_types=[
        f"{__name__}:ReviewRequest", f"{__name__}:OfficerDecision"])
    builder = WorkflowBuilder(name="grant-screening", description="Hibe başvurusu ön uygunluk taraması",
                              start_executor=intake, checkpoint_storage=storage,
                              output_executors=[officer])
    builder.add_chain([intake, structure, rules])
    # conditional routing: early exit after the gate ...
    builder.add_edge(rules, decide, condition=lambda s: s["gate_failed"])
    # ... otherwise two conditional edges = a conditional fan-out (both run in the same superstep)
    builder.add_edge(rules, claims, condition=lambda s: not s["gate_failed"])
    builder.add_edge(rules, risk, condition=lambda s: not s["gate_failed"])
    builder.add_fan_in_edges([claims, risk], verify)
    builder.add_chain([verify, decide, letter, officer])
    return builder.build()
