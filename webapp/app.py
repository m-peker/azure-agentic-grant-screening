"""Program Uzmanı arayüzü — FastAPI + Jinja2, data in Cosmos DB.

Two modes, one codebase:
  cloud (App Service)   review results and record decisions; `run_workflow.py sync` applies them
  local (scripts/ui.py) GRANT_UI_LOCAL=1: also screens incoming proposals in this process and
                        applies decisions immediately (the paused workflow resumes)

Security:
  * Cloud sign-in: Easy Auth + Entra ID, only assigned users; the officer name comes from
    the X-MS-CLIENT-PRINCIPAL-NAME header injected by Easy Auth.
  * No keys: Cosmos DB via managed identity (cloud) or az login (local).
  * Application text is untrusted: Jinja2 autoescaping renders injected markup as text.
  * CSRF: state-changing POSTs must come from this site (Origin/Referer check).
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

HERE = Path(__file__).resolve().parent
LOCAL = os.environ.get("GRANT_UI_LOCAL") == "1"
if LOCAL:
    sys.path.insert(0, str(HERE.parent / "src"))

app = FastAPI(title="Hibe Ön Uygunluk", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")

# ---------------------------------------------------------------------------
# Vocabulary (what the officer reads)
# ---------------------------------------------------------------------------
DECISIONS = {
    "AUTO_PASS": ("Uygun", "ok", "✓", "Tüm ön uygunluk koşulları karşılandı."),
    "OFFICER_REVIEW": ("Eksiklik var", "warn", "!", "Başvuruda giderilmesi gereken eksiklikler bulundu."),
    "INTEGRITY_REVIEW": ("Bütünlük sorunu", "bad", "⚑",
                         "Belgede değerlendirmeyi yönlendirmeye yönelik görünmez içerik bulundu."),
    "INELIGIBLE": ("Uygun değil", "bad", "✕", "Yürütücü uygunluk koşulunu sağlamıyor."),
}
STATUSES = {"PENDING_REVIEW": ("Karar bekliyor", "warn"), "DECISION_SUBMITTED": ("Uygulanıyor", "info"),
            "DONE": ("Tamamlandı", "ok")}
RULE_STATUS = {"COMPLIANT": ("Uygun", "ok"), "COMPLIANT_WITH_EXTENSION": ("Uygun", "ok"),
               "COMPLIANT_WITH_EXCEPTION": ("Uygun", "ok"), "VIOLATION": ("Karşılanmıyor", "bad"),
               "UNRESOLVED": ("Kontrol edin", "warn"), "NOT_EVALUATED": ("Değerlendirilmedi", "muted")}
FINALS = [
    ("RETURN_FOR_REVISION", "Eksiklik yazısı gönder", "Başvuru sahibinden düzeltme istenir."),
    ("FORWARD_TO_PANEL", "Bilimsel panele ilet", "Başvuru ön uygunluğu geçti."),
    ("REJECT_INELIGIBLE", "Uygun değil olarak kapat", "Yürütücü veya çağrı koşulu sağlanmıyor."),
    ("INTEGRITY_BOARD", "Bilimsel Dürüstlük Kurulu'na ilet", "Gizli içerik veya etik ihlali şüphesi."),
]
SUGGESTED = {"OFFICER_REVIEW": "RETURN_FOR_REVISION", "INTEGRITY_REVIEW": "INTEGRITY_BOARD",
             "INELIGIBLE": "REJECT_INELIGIBLE", "AUTO_PASS": "FORWARD_TO_PANEL"}
INTEGRITY_SENTENCE = ("Belgede insan gözüyle görülmeyen, değerlendirme sistemini yönlendirmeye yönelik bir "
                      "talimat bulunmuştur (Çağrı Metni madde 7.1).")
# Live progress during a screening, in plain language
STEPS = [("A", "Belge okunuyor ve güvenlik kontrolü yapılıyor"), ("B", "Başvuru bilgileri çıkarılıyor"),
         ("C", "Çağrı koşulları kontrol ediliyor"), ("D2", "Başvurudaki iddialar araştırılıyor"),
         ("E", "Ek riskler inceleniyor"), ("F", "Bulgular doğrulanıyor"), ("F3", "Öneri hazırlanıyor"),
         ("G1", "Eksiklik yazısı hazırlanıyor"), ("G2", "Uzman kararına sunuluyor")]


def tl(n) -> str:
    return f"{n:,} TL".replace(",", ".") if isinstance(n, (int, float)) else "—"


def date_tr(iso) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d.%m.%Y")
    except ValueError:
        return "—"


def when(iso) -> str:
    try:
        return datetime.fromisoformat(str(iso)).astimezone().strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return ""


def pick(table: dict, key, i: int, default: str = "") -> str:
    return table[key][i] if key in table else (default or str(key))


templates.env.globals.update(
    tl=tl, date_tr=date_tr, when=when, local_mode=LOCAL, finals=FINALS,
    decision_label=lambda d: pick(DECISIONS, d, 0), decision_kind=lambda d: pick(DECISIONS, d, 1, "muted"),
    decision_icon=lambda d: pick(DECISIONS, d, 2, "•"), decision_text=lambda d: pick(DECISIONS, d, 3, " "),
    status_label=lambda s: pick(STATUSES, s, 0), status_kind=lambda s: pick(STATUSES, s, 1, "muted"),
    rule_label=lambda s: pick(RULE_STATUS, s, 0), rule_kind=lambda s: pick(RULE_STATUS, s, 1, "muted"),
    final_label=lambda k: next((f[1] for f in FINALS if f[0] == k), k),
)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def db():
    if LOCAL:
        import grant_screening.azure_clients  # noqa: F401  (loads .env)
    return CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=DefaultAzureCredential()).get_database_client("screening")


def results():
    return db().get_container_client("results")


def officer_name(request: Request) -> str:
    return request.headers.get("x-ms-client-principal-name") or ("Program Uzmanı" if LOCAL else "Uzman")


def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"officer": officer_name(request), **ctx},
                                      status_code=status_code)


def same_origin(request: Request) -> bool:
    origin = request.headers.get("origin") or request.headers.get("referer")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    return bool(origin) and urlparse(origin).netloc == host


LAYER_LABELS = {"hidden_text": "Görünmeyen metin", "prompt_shields": "Talimat içeren metin",
                "metadata": "Belge özelliklerine gizlenmiş metin"}


def findings_for(r: dict) -> list[dict]:
    """'Tespitler': integrity first, then the approved deficiency sentences (same text the applicant gets)."""
    items = []
    if (r.get("integrity") or {}).get("flag"):
        quotes = [{"label": LAYER_LABELS.get(f["layer"], f["layer"]) + (f" · sayfa {f['page']}" if f.get("page") else ""),
                   "text": f["text"]} for f in r.get("integrity_findings") or []]
        items.append({"text": INTEGRITY_SENTENCE, "kind": "bad", "quotes": quotes})
    items += [{"text": s, "kind": "warn"} for s in (r.get("letter") or {}).get("sentences") or []]
    # what the system could not read reliably: shown to the officer, never sent to the applicant
    review = list(r.get("stage_problems") or [])
    review += [x.get("summary") or x.get("detail") for x in r.get("rule_results") or []
               if x["status"] == "UNRESOLVED" and (x.get("summary") or x.get("detail"))]
    items += [{"text": "Uzman kontrolü gerekli: " + t, "kind": "info"} for t in dict.fromkeys(review)]
    return items


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith(("/run/", "/static/", "/healthz")):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return render(request, "error.html", status_code=exc.status_code, code=exc.status_code, message=exc.detail)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, f: str = "pending"):
    items = list(results().query_items("SELECT * FROM c ORDER BY c.updated_at DESC", enable_cross_partition_query=True))
    counts = {
        "pending": sum(r["status"] in ("PENDING_REVIEW", "DECISION_SUBMITTED") for r in items),
        "done": sum(r["status"] == "DONE" for r in items),
        "integrity": sum(bool((r.get("integrity") or {}).get("flag")) for r in items),
    }
    shown = {"pending": [r for r in items if r["status"] in ("PENDING_REVIEW", "DECISION_SUBMITTED")],
             "done": [r for r in items if r["status"] == "DONE"]}.get(f, items)
    filters = [("pending", "Karar bekleyen", counts["pending"]), ("done", "Tamamlanan", counts["done"]),
               ("all", "Tümü", len(items))]
    return render(request, "dashboard.html", active="panel", items=shown, counts=counts, filters=filters, f=f)


@app.get("/a/{application_id}", response_class=HTMLResponse)
def detail(request: Request, application_id: str, saved: int = 0, error: str = ""):
    try:
        r = results().read_item(application_id, partition_key=application_id)
    except Exception:
        raise HTTPException(404, "Başvuru bulunamadı.")
    if not r.get("title"):  # e.g. an uploaded PDF without a "Proje Başlığı:" line: fall back to its file name
        sub = submission(application_id) or {}
        r["title"] = sub.get("title") or sub.get("filename")
    checks = [x for x in r["rule_results"] if x["status"] != "NOT_EVALUATED"]
    skipped = [x for x in r["rule_results"] if x["status"] == "NOT_EVALUATED"]
    passed = sum(x["status"].startswith("COMPLIANT") for x in checks)
    return render(request, "detail.html", active="panel", r=r, findings=findings_for(r), checks=checks,
                  skipped=skipped, passed=passed, suggested=SUGGESTED.get(r["decision"]["decision"]),
                  saved=bool(saved), error=error)


@lru_cache(maxsize=1)
def blob_service():
    from azure.storage.blob import BlobServiceClient

    # Fail fast: short timeouts and few retries, so a blocked network cannot freeze an upload for minutes
    return BlobServiceClient(os.environ["STORAGE_ACCOUNT_URL"], credential=DefaultAzureCredential(),
                             retry_total=2, connection_timeout=5, read_timeout=30)


def read_document(application_id: str) -> bytes | None:
    """The submitted PDF from Blob Storage (managed identity); local mode falls back to the scenario file."""
    if not re.fullmatch(r"[A-Z0-9-]{4,40}", application_id):
        return None
    if os.environ.get("STORAGE_ACCOUNT_URL"):
        try:
            return blob_service().get_blob_client("proposals", f"{application_id}.pdf").download_blob().readall()
        except Exception:  # noqa: BLE001 - not uploaded yet; try the local copy
            pass
    if LOCAL:
        for folder in (UPLOAD_DIR, HERE.parent / "scenario" / "proposals" / "pdf"):
            local = folder / f"{application_id}.pdf"
            if local.exists():
                return local.read_bytes()
    return None


@app.get("/a/{application_id}/document")
def document(application_id: str, download: int = 0):
    data = read_document(application_id)
    if data is None:
        raise HTTPException(404, "Belge bulunamadı.")
    disposition = "attachment" if download else "inline"
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'{disposition}; filename="{application_id}.pdf"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "frame-ancestors 'self'",   # may be embedded only by this site
        "Cache-Control": "private, max-age=300",
    })


@app.post("/a/{application_id}/decision")
def submit(request: Request, application_id: str, final_decision: str = Form(...), note: str = Form("")):
    if not same_origin(request):
        raise HTTPException(403, "Geçersiz istek kaynağı.")
    if final_decision not in {k for k, _, _ in FINALS}:
        raise HTTPException(400, "Geçersiz seçim.")
    r = results().read_item(application_id, partition_key=application_id)
    if r["status"] != "PENDING_REVIEW":
        raise HTTPException(409, "Bu başvuru karar beklemiyor.")
    suggested = SUGGESTED.get(r["decision"]["decision"])
    if final_decision != suggested and not note.strip():
        return RedirectResponse(f"/a/{application_id}?error=note", status_code=303)
    action = "APPROVE" if final_decision == suggested else "CORRECT"  # derived, never asked
    now = datetime.now(timezone.utc).isoformat()
    db().get_container_client("decisions").create_item({
        "id": uuid.uuid4().hex, "application_id": application_id, "request_id": r["request_id"],
        "officer": officer_name(request), "action": action, "final_decision": final_decision,
        "note": note.strip()[:2000], "status": "NEW", "submitted_at": now})
    results().upsert_item(r | {"status": "DECISION_SUBMITTED", "updated_at": now})
    if LOCAL:  # apply now: the paused workflow resumes (sync route = runs in a worker thread)
        apply_decisions_now()
    return RedirectResponse(f"/a/{application_id}?saved=1", status_code=303)


def apply_decisions_now() -> None:
    """Runs in a worker thread with its own event loop (the pipeline makes blocking SDK calls)."""
    from grant_screening.workflow import runner

    print("\n".join(asyncio.run(runner.sync())))


# ---------------------------------------------------------------------------
# Incoming proposals: upload (both modes) and live screening (local mode)
# ---------------------------------------------------------------------------
PROPOSAL_DIR = HERE.parent / "scenario" / "proposals"
UPLOAD_DIR = HERE.parent / "data" / "uploads"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PAGES = 30
UPLOAD_ERRORS = {
    "empty": "Dosya boş.",
    "size": "Dosya 10 MB sınırını aşıyor.",
    "type": "Dosya bir PDF değil. Yalnızca PDF yüklenebilir.",
    "broken": "PDF açılamadı; dosya bozuk olabilir.",
    "encrypted": "Şifreli PDF kabul edilmiyor.",
    "pages": f"Belge en fazla {MAX_PAGES} sayfa olabilir.",
    "duplicate": "Bu belge daha önce yüklenmiş.",
    "storage": "Belge depoya kaydedilemedi. Lütfen tekrar deneyin.",
}
SUBMISSION_STATUS = {"NEW": ("Sırada", "info"), "PROCESSING": ("İnceleniyor", "info"),
                     "FAILED": ("İncelenemedi", "bad")}
LIVE: dict[str, asyncio.Queue] = {}
ACTIVE: set[str] = set()


def submissions_container():
    return db().get_container_client("submissions")


def submission(app_id: str) -> dict | None:
    try:
        return submissions_container().read_item(app_id, partition_key=app_id)
    except Exception:  # noqa: BLE001
        return None


def validate_pdf(data: bytes) -> tuple[str | None, dict]:
    """Check the CONTENT, never the file name or the browser's content type."""
    if not data:
        return "empty", {}
    if len(data) > MAX_UPLOAD_BYTES:
        return "size", {}
    if b"%PDF-" not in data[:1024]:
        return "type", {}
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return "encrypted", {}
        pages = len(reader.pages)
        first_text = (reader.pages[0].extract_text() or "") if pages else ""
    except Exception:  # noqa: BLE001 - any parser failure means we cannot screen it
        return "broken", {}
    if not 1 <= pages <= MAX_PAGES:
        return "pages", {}
    m = re.search(r"Proje Başlığı:\s*(.+)", first_text)
    return None, {"pages": pages, "title": m.group(1).strip()[:200] if m else None}


def next_application_id() -> str:
    ids = submissions_container().query_items("SELECT VALUE c.application_id FROM c",
                                              enable_cross_partition_query=True)
    numbers = [int(x.rsplit("-", 1)[1]) for x in ids if x.rsplit("-", 1)[1].isdigit()]
    return f"MGA-2026-{max([5000, *numbers]) + 1}"


def scenario_proposals() -> list[dict]:
    out = []
    for md in sorted(PROPOSAL_DIR.glob("MGA-*.md")):
        text = md.read_text(encoding="utf-8")
        app_id = re.search(r"application_id:\s*(\S+)", text).group(1)
        title = re.search(r"\*\*Proje Başlığı:\*\*\s*(.+)", text)
        summary = re.search(r"## Özet\n(.+)", text)
        submitted = re.search(r"submitted:\s*(\S+)", text)
        out.append({"id": app_id, "title": title.group(1).strip() if title else app_id,
                    "summary": summary.group(1).strip() if summary else "",
                    "date": submitted.group(1) if submitted else None, "source": "sample"})
    return out


def uploaded_proposals() -> list[dict]:
    items = submissions_container().query_items("SELECT * FROM c ORDER BY c.uploaded_at DESC",
                                                enable_cross_partition_query=True)
    return [{"id": s["application_id"], "title": s.get("title") or s.get("filename") or s["application_id"],
             "summary": f"{s.get('filename', '')} · {s.get('pages', '?')} sayfa · yükleyen: {s.get('uploaded_by', '')}",
             "date": s.get("uploaded_at"), "source": "upload", "submission_status": s.get("status")}
            for s in items]


def known_ids() -> set[str]:
    samples = {p["id"] for p in scenario_proposals()} if LOCAL else set()
    return samples | {p["id"] for p in uploaded_proposals()}


@app.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request, uploaded: str = "", error: str = ""):
    uploads = uploaded_proposals()
    samples = scenario_proposals() if LOCAL else []
    for p in uploads + samples:
        try:
            p["status"] = results().read_item(p["id"], partition_key=p["id"])["status"]
        except Exception:  # noqa: BLE001 - not screened yet
            p["status"] = None
    return render(request, "inbox.html", active="inbox", uploads=uploads, samples=samples, steps=STEPS,
                  uploaded=uploaded, error=UPLOAD_ERRORS.get(error, ""), submission_status=SUBMISSION_STATUS,
                  max_pages=MAX_PAGES)


@app.post("/inbox/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    if not same_origin(request):
        raise HTTPException(403, "Geçersiz istek kaynağı.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    target = await asyncio.to_thread(store_upload, data, file.filename, officer_name(request))
    return RedirectResponse(target, status_code=303)


def store_upload(data: bytes, filename: str | None, officer: str) -> str:
    """Validate and store an uploaded PDF. Returns the redirect target. Runs in a worker thread."""
    error, meta = validate_pdf(data)
    if error:
        return f"/inbox?error={error}"
    sha = hashlib.sha256(data).hexdigest()
    duplicate = list(submissions_container().query_items(
        "SELECT c.id FROM c WHERE c.sha256 = @s", parameters=[{"name": "@s", "value": sha}],
        enable_cross_partition_query=True))
    if duplicate:
        return "/inbox?error=duplicate"

    app_id = next_application_id()
    stored_in_blob = False
    # Local mode keeps a local copy and lets the pipeline upload to Blob after screening, so the
    # upload returns instantly even on networks that block Blob Storage. The cloud must store now.
    if os.environ.get("STORAGE_ACCOUNT_URL") and not LOCAL:
        from azure.storage.blob import ContentSettings

        try:
            blob_service().get_blob_client("proposals", f"{app_id}.pdf").upload_blob(
                data, overwrite=False, content_settings=ContentSettings(
                    content_type="application/pdf", content_disposition=f'inline; filename="{app_id}.pdf"'))
            stored_in_blob = True
        except Exception as exc:  # noqa: BLE001
            print(f"blob upload failed for {app_id}: {type(exc).__name__}", file=sys.stderr)
    if LOCAL:  # the pipeline runs here: keep a local copy (also covers networks that block Blob Storage)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (UPLOAD_DIR / f"{app_id}.pdf").write_bytes(data)
    elif not stored_in_blob:
        return "/inbox?error=storage"

    name = Path(filename or "basvuru.pdf").name[:120]
    submissions_container().create_item({
        "id": app_id, "application_id": app_id, "status": "NEW", "filename": name, "title": meta["title"],
        "pages": meta["pages"], "size": len(data), "sha256": sha, "stored_in_blob": stored_in_blob,
        "uploaded_by": officer, "uploaded_at": datetime.now(timezone.utc).isoformat()})
    return f"/inbox?uploaded={app_id}"


@app.get("/run")
def old_run_page():
    return RedirectResponse("/inbox", status_code=308)


@app.post("/run/{application_id}")
async def start_run(request: Request, application_id: str):
    if not LOCAL:
        raise HTTPException(404, "yalnızca yerel modda")
    if not same_origin(request):
        raise HTTPException(403, "geçersiz istek kaynağı")
    if application_id not in await asyncio.to_thread(known_ids):
        raise HTTPException(404, "bilinmeyen başvuru")
    if ACTIVE:
        raise HTTPException(409, "Başka bir inceleme sürüyor.")
    run_id = uuid.uuid4().hex
    queue: asyncio.Queue = asyncio.Queue()
    LIVE[run_id] = queue
    ACTIVE.add(application_id)
    loop = asyncio.get_running_loop()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def worker() -> None:
        # The screening runs in its OWN thread and event loop. Lesson: running it on the server's
        # loop froze the whole UI (no SSE, no other pages) whenever an SDK call blocked.
        try:
            from grant_screening.workflow import runner

            async def on_event(e: dict) -> None:
                emit(e)

            asyncio.run(runner.start(application_id, on_event))
        except Exception as exc:  # noqa: BLE001 - user sees a plain message, details go to the log
            emit({"event": "error", "detail": "İnceleme tamamlanamadı. Ayrıntı sunucu günlüğünde."})
            print(f"screening failed for {application_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            ACTIVE.discard(application_id)
            emit({"event": "done"})

    threading.Thread(target=worker, name=f"screening-{application_id}", daemon=True).start()
    return JSONResponse({"run_id": run_id})


@app.get("/run/{run_id}/events")
async def run_events(run_id: str):
    queue = LIVE.get(run_id)
    if queue is None:
        raise HTTPException(404, "bilinmeyen çalıştırma")

    async def stream():
        while True:
            e = await queue.get()
            e = {k: v for k, v in e.items() if k in ("event", "stage", "decision", "detail")}
            yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
            if e["event"] == "done":
                LIVE.pop(run_id, None)
                break

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
