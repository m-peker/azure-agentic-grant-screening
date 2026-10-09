"""Upload of new proposals (offline: fake Cosmos and fake Blob Storage)."""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "scenario" / "upload_samples" / "ornek-1-biyokomur.pdf"


class FakeContainer:
    def __init__(self):
        self.docs = {}

    def query_items(self, query, parameters=None, **kwargs):
        if "SELECT VALUE c.application_id" in query:
            return [d["application_id"] for d in self.docs.values()]
        if parameters:
            value = parameters[0]["value"]
            return [{"id": d["id"]} for d in self.docs.values() if d.get("sha256") == value]
        return list(self.docs.values())

    def read_item(self, item, partition_key=None):
        return dict(self.docs[item])

    def create_item(self, doc):
        assert doc["id"] not in self.docs
        self.docs[doc["id"]] = dict(doc)

    def upsert_item(self, doc):
        self.docs[doc["id"]] = dict(doc)


class FakeDb:
    def __init__(self):
        self.c = {n: FakeContainer() for n in ("results", "decisions", "audit", "submissions")}

    def get_container_client(self, name):
        return self.c[name]


class FakeBlobs:
    def __init__(self):
        self.stored = {}

    def get_blob_client(self, container, name):
        outer = self

        class Client:
            def upload_blob(self, data, overwrite=False, content_settings=None):
                outer.stored[name] = data

        return Client()


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.delenv("GRANT_UI_LOCAL", raising=False)
    monkeypatch.setenv("STORAGE_ACCOUNT_URL", "https://fake.blob.core.windows.net/")
    sys.path.insert(0, str(ROOT / "webapp"))
    app_module = importlib.reload(importlib.import_module("app"))
    fake_db, fake_blobs = FakeDb(), FakeBlobs()
    monkeypatch.setattr(app_module, "db", lambda: fake_db)
    monkeypatch.setattr(app_module, "blob_service", lambda: fake_blobs)
    c = TestClient(app_module.app)
    c.db, c.blobs = fake_db, fake_blobs
    return c


def post(client, name, data, origin=True):
    headers = {"origin": "http://testserver"} if origin else {}
    return client.post("/inbox/upload", headers=headers, follow_redirects=False,
                       files={"file": (name, data, "application/pdf")})


def test_valid_pdf_gets_an_id_and_is_stored(client):
    r = post(client, "basvuru.pdf", SAMPLE.read_bytes())
    assert r.status_code == 303 and r.headers["location"] == "/inbox?uploaded=MGA-2026-5001"
    sub = client.db.c["submissions"].docs["MGA-2026-5001"]
    assert sub["status"] == "NEW" and sub["pages"] == 2 and sub["stored_in_blob"]
    assert sub["title"].startswith("Çay Fabrikası Atıklarından Biyokömür")
    assert client.blobs.stored["MGA-2026-5001.pdf"] == SAMPLE.read_bytes()


def test_next_upload_gets_the_next_number(client):
    post(client, "a.pdf", SAMPLE.read_bytes())
    other = (ROOT / "scenario" / "upload_samples" / "ornek-2-deprem.pdf").read_bytes()
    assert post(client, "b.pdf", other).headers["location"].endswith("MGA-2026-5002")


def test_same_document_twice_is_rejected(client):
    post(client, "a.pdf", SAMPLE.read_bytes())
    assert post(client, "kopya.pdf", SAMPLE.read_bytes()).headers["location"] == "/inbox?error=duplicate"


@pytest.mark.parametrize("name, data, code", [
    ("sahte.pdf", b"Bu bir metin dosyasi, PDF degil.", "type"),     # name says PDF, content does not
    ("bozuk.pdf", b"%PDF-1.4\n bozuk icerik", "broken"),
    ("bos.pdf", b"", "empty"),
])
def test_invalid_files_are_rejected_by_content(client, name, data, code):
    assert post(client, name, data).headers["location"] == f"/inbox?error={code}"
    assert client.db.c["submissions"].docs == {}


def test_upload_requires_same_origin(client):
    assert post(client, "a.pdf", SAMPLE.read_bytes(), origin=False).status_code == 403


def test_inbox_lists_uploads_in_cloud_mode(client):
    post(client, "a.pdf", SAMPLE.read_bytes())
    html = client.get("/inbox").text
    assert "MGA-2026-5001" in html and "Sırada" in html
    assert "data-run" not in html          # screening button only in local mode
