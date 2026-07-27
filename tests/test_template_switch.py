"""PATCH /applications/{id}/template re-renders stored content in a new template.

No Claude call, no cost, no version bump: the content is unchanged, only its
presentation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session

from backend.app.models import Application, Job, Profile
from backend.app.schemas import TailorResult
from backend.app.services import render

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


def _resume_json() -> str:
    data = json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))
    return TailorResult.model_validate(data).resume.model_dump_json()


@pytest.fixture()
def seeded(engine, tmp_path, monkeypatch):
    """A ready application with stored resume content, and no real PDF rendering."""
    calls: list[tuple] = []

    def fake_export(application_id, resume, cover_md, contact, template, data_dir, page_size="Letter"):
        calls.append((application_id, template))
        out = Path(data_dir) / "exports" / str(application_id)
        out.mkdir(parents=True, exist_ok=True)
        return out

    monkeypatch.setattr(render, "export_application", fake_export)

    with Session(engine) as session:
        profile = Profile(name="Ada", contact_json=json.dumps({
            "name": "Ada Lovelace", "email": "ada@example.com", "links": []
        }))
        session.add(profile)
        session.commit()
        session.refresh(profile)
        job = Job(url="https://example.com/job", raw_text="text")
        session.add(job)
        session.commit()
        session.refresh(job)
        app_row = Application(
            profile_id=profile.id,
            job_id=job.id,
            template="slate",
            status="ready",
            version=1,
            resume_json=_resume_json(),
            cover_letter_md="Dear team,",
        )
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
        app_id = app_row.id
    return {"application_id": app_id, "calls": calls, "data_dir": tmp_path}


def test_switching_template_updates_the_row(client, seeded):
    resp = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    )
    assert resp.status_code == 200
    assert resp.json()["template"] == "ledger"


def test_switching_template_re_exports_in_the_new_template(client, seeded):
    client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    )
    assert seeded["calls"], "export_application was never called"
    assert seeded["calls"][-1][1] == "ledger"


def test_switching_template_does_not_bump_the_version(client, seeded):
    before = client.get(f"/api/applications/{seeded['application_id']}").json()["version"]
    after = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    ).json()["version"]
    assert after == before


def test_switching_template_does_not_change_the_cost(client, seeded):
    before = client.get(f"/api/applications/{seeded['application_id']}").json()["cost_usd"]
    after = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    ).json()["cost_usd"]
    assert after == before


def test_switching_template_leaves_the_resume_content_identical(client, seeded):
    before = client.get(f"/api/applications/{seeded['application_id']}").json()["resume"]
    after = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    ).json()["resume"]
    assert after == before


def test_switching_to_an_unknown_template_is_422(client, seeded):
    resp = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "nonexistent"},
    )
    assert resp.status_code == 422


def test_switching_template_on_a_missing_application_is_404(client):
    resp = client.patch("/api/applications/9999/template", json={"template": "ledger"})
    assert resp.status_code == 404


def test_switching_template_mid_pipeline_is_409(client, seeded, engine):
    with Session(engine) as session:
        row = session.get(Application, seeded["application_id"])
        row.status = "tailoring"
        session.add(row)
        session.commit()
    resp = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    )
    assert resp.status_code == 409


def test_switching_template_with_no_stored_resume_is_422(client, seeded, engine):
    with Session(engine) as session:
        row = session.get(Application, seeded["application_id"])
        row.resume_json = None
        session.add(row)
        session.commit()
    resp = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    )
    assert resp.status_code == 422


def test_switching_template_never_calls_claude(client, seeded, monkeypatch):
    """The whole point: a different template costs nothing."""
    from backend.app.services import claude as claude_module

    def explode(*args, **kwargs):
        raise AssertionError("switching a template must not call Claude")

    monkeypatch.setattr(claude_module.ClaudeService, "structured", explode)
    resp = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    )
    assert resp.status_code == 200


def test_switching_template_does_not_reorder_sections(client, seeded):
    """Documented limitation: section order was decided at tailoring time and a
    template switch deliberately does not re-run the LLM to revisit it."""
    before = [s["type"] for s in client.get(
        f"/api/applications/{seeded['application_id']}"
    ).json()["resume"]["sections"]]
    after = [s["type"] for s in client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "terminal"},
    ).json()["resume"]["sections"]]
    assert after == before


def test_mcp_set_application_template(engine, seeded):
    from backend import mcp_ops

    result = mcp_ops.set_application_template(
        engine, seeded["data_dir"], seeded["application_id"], "ledger"
    )
    assert result["template"] == "ledger"
    assert result["application_id"] == seeded["application_id"]


def test_mcp_set_application_template_rejects_unknown(engine, seeded):
    from backend import mcp_ops

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.set_application_template(
            engine, seeded["data_dir"], seeded["application_id"], "nope"
        )
    assert "nope" in str(exc.value)


def test_mcp_set_application_template_rejects_mid_pipeline(engine, seeded):
    """Uses "rendering", not "tailoring".

    The MCP guard `_reject_if_pipeline_active` deliberately EXCLUDES "tailoring"
    from `_PIPELINE_ACTIVE_STATUSES` (mcp_ops.py:369-373): that is the MCP
    parking state between create_application and save_tailored_resume, so an
    agent must be able to act on an application sitting in it. The HTTP route
    guards on `PROCESSING_STATUSES`, which does include "tailoring". The
    asymmetry is intentional and this test pins it.
    """
    from backend import mcp_ops

    with Session(engine) as session:
        row = session.get(Application, seeded["application_id"])
        row.status = "rendering"
        session.add(row)
        session.commit()
    with pytest.raises(mcp_ops.McpOpsError):
        mcp_ops.set_application_template(
            engine, seeded["data_dir"], seeded["application_id"], "ledger"
        )


def test_mcp_set_application_template_allows_the_mcp_parking_state(engine, seeded):
    """"tailoring" is where an MCP agent parks an application; it must not block."""
    from backend import mcp_ops

    with Session(engine) as session:
        row = session.get(Application, seeded["application_id"])
        row.status = "tailoring"
        session.add(row)
        session.commit()
    result = mcp_ops.set_application_template(
        engine, seeded["data_dir"], seeded["application_id"], "ledger"
    )
    assert result["template"] == "ledger"
