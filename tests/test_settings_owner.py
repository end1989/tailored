"""Every settings consumer uses the application's OWNER (spec 5.2, 9).

Two people with different settings, one application each, through every path
that reads settings: batch create (template and depth), the pipeline render,
the web template switch and content save, and both MCP render paths (page
size). Every render caller reaches export_application through the render
module attribute (`from ..services import pipeline, render` in
api/applications.py, `from . import fetcher, render` in services/pipeline.py,
`from .app.services import render` in mcp_ops.py), so one monkeypatch on
`render.export_application` intercepts all of them.

The two page sizes are A4 and Letter, the only two there are, so each test
asserts BOTH people: reading the app-wide file gives both the same value, and
reading the wrong person gives one of them the other's.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session

from backend import mcp_ops
from backend.app.config import save_user_settings
from backend.app.models import (
    Application,
    Job,
    Profile,
    set_contact,
    set_master_profile,
    set_profile_settings,
)
from backend.app.schemas import TailorResult
from backend.app.services import pipeline, render
from backend.app.services.intake import IntakeResult

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"

POSTING_TEXT = (
    "Senior Backend Engineer at Northwind Labs. Python, FastAPI, PostgreSQL, "
    "event-driven pipelines. Remote friendly."
)

ADA_SETTINGS = {"default_template": "terminal", "default_depth": "deep", "page_size": "A4"}
BEA_SETTINGS = {"default_template": "ledger", "default_depth": "quick", "page_size": "Letter"}


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture()
def exports(monkeypatch) -> list[tuple[int, str]]:
    """Record (application_id, page_size) for every export; write stub files.

    The MCP paths list the export directory after rendering, so the stub
    writes the real file names.
    """
    calls: list[tuple[int, str]] = []

    def fake_export(application_id, resume, cover_md, contact, template, data_dir,
                    page_size="Letter"):
        calls.append((application_id, page_size))
        out = Path(data_dir) / "exports" / str(application_id)
        out.mkdir(parents=True, exist_ok=True)
        for name in mcp_ops.EXPORT_FILES:
            (out / name).write_bytes(b"%PDF-1.4 fake" if name.endswith(".pdf") else b"text")
        return out

    monkeypatch.setattr(render, "export_application", fake_export)
    return calls


@pytest.fixture()
def people(engine, claude_fake) -> dict[str, int]:
    """Ada (A4) and Bea (Letter), both with the intake fixture's master profile,
    which the tailor fixture's resume passes the truthfulness guard against."""
    intake, _usage = claude_fake.structured(
        task="intake", system="seed", user_content="seed", schema_model=IntakeResult
    )
    ids: dict[str, int] = {}
    with Session(engine) as session:
        for name, own in (("Ada", ADA_SETTINGS), ("Bea", BEA_SETTINGS)):
            profile = Profile(name=name)
            set_contact(profile, intake.contact)
            set_master_profile(profile, intake.master_profile)
            set_profile_settings(profile, own)
            session.add(profile)
            session.commit()
            session.refresh(profile)
            ids[name] = profile.id
    return ids


def _ready_application(engine, profile_id: int) -> int:
    """An application that already has content, so it can be re-rendered."""
    resume_json = TailorResult.model_validate(_fixture("tailor")).resume.model_dump_json()
    with Session(engine) as session:
        job = Job(url="https://jobs.example.com/senior-backend", raw_text=POSTING_TEXT)
        session.add(job)
        session.commit()
        session.refresh(job)
        app_row = Application(
            profile_id=profile_id,
            job_id=job.id,
            template="slate",
            status="ready",
            stage="drafted",
            resume_json=resume_json,
            cover_letter_md="Dear team,",
        )
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
        return app_row.id


def _batch(client, profile_id: int, **extra) -> dict:
    resp = client.post("/api/applications/batch", json={
        "profile_id": profile_id,
        "jobs": [{"url": "https://jobs.example.com/a"}],
        "generate": False,  # nothing scheduled: no pipeline run in this test
        **extra,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()[0]


# --- batch create: the person's default template and depth -----------------


def test_batch_create_uses_each_persons_default_template_and_depth(client, people):
    ada = _batch(client, people["Ada"])
    bea = _batch(client, people["Bea"])
    assert (ada["template"], ada["depth"]) == ("terminal", "deep")
    assert (bea["template"], bea["depth"]) == ("ledger", "quick")


def test_batch_create_request_values_still_beat_the_persons_defaults(client, people):
    from_body = _batch(
        client, people["Ada"], default_template="slate", default_depth="standard"
    )
    assert (from_body["template"], from_body["depth"]) == ("slate", "standard")

    resp = client.post("/api/applications/batch", json={
        "profile_id": people["Ada"],
        "jobs": [{"url": "https://jobs.example.com/b", "template": "ledger", "depth": "quick"}],
        "generate": False,
    })
    assert (resp.json()[0]["template"], resp.json()[0]["depth"]) == ("ledger", "quick")


def test_batch_create_for_a_person_without_own_values_uses_the_app_wide_ones(
    client, engine, fake_settings
):
    save_user_settings(fake_settings.data_dir, {"default_template": "terminal",
                                                "default_depth": "deep"})
    with Session(engine) as session:
        profile = Profile(name="Cy")
        session.add(profile)
        session.commit()
        session.refresh(profile)
        pid = profile.id
    row = _batch(client, pid)
    assert (row["template"], row["depth"]) == ("terminal", "deep")


# --- page size: every render path -------------------------------------------


def test_pipeline_render_uses_the_owners_page_size(
    engine, claude_fake, fake_settings, people, exports, monkeypatch
):
    monkeypatch.setattr(pipeline, "get_settings", lambda: fake_settings)
    app_ids = {}
    for name in ("Ada", "Bea"):
        with Session(engine) as session:
            # raw_text skips the fetch; depth "quick" skips research.
            job = Job(url=f"https://jobs.example.com/{name}", raw_text=POSTING_TEXT,
                      depth="quick")
            session.add(job)
            session.commit()
            session.refresh(job)
            app_row = Application(profile_id=people[name], job_id=job.id)
            session.add(app_row)
            session.commit()
            session.refresh(app_row)
            app_ids[name] = app_row.id
        pipeline.process_application(app_ids[name], engine=engine, claude=claude_fake)
        with Session(engine) as session:
            app_row = session.get(Application, app_ids[name])
            assert app_row.status == "ready", app_row.error_message

    assert exports == [(app_ids["Ada"], "A4"), (app_ids["Bea"], "Letter")]


def test_template_switch_uses_the_owners_page_size(client, engine, people, exports):
    ada_app = _ready_application(engine, people["Ada"])
    bea_app = _ready_application(engine, people["Bea"])
    for app_id in (ada_app, bea_app):
        resp = client.patch(f"/api/applications/{app_id}/template",
                            json={"template": "ledger"})
        assert resp.status_code == 200, resp.text

    assert exports == [(ada_app, "A4"), (bea_app, "Letter")]


def test_content_save_uses_the_owners_page_size(client, engine, people, exports):
    ada_app = _ready_application(engine, people["Ada"])
    bea_app = _ready_application(engine, people["Bea"])
    for app_id in (ada_app, bea_app):
        resp = client.put(f"/api/applications/{app_id}/content",
                          json={"cover_letter_md": "Dear Northwind team,"})
        assert resp.status_code == 200, resp.text

    assert exports == [(ada_app, "A4"), (bea_app, "Letter")]


def test_mcp_set_application_template_uses_the_owners_page_size(
    engine, tmp_path, people, exports
):
    ada_app = _ready_application(engine, people["Ada"])
    bea_app = _ready_application(engine, people["Bea"])
    for app_id in (ada_app, bea_app):
        mcp_ops.set_application_template(engine, tmp_path, app_id, "ledger")

    assert exports == [(ada_app, "A4"), (bea_app, "Letter")]


def test_mcp_save_tailored_resume_uses_the_owners_page_size(
    engine, tmp_path, people, exports
):
    tailor = _fixture("tailor")
    app_ids = []
    for name in ("Ada", "Bea"):
        created = mcp_ops.create_application(
            engine, people[name], f"https://jobs.example.com/{name}", POSTING_TEXT, "slate"
        )
        app_id = created["application_id"]
        result = mcp_ops.save_tailored_resume(
            engine, tmp_path, app_id, tailor["resume"], tailor["cover_letter_md"],
            tailor.get("tailoring_notes", ""),
        )
        assert result["status"] == "ready"
        app_ids.append(app_id)

    assert exports == [(app_ids[0], "A4"), (app_ids[1], "Letter")]
