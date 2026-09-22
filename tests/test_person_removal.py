"""DELETE /api/profiles/{id}?confirm_name=...: removing a person, their rows
and their exported files, and nobody else's."""
from __future__ import annotations

import logging
from datetime import timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import Session, select

from backend.app.models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
    SourceDocument,
    _utcnow,
    set_parsed,
)
from backend.app.schemas import ParsedPosting
from backend.app.services import removal


# --- helpers ---------------------------------------------------------------


def _person(engine, name, documents=1) -> int:
    with Session(engine) as s:
        p = Profile(name=name)
        s.add(p)
        s.commit()
        s.refresh(p)
        for i in range(documents):
            s.add(SourceDocument(profile_id=p.id, filename=f"resume{i}.txt",
                                 kind="paste", text=f"{name}'s resume {i}"))
        s.commit()
        return p.id


def _application(engine, profile_id, *, status="ready", minutes_ago=0,
                 company=None, url="https://jobs.example.com/posting",
                 archived=False) -> int:
    """An application with a job, a research brief, a version and an event,
    last touched `minutes_ago` minutes ago."""
    with Session(engine) as s:
        job = Job(url=url)
        if company is not None:
            set_parsed(job, ParsedPosting(title="Engineer", company=company))
        s.add(job)
        s.commit()
        s.refresh(job)
        row = Application(
            profile_id=profile_id,
            job_id=job.id,
            status=status,
            archived_at=_utcnow() if archived else None,
            updated_at=_utcnow() - timedelta(minutes=minutes_ago),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        s.add(ResearchBrief(job_id=job.id, depth="standard"))
        s.add(ApplicationVersion(application_id=row.id, version=1,
                                 resume_json="{}", cover_letter_md=""))
        s.add(ApplicationEvent(application_id=row.id, kind="note", body="x"))
        s.commit()
        return row.id


def _export_dir(data_dir, app_id) -> Path:
    d = Path(data_dir) / "exports" / str(app_id)
    d.mkdir(parents=True)
    (d / "resume.pdf").write_bytes(b"%PDF-1.4")
    return d


_TABLES = {
    "profile": Profile,
    "documents": SourceDocument,
    "applications": Application,
    "jobs": Job,
    "briefs": ResearchBrief,
    "versions": ApplicationVersion,
    "events": ApplicationEvent,
}
NOTHING = {key: [] for key in _TABLES}


def _snapshot(engine, profile_id) -> dict[str, list[int]]:
    """The ids of every row the person owns, by table."""
    with Session(engine) as s:
        apps = s.exec(
            select(Application).where(Application.profile_id == profile_id)
        ).all()
        app_ids = [a.id for a in apps]
        job_ids = [a.job_id for a in apps]
        return {
            "profile": [profile_id] if s.get(Profile, profile_id) is not None else [],
            "documents": list(s.exec(select(SourceDocument.id)
                                     .where(SourceDocument.profile_id == profile_id)).all()),
            "applications": app_ids,
            "jobs": job_ids,
            "briefs": list(s.exec(select(ResearchBrief.id)
                                  .where(ResearchBrief.job_id.in_(job_ids))).all()),
            "versions": list(s.exec(select(ApplicationVersion.id)
                                    .where(ApplicationVersion.application_id.in_(app_ids))).all()),
            "events": list(s.exec(select(ApplicationEvent.id)
                                  .where(ApplicationEvent.application_id.in_(app_ids))).all()),
        }


def _surviving(engine, snapshot) -> dict[str, list[int]]:
    """Which of the snapshotted rows still exist, looked up by id."""
    with Session(engine) as s:
        return {
            key: [i for i in ids if s.get(_TABLES[key], i) is not None]
            for key, ids in snapshot.items()
        }


def _staging(data_dir, profile_id) -> Path:
    return Path(data_dir) / "exports" / f".removing-{profile_id}"


def _remove(client, profile_id, confirm_name):
    return client.delete(f"/api/profiles/{profile_id}",
                         params={"confirm_name": confirm_name})


# --- confirmation ----------------------------------------------------------


def test_unknown_person_is_404(client):
    resp = _remove(client, 9999, "Anyone")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "profile not found"


@pytest.mark.parametrize("params", [
    {},                                    # missing
    {"confirm_name": ""},                  # blank
    {"confirm_name": "   "},               # blank after strip
    {"confirm_name": "ada lovelace"},      # wrong case
    {"confirm_name": " Ada Lovelace "},    # not exactly the name
    {"confirm_name": "Ada"},               # a prefix
])
def test_a_missing_blank_or_wrong_name_is_422_and_removes_nothing(client, engine, params):
    pid = _person(engine, "Ada Lovelace")
    _application(engine, pid)
    before = _snapshot(engine, pid)

    resp = client.delete(f"/api/profiles/{pid}", params=params)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "confirm_name must equal the person's name"
    assert _surviving(engine, before) == before


# --- success ---------------------------------------------------------------


def test_removes_the_person_rows_and_files_and_nobody_elses(client, engine, fake_settings):
    ada = _person(engine, "Ada Lovelace", documents=2)
    ben = _person(engine, "Ben")
    ada_apps = [
        _application(engine, ada),
        _application(engine, ada, archived=True),
        _application(engine, ada, status="not_started"),  # a saved job
    ]
    ben_app = _application(engine, ben)
    ada_dirs = [_export_dir(fake_settings.data_dir, a) for a in ada_apps[:2]]
    ben_dir = _export_dir(fake_settings.data_dir, ben_app)
    ada_before = _snapshot(engine, ada)
    ben_before = _snapshot(engine, ben)

    resp = _remove(client, ada, "Ada Lovelace")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": ada, "applications": 3, "documents": 2}
    assert _surviving(engine, ada_before) == NOTHING
    for d in ada_dirs:
        assert not d.exists()
    assert not _staging(fake_settings.data_dir, ada).exists()
    assert _surviving(engine, ben_before) == ben_before
    assert (ben_dir / "resume.pdf").is_file()
    assert [p["id"] for p in client.get("/api/profiles").json()] == [ben]


def test_a_person_with_nothing_is_removed(client, engine):
    pid = _person(engine, "Ada", documents=0)

    resp = _remove(client, pid, "Ada")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": pid, "applications": 0, "documents": 0}
    assert client.get(f"/api/profiles/{pid}").status_code == 404


# --- active work -----------------------------------------------------------


def test_recent_active_work_is_409_and_listed(client, engine, fake_settings):
    ada = _person(engine, "Ada")
    fetching = _application(engine, ada, status="fetching", minutes_ago=1,
                            company="Northwind Labs")
    queued = _application(engine, ada, status="queued", minutes_ago=14,
                          url="https://jobs.example.com/queued")
    _application(engine, ada, status="ready")
    ada_dir = _export_dir(fake_settings.data_dir, fetching)
    before = _snapshot(engine, ada)

    resp = _remove(client, ada, "Ada")

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail["message"], str) and detail["message"]
    assert detail["blocking"] == [
        {"id": fetching, "label": "Northwind Labs", "status": "fetching"},
        {"id": queued, "label": "https://jobs.example.com/queued", "status": "queued"},
    ]
    assert _surviving(engine, before) == before
    assert (ada_dir / "resume.pdf").is_file()


@pytest.mark.parametrize("status", ["queued", "fetching", "researching", "tailoring", "rendering"])
def test_every_active_status_blocks_while_recent(client, engine, status):
    ada = _person(engine, "Ada")
    app_id = _application(engine, ada, status=status, minutes_ago=2)

    resp = _remove(client, ada, "Ada")

    assert resp.status_code == 409
    assert [b["id"] for b in resp.json()["detail"]["blocking"]] == [app_id]


def test_stale_active_rows_do_not_block_and_are_removed(client, engine):
    ada = _person(engine, "Ada")
    # A pipeline run killed by a server restart, and a row an MCP agent
    # parked in tailoring and never finished.
    _application(engine, ada, status="fetching", minutes_ago=16)
    _application(engine, ada, status="tailoring", minutes_ago=60 * 24)
    before = _snapshot(engine, ada)

    resp = _remove(client, ada, "Ada")

    assert resp.status_code == 200, resp.text
    assert resp.json()["applications"] == 2
    assert _surviving(engine, before) == NOTHING


def test_blocking_applications_uses_the_fifteen_minute_window(engine):
    ada = _person(engine, "Ada")
    app_id = _application(engine, ada, status="rendering")
    with Session(engine) as s:
        touched = s.get(Application, app_id).updated_at

        recent = removal.blocking_applications(s, ada, now=touched + timedelta(minutes=14))
        stale = removal.blocking_applications(s, ada, now=touched + timedelta(minutes=16))
        aware = removal.blocking_applications(
            s, ada, now=touched.replace(tzinfo=timezone.utc) + timedelta(minutes=1))

    assert [a.id for a in recent] == [app_id]
    assert stale == []
    assert [a.id for a in aware] == [app_id]


def test_blocking_applications_ignores_other_people_and_idle_statuses(engine):
    ada = _person(engine, "Ada")
    ben = _person(engine, "Ben")
    _application(engine, ben, status="fetching")
    for status in ("not_started", "ready", "needs_paste", "error"):
        _application(engine, ada, status=status)

    with Session(engine) as s:
        assert removal.blocking_applications(s, ada) == []


# --- files -----------------------------------------------------------------


def test_a_locked_export_directory_removes_nothing(client, engine, fake_settings, monkeypatch):
    ada = _person(engine, "Ada")
    first = _application(engine, ada)
    second = _application(engine, ada)
    first_dir = _export_dir(fake_settings.data_dir, first)
    second_dir = _export_dir(fake_settings.data_dir, second)
    before = _snapshot(engine, ada)

    real_rename = removal.os.rename

    def rename(src, dst, *args, **kwargs):
        # Windows refuses to move a directory while a file inside is open.
        if Path(src) == second_dir:
            raise PermissionError(13, "The process cannot access the file", str(src))
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(removal.os, "rename", rename)

    resp = _remove(client, ada, "Ada")

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail["message"], str) and detail["message"]
    assert len(detail["blocking"]) == 1
    assert detail["blocking"][0]["id"] == second
    assert detail["blocking"][0]["status"] == "locked"
    assert Path(detail["blocking"][0]["label"]) == second_dir
    # The first directory was moved into staging, then moved back.
    assert (first_dir / "resume.pdf").is_file()
    assert (second_dir / "resume.pdf").is_file()
    assert not _staging(fake_settings.data_dir, ada).exists()
    assert _surviving(engine, before) == before


def test_a_staging_cleanup_failure_is_logged_not_raised(
        client, engine, fake_settings, monkeypatch, caplog):
    ada = _person(engine, "Ada")
    app_id = _application(engine, ada)
    _export_dir(fake_settings.data_dir, app_id)
    before = _snapshot(engine, ada)

    def rmtree(path, *args, **kwargs):
        raise OSError("file in use")

    monkeypatch.setattr(removal.shutil, "rmtree", rmtree)

    with caplog.at_level(logging.WARNING, logger=removal.__name__):
        resp = _remove(client, ada, "Ada")

    assert resp.status_code == 200, resp.text
    assert _surviving(engine, before) == NOTHING
    staging = _staging(fake_settings.data_dir, ada)
    assert (staging / str(app_id) / "resume.pdf").is_file()  # left behind, logged
    assert any(str(staging) in r.getMessage() for r in caplog.records)


def test_a_leftover_staging_directory_is_cleared_first(client, engine, fake_settings):
    ada = _person(engine, "Ada")
    app_id = _application(engine, ada)
    _export_dir(fake_settings.data_dir, app_id)
    # Left by an earlier removal, of a person who had the same id, whose
    # cleanup failed. Its rows are long gone.
    leftover = _staging(fake_settings.data_dir, ada) / str(app_id)
    leftover.mkdir(parents=True)
    (leftover / "old.pdf").write_bytes(b"%PDF-1.4")

    resp = _remove(client, ada, "Ada")

    assert resp.status_code == 200, resp.text
    assert not _staging(fake_settings.data_dir, ada).exists()
    assert not (Path(fake_settings.data_dir) / "exports" / str(app_id)).exists()
