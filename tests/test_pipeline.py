from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, select

from backend.app.models import (
    Application,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
    SourceDocument,
    set_contact,
    set_master_profile,
)
from backend.app.schemas import FetchResult, UsageInfo
from backend.app.services import fetcher, pipeline, render
from backend.app.services.claude import ClaudeService
from backend.app.services.intake import IntakeResult

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"

POSTING_TEXT = (
    "Senior Backend Engineer at Acme Robotics. Build the fleet telemetry "
    "platform. Requirements: 5+ years Python, FastAPI, PostgreSQL, AWS. "
    "Nice to have: Kubernetes, Terraform."
)


class RecordingClaude(ClaudeService):
    """Fake-mode ClaudeService that records every structured() call's kwargs."""

    def __init__(self, fixtures_dir: Path):
        super().__init__(fake_mode=True, fixtures_dir=fixtures_dir)

    def structured(self, *, task, system, user_content, schema_model,
                   tools=None, max_tokens=16000):
        result = super().structured(
            task=task, system=system, user_content=user_content,
            schema_model=schema_model, tools=tools, max_tokens=max_tokens,
        )
        self.calls[-1] = {
            "task": task,
            "system": system,
            "user_content": user_content,
            "schema_model": schema_model,
            "tools": tools,
            "max_tokens": max_tokens,
        }
        return result


@pytest.fixture()
def claude_fake() -> RecordingClaude:
    return RecordingClaude(FIXTURES_DIR)


class BilledClaude(RecordingClaude):
    """Fake-mode ClaudeService stand-in that reports nonzero usage.

    Fake mode otherwise reports UsageInfo(0, 0, 0.0) for every call, which
    makes accumulated usage indistinguishable between one and two attempts.
    This stand-in reports fixed nonzero usage per call so a test can assert
    that a retry's accumulated usage is strictly greater than a clean run's.
    """

    def structured(self, *, task, system, user_content, schema_model,
                   tools=None, max_tokens=16000):
        model, _usage = super().structured(
            task=task, system=system, user_content=user_content,
            schema_model=schema_model, tools=tools, max_tokens=max_tokens,
        )
        return model, UsageInfo(input_tokens=1000, output_tokens=200, cost_usd=0.01)


@pytest.fixture()
def pipeline_settings(fake_settings, monkeypatch):
    """Route pipeline.get_settings() to the tmp-dir Settings from conftest."""
    monkeypatch.setattr(pipeline, "get_settings", lambda: fake_settings)
    return fake_settings


@pytest.fixture()
def fetched_ok(monkeypatch):
    monkeypatch.setattr(
        fetcher, "fetch_posting",
        lambda url, timeout=20.0: FetchResult(status="fetched", text=POSTING_TEXT),
    )


@pytest.fixture()
def pdf_faked(monkeypatch):
    """Replace Playwright PDF rendering with a fake PDF byte-write.

    HTML/txt exports stay real; only chromium is avoided.
    """

    def _fake_pdf(html: str, out_path, page_size: str = "Letter") -> None:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(render, "render_pdf", _fake_pdf)


def seed_application(engine, claude_fake, depth="standard", template="slate") -> int:
    """Create Profile (from the intake fixture) + Job + queued Application."""
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
        job = Job(url="https://jobs.example.com/senior-backend", depth=depth)
        session.add(job)
        session.commit()
        session.refresh(job)
        app = Application(profile_id=profile.id, job_id=job.id, template=template)
        session.add(app)
        session.commit()
        session.refresh(app)
        return app.id


def test_process_application_reaches_ready_with_exports(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
):
    app_id = seed_application(engine, claude_fake, depth="standard")
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "ready"
        assert app.error_message is None
        assert app.version == 1
        assert app.resume_json
        assert app.cover_letter_md
        assert isinstance(app.input_tokens, int)
        assert isinstance(app.output_tokens, int)
        assert isinstance(app.cost_usd, float)
        assert app.export_dir
        export_dir = Path(app.export_dir)

        job = session.get(Job, app.job_id)
        assert job.fetch_status == "fetched"
        assert job.raw_text == POSTING_TEXT
        assert job.parsed_json

        briefs = session.exec(
            select(ResearchBrief).where(ResearchBrief.job_id == job.id)
        ).all()
        assert len(briefs) == 1

        versions = session.exec(
            select(ApplicationVersion).where(
                ApplicationVersion.application_id == app_id
            )
        ).all()
        assert len(versions) == 1
        assert versions[0].version == 1

    assert (export_dir / "resume.html").read_text(encoding="utf-8")
    assert (export_dir / "resume.txt").read_text(encoding="utf-8")
    assert (export_dir / "cover_letter.txt").read_text(encoding="utf-8")
    assert (export_dir / "resume.pdf").read_bytes() == b"%PDF-1.4 fake"
    assert (export_dir / "cover_letter.pdf").read_bytes() == b"%PDF-1.4 fake"

    tasks = [c["task"] for c in claude_fake.calls]
    assert tasks == ["intake", "parse_posting", "research_standard", "tailor"]


def test_quick_depth_skips_research(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
):
    app_id = seed_application(engine, claude_fake, depth="quick")
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "ready"
        job = session.get(Job, app.job_id)
        briefs = session.exec(
            select(ResearchBrief).where(ResearchBrief.job_id == job.id)
        ).all()
        assert briefs == []

    tasks = [c["task"] for c in claude_fake.calls]
    assert "research_standard" not in tasks
    assert "research_deep" not in tasks


def test_needs_paste_short_circuits(
    engine, claude_fake, pipeline_settings, pdf_faked, monkeypatch
):
    monkeypatch.setattr(
        fetcher, "fetch_posting",
        lambda url, timeout=20.0: FetchResult(status="needs_paste", reason="HTTP 403"),
    )
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "needs_paste"
        job = session.get(Job, app.job_id)
        assert job.fetch_status == "needs_paste"

    tasks = [c["task"] for c in claude_fake.calls]
    assert tasks == ["intake"]  # only the seeding call; no pipeline API calls


def test_truthfulness_failure_sets_error(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    monkeypatch.setattr(
        pipeline, "verify_truthfulness",
        lambda resume, profile: [
            "Experience 'CTO' at 'Fake Corp' (2020 to 2024) does not match "
            "any master-profile experience"
        ],
    )
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "error"
        assert "Fake Corp" in (app.error_message or "")


def test_mark_error_writes_status_after_failed_transaction(engine, claude_fake):
    """_mark_error must record status='error' even when the session's
    transaction already failed (e.g. a SQLite "database is locked"
    OperationalError during a prior commit).

    A raw "SELECT from a nonexistent table" does NOT poison a SQLAlchemy
    Session on SQLite (verified empirically: the DBAPI error is local to
    that statement). The state this bug is about -- Session.commit()
    raising PendingRollbackError on the *next* operation -- only appears
    after a failed ORM flush/commit. So this test provokes it genuinely:
    it forces a real flush failure (duplicate primary key -> IntegrityError
    on commit) on an unrelated row, leaving the session's transaction
    unusable, then calls `_mark_error` on the already-loaded `app` row.
    """
    app_id = seed_application(engine, claude_fake)
    with Session(engine) as session:
        job_id = session.get(Application, app_id).job_id
        app_row = session.get(Application, app_id)

        # Poison the session's transaction with a genuine flush failure.
        dup_job = Job(id=job_id, url="https://dup.example.com", depth="standard")
        session.add(dup_job)
        try:
            session.commit()
        except Exception:
            pass  # session's transaction now requires a rollback

        pipeline._mark_error(session, app_row, "boom")

    with Session(engine) as check:
        row = check.get(Application, app_id)
        assert row.status == "error"
        assert row.error_message == "boom"


def test_resume_after_paste_completes_needs_paste_application(
    engine, claude_fake, pipeline_settings, pdf_faked, monkeypatch
):
    monkeypatch.setattr(
        fetcher, "fetch_posting",
        lambda url, timeout=20.0: FetchResult(status="needs_paste", reason="HTTP 403"),
    )
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        assert session.get(Application, app_id).status == "needs_paste"

    pipeline.resume_after_paste(app_id, POSTING_TEXT, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "ready"
        assert app.export_dir
        job = session.get(Job, app.job_id)
        assert job.fetch_status == "pasted"
        assert job.raw_text == POSTING_TEXT


def test_regenerate_bumps_version_and_snapshots(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
):
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)
    pipeline.regenerate_application(
        app_id, "Lead with the migration project", engine=engine, claude=claude_fake
    )

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "ready"
        assert app.version == 2
        versions = session.exec(
            select(ApplicationVersion)
            .where(ApplicationVersion.application_id == app_id)
            .order_by(ApplicationVersion.version)
        ).all()
        assert [v.version for v in versions] == [1, 2]

    tailor_calls = [c for c in claude_fake.calls if c["task"] == "tailor"]
    assert len(tailor_calls) == 2
    assert "Lead with the migration project" in tailor_calls[-1]["user_content"]


def _style_failure_once():
    """A check_style stand-in that fails the first call and passes after."""
    calls = {"n": 0}

    def _check(resume, cover_md):
        calls["n"] += 1
        return ["Summary: em dash. Rewrite the sentence."] if calls["n"] == 1 else []

    return _check, calls


def test_a_style_failure_retries_tailoring_once_and_succeeds(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    check, calls = _style_failure_once()
    monkeypatch.setattr(pipeline, "check_style", check)
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "ready"
    assert calls["n"] == 2, "expected exactly one retry"


def test_the_retry_passes_the_violations_back_to_the_model(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    """A retry that does not say what was wrong is just a second dice roll."""
    check, _calls = _style_failure_once()
    monkeypatch.setattr(pipeline, "check_style", check)
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    tailor_calls = [c for c in claude_fake.calls if c.get("task") == "tailor"]
    assert len(tailor_calls) == 2
    assert "em dash" in tailor_calls[-1]["user_content"]
    assert "em dash" not in tailor_calls[0]["user_content"]


def test_two_style_failures_mark_the_application_error(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    monkeypatch.setattr(
        pipeline,
        "check_style",
        lambda resume, cover_md: ["Summary: em dash. Rewrite the sentence."],
    )
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "error"
        assert "Style check failed" in (app.error_message or "")
        assert "em dash" in (app.error_message or "")


def test_a_style_failure_never_loops(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    """Exactly two tailoring calls, never three. Burning tokens in a cycle is
    worse than surfacing the problem."""
    monkeypatch.setattr(
        pipeline, "check_style", lambda resume, cover_md: ["Summary: em dash."]
    )
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    assert len([c for c in claude_fake.calls if c.get("task") == "tailor"]) == 2


def test_the_retry_is_billed(
    engine, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    """Two API calls cost two API calls. A cost that hides the retry is a lie."""
    claude = BilledClaude(FIXTURES_DIR)
    check, _calls = _style_failure_once()
    monkeypatch.setattr(pipeline, "check_style", check)
    retried_id = seed_application(engine, claude)
    pipeline.process_application(retried_id, engine=engine, claude=claude)

    monkeypatch.setattr(pipeline, "check_style", lambda resume, cover_md: [])
    clean_id = seed_application(engine, claude)
    pipeline.process_application(clean_id, engine=engine, claude=claude)

    with Session(engine) as session:
        retried = session.get(Application, retried_id)
        clean = session.get(Application, clean_id)
        assert retried.input_tokens > clean.input_tokens
        assert retried.cost_usd > clean.cost_usd


def test_truthfulness_is_still_never_retried(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    monkeypatch.setattr(
        pipeline, "verify_truthfulness", lambda resume, profile: ["invented Fake Corp"]
    )
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "error"
        assert "Truthfulness" in (app.error_message or "")
    assert len([c for c in claude_fake.calls if c.get("task") == "tailor"]) == 1


def test_a_retry_that_becomes_untruthful_is_rejected(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    """Both gates run on the retry, not just the one that failed."""
    style_calls = {"n": 0}

    def _style(resume, cover_md):
        style_calls["n"] += 1
        return ["Summary: em dash."] if style_calls["n"] == 1 else []

    truth_calls = {"n": 0}

    def _truth(resume, profile):
        truth_calls["n"] += 1
        return [] if truth_calls["n"] == 1 else ["invented Fake Corp"]

    monkeypatch.setattr(pipeline, "check_style", _style)
    monkeypatch.setattr(pipeline, "verify_truthfulness", _truth)
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "error"
        assert "Truthfulness" in (app.error_message or "")


def test_a_clean_generation_makes_exactly_one_tailoring_call(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
):
    """The retry must not fire on the happy path."""
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        assert session.get(Application, app_id).status == "ready"
    assert len([c for c in claude_fake.calls if c.get("task") == "tailor"]) == 1


def test_the_pipeline_passes_voice_notes_to_the_model(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
):
    app_id = seed_application(engine, claude_fake)
    with Session(engine) as session:
        app = session.get(Application, app_id)
        profile = session.get(Profile, app.profile_id)
        profile.voice_notes = "Plain and direct. Short sentences."
        session.add(profile)
        session.commit()

    pipeline.process_application(app_id, engine=engine, claude=claude_fake)
    tailor_calls = [c for c in claude_fake.calls if c.get("task") == "tailor"]
    assert "Plain and direct. Short sentences." in tailor_calls[-1]["user_content"]


def test_the_pipeline_passes_the_most_recent_source_document_as_voice(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
):
    app_id = seed_application(engine, claude_fake)
    with Session(engine) as session:
        app = session.get(Application, app_id)
        session.add(
            SourceDocument(
                profile_id=app.profile_id, filename="old.txt", kind="txt",
                text="OLDER WRITING SAMPLE",
            )
        )
        session.commit()
        session.add(
            SourceDocument(
                profile_id=app.profile_id, filename="new.txt", kind="txt",
                text="NEWER WRITING SAMPLE",
            )
        )
        session.commit()

    pipeline.process_application(app_id, engine=engine, claude=claude_fake)
    content = [c for c in claude_fake.calls if c.get("task") == "tailor"][-1]["user_content"]
    assert "NEWER WRITING SAMPLE" in content
    assert "OLDER WRITING SAMPLE" not in content


def test_a_voice_sample_cannot_smuggle_in_an_employer(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    """The voice sample is style-only, and truthfulness is what makes that true.

    A model that lifts an employer out of the sample is rejected by the existing
    structural guard, which is the argument for having built it structurally.
    """
    app_id = seed_application(engine, claude_fake)
    with Session(engine) as session:
        app = session.get(Application, app_id)
        session.add(
            SourceDocument(
                profile_id=app.profile_id, filename="v.txt", kind="txt",
                text="At Nonexistent Holdings I ran the whole platform.",
            )
        )
        session.commit()

    # Simulate the model taking the bait.
    real = pipeline.verify_truthfulness

    def _tempted(resume, profile):
        for section in resume.sections:
            if section.type == "experience" and section.items:
                section.items[0].company = "Nonexistent Holdings"
                break
        return real(resume, profile)

    monkeypatch.setattr(pipeline, "verify_truthfulness", _tempted)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "error"
        assert "Nonexistent Holdings" in (app.error_message or "")
