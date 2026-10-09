"""Audit trail: one immutable record per screening decision.

Phase 7: records are appended to a local JSONL file (.cache/audit.jsonl).
Phase 9: when COSMOS_ENDPOINT is set, records also go to Azure Cosmos DB
(serverless) with Entra ID auth, so the officer UI in the cloud can read them.

A record contains everything needed to reconstruct WHY a decision was made:
rule results with sources, agent findings with evidence and tool calls,
rulebook and prompt versions, model deployment, cost, and the officer's action.
It never contains the PII mapping.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from grant_screening.cache import CACHE_ROOT

AUDIT_FILE = CACHE_ROOT / "audit.jsonl"


def build_record(state: dict) -> dict:
    record = {
        "id": f"{state['application_id']}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
        "application_id": state["application_id"],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model_deployment": os.environ.get("CHAT_DEPLOYMENT"),
        "source_sha256": state["intake"]["source_sha256"],
        "system_decision": state["decision"],
        "officer": state.get("officer"),
        "rule_results": state["rule_results"],
        "findings": state.get("findings", []),
        "integrity": state["intake"]["integrity"],
        "letter": state.get("letter"),
        "trace": state.get("trace", []),
        "cost": _cost(state),
    }
    record["record_sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False)
                                             .encode("utf-8")).hexdigest()
    return record


def _cost(state: dict) -> dict:
    from grant_screening.llm import Ledger, Usage

    return Ledger([Usage(**u) for u in state.get("ledger", [])]).summary()


def record_final(state: dict) -> dict:
    record = build_record(state)
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    if os.environ.get("COSMOS_ENDPOINT"):
        from grant_screening.store import upsert_audit

        upsert_audit(record)
    return record
