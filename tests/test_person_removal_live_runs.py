"""Person removal never deletes live work: a pipeline run in this process
blocks however long it has sat in one status, and MCP writes on a parked row
refresh its updated_at."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlmodel import Session

from backend import mcp_ops
from backend.app.models import Application, Job, Profile, _utcnow
from backend.app.services import pipeline, removal

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


def _person(engine, name="Ada") -> int:
    with Session(engine) as s:
        p = Profile(name=name)
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id


def _application(engine, profile_id, *, status, minutes_ago) -> int:
    with Session(engine) as s:
        job = Job(url="https://jobs.example.com/posting")
        s.add(job)
        s.commit()
        s.refresh(job)
        row = Application(profile_id=profile_id, job_id=job.id, status=status,
                          updated_at=_utcnow() - timedelta(minutes=minutes_ago))
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


def _age(engine, app_id, minutes) -> None:
    with Session(engine) as s:
        row = s.get(Application, app_id)
        row.updated_at = _utcnow() - timedelta(minutes=minutes)
        s.add(row)
        s.commit()


def _remove(client, pid, name="Ada"):
    return client.delete(f"/api/profiles/{pid}", params={"confirm_name": name})


# --- live pipeline runs ----------------------------------------------------


def test_a_live_run_blocks_removal_however_old_its_row(client, engine):
    ada = _person(engine)
    app_id = _application(engine, ada, status="researching", minutes_ago=16)

    with pipeline.live_run(app_id):
        resp = _remove(client, ada)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["blocking"] == [
            {"id": app_id, "label": "https://jobs.example.com/posting",
             "status": "researching"},
        ]

    # The run ended: the same stale row is abandoned and no longer blocks.
    assert app_id not in pipeline.live_application_ids()
    resp = _remove(client, ada)
    assert resp.status_code == 200, resp.text
    assert resp.json()["applications"] == 1


def test_a_live_run_of_another_person_does_not_block(engine):
    ada = _person(engine)
    bob = _person(engine, "Bob")
    bobs = _application(engine, bob, status="researching", minutes_ago=16)
    with pipeline.live_run(bobs), Session(engine) as s:
        assert removal.blocking_applications(s, ada) == []
        assert [r.id for r in removal.blocking_applications(s, bob)] == [bobs]


def test_the_registry_is_cleared_when_the_body_raises():
    with pytest.raises(RuntimeError):
        with pipeline.live_run(4242):
            assert 4242 in pipeline.live_application_ids()
            raise RuntimeError("boom")
    assert 4242 not in pipeline.live_application_ids()


def test_process_application_is_live_while_running_and_cleared_after_a_failure(
        engine, claude_fake, monkeypatch):
    ada = _person(engine)
    app_id = _application(engine, ada, status="queued", minutes_ago=0)
    seen = []

    def _failing_fetch(url):
        seen.append(pipeline.is_live(app_id))
        raise RuntimeError("network down")

    monkeypatch.setattr(pipeline.fetcher, "fetch_posting", _failing_fetch)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    assert seen == [True]
    assert not pipeline.is_live(app_id)
    with Session(engine) as s:
        assert s.get(Application, app_id).status == "error"


def test_resume_after_paste_and_regenerate_clear_the_registry(
        engine, claude_fake, monkeypatch):
    ada = _person(engine)
    app_id = _application(engine, ada, status="needs_paste", minutes_ago=0)
    seen = []

    def _failing(*args, **kwargs):
        seen.append(pipeline.is_live(app_id))
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline, "_run_from_research", _failing)
    pipeline.resume_after_paste(app_id, "posting text", engine=engine,
                                claude=claude_fake)
    monkeypatch.setattr(pipeline, "get_parsed", _failing)
    pipeline.regenerate_application(app_id, "", engine=engine, claude=claude_fake)

    assert seen == [True, True]
    assert not pipeline.is_live(app_id)


# --- MCP writes refresh updated_at -----------------------------------------


def _parked(engine, profile_id) -> int:
    created = mcp_ops.create_application(
        engine, profile_id, "https://jobs.example.com/x", "A posting.", "slate")
    return created["application_id"]


def _fixture(name):
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _updated_at(engine, app_id):
    with Session(engine) as s:
        return s.get(Application, app_id).updated_at


def test_save_parsed_posting_and_save_research_refresh_updated_at(engine):
    ada = _person(engine)
    app_id = _parked(engine, ada)

    _age(engine, app_id, 30)
    old = _updated_at(engine, app_id)
    mcp_ops.save_parsed_posting(engine, app_id, _fixture("parse_posting"))
    assert _updated_at(engine, app_id) > old + timedelta(minutes=29)

    _age(engine, app_id, 30)
    old = _updated_at(engine, app_id)
    mcp_ops.save_research(engine, app_id, _fixture("research_standard"))
    assert _updated_at(engine, app_id) > old + timedelta(minutes=29)


def test_a_row_an_agent_just_wrote_to_blocks_removal(client, engine):
    ada = _person(engine)
    app_id = _parked(engine, ada)
    _age(engine, app_id, 60)  # parked an hour ago...
    mcp_ops.save_parsed_posting(engine, app_id, _fixture("parse_posting"))  # ...written now

    resp = _remove(client, ada)
    assert resp.status_code == 409, resp.text
    assert [b["id"] for b in resp.json()["detail"]["blocking"]] == [app_id]
