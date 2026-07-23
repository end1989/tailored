"""API route tests (Task 12). All pipeline work is monkeypatched - no Claude, no network."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db import get_engine
from backend.app.main import create_app
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
