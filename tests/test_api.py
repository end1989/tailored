"""API route tests (Task 12). All pipeline work is monkeypatched - no Claude, no network."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.app.config import Settings
from backend.app.db import get_engine
from backend.app.main import create_app
from backend.app.models import Application
from backend.app.schemas import Contact, MasterProfile, MPExperience, TaggedBullet, UsageInfo
from backend.app.services import intake, pipeline, render

CONTACT = {
    "name": "Avery Kim",
    "email": "avery.kim@example.com",
    "phone": "(206) 555-0142",
    "location": "Seattle, WA",
    "links": [{"label": "GitHub", "url": "https://github.com/averykim"}],
}

VALID_RESUME = {
    "contact": {
        "name": "Avery Kim",
        "email": "avery.kim@example.com",
        "phone": None,
        "location": "Seattle, WA",
        "links": [],
    },
    "headline": "Senior Software Engineer",
    "summary": "Backend engineer with eight years of Python service experience.",
    "sections": [
        {
            "type": "experience",
            "title": "Experience",
            "items": [
                {
                    "company": "Meridian Analytics",
                    "role": "Senior Software Engineer",
                    "start": "2021-03",
                    "end": None,
                    "location": "Remote",
                    "bullets": ["Designed and shipped a FastAPI event-ingestion service."],
                }
            ],
        },
        {
            "type": "skills",
            "title": "Skills",
            "groups": [{"label": "Languages", "items": ["Python", "TypeScript"]}],
        },
    ],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILORED_FAKE", "1")
    monkeypatch.setenv("TAILORED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings()
    engine = get_engine(tmp_path / "test.db")
    app = create_app(settings=settings, engine=engine)

    calls = {"process": [], "paste": [], "regenerate": []}
    monkeypatch.setattr(
        pipeline, "process_application",
        lambda app_id, engine=None: calls["process"].append(app_id))
    monkeypatch.setattr(
        pipeline, "resume_after_paste",
        lambda app_id, text, engine=None: calls["paste"].append((app_id, text)))
    monkeypatch.setattr(
        pipeline, "regenerate_application",
        lambda app_id, feedback, engine=None: calls["regenerate"].append((app_id, feedback)))

    # Plain TestClient (no context manager): startup hooks never run, so the
    # demo seeding added in Task 13 cannot pollute these tests.
    test_client = TestClient(app)
    test_client.calls = calls
    return test_client


def make_profile(client) -> int:
    resp = client.post("/api/profiles", json={"name": "Avery Kim", "contact": CONTACT})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_profile_crud(client):
    assert client.get("/api/profiles").json() == []

    pid = make_profile(client)
    listing = client.get("/api/profiles").json()
    assert len(listing) == 1
    assert listing[0]["id"] == pid
    assert listing[0]["name"] == "Avery Kim"
    assert listing[0]["contact"]["email"] == "avery.kim@example.com"
    assert listing[0]["has_master_profile"] is False

    detail = client.get(f"/api/profiles/{pid}").json()
    assert detail["id"] == pid
    assert detail["master_profile"]["experiences"] == []
    assert detail["documents"] == []

    mp = {
        "summary_notes": "Backend engineer.",
        "experiences": [{
            "company": "Meridian Analytics", "title": "Senior Software Engineer",
            "start": "2021-03", "end": None, "location": "Remote",
            "bullets": [{"text": "Built APIs", "tags": ["python"]}],
        }],
        "projects": [], "skills": [], "education": [], "certifications": [], "extras": [],
    }
    updated = client.put(f"/api/profiles/{pid}", json={"name": "Avery K.", "master_profile": mp})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Avery K."
    assert updated.json()["master_profile"]["experiences"][0]["company"] == "Meridian Analytics"
    assert client.get("/api/profiles").json()[0]["has_master_profile"] is True

    assert client.get("/api/profiles/9999").status_code == 404
    assert client.put("/api/profiles/9999", json={"name": "x"}).status_code == 404


def test_document_upload_multipart_and_json(client):
    pid = make_profile(client)

    multipart = client.post(
        f"/api/profiles/{pid}/documents",
        files={"file": ("resume.txt", b"Avery Kim resume body", "text/plain")})
    assert multipart.status_code == 200, multipart.text
    body = multipart.json()
    assert body["filename"] == "resume.txt"
    assert body["kind"] == "txt"

    pasted = client.post(
        f"/api/profiles/{pid}/documents",
        json={"filename": "notes.txt", "text": "Extra career notes"})
    assert pasted.status_code == 200
    assert pasted.json()["kind"] == "paste"

    empty = client.post(f"/api/profiles/{pid}/documents", json={"filename": "x.txt", "text": ""})
    assert empty.status_code == 422

    detail = client.get(f"/api/profiles/{pid}").json()
    assert len(detail["documents"]) == 2
    assert client.post(
        "/api/profiles/9999/documents", json={"filename": "a", "text": "b"}).status_code == 404


def test_build_master_profile(client, monkeypatch):
    pid = make_profile(client)
    assert client.post(f"/api/profiles/{pid}/build").status_code == 422  # no documents yet

    client.post(f"/api/profiles/{pid}/documents",
                json={"filename": "resume.txt", "text": "Avery resume text"})

    mp = MasterProfile(
        summary_notes="Backend engineer",
        experiences=[MPExperience(
            company="Meridian Analytics", title="Senior Software Engineer", start="2021-03",
            bullets=[TaggedBullet(text="Built APIs", tags=["python"])])],
    )
    contact = Contact(name="Avery Kim", email="avery.kim@example.com")
    recorded = {}

    def fake_build(docs, claude):
        recorded["docs"] = list(docs)
        return mp, contact, UsageInfo(input_tokens=1000, output_tokens=500, cost_usd=0.0175)

    monkeypatch.setattr(intake, "build_master_profile", fake_build)
    resp = client.post(f"/api/profiles/{pid}/build")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert recorded["docs"] == ["Avery resume text"]
    assert body["master_profile"]["experiences"][0]["company"] == "Meridian Analytics"
    assert body["usage"] == {"input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.0175}


def make_application(client, pid: int, **job_kwargs) -> int:
    job = {"url": "https://jobs.example.com/posting", **job_kwargs}
    resp = client.post("/api/applications/batch", json={"profile_id": pid, "jobs": [job]})
    assert resp.status_code == 200, resp.text
    return resp.json()[0]["id"]


def test_batch_creates_applications_and_schedules(client):
    pid = make_profile(client)
    resp = client.post("/api/applications/batch", json={
        "profile_id": pid,
        "jobs": [
            {"url": "https://jobs.example.com/a"},
            {"url": "https://jobs.example.com/b", "depth": "deep", "template": "terminal"},
        ],
        "default_depth": "quick",
    })
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 2
    assert all(item["status"] == "queued" for item in items)
    assert items[0]["depth"] == "quick"        # from default_depth
    assert items[0]["template"] == "slate"     # from user-settings default
    assert items[1]["depth"] == "deep"
    assert items[1]["template"] == "terminal"
    assert items[0]["url"] == "https://jobs.example.com/a"
    assert items[0]["company"] is None and items[0]["title"] is None
    assert items[0]["cost_usd"] == 0.0
    assert items[0]["error_message"] is None

    ids = [item["id"] for item in items]
    assert client.calls["process"] == ids  # one scheduled pipeline call per application

    listing = client.get(f"/api/applications?profile_id={pid}").json()
    assert [row["id"] for row in listing] == sorted(ids, reverse=True)
    assert client.get("/api/applications?profile_id=9999").json() == []

    detail = client.get(f"/api/applications/{ids[0]}").json()
    assert detail["resume"] is None
    assert detail["parsed"] is None
    assert detail["research"] is None
    assert detail["cover_letter_md"] is None
    assert detail["raw_text_present"] is False
    assert client.get("/api/applications/99999").status_code == 404
    assert client.post(
        "/api/applications/batch",
        json={"profile_id": 9999, "jobs": [{"url": "https://x"}]}).status_code == 404


def test_batch_rejects_bad_enums(client):
    pid = make_profile(client)
    bad_depth = client.post("/api/applications/batch", json={
        "profile_id": pid, "jobs": [{"url": "https://x", "depth": "ultra"}]})
    assert bad_depth.status_code == 422
    bad_template = client.post("/api/applications/batch", json={
        "profile_id": pid, "jobs": [{"url": "https://x", "template": "comic-sans"}]})
    assert bad_template.status_code == 422
    assert client.calls["process"] == []  # nothing scheduled on validation failure


def test_paste_schedules_resume_after_paste(client):
    pid = make_profile(client)
    app_id = make_application(client, pid)
    assert client.post(
        f"/api/applications/{app_id}/paste", json={"text": "   "}).status_code == 422
    resp = client.post(
        f"/api/applications/{app_id}/paste", json={"text": "Pasted posting body"})
    assert resp.status_code == 200
    assert client.calls["paste"] == [(app_id, "Pasted posting body")]
    assert client.post(
        "/api/applications/9999/paste", json={"text": "x"}).status_code == 404


def test_regenerate_requires_feedback(client):
    pid = make_profile(client)
    app_id = make_application(client, pid)
    assert client.post(
        f"/api/applications/{app_id}/regenerate", json={"feedback": ""}).status_code == 422
    assert client.post(
        f"/api/applications/{app_id}/regenerate", json={}).status_code == 422
    ok = client.post(
        f"/api/applications/{app_id}/regenerate",
        json={"feedback": "More emphasis on Postgres"})
    assert ok.status_code == 200
    assert client.calls["regenerate"] == [(app_id, "More emphasis on Postgres")]


def test_retry_requeues_and_reschedules(client):
    pid = make_profile(client)
    app_id = make_application(client, pid)
    resp = client.post(f"/api/applications/{app_id}/retry")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["error_message"] is None
    # one schedule from batch creation plus one from the retry
    assert client.calls["process"] == [app_id, app_id]
    assert client.post("/api/applications/99999/retry").status_code == 404


def test_content_edit(client, monkeypatch):
    pid = make_profile(client)
    app_id = make_application(client, pid)

    bad = client.put(
        f"/api/applications/{app_id}/content",
        json={"resume": {"headline": "missing contact"}})
    assert bad.status_code == 422

    exports = []

    def fake_export(application_id, resume, cover_md, contact, template, data_dir,
                    page_size="Letter"):
        out = Path(data_dir) / "exports" / str(application_id)
        out.mkdir(parents=True, exist_ok=True)
        exports.append((application_id, template, page_size))
        return out

    monkeypatch.setattr(render, "export_application", fake_export)
    before = len(client.calls["process"]) + len(client.calls["regenerate"])
    resp = client.put(
        f"/api/applications/{app_id}/content",
        json={"resume": VALID_RESUME, "cover_letter_md": "Dear Northwind team,"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resume"]["headline"] == "Senior Software Engineer"
    assert body["cover_letter_md"] == "Dear Northwind team,"
    assert exports == [(app_id, "slate", "Letter")]
    # editing content never triggers a Claude/pipeline call
    assert len(client.calls["process"]) + len(client.calls["regenerate"]) == before


def test_preview(client, monkeypatch):
    pid = make_profile(client)
    app_id = make_application(client, pid)
    assert client.get(f"/api/applications/{app_id}/preview").status_code == 404

    monkeypatch.setattr(
        render, "export_application",
        lambda *args, **kwargs: Path(client.app.state.settings.data_dir)
        / "exports" / str(app_id))
    client.put(f"/api/applications/{app_id}/content", json={"resume": VALID_RESUME})
    resp = client.get(f"/api/applications/{app_id}/preview")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Avery Kim" in resp.text


def test_export_downloads(client):
    pid = make_profile(client)
    app_id = make_application(client, pid)
    # unknown kind -> 404
    assert client.get(
        f"/api/applications/{app_id}/exports/resume.docx").status_code == 404
    # known kind but not generated yet -> 404
    assert client.get(
        f"/api/applications/{app_id}/exports/resume.pdf").status_code == 404

    export_dir = Path(client.app.state.settings.data_dir) / "exports" / str(app_id)
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "resume.txt").write_text("AVERY KIM", encoding="utf-8")
    ok = client.get(f"/api/applications/{app_id}/exports/resume.txt")
    assert ok.status_code == 200
    assert ok.text == "AVERY KIM"


def test_settings_round_trip(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json() == {
        "api_key_set": False,      # ANTHROPIC_API_KEY deleted in the fixture
        "fake_mode": True,         # TAILORED_FAKE=1 in the fixture
        "default_template": "slate",
        "default_depth": "standard",
        "page_size": "Letter",
    }

    updated = client.put(
        "/api/settings", json={"default_template": "terminal", "page_size": "A4"})
    assert updated.status_code == 200
    body = updated.json()
    assert body["default_template"] == "terminal"
    assert body["default_depth"] == "standard"
    assert body["page_size"] == "A4"

    again = client.get("/api/settings").json()  # persisted in data/settings.json
    assert again["default_template"] == "terminal"
    assert again["page_size"] == "A4"

    assert client.put(
        "/api/settings", json={"default_depth": "extreme"}).status_code == 422
    assert client.put(
        "/api/settings", json={"default_template": "papyrus"}).status_code == 422
    assert client.put(
        "/api/settings", json={"page_size": "Legal"}).status_code == 422


def test_document_upload_corrupt_pdf_returns_422(client):
    pid = make_profile(client)
    resp = client.post(
        f"/api/profiles/{pid}/documents",
        files={"file": ("broken.pdf", b"%PDF-1.4 this is not a real pdf", "application/pdf")},
    )
    assert resp.status_code == 422
    assert "broken.pdf" in resp.json()["detail"]


def test_paste_and_retry_conflict_while_processing(client):
    pid = make_profile(client)
    app_id = make_application(client, pid)
    # put the application into an in-flight status directly
    with Session(client.app.state.engine) as session:
        app_row = session.get(Application, app_id)
        app_row.status = "tailoring"
        session.add(app_row)
        session.commit()
    assert client.post(f"/api/applications/{app_id}/paste", json={"text": "x"}).status_code == 409
    assert client.post(f"/api/applications/{app_id}/retry").status_code == 409
    # no new pipeline calls were scheduled by the rejected requests
    assert client.calls["paste"] == []
    assert client.calls["process"] == [app_id]  # only the original batch-create schedule
