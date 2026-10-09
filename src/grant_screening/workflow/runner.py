"""Start, resume and sync screening workflows. Shared by the CLI and the local UI.

  start(app_id, on_event)   run until the officer step (pause) or the end (AUTO_PASS);
                            on_event receives live stage events for the UI
  resume(app_id, decision)  continue a paused run from its checkpoint
  sync()                    apply decisions submitted in the cloud UI (Cosmos 'decisions')
"""
from __future__ import annotations

import json
import os
from typing import Awaitable, Callable

from grant_screening.audit import record_final
from grant_screening.cache import CACHE_ROOT
from grant_screening.workflow.graph import OfficerDecision, build, view_from_state

RUNS = CACHE_ROOT / "workflow_runs.json"

# executor id -> (pipeline stage, label, kind)
STAGES = {
    "A_intake": ("A", "Alım ve kalkan", "code"),
    "B_structure": ("B", "Yapılandırma", "llm"),
    "C_rules": ("C", "Kural kapısı", "code"),
    "D2_claims": ("D2", "Kayıt Araştırmacı", "agent"),
    "E_open_risk": ("E", "Açık risk", "agent"),
    "F_verify": ("F", "Doğrulama", "llm"),
    "F3_decide": ("F3", "Karar motoru", "code"),
    "G1_letter": ("G1", "Eksiklik yazısı", "llm"),
    "G2_officer": ("G2", "Program Uzmanı", "human"),
}

EventFn = Callable[[dict], Awaitable[None]]


def cosmos_enabled() -> bool:
    import grant_screening.azure_clients  # noqa: F401  (loads .env)

    return bool(os.environ.get("COSMOS_ENDPOINT"))


def _runs() -> dict:
    return json.loads(RUNS.read_text(encoding="utf-8")) if RUNS.exists() else {}


def _save_runs(runs: dict) -> None:
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    RUNS.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")


def pending_runs() -> dict:
    return _runs()


def on_pending(state: dict, request_id: str) -> None:
    if cosmos_enabled():
        from grant_screening import store

        store.upsert_result(view_from_state(state), "PENDING_REVIEW", request_id=request_id)


def on_final(state: dict) -> None:
    record_final(state)
    if cosmos_enabled():
        from grant_screening import store

        store.upsert_result(view_from_state(state), "DONE")


def workflow():
    return build(on_final=on_final, on_pending=on_pending)


async def start(app_id: str, on_event: EventFn | None = None) -> dict:
    async def emit(e: dict) -> None:
        if on_event:
            await on_event(e)

    wf = workflow()
    stream = wf.run(app_id, stream=True)
    request = None
    async for ev in stream:
        t = getattr(ev, "type", None)
        ex_id = getattr(ev, "executor_id", None)
        if t in ("executor_invoked", "executor_completed") and ex_id in STAGES:
            stage, label, kind = STAGES[ex_id]
            await emit({"event": "started" if t == "executor_invoked" else "completed",
                        "stage": stage, "label": label, "kind": kind})
        elif t == "request_info":
            request = ev
        elif t == "failed" or t == "executor_failed":
            await emit({"event": "error", "detail": str(getattr(ev, "data", ""))[:300]})
    result = await stream.get_final_response()
    mark_submission(app_id, "SCREENED")
    outputs = result.get_outputs()
    if outputs:
        await emit({"event": "finished", "decision": outputs[0]["decision"]["decision"]})
        ensure_document_uploaded(app_id)  # after the user has the result: storage never delays it
        return {"status": "finished", "decision": outputs[0]["decision"]["decision"]}

    checkpoint_id = wf.get_last_checkpoint_id()
    runs = _runs()
    runs[app_id] = {"request_id": request.request_id, "checkpoint_id": checkpoint_id}
    _save_runs(runs)
    if cosmos_enabled():
        from grant_screening import store

        doc = store.container("results").read_item(app_id, partition_key=app_id)
        store.container("results").upsert_item(doc | {"checkpoint_id": checkpoint_id})
    await emit({"event": "paused", "decision": request.data.system_decision})
    ensure_document_uploaded(app_id)
    return {"status": "paused", "request_id": request.request_id, "checkpoint_id": checkpoint_id,
            "decision": request.data.system_decision}


def ensure_document_uploaded(app_id: str) -> None:
    """Make the PDF available to the cloud UI. Runs after screening: storage problems never delay it."""
    if not cosmos_enabled():
        return
    import sys

    from grant_screening import store
    from grant_screening.screening import pdf_path

    try:
        if not store.document_exists(app_id):   # uploads are already in Blob Storage
            store.upload_document(app_id, pdf_path(app_id))
    except Exception as exc:  # noqa: BLE001 - a storage hiccup must not affect the screening result
        print(f"warning: document upload failed for {app_id} ({type(exc).__name__}); "
              "re-run start to upload again", file=sys.stderr)


async def resume(app_id: str, decision: OfficerDecision, request_id: str | None = None,
                 checkpoint_id: str | None = None) -> dict:
    if not (request_id and checkpoint_id):
        pending = _runs().get(app_id)
        if not pending:
            raise LookupError(f"{app_id} için duraklatılmış bir akış yok")
        request_id, checkpoint_id = pending["request_id"], pending["checkpoint_id"]
    result = await workflow().run(checkpoint_id=checkpoint_id, responses={request_id: decision})
    runs = _runs()
    runs.pop(app_id, None)
    _save_runs(runs)
    return result.get_outputs()[0]


async def sync() -> list[str]:
    from grant_screening import store

    log = []
    for d in store.pending_decisions():
        app_id = d["application_id"]
        try:
            res = store.container("results").read_item(app_id, partition_key=app_id)
            if res.get("request_id") != d["request_id"] or not res.get("checkpoint_id"):
                store.mark_decision(d, "STALE", "request id does not match the paused run")
                log.append(f"STALE    : {app_id}")
                continue
            out = await resume(app_id, OfficerDecision(officer=d["officer"], action=d["action"],
                                                       final_decision=d["final_decision"], note=d.get("note", "")),
                               d["request_id"], res["checkpoint_id"])
            store.mark_decision(d, "APPLIED")
            log.append(f"APPLIED  : {app_id} by {out['officer']['officer']} -> {out['officer']['final_decision']}")
        except Exception as exc:  # noqa: BLE001 - one bad decision must not block the others
            store.mark_decision(d, "FAILED", str(exc)[:300])
            log.append(f"FAILED   : {app_id}: {exc}")
    return log or ["no new officer decisions"]


# ---------------------------------------------------------------------------
# Uploaded proposals (Cosmos 'submissions')
# ---------------------------------------------------------------------------
def mark_submission(app_id: str, status: str) -> None:
    if not cosmos_enabled():
        return
    from grant_screening import store

    try:
        doc = store.container("submissions").read_item(app_id, partition_key=app_id)
    except Exception:  # noqa: BLE001 - scenario samples have no submission record
        return
    store.container("submissions").upsert_item(doc | {"status": status, "updated_at": store.now()})


async def process_inbox(on_event: EventFn | None = None) -> list[str]:
    """Screen every uploaded proposal that is still NEW (used when uploads come from the cloud UI)."""
    from grant_screening import store
    from grant_screening.screening import UPLOAD_DIR

    log = []
    items = list(store.container("submissions").query_items(
        "SELECT * FROM c WHERE c.status = 'NEW'", enable_cross_partition_query=True))
    for s in items:
        app_id = s["application_id"]
        local = UPLOAD_DIR / f"{app_id}.pdf"
        try:
            if not local.exists():
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                local.write_bytes(store.download_document(app_id))
            mark_submission(app_id, "PROCESSING")
            out = await start(app_id, on_event)
            log.append(f"SCREENED : {app_id} -> {out['decision']}")
        except Exception as exc:  # noqa: BLE001 - one bad upload must not block the others
            mark_submission(app_id, "FAILED")
            log.append(f"FAILED   : {app_id}: {type(exc).__name__}: {exc}")
    return log or ["no new uploads"]
