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


def test_events_are_ordered_by_occurrence_not_insertion(client):
    """Post in the OPPOSITE order to the expected result, so a regression that
    ordered by id alone would fail. Posting oldest-first would let id-only
    ordering produce the same answer and pass a broken implementation."""
    pid = make_profile(client)
    aid = make_application(client, pid)

    client.post(f"/api/applications/{aid}/events",
                json={"kind": "note", "body": "newer", "occurred_at": "2026-06-01T00:00:00"})
    client.post(f"/api/applications/{aid}/events",
                json={"kind": "note", "body": "older", "occurred_at": "2026-01-01T00:00:00"})

    bodies = [e["body"] for e in client.get(f"/api/applications/{aid}/events").json()]
    assert bodies == ["newer", "older"]


def test_events_with_equal_occurrence_tiebreak_on_id_desc(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    same = "2026-03-01T00:00:00"

    client.post(f"/api/applications/{aid}/events",
                json={"kind": "note", "body": "first", "occurred_at": same})
    client.post(f"/api/applications/{aid}/events",
                json={"kind": "note", "body": "second", "occurred_at": same})

    bodies = [e["body"] for e in client.get(f"/api/applications/{aid}/events").json()]
    assert bodies == ["second", "first"]


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


# --- stages ----------------------------------------------------------------


def test_new_application_starts_saved(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    assert client.get(f"/api/applications/{aid}").json()["stage"] == "saved"


def test_set_stage(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    resp = client.patch(f"/api/applications/{aid}", json={"stage": "interview"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage"] == "interview"


def test_invalid_stage_is_rejected(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    resp = client.patch(f"/api/applications/{aid}", json={"stage": "ghosted"})
    assert resp.status_code == 422
    assert "ghosted" in resp.json()["detail"]


def test_applied_at_is_stamped_once(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    first = client.patch(f"/api/applications/{aid}", json={"stage": "applied"}).json()
    assert first["applied_at"] is not None

    client.patch(f"/api/applications/{aid}", json={"stage": "screening"})
    again = client.patch(f"/api/applications/{aid}", json={"stage": "applied"}).json()
    assert again["applied_at"] == first["applied_at"]


def test_stage_is_independent_of_status(client):
    """Regenerating a job you are interviewing for must not reset the funnel."""
    pid = make_profile(client)
    aid = make_application(client, pid)
    client.patch(f"/api/applications/{aid}", json={"stage": "interview"})

    resp = client.post(f"/api/applications/{aid}/retry")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert resp.json()["stage"] == "interview"


def set_status(client, application_id: int, status: str) -> None:
    """Force a generation status the pipeline would normally set. The pipeline
    is monkeypatched in these tests, so status is driven directly."""
    from sqlmodel import Session

    from backend.app.models import Application

    with Session(client.app.state.engine) as s:
        row = s.get(Application, application_id)
        row.status = status
        s.add(row)
        s.commit()


def test_cannot_move_a_generated_application_back_to_saved(client):
    """'saved' means no documents exist. Allowing it on a ready application
    would also break the migration backfill's idempotence, which identifies
    pre-migration rows precisely by ready + saved being impossible."""
    pid = make_profile(client)
    aid = make_application(client, pid)
    set_status(client, aid, "ready")

    resp = client.patch(f"/api/applications/{aid}", json={"stage": "saved"})
    assert resp.status_code == 422
    assert "saved" in resp.json()["detail"]


# --- archive ---------------------------------------------------------------


def test_archive_hides_from_default_listing(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    assert client.post(f"/api/applications/{aid}/archive").status_code == 200
    assert [a["id"] for a in client.get("/api/applications").json()] == []


def test_archived_filter_shows_only_archived(client):
    pid = make_profile(client)
    kept = make_application(client, pid)
    gone = make_application(client, pid)
    client.post(f"/api/applications/{gone}/archive")

    archived = client.get("/api/applications?archived=true").json()
    assert [a["id"] for a in archived] == [gone]
    assert [a["id"] for a in client.get("/api/applications").json()] == [kept]


def test_restore_returns_it_to_the_default_listing(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    client.post(f"/api/applications/{aid}/archive")

    assert client.post(f"/api/applications/{aid}/restore").status_code == 200
    assert [a["id"] for a in client.get("/api/applications").json()] == [aid]


def test_stage_filter(client):
    pid = make_profile(client)
    a1 = make_application(client, pid)
    a2 = make_application(client, pid)
    client.patch(f"/api/applications/{a2}", json={"stage": "offer"})

    rows = client.get("/api/applications?stage=offer").json()
    assert [a["id"] for a in rows] == [a2]


def test_invalid_stage_filter_is_rejected(client):
    assert client.get("/api/applications?stage=nope").status_code == 422
