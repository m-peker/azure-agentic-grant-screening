"""Phase 9: Azure Cosmos DB (serverless) as the shared store between pipeline and officer UI.

  results    latest public view of each application (what the officer sees)
  decisions  officer actions submitted in the web app, waiting to resume a paused workflow
  audit      immutable decision records (one per final decision)

Auth: Entra ID only (local auth is disabled on the account). Locally the az login
user, in the cloud the web app's managed identity, each with the built-in
"Cosmos DB Built-in Data Contributor" data-plane role.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache

from azure.cosmos import CosmosClient

DATABASE = "screening"


@lru_cache(maxsize=1)
def _db():
    from grant_screening.azure_clients import credential

    return CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=credential()).get_database_client(DATABASE)


def container(name: str):
    return _db().get_container_client(name)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_result(view: dict, status: str, request_id: str | None = None,
                  checkpoint_id: str | None = None) -> None:
    """status: PENDING_REVIEW | DONE"""
    doc = {
        "id": view["application_id"], "application_id": view["application_id"], "status": status,
        "updated_at": now(), "request_id": request_id, "checkpoint_id": checkpoint_id,
        "decision": view["decision"], "rule_results": view["rule_results"],
        "findings": [{k: f.get(k) for k in ("id", "kind", "status", "trusted", "template", "rationale", "evidence")}
                     for f in view.get("findings", [])],
        "integrity": {"flag": view["intake"]["integrity"]["flag"],
                      "layers": sorted({f["layer"] for f in view["intake"]["integrity"]["findings"]})},
        "letter": view.get("letter"), "cost": view.get("cost"), "officer": view.get("officer"),
        "rulebook": view.get("rulebook"), "trace": view.get("trace"),
        "timings": view.get("timings", {}), "early_exit": view.get("gate_failed", False),
        "title": _title(view), "facts": _facts(view),
        "document_number": view["intake"].get("document_number"),
        "stage_problems": view["intake"].get("problems") or [],
        "document": {"blob": f"{DOCUMENT_CONTAINER}/{view['application_id']}.pdf",
                     "pages": view["intake"].get("page_count"), "sha256": view["intake"].get("source_sha256")},
        # what the integrity layers found, so the officer can SEE the invisible content (escaped in the UI)
        "integrity_findings": [{"layer": f["layer"], "page": f["page"], "text": f["text"][:600]}
                               for f in view["intake"]["integrity"]["findings"]],
    }
    container("results").upsert_item(doc)


def _title(view: dict) -> str | None:
    for s in view["intake"]["sections"]:
        for p in s["paragraphs"]:
            if p["text"].startswith("Proje Başlığı:"):
                return p["text"].split(":", 1)[1].strip()
    return view["intake"].get("document_title")


def _facts(view: dict) -> dict:
    s = view.get("structured") or {}
    b = view["intake"].get("budget") or {}

    def val(name):
        f = s.get(name) or {}
        return f.get("value") if f.get("status") == "ok" else None

    return {"phd_date": val("phd_date"), "duration_months": val("duration_months"),
            "declared_total": val("declared_total"), "rows_sum": b.get("rows_sum"),
            "by_category": b.get("by_category", {}), "leaves": len(s.get("leaves", [])),
            "pages": view["intake"].get("page_count")}


DOCUMENT_CONTAINER = "proposals"


def _blob(app_id: str):
    from azure.storage.blob import BlobServiceClient

    from grant_screening.azure_clients import credential

    service = BlobServiceClient(os.environ["STORAGE_ACCOUNT_URL"], credential=credential(),
                                retry_total=2, connection_timeout=5, read_timeout=30)
    return service.get_blob_client(DOCUMENT_CONTAINER, f"{app_id}.pdf")


def upload_document(app_id: str, pdf_path) -> str | None:
    """Store the submitted PDF so officers can read it in the UI (cloud and local). Entra ID only."""
    if not os.environ.get("STORAGE_ACCOUNT_URL"):
        return None
    from azure.storage.blob import ContentSettings

    from pathlib import Path

    data = Path(pdf_path).read_bytes()
    _blob(app_id).upload_blob(data, overwrite=True, content_settings=ContentSettings(
        content_type="application/pdf", content_disposition=f'inline; filename="{app_id}.pdf"'))
    return f"{DOCUMENT_CONTAINER}/{app_id}.pdf"


def document_exists(app_id: str) -> bool:
    if not os.environ.get("STORAGE_ACCOUNT_URL"):
        return False
    try:
        return _blob(app_id).exists()
    except Exception:  # noqa: BLE001 - unreachable storage: treat as missing, caller decides
        return False


def download_document(app_id: str) -> bytes:
    return _blob(app_id).download_blob().readall()


def upsert_audit(record: dict) -> None:
    container("audit").upsert_item(record)


def pending_decisions() -> list[dict]:
    q = "SELECT * FROM c WHERE c.status = 'NEW'"
    return list(container("decisions").query_items(q, enable_cross_partition_query=True))


def mark_decision(doc: dict, status: str, note: str = "") -> None:
    doc = dict(doc, status=status, processed_at=now(), processing_note=note)
    container("decisions").upsert_item(doc)
