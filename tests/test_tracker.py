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


# --- permanent delete ------------------------------------------------------


def test_delete_removes_rows_and_exports(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    client.post(f"/api/applications/{aid}/events", json={"kind": "note", "body": "x"})

    export_dir = client.data_dir / "exports" / str(aid)
    export_dir.mkdir(parents=True)
    (export_dir / "resume.pdf").write_bytes(b"%PDF-1.4")

    resp = client.delete(f"/api/applications/{aid}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": aid, "exports_removed": True}

    assert client.get(f"/api/applications/{aid}").status_code == 404
    assert not export_dir.exists()


def test_delete_leaves_other_export_directories_alone(client):
    pid = make_profile(client)
    doomed = make_application(client, pid)
    kept = make_application(client, pid)

    for aid in (doomed, kept):
        d = client.data_dir / "exports" / str(aid)
        d.mkdir(parents=True)
        (d / "resume.pdf").write_bytes(b"%PDF-1.4")

    client.delete(f"/api/applications/{doomed}")

    assert not (client.data_dir / "exports" / str(doomed)).exists()
    assert (client.data_dir / "exports" / str(kept) / "resume.pdf").is_file()


def test_delete_with_no_export_directory_succeeds(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    assert client.delete(f"/api/applications/{aid}").status_code == 200


def test_delete_is_refused_mid_pipeline(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    set_status(client, aid, "tailoring")  # helper defined in the stage section

    resp = client.delete(f"/api/applications/{aid}")
    assert resp.status_code == 409
    assert "tailoring" in resp.json()["detail"]


def test_delete_removes_timeline_rows(client):
    from sqlmodel import Session, select
    from backend.app.models import ApplicationEvent

    pid = make_profile(client)
    aid = make_application(client, pid)
    client.post(f"/api/applications/{aid}/events", json={"kind": "note", "body": "x"})

    client.delete(f"/api/applications/{aid}")

    with Session(client.app.state.engine) as s:
        remaining = s.exec(
            select(ApplicationEvent).where(ApplicationEvent.application_id == aid)
        ).all()
    assert remaining == []


def test_delete_survives_a_locked_export_directory(client, monkeypatch):
    """rmtree failure (e.g. WinError 32 on a PDF held open in a viewer) must
    not escape as an unhandled 500 after the rows are already committed as
    deleted -- that would tell the caller the delete failed when the
    application has in fact vanished, and a retry would just 404."""
    pid = make_profile(client)
    aid = make_application(client, pid)

    export_dir = client.data_dir / "exports" / str(aid)
    export_dir.mkdir(parents=True)
    (export_dir / "resume.pdf").write_bytes(b"%PDF-1.4")

    from backend.app.api import applications as applications_module

    def boom(path):
        raise OSError("WinError 32: file in use by another process")

    monkeypatch.setattr(applications_module.shutil, "rmtree", boom)

    resp = client.delete(f"/api/applications/{aid}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": aid, "exports_removed": False}
    assert client.get(f"/api/applications/{aid}").status_code == 404


def test_remove_export_dir_refuses_a_path_outside_exports(client):
    """Drives the containment refusal directly, bypassing the route's int
    typing. An empty-string id collapses data_dir/exports/"" back to
    data_dir/exports itself, which must be refused -- not wiped."""
    from fastapi import HTTPException

    from backend.app.api.applications import _remove_export_dir

    exports_dir = client.data_dir / "exports"
    exports_dir.mkdir(parents=True)
    (exports_dir / "1").mkdir()

    with pytest.raises(HTTPException) as exc_info:
        _remove_export_dir(client.data_dir, "")
    assert exc_info.value.status_code == 500

    assert exports_dir.exists()
    assert (exports_dir / "1").exists()


def test_remove_export_dir_missing_directory_raises_nothing(client):
    from backend.app.api.applications import _remove_export_dir

    # No exports directory exists at all yet.
    assert _remove_export_dir(client.data_dir, 999) is True


# --- saved jobs ------------------------------------------------------------


def test_generate_false_creates_saved_job_without_running_anything(client):
    pid = make_profile(client)
    resp = client.post("/api/applications/batch", json={
        "profile_id": pid,
        "jobs": [{"url": "https://example.com/a"}, {"url": "https://example.com/b"}],
        "generate": False,
    })
    assert resp.status_code == 200, resp.text

    rows = resp.json()
    assert [r["status"] for r in rows] == ["not_started", "not_started"]
    assert [r["stage"] for r in rows] == ["saved", "saved"]
    assert client.calls["process"] == []  # nothing queued, nothing spent


def test_generate_defaults_to_true(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    assert client.calls["process"] == [aid]


def test_generate_endpoint_starts_a_saved_job(client):
    pid = make_profile(client)
    aid = client.post("/api/applications/batch", json={
        "profile_id": pid,
        "jobs": [{"url": "https://example.com/a"}],
        "generate": False,
    }).json()[0]["id"]

    resp = client.post(f"/api/applications/{aid}/generate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"
    assert client.calls["process"] == [aid]


def test_generate_endpoint_refuses_an_already_started_job(client):
    pid = make_profile(client)
    aid = make_application(client, pid)  # status 'queued'

    resp = client.post(f"/api/applications/{aid}/generate")
    assert resp.status_code == 409
    assert "not_started" in resp.json()["detail"]


def test_not_started_jobs_are_deletable_and_archivable(client):
    pid = make_profile(client)
    aid = client.post("/api/applications/batch", json={
        "profile_id": pid,
        "jobs": [{"url": "https://example.com/a"}],
        "generate": False,
    }).json()[0]["id"]

    assert client.post(f"/api/applications/{aid}/archive").status_code == 200
    assert client.delete(f"/api/applications/{aid}").status_code == 200
