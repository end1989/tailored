"""Job tracker tests: stages, timeline, archive, delete, saved jobs."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db import get_engine
from backend.app.main import create_app
from backend.app.services import pipeline

CONTACT = {
    "name": "Avery Kim",
    "email": "avery.kim@example.com",
    "phone": None,
    "location": "Seattle, WA",
    "links": [],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILORED_FAKE", "1")
    monkeypatch.setenv("TAILORED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings()
    engine = get_engine(tmp_path / "test.db")
    app = create_app(settings=settings, engine=engine)

    calls = {"process": []}
    monkeypatch.setattr(
        pipeline, "process_application",
        lambda app_id, engine=None: calls["process"].append(app_id))

    test_client = TestClient(app)
    test_client.calls = calls
    test_client.data_dir = tmp_path / "data"
    return test_client


def make_profile(client) -> int:
    resp = client.post("/api/profiles", json={"name": "Avery Kim", "contact": CONTACT})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def make_application(client, profile_id: int, **batch) -> int:
    body = {"profile_id": profile_id, "jobs": [{"url": "https://example.com/job"}]}
    body.update(batch)
    resp = client.post("/api/applications/batch", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()[0]["id"]


# --- timeline --------------------------------------------------------------


def test_add_and_list_events(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    created = client.post(
        f"/api/applications/{aid}/events",
        json={"kind": "callback", "body": "Recruiter called, 20 minutes."},
    )
    assert created.status_code == 200, created.text
    assert created.json()["kind"] == "callback"
    assert created.json()["body"] == "Recruiter called, 20 minutes."

    listing = client.get(f"/api/applications/{aid}/events").json()
    assert len(listing) == 1
    assert listing[0]["id"] == created.json()["id"]


def test_events_are_ordered_newest_occurrence_first(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    client.post(f"/api/applications/{aid}/events",
                json={"kind": "note", "body": "older", "occurred_at": "2026-01-01T00:00:00"})
    client.post(f"/api/applications/{aid}/events",
                json={"kind": "note", "body": "newer", "occurred_at": "2026-06-01T00:00:00"})

    bodies = [e["body"] for e in client.get(f"/api/applications/{aid}/events").json()]
    assert bodies == ["newer", "older"]


def test_event_kind_is_validated(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    resp = client.post(f"/api/applications/{aid}/events", json={"kind": "lunch"})
    assert resp.status_code == 422
    assert "lunch" in resp.json()["detail"]


def test_delete_event(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    eid = client.post(f"/api/applications/{aid}/events",
                      json={"kind": "note", "body": "x"}).json()["id"]

    assert client.delete(f"/api/applications/{aid}/events/{eid}").status_code == 200
    assert client.get(f"/api/applications/{aid}/events").json() == []


def test_delete_event_belonging_to_another_application_is_404(client):
    pid = make_profile(client)
    a1 = make_application(client, pid)
    a2 = make_application(client, pid)
    eid = client.post(f"/api/applications/{a1}/events",
                      json={"kind": "note", "body": "x"}).json()["id"]

    assert client.delete(f"/api/applications/{a2}/events/{eid}").status_code == 404


def test_summary_reports_last_activity(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    client.post(f"/api/applications/{aid}/events",
                json={"kind": "callback", "occurred_at": "2026-06-01T00:00:00"})

    row = next(a for a in client.get("/api/applications").json() if a["id"] == aid)
    assert row["last_activity_at"].startswith("2026-06-01")


def test_detail_embeds_events(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    client.post(f"/api/applications/{aid}/events", json={"kind": "note", "body": "hello"})

    detail = client.get(f"/api/applications/{aid}").json()
    assert [e["body"] for e in detail["events"]] == ["hello"]
