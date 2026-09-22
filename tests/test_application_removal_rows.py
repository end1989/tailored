"""delete_application_rows removes everything one application owns, and the
single-application delete route now uses it, so the Job and ResearchBrief
rows no longer outlive their application."""
from __future__ import annotations

from sqlmodel import Session, select

from backend.app.models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
)
from backend.app.services.removal import delete_application_rows


def _profile(engine, name="Ada") -> int:
    with Session(engine) as s:
        p = Profile(name=name)
        s.add(p)
        s.commit()
        return p.id


def _full_application(engine, profile_id, status="ready") -> tuple[int, int]:
    """An application with a job, two research briefs, a version and an event.
    Returns (application_id, job_id)."""
    with Session(engine) as s:
        job = Job(url="https://jobs.example.com/posting")
        s.add(job)
        s.commit()
        s.refresh(job)
        app_row = Application(profile_id=profile_id, job_id=job.id, status=status)
        s.add(app_row)
        s.commit()
        s.refresh(app_row)
        s.add(ResearchBrief(job_id=job.id, depth="standard"))
        s.add(ResearchBrief(job_id=job.id, depth="deep"))
        s.add(ApplicationVersion(application_id=app_row.id, version=1,
                                 resume_json="{}", cover_letter_md=""))
        s.add(ApplicationEvent(application_id=app_row.id, kind="note", body="x"))
        s.commit()
        return app_row.id, job.id


def _rows(engine, app_id, job_id) -> dict[str, int]:
    with Session(engine) as s:
        return {
            "application": len(s.exec(select(Application).where(Application.id == app_id)).all()),
            "job": len(s.exec(select(Job).where(Job.id == job_id)).all()),
            "briefs": len(s.exec(select(ResearchBrief).where(ResearchBrief.job_id == job_id)).all()),
            "versions": len(s.exec(select(ApplicationVersion)
                                   .where(ApplicationVersion.application_id == app_id)).all()),
            "events": len(s.exec(select(ApplicationEvent)
                                 .where(ApplicationEvent.application_id == app_id)).all()),
        }


GONE = {"application": 0, "job": 0, "briefs": 0, "versions": 0, "events": 0}
INTACT = {"application": 1, "job": 1, "briefs": 2, "versions": 1, "events": 1}


def test_deletes_every_row_the_application_owns(engine):
    pid = _profile(engine)
    doomed, doomed_job = _full_application(engine, pid)
    kept, kept_job = _full_application(engine, pid)

    with Session(engine) as s:
        delete_application_rows(s, s.get(Application, doomed))
        s.commit()

    assert _rows(engine, doomed, doomed_job) == GONE
    assert _rows(engine, kept, kept_job) == INTACT


def test_does_not_commit(engine):
    pid = _profile(engine)
    app_id, job_id = _full_application(engine, pid)

    with Session(engine) as s:
        delete_application_rows(s, s.get(Application, app_id))
        s.rollback()

    assert _rows(engine, app_id, job_id) == INTACT


def test_an_application_whose_job_is_already_gone(engine):
    pid = _profile(engine)
    app_id, job_id = _full_application(engine, pid)
    with Session(engine) as s:
        s.delete(s.get(Job, job_id))
        s.commit()

    with Session(engine) as s:
        delete_application_rows(s, s.get(Application, app_id))
        s.commit()

    assert _rows(engine, app_id, job_id) == GONE


def test_delete_route_removes_job_and_research_briefs(client, engine):
    pid = _profile(engine)
    doomed, doomed_job = _full_application(engine, pid)
    kept, kept_job = _full_application(engine, pid)

    resp = client.delete(f"/api/applications/{doomed}")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": doomed}
    assert _rows(engine, doomed, doomed_job) == GONE
    assert _rows(engine, kept, kept_job) == INTACT


def test_delete_route_still_refuses_mid_pipeline(client, engine):
    pid = _profile(engine)
    app_id, job_id = _full_application(engine, pid, status="researching")

    resp = client.delete(f"/api/applications/{app_id}")

    assert resp.status_code == 409
    assert _rows(engine, app_id, job_id) == INTACT
