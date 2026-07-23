"""Fast unit tests for backend/mcp_ops.py - no MCP stdio, no Playwright.

Drives the business-logic functions directly against the conftest engine with
a profile seeded from the intake fixture (the same profile tailor.json's
resume passes truthfulness against).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from backend import mcp_ops
from backend.app.models import (
    Application,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
    set_contact,
    set_master_profile,
)
from backend.app.services import render
from backend.app.services.intake import IntakeResult

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"

POSTING_TEXT = (
    "Senior Backend Engineer at Northwind Labs. Python, FastAPI, PostgreSQL, "
    "event-driven pipelines. Remote friendly."
)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture()
def profile_id(engine, claude_fake) -> int:
    """Seed one profile from the intake fixture."""
    intake, _usage = claude_fake.structured(
        task="intake", system="seed", user_content="seed", schema_model=IntakeResult
    )
    with Session(engine) as session:
        profile = Profile(name="Test User")
        set_contact(profile, intake.contact)
        set_master_profile(profile, intake.master_profile)
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile.id


@pytest.fixture()
def pdf_faked(monkeypatch):
    """Stub render_pdf so the fast suite never launches Chromium."""

    def _fake_pdf(html: str, out_path, page_size: str = "Letter") -> None:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(render, "render_pdf", _fake_pdf)


def _create_app(engine, profile_id: int, template: str = "slate") -> int:
    created = mcp_ops.create_application(
        engine, profile_id, "https://jobs.example.com/senior-backend",
        POSTING_TEXT, template,
    )
    return created["application_id"]


def _save_tailor(engine, data_dir, app_id: int, tailor: dict) -> dict:
    return mcp_ops.save_tailored_resume(
        engine, data_dir, app_id,
        tailor["resume"], tailor["cover_letter_md"],
        tailor.get("tailoring_notes", ""),
    )


# --- workflow guide ---

def test_workflow_guide_contents():
    guide = mcp_ops.get_workflow_guide()
    assert "NEVER invent" in guide
    assert '"additionalProperties"' in guide  # embedded strict schemas
    assert "save_tailored_resume" in guide
    assert "projects-forward" in guide
    assert "get_master_profile" in guide


# --- profile / template listing ---

def test_get_master_profile_sole_and_explicit(engine, profile_id):
    data = mcp_ops.get_master_profile(engine)  # sole profile resolves
    assert data["profile_id"] == profile_id
    assert data["master_profile"]["experiences"]
    assert data["contact"]["name"]
    assert mcp_ops.get_master_profile(engine, profile_id)["profile_id"] == profile_id

    listing = mcp_ops.list_profiles(engine)
    assert [p["id"] for p in listing] == [profile_id]
    assert listing[0]["has_master_profile"] is True


def test_get_master_profile_ambiguous_and_missing(engine, profile_id):
    with Session(engine) as session:
        session.add(Profile(name="Second User"))
        session.commit()
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.get_master_profile(engine)
    assert "profile_id" in str(exc.value)
    assert "Second User" in str(exc.value)  # error lists the profiles
    with pytest.raises(mcp_ops.McpOpsError):
        mcp_ops.get_master_profile(engine, 999)


def test_list_templates_matches_gallery_metadata():
    templates = mcp_ops.list_templates()
    assert [t["name"] for t in templates] == list(render.TEMPLATES)
    assert all({"name", "label", "description", "best_for"} <= set(t) for t in templates)


# --- create_application ---

def test_create_application_rejects_unknown_template(engine, profile_id):
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.create_application(
            engine, profile_id, "https://x.example.com/job", POSTING_TEXT, "fancy"
        )
    assert "fancy" in str(exc.value)
    assert "slate" in str(exc.value)  # lists the valid templates
    with Session(engine) as session:
        assert session.exec(select(Job)).all() == []
        assert session.exec(select(Application)).all() == []


# --- full flow ---

def test_full_flow_reaches_ready(engine, profile_id, tmp_path, pdf_faked):
    created = mcp_ops.create_application(
        engine, profile_id, "https://jobs.example.com/senior-backend", POSTING_TEXT
    )
    app_id = created["application_id"]
    assert created["status"] == "tailoring"
    assert "save_parsed_posting" in created["next"]

    parsed_result = mcp_ops.save_parsed_posting(engine, app_id, _fixture("parse_posting"))
    assert parsed_result["company"] == "Northwind Labs"
    assert parsed_result["title"] == "Senior Backend Engineer"

    result = _save_tailor(engine, tmp_path, app_id, _fixture("tailor"))
    assert result["status"] == "ready"
    assert result["version"] == 1
    export_dir = Path(result["export_dir"])
    assert set(result["files"]) == set(mcp_ops.EXPORT_FILES)
    assert (export_dir / "resume.pdf").read_bytes() == b"%PDF-1.4 fake"
    assert (export_dir / "resume.txt").read_text(encoding="utf-8")

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "ready"
        assert app.error_message is None
        assert app.version == 1
        job = session.get(Job, app.job_id)
        assert job.depth == "external"
        assert job.fetch_status == "pasted"
        assert job.raw_text == POSTING_TEXT
        versions = session.exec(
            select(ApplicationVersion).where(
                ApplicationVersion.application_id == app_id
            )
        ).all()
        assert [v.version for v in versions] == [1]

    detail = mcp_ops.get_application(engine, app_id)
    assert detail["status"] == "ready"
    assert detail["company"] == "Northwind Labs"
    assert set(detail["files"]) == set(mcp_ops.EXPORT_FILES)


# --- truthfulness gate ---

def test_truthfulness_rejection_then_corrected_save(engine, profile_id, tmp_path, pdf_faked):
    app_id = _create_app(engine, profile_id)
    tailor = _fixture("tailor")
    bad = copy.deepcopy(tailor)
    experience = next(
        s for s in bad["resume"]["sections"] if s["type"] == "experience"
    )
    experience["items"][0]["company"] = "Fake Corp"

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        _save_tailor(engine, tmp_path, app_id, bad)
    message = str(exc.value)
    assert "Fake Corp" in message  # violation listed verbatim
    assert "call this tool again" in message

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "tailoring"  # unchanged by the rejection
        assert app.resume_json is None
        assert session.exec(select(ApplicationVersion)).all() == []

    result = _save_tailor(engine, tmp_path, app_id, tailor)  # corrected save
    assert result["status"] == "ready"
    assert result["version"] == 1


def test_resume_validation_error(engine, profile_id, tmp_path, pdf_faked):
    app_id = _create_app(engine, profile_id)
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.save_tailored_resume(
            engine, tmp_path, app_id, {"headline": "x"}, "cover"
        )
    assert "ResumeDoc validation" in str(exc.value)
    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "tailoring"


# --- research ---

def test_save_research_stores_brief(engine, profile_id):
    app_id = _create_app(engine, profile_id)
    findings = _fixture("research_standard")
    result = mcp_ops.save_research(engine, app_id, findings)
    assert result["application_id"] == app_id
    with Session(engine) as session:
        app = session.get(Application, app_id)
        brief = session.exec(
            select(ResearchBrief).where(ResearchBrief.job_id == app.job_id)
        ).one()
        assert brief.depth == "external"
        assert brief.input_tokens == 0
        assert brief.output_tokens == 0
        assert brief.cost_usd == 0.0
        assert json.loads(brief.findings_json)["mission"] == findings["mission"]


def test_save_research_rejects_invalid_findings(engine, profile_id):
    app_id = _create_app(engine, profile_id)
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.save_research(engine, app_id, {"mission": ["not", "a", "string"]})
    assert "ResearchFindings validation" in str(exc.value)


# --- versioning ---

def test_version_increments_on_second_save(engine, profile_id, tmp_path, pdf_faked):
    app_id = _create_app(engine, profile_id)
    tailor = _fixture("tailor")
    first = _save_tailor(engine, tmp_path, app_id, tailor)
    assert first["version"] == 1
    second = _save_tailor(engine, tmp_path, app_id, tailor)
    assert second["version"] == 2
    assert second["status"] == "ready"
    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.version == 2
        versions = session.exec(
            select(ApplicationVersion)
            .where(ApplicationVersion.application_id == app_id)
            .order_by(ApplicationVersion.version)
        ).all()
        assert [v.version for v in versions] == [1, 2]


# --- pipeline status guard ---

def test_save_tailored_resume_rejects_while_pipeline_active(
    engine, profile_id, tmp_path, pdf_faked
):
    app_id = _create_app(engine, profile_id)
    with Session(engine) as session:
        app = session.get(Application, app_id)
        app.status = "researching"
        session.add(app)
        session.commit()

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        _save_tailor(engine, tmp_path, app_id, _fixture("tailor"))
    assert "researching" in str(exc.value)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "researching"  # unchanged
        assert app.resume_json is None  # unchanged


# --- render crash -> error status, not stuck "rendering" ---

def test_render_crash_marks_error(engine, profile_id, tmp_path, monkeypatch):
    app_id = _create_app(engine, profile_id)

    def _boom(html: str, out_path, page_size: str = "Letter") -> None:
        raise RuntimeError("chromium exploded")

    monkeypatch.setattr(render, "render_pdf", _boom)
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        _save_tailor(engine, tmp_path, app_id, _fixture("tailor"))
    assert "chromium exploded" in str(exc.value)
    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "error"
        assert "chromium exploded" in app.error_message


# --- add_profile_evidence (portfolio import) ---

def test_add_profile_evidence_appends_projects(engine, profile_id):
    result = mcp_ops.add_profile_evidence(
        engine,
        profile_id,
        projects=[
            {
                "name": "Tailored",
                "description": "Local resume-and-cover-letter builder",
                "url": "https://github.com/x/tailored",
                "bullets": [
                    {"text": "Built an stdio MCP server", "tags": ["python", "mcp"]}
                ],
            },
            {
                "name": "gitnexus",
                "description": "Code-graph query engine over git repos",
                "bullets": [{"text": "Cypher queries over a code graph", "tags": ["graph"]}],
            },
        ],
    )
    assert result["added_projects"] == ["Tailored", "gitnexus"]
    assert result["skipped_projects"] == []

    mp = result["master_profile"]
    names = [p["name"] for p in mp["projects"]]
    assert names == ["queuelite", "Tailored", "gitnexus"]  # original preserved, appended
    # Additive: unrelated master-profile content is untouched.
    assert len(mp["experiences"]) == 2
    assert len(mp["education"]) == 1

    # Persisted to the DB, not just returned.
    reloaded = mcp_ops.get_master_profile(engine, profile_id)["master_profile"]
    assert [p["name"] for p in reloaded["projects"]] == ["queuelite", "Tailored", "gitnexus"]


def test_add_profile_evidence_skips_duplicate_project(engine, profile_id):
    result = mcp_ops.add_profile_evidence(
        engine,
        profile_id,
        projects=[
            {"name": "Queuelite ", "description": "SHOULD NOT OVERWRITE"},  # dup (case/space)
            {"name": "newproj", "description": "brand new"},
        ],
    )
    assert result["added_projects"] == ["newproj"]
    assert result["skipped_projects"] == ["Queuelite "]

    by_name = {p["name"]: p for p in result["master_profile"]["projects"]}
    assert "newproj" in by_name
    # Existing project untouched - its original description survives.
    assert (
        by_name["queuelite"]["description"]
        == "Open-source lightweight Python task queue backed by SQLite"
    )


def test_add_profile_evidence_merges_skill_groups(engine, profile_id):
    result = mcp_ops.add_profile_evidence(
        engine,
        profile_id,
        skill_groups=[
            # Case-insensitive label match -> merge; "Python" is a dup, "Go" is new,
            # "python" is a within-payload dup that must also be deduped.
            {"label": "languages & frameworks", "items": ["Python", "Go", "python"]},
            {"label": "Testing", "items": ["pytest", "vitest"]},  # new label -> append
        ],
    )
    assert result["skill_groups_added"] == ["Testing"]
    assert result["skill_groups_merged"] == ["Languages & Frameworks"]  # existing label kept

    groups = {g["label"]: g["items"] for g in result["master_profile"]["skills"]}
    assert groups["Languages & Frameworks"] == [
        "Python", "TypeScript", "SQL", "FastAPI", "Flask", "Go",
    ]
    assert groups["Testing"] == ["pytest", "vitest"]


def test_add_profile_evidence_appends_summary_note(engine, profile_id):
    original = mcp_ops.get_master_profile(engine, profile_id)["master_profile"][
        "summary_notes"
    ]
    assert original  # the fixture profile has a non-empty summary

    result = mcp_ops.add_profile_evidence(
        engine, profile_id, summary_note="  Portfolio scan: 12 repos, 3 standout.  "
    )
    assert result["summary_appended"] is True
    new_notes = result["master_profile"]["summary_notes"]
    assert original in new_notes  # original text still present
    assert new_notes == original + "\n\n" + "Portfolio scan: 12 repos, 3 standout."

    # Whitespace-only note is a no-op.
    noop = mcp_ops.add_profile_evidence(engine, profile_id, summary_note="   ")
    assert noop["summary_appended"] is False
    assert noop["master_profile"]["summary_notes"] == new_notes


def test_add_profile_evidence_invalid_project_writes_nothing(engine, profile_id):
    before = mcp_ops.get_master_profile(engine, profile_id)["master_profile"]
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.add_profile_evidence(
            engine,
            profile_id,
            projects=[
                {"name": "valid one", "description": "ok"},
                {"description": "missing the required name"},  # invalid -> index 1
            ],
            skill_groups=[{"label": "Would Be Added", "items": ["x"]}],
            summary_note="would be appended",
        )
    assert "projects[1]" in str(exc.value)

    # Nothing written: not the valid project, not the skill group, not the note.
    after = mcp_ops.get_master_profile(engine, profile_id)["master_profile"]
    assert after == before


def test_add_profile_evidence_missing_profile(engine, profile_id):
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.add_profile_evidence(engine, 999, projects=[{"name": "x"}])
    assert "999" in str(exc.value)


def test_add_profile_evidence_returns_expected_keys(engine, profile_id):
    result = mcp_ops.add_profile_evidence(
        engine,
        profile_id,
        projects=[{"name": "keytest", "description": "x"}],
        skill_groups=[{"label": "New Skills", "items": ["thing"]}],
        summary_note="a note",
    )
    assert set(result) == {
        "profile_id",
        "added_projects",
        "skipped_projects",
        "skill_groups_added",
        "skill_groups_merged",
        "summary_appended",
        "master_profile",
    }
    assert result["profile_id"] == profile_id
    assert result["added_projects"] == ["keytest"]
    assert result["skipped_projects"] == []
    assert result["skill_groups_added"] == ["New Skills"]
    assert result["skill_groups_merged"] == []
    assert result["summary_appended"] is True
