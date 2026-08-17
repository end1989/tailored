"""Fast unit tests for backend/mcp_ops.py - no MCP stdio, no Playwright.

Drives the business-logic functions directly against the conftest engine with
a profile seeded from the intake fixture (the same profile tailor.json's
resume passes truthfulness against).
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import Session, select
from starlette.background import BackgroundTasks

from backend import mcp_ops
from backend.app.models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
    set_contact,
    set_master_profile,
)
from backend.app.schemas import FetchResult
from backend.app.services import fetcher, pipeline, render
from backend.app.services.intake import IntakeResult

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


def _utcnow() -> datetime:
    """Naive UTC, matching backend.app.models._utcnow (datetime.utcnow is
    deprecated on this Python and warns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

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
    # The guide must still tell the agent that templates differ in how they
    # order sections; it no longer names a specific structure literal, because
    # the structures now come from the on-disk manifests.
    assert "section order" in guide
    assert "get_master_profile" in guide

    # The fetch ladder. This guide IS the deliverable for the browser half of
    # the design, and it silently rotting is the realistic failure mode.
    assert "DIRECT FETCH" in guide
    assert "BROWSER ESCALATION" in guide
    assert "ASK FOR A PASTE" in guide
    assert "403" in guide
    assert "400 characters" in guide, "the short-body heuristic must survive"
    assert "user's own browser" in guide
    assert "report_fetch_blocked" in guide

    assert "em dash" in guide.lower()
    assert "passionate about" in guide
    # The guide has to point at the candidate's own direction, not just at the
    # ban list, or an agent never asks for it.
    assert "voice_notes" in guide

    # The explicit refusal to help with evasion is part of the deliverable.
    lowered = guide.lower()
    assert "do not attempt to disguise automated traffic" in lowered

    # The batch loop.
    assert "queue_jobs" in guide
    assert "next_pending_job" in guide
    assert "one job to completion before starting the next" in lowered

    # Step 2c must be actionable in BOTH flows. In the batch flow the id comes
    # from next_pending_job; in the single-job flow no application exists yet,
    # so the guide must say to create the row (queue_jobs) before reporting -
    # an impossible instruction here is how the silent-failure mode returns.
    assert "queue_jobs(profile_id, [url])" in guide
    assert "needs_paste" in guide
    assert "never guess an id" in lowered


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


def test_get_master_profile_returns_voice_notes(engine, profile_id):
    """The candidate's explicit direction has to reach MCP agents too, or the
    two generation paths write in different voices."""
    with Session(engine) as session:
        profile = session.get(Profile, profile_id)
        profile.voice_notes = "Plain and direct. Short sentences."
        session.add(profile)
        session.commit()

    data = mcp_ops.get_master_profile(engine, profile_id)
    assert data["voice_notes"] == "Plain and direct. Short sentences."


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


# --- saved -> drafted stage advance -----------------------------------------

def test_save_tailored_resume_advances_stage_saved_to_drafted(
    engine, profile_id, tmp_path, pdf_faked
):
    """The one sanctioned status/stage coupling: a successful MCP-driven save
    moves a freshly created ('saved') application to 'drafted'. Without the
    `if app.stage == "saved":` guard in save_tailored_resume, every
    MCP-generated application would sit in 'saved' forever."""
    app_id = _create_app(engine, profile_id)
    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.stage == "saved"  # sanity: default stage before generation

    result = _save_tailor(engine, tmp_path, app_id, _fixture("tailor"))
    assert result["status"] == "ready"

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.stage == "drafted"


def test_save_tailored_resume_leaves_non_saved_stage_alone(
    engine, profile_id, tmp_path, pdf_faked
):
    """The other half of the guard: a job already moved further down the
    funnel (e.g. 'interview') must not be reset by a regeneration. Only
    stage == 'saved' advances."""
    app_id = _create_app(engine, profile_id)
    with Session(engine) as session:
        app = session.get(Application, app_id)
        app.stage = "interview"
        session.add(app)
        session.commit()

    result = _save_tailor(engine, tmp_path, app_id, _fixture("tailor"))
    assert result["status"] == "ready"

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.stage == "interview"  # unchanged


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


def test_add_profile_evidence_strips_skill_items(engine, profile_id):
    result = mcp_ops.add_profile_evidence(
        engine,
        profile_id,
        skill_groups=[
            # "Python" (whitespace) dedups against the existing clean "Python";
            # " Go " is new and must persist stripped in both the merge path
            # (Languages & Frameworks, an existing label) and the new-group
            # append path (Deployment, a brand new label).
            {"label": "languages & frameworks", "items": [" Python ", " Go "]},
            {"label": "Deployment", "items": [" Go ", "Docker "]},
        ],
    )
    groups = {g["label"]: g["items"] for g in result["master_profile"]["skills"]}
    assert groups["Languages & Frameworks"] == [
        "Python", "TypeScript", "SQL", "FastAPI", "Flask", "Go",
    ]
    assert groups["Deployment"] == ["Go", "Docker"]

    reloaded = mcp_ops.get_master_profile(engine, profile_id)["master_profile"]
    reloaded_groups = {g["label"]: g["items"] for g in reloaded["skills"]}
    assert reloaded_groups["Languages & Frameworks"][-1] == "Go"
    assert reloaded_groups["Deployment"] == ["Go", "Docker"]


def test_add_profile_evidence_dedups_duplicate_project_within_payload(
    engine, profile_id
):
    """Two projects with the same name in ONE payload: first added, second skipped."""
    result = mcp_ops.add_profile_evidence(
        engine,
        profile_id,
        projects=[
            {"name": "Brand New Project", "description": "first copy"},
            {"name": "brand new project ", "description": "second copy, duplicate"},
        ],
    )
    assert result["added_projects"] == ["Brand New Project"]
    assert result["skipped_projects"] == ["brand new project "]

    names = [p["name"] for p in result["master_profile"]["projects"]]
    assert names.count("Brand New Project") == 1
    by_name = {p["name"]: p for p in result["master_profile"]["projects"]}
    assert by_name["Brand New Project"]["description"] == "first copy"


def test_add_profile_evidence_dedups_duplicate_skill_group_within_payload(
    engine, profile_id
):
    """Two skill_groups with the same label in ONE payload merge into one group."""
    result = mcp_ops.add_profile_evidence(
        engine,
        profile_id,
        skill_groups=[
            {"label": "Cloud", "items": ["AWS"]},
            {"label": "cloud ", "items": ["GCP", "AWS"]},
        ],
    )
    assert result["skill_groups_added"] == ["Cloud"]
    assert result["skill_groups_merged"] == ["Cloud"]

    matching = [g for g in result["master_profile"]["skills"] if g["label"] == "Cloud"]
    assert len(matching) == 1
    assert matching[0]["items"] == ["AWS", "GCP"]


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


# --- queue_jobs (the MCP batch queue) ---

QUEUE_URLS = [
    "https://jobs.example.com/one",
    "https://jobs.example.com/two",
    "https://jobs.example.com/three",
]


def test_queue_jobs_creates_one_parked_application_per_url(engine, profile_id):
    result = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    assert len(result) == 3
    assert [r["url"] for r in result] == QUEUE_URLS
    with Session(engine) as session:
        apps = session.exec(select(Application)).all()
        assert len(apps) == 3
        for app in apps:
            assert app.status == "not_started"
            assert app.stage == "saved"
            assert app.cost_usd == 0.0
            assert app.resume_json is None


def test_queue_jobs_stores_no_posting_text(engine, profile_id):
    """The agent fetches each posting later, one at a time."""
    mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    with Session(engine) as session:
        for job in session.exec(select(Job)).all():
            assert job.raw_text is None
            assert job.fetch_status == "pending"


def test_queue_jobs_returns_the_ids_and_urls(engine, profile_id):
    result = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    for entry in result:
        assert entry["status"] == "not_started"
        assert isinstance(entry["application_id"], int)


def test_queue_jobs_never_calls_claude(engine, profile_id, monkeypatch):
    """Queueing twenty URLs must cost nothing."""
    from backend.app.services import claude as claude_module

    def explode(*args, **kwargs):
        raise AssertionError("queue_jobs must not call Claude")

    monkeypatch.setattr(claude_module.ClaudeService, "structured", explode)
    assert len(mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)) == 3


def test_queue_jobs_rejects_an_empty_list(engine, profile_id):
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.queue_jobs(engine, profile_id, [])
    assert "empty" in str(exc.value).lower()


def test_queue_jobs_rejects_an_unknown_profile(engine):
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.queue_jobs(engine, 9999, QUEUE_URLS)
    assert "9999" in str(exc.value)


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "not-a-url", "example.com/job", "ftp://example.com/job", "javascript:alert(1)"],
)
def test_queue_jobs_rejects_a_malformed_url(engine, profile_id, bad):
    with pytest.raises(mcp_ops.McpOpsError):
        mcp_ops.queue_jobs(engine, profile_id, [bad])


def test_one_bad_url_in_twenty_creates_nothing(engine, profile_id):
    """All-or-nothing, matching the web batch route. A partial queue is worse
    than a rejected one: the agent cannot tell which half landed."""
    urls = [f"https://jobs.example.com/{i}" for i in range(19)] + ["not-a-url"]
    with pytest.raises(mcp_ops.McpOpsError):
        mcp_ops.queue_jobs(engine, profile_id, urls)
    with Session(engine) as session:
        assert session.exec(select(Application)).all() == []
        assert session.exec(select(Job)).all() == []


def test_queueing_the_same_url_twice_skips_the_second(engine, profile_id):
    """Pasting a list twice is normal user behaviour and must not create
    twenty duplicates."""
    first = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    second = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)

    assert [r["status"] for r in second] == ["skipped"] * 3
    assert [r["application_id"] for r in second] == [r["application_id"] for r in first]
    assert all("reason" in r for r in second)
    with Session(engine) as session:
        assert len(session.exec(select(Application)).all()) == 3


def test_a_duplicate_within_one_queue_call_is_skipped(engine, profile_id):
    result = mcp_ops.queue_jobs(
        engine, profile_id, ["https://jobs.example.com/a", "https://jobs.example.com/a"]
    )
    assert [r["status"] for r in result] == ["not_started", "skipped"]
    with Session(engine) as session:
        assert len(session.exec(select(Application)).all()) == 1


def test_dedup_is_scoped_to_the_profile(engine, profile_id, claude_fake):
    """Two people may legitimately apply to the same job."""
    with Session(engine) as session:
        other = Profile(name="Someone Else")
        session.add(other)
        session.commit()
        session.refresh(other)
        other_id = other.id

    mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    result = mcp_ops.queue_jobs(engine, other_id, ["https://jobs.example.com/a"])
    assert result[0]["status"] == "not_started"


def test_an_archived_application_does_not_block_requeueing(engine, profile_id):
    """Archiving is how a user says 'done with this'. Re-queueing must work."""
    first = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    with Session(engine) as session:
        app = session.get(Application, first[0]["application_id"])
        app.archived_at = _utcnow()
        session.add(app)
        session.commit()

    second = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    assert second[0]["status"] == "not_started"
    assert second[0]["application_id"] != first[0]["application_id"]


def test_queue_jobs_uses_a_depth_the_pipeline_can_dispatch(engine, profile_id):
    """Queued rows are generate-able from the dashboard (status not_started is
    exactly what POST /generate accepts), and research_company only handles
    quick/standard/deep. Stamping depth "external" here made every Generate
    click die with ValueError after the parse call had already been paid for."""
    mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    with Session(engine) as session:
        for job in session.exec(select(Job)).all():
            assert job.depth == "standard"


def test_a_queued_job_generates_to_ready_through_the_web_pipeline(
    engine, profile_id, client, fake_settings, claude_fake, pdf_faked, monkeypatch
):
    """The full path the dashboard offers for a queued row: the Generate
    button (POST /generate), then the built-in pipeline fetches, parses,
    researches, tailors, and renders. With depth "external" this reached
    research_company and died in ValueError, landing the row in status
    "error" with a Retry button that repeated the same failure."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]

    # The route flips status and schedules the pipeline; drop the scheduling
    # so the pipeline can be driven synchronously against the test engine.
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, fn, *a, **k: None)
    resp = client.post(f"/api/applications/{app_id}/generate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"

    monkeypatch.setattr(pipeline, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(
        fetcher,
        "fetch_posting",
        lambda url, timeout=20.0: FetchResult(status="fetched", text=POSTING_TEXT),
    )
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "ready", app.error_message
        assert app.error_message is None
        job = session.get(Job, app.job_id)
        assert job.depth == "standard"
        assert job.fetch_status == "fetched"


# --- next_pending_job (MCP queue consumption) ---


def test_next_pending_job_returns_the_oldest_first(engine, profile_id):
    queued = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    nxt = mcp_ops.next_pending_job(engine, profile_id)
    assert nxt["application_id"] == queued[0]["application_id"]
    assert nxt["url"] == QUEUE_URLS[0]


def test_next_pending_job_returns_none_on_an_empty_queue(engine, profile_id):
    assert mcp_ops.next_pending_job(engine, profile_id) is None


def test_next_pending_job_ignores_applications_already_started(engine, profile_id):
    queued = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    with Session(engine) as session:
        app = session.get(Application, queued[0]["application_id"])
        app.status = "ready"
        session.add(app)
        session.commit()

    assert mcp_ops.next_pending_job(engine, profile_id)["application_id"] == (
        queued[1]["application_id"]
    )


def test_next_pending_job_ignores_other_profiles(engine, profile_id):
    with Session(engine) as session:
        other = Profile(name="Someone Else")
        session.add(other)
        session.commit()
        session.refresh(other)
        other_id = other.id

    mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    assert mcp_ops.next_pending_job(engine, other_id) is None


def test_next_pending_job_ignores_archived_applications(engine, profile_id):
    queued = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    with Session(engine) as session:
        app = session.get(Application, queued[0]["application_id"])
        app.archived_at = _utcnow()
        session.add(app)
        session.commit()

    assert mcp_ops.next_pending_job(engine, profile_id)["application_id"] == (
        queued[1]["application_id"]
    )


def test_the_queue_resumes_after_a_context_loss(engine, profile_id, tmp_path, pdf_faked):
    """The property this whole design exists for.

    Queue five, complete two, and the third is what comes back - with no
    memory of the run carried anywhere but the database.
    """
    urls = [f"https://jobs.example.com/{i}" for i in range(5)]
    queued = mcp_ops.queue_jobs(engine, profile_id, urls)

    for entry in queued[:2]:
        with Session(engine) as session:
            app = session.get(Application, entry["application_id"])
            app.status = "ready"
            session.add(app)
            session.commit()

    nxt = mcp_ops.next_pending_job(engine, profile_id)
    assert nxt["application_id"] == queued[2]["application_id"]
    assert nxt["url"] == urls[2]


def test_a_user_deleting_a_saved_job_mid_run_simply_removes_it(engine, profile_id):
    """Correct behaviour, not an error: the agent just never receives it."""
    queued = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    with Session(engine) as session:
        session.delete(session.get(Application, queued[0]["application_id"]))
        session.commit()

    assert mcp_ops.next_pending_job(engine, profile_id)["application_id"] == (
        queued[1]["application_id"]
    )


# --- report_fetch_blocked (MCP escalation failure handler) ---


def test_report_fetch_blocked_sets_the_fetch_status(engine, profile_id):
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]

    result = mcp_ops.report_fetch_blocked(engine, app_id, "403 and a bot check")
    assert result["fetch_status"] == "blocked"

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert session.get(Job, app.job_id).fetch_status == "blocked"


def test_report_fetch_blocked_moves_a_queued_application_to_needs_paste(
    engine, profile_id
):
    """The status move is what surfaces the paste box on the dashboard AND
    what takes the job out of next_pending_job's pending set."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]

    result = mcp_ops.report_fetch_blocked(engine, app_id, "403 and a bot check")
    assert result["status"] == "needs_paste"

    with Session(engine) as session:
        assert session.get(Application, app_id).status == "needs_paste"


def test_a_blocked_job_leaves_the_queue(engine, profile_id):
    """The live-lock regression. Blocking job 1 must make next_pending_job
    hand out job 2 - the guide says "move on to the next job", and before this
    fix the only tool for advancing the queue returned the blocked job
    forever, so a 20-URL batch stopped at the first refusal."""
    queued = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)

    mcp_ops.report_fetch_blocked(
        engine, queued[0]["application_id"], "403 and a bot check"
    )

    nxt = mcp_ops.next_pending_job(engine, profile_id)
    assert nxt["application_id"] == queued[1]["application_id"]
    assert nxt["url"] == QUEUE_URLS[1]


def test_blocking_every_job_drains_the_queue(engine, profile_id):
    """A batch where every posting is refused must still terminate on the
    plain None condition, not loop."""
    queued = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    for entry in queued:
        mcp_ops.report_fetch_blocked(engine, entry["application_id"], "login wall")

    assert mcp_ops.next_pending_job(engine, profile_id) is None


def test_report_fetch_blocked_rejects_while_the_pipeline_owns_the_row(
    engine, profile_id
):
    """The same guard as the other MCP writes: a misdirected application_id
    must not scribble a blocked state onto a row the built-in pipeline is
    actively processing."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]
    with Session(engine) as session:
        app = session.get(Application, app_id)
        app.status = "fetching"
        session.add(app)
        session.commit()

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.report_fetch_blocked(engine, app_id, "403")
    assert "fetching" in str(exc.value)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "fetching"  # unchanged
        assert session.get(Job, app.job_id).fetch_status == "pending"  # unchanged
        events = session.exec(
            select(ApplicationEvent).where(ApplicationEvent.application_id == app_id)
        ).all()
        assert events == []  # nothing written


def test_report_fetch_blocked_writes_a_timeline_note(engine, profile_id):
    """The user must see WHY a posting stalled, not just that it did."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]

    mcp_ops.report_fetch_blocked(engine, app_id, "403 and a bot check")

    with Session(engine) as session:
        events = session.exec(
            select(ApplicationEvent).where(ApplicationEvent.application_id == app_id)
        ).all()
        assert len(events) == 1
        assert events[0].kind == "note"
        assert "403 and a bot check" in events[0].body


def test_report_fetch_blocked_is_visible_on_the_application(client, engine, profile_id):
    """It has to reach the dashboard, or it is not a report."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]
    mcp_ops.report_fetch_blocked(engine, app_id, "login wall")

    detail = client.get(f"/api/applications/{app_id}").json()
    assert any("login wall" in e["body"] for e in detail["events"])


def test_report_fetch_blocked_leaves_the_job_pasteable_to_ready(
    engine, profile_id, client, fake_settings, claude_fake, pdf_faked, monkeypatch
):
    """Blocked is a record, not a deletion: the promise is that the USER can
    still paste the posting text and get a finished resume. Exercise the real
    paste route on the blocked row, then run the paste pipeline to 'ready' -
    a status/fetch_status combination the paste path rejects would fail here."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]
    mcp_ops.report_fetch_blocked(engine, app_id, "login wall")

    # The paste route must accept the blocked application...
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, fn, *a, **k: None)
    resp = client.post(f"/api/applications/{app_id}/paste", json={"text": POSTING_TEXT})
    assert resp.status_code == 200, resp.text

    # ...and the pasted text must carry the pipeline all the way to ready.
    monkeypatch.setattr(pipeline, "get_settings", lambda: fake_settings)
    pipeline.resume_after_paste(app_id, POSTING_TEXT, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "ready", app.error_message
        job = session.get(Job, app.job_id)
        assert job.fetch_status == "pasted"
        assert job.raw_text == POSTING_TEXT


def test_report_fetch_blocked_rejects_a_row_that_already_has_posting_text(
    engine, profile_id
):
    """The other half of the misdirected-id guard. The pipeline check catches
    rows mid-run; this catches finished ones. A wrong application_id must not
    overwrite a pasted/fetched job with "blocked" and hang "Could not read the
    posting" on an application whose resume is already exported."""
    app_id = mcp_ops.create_application(
        engine, profile_id, "https://jobs.example.com/done", POSTING_TEXT
    )["application_id"]

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.report_fetch_blocked(engine, app_id, "403")
    assert "already has posting text" in str(exc.value)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        job = session.get(Job, app.job_id)
        assert job.raw_text == POSTING_TEXT  # untouched
        assert job.fetch_status == "pasted"  # not overwritten with "blocked"
        events = session.exec(
            select(ApplicationEvent).where(ApplicationEvent.application_id == app_id)
        ).all()
        assert events == []  # no false note on the timeline


def test_report_fetch_blocked_is_idempotent_on_a_stubborn_url(engine, profile_id):
    """Re-running a batch over the same refusing URL must stay a no-op rather
    than raise. The guard is keyed on posting text, not status, precisely so
    that a second report on an already-blocked (needs_paste) row is allowed -
    the tool exists to keep a batch moving, not to make it throw."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]

    mcp_ops.report_fetch_blocked(engine, app_id, "login wall")
    again = mcp_ops.report_fetch_blocked(engine, app_id, "login wall, still")

    assert again["status"] == "needs_paste"
    assert again["fetch_status"] == "blocked"


def test_report_fetch_blocked_rejects_an_unknown_application(engine):
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.report_fetch_blocked(engine, 9999, "nope")
    assert "9999" in str(exc.value)


def test_report_fetch_blocked_requires_a_reason(engine, profile_id):
    """A blocked row with no reason is exactly the silent failure this prevents."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    with pytest.raises(mcp_ops.McpOpsError):
        mcp_ops.report_fetch_blocked(engine, queued[0]["application_id"], "   ")


def test_save_tailored_resume_rejects_an_em_dash(engine, profile_id, tmp_path, pdf_faked):
    app_id = _create_app(engine, profile_id)
    tailor = _fixture("tailor")
    resume = tailor["resume"]
    resume["summary"] = "Eight years building payment systems — mostly in Python."

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.save_tailored_resume(
            engine, tmp_path, app_id, resume, tailor["cover_letter_md"], ""
        )
    message = str(exc.value)
    assert "Style check failed" in message
    assert "em dash" in message.lower()
    assert "Summary" in message


def test_a_style_rejection_persists_nothing(engine, profile_id, tmp_path, pdf_faked):
    app_id = _create_app(engine, profile_id)
    tailor = _fixture("tailor")
    resume = tailor["resume"]
    resume["summary"] = "I am passionate about payment systems."

    with pytest.raises(mcp_ops.McpOpsError):
        mcp_ops.save_tailored_resume(
            engine, tmp_path, app_id, resume, tailor["cover_letter_md"], ""
        )
    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.resume_json is None
        assert app.cover_letter_md is None
        assert app.status == "tailoring", "the agent must be able to correct and retry"


def test_truthfulness_is_reported_before_style(engine, profile_id, tmp_path, pdf_faked):
    """A resume that invents an employer should be reported as inventing an
    employer, not as having an em dash in the invented employer's bullet."""
    app_id = _create_app(engine, profile_id)
    tailor = _fixture("tailor")
    resume = tailor["resume"]
    resume["summary"] = "Built things — quickly."
    for section in resume["sections"]:
        if section["type"] == "experience":
            section["items"][0]["company"] = "Totally Invented Corp"
            break

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.save_tailored_resume(
            engine, tmp_path, app_id, resume, tailor["cover_letter_md"], ""
        )
    message = str(exc.value)
    assert "Truthfulness check failed" in message
    assert "Style check failed" not in message


def test_a_style_rejection_tells_the_agent_what_to_do(engine, profile_id, tmp_path, pdf_faked):
    app_id = _create_app(engine, profile_id)
    tailor = _fixture("tailor")
    resume = tailor["resume"]
    resume["summary"] = "Built things — quickly."

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.save_tailored_resume(
            engine, tmp_path, app_id, resume, tailor["cover_letter_md"], ""
        )
    assert "call this tool again" in str(exc.value)


def test_the_clean_fixture_still_saves(engine, profile_id, tmp_path, pdf_faked):
    """The style gate must not block the sample data the whole suite relies on."""
    app_id = _create_app(engine, profile_id)
    result = _save_tailor(engine, tmp_path, app_id, _fixture("tailor"))
    assert result["status"] == "ready"
