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
    set_contact,
    set_master_profile,
)
from backend.app.schemas import FetchResult
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
