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
