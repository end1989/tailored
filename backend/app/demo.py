"""Demo-mode seeding: one profile plus one fully processed application.

Runs only when settings.fake_mode is on and the database has no Profile rows.
Fully offline: the injected fake ClaudeService serves canned fixtures, and PDF
rendering falls back to a placeholder file when Chromium is unavailable, so the
demo never hard-fails without `playwright install chromium`.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import select

from .db import session_scope
from .models import Application, Job, Profile, set_contact, set_master_profile
from .schemas import Contact, MasterProfile
from .services import claude as claude_service
from .services import pipeline, render

DEMO_DIR = Path(__file__).resolve().parent / "fixtures" / "demo"
DEMO_JOB_URL = "https://careers.northwindlabs.example/jobs/senior-software-engineer"
PDF_PLACEHOLDER = b"%PDF-1.4\n% demo placeholder"


def seed_demo(engine, claude, data_dir) -> None:
    """Seed the demo profile + application and run the pipeline to 'ready'."""
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    with session_scope(engine) as session:
        if session.exec(select(Profile)).first() is not None:
            return

        payload = json.loads((DEMO_DIR / "profile.json").read_text(encoding="utf-8"))
        contact = Contact.model_validate(payload["contact"])
        master = MasterProfile.model_validate(payload["master_profile"])
        profile = Profile(name=contact.name)
        set_contact(profile, contact)
        set_master_profile(profile, master)
        session.add(profile)
        session.flush()  # assigns profile.id without committing

        posting_text = (DEMO_DIR / "job_posting.txt").read_text(encoding="utf-8")
        job = Job(
            url=DEMO_JOB_URL,
            raw_text=posting_text,
            fetch_status="pasted",
            depth="standard",
        )
        session.add(job)
        session.flush()  # assigns job.id without committing

        app_row = Application(
            profile_id=profile.id, job_id=job.id, template="slate", status="queued"
        )
        session.add(app_row)
        session.flush()  # assigns app_row.id without committing
        application_id = app_row.id
        # session_scope commits once here, on normal exit of the `with` block,
        # so Profile+Job+Application land atomically. An interruption before
        # this point leaves no rows at all, so the "any Profile exists" gate
        # above can never see a half-seeded demo.

    _run_pipeline_with_fake_claude(application_id, engine, claude)


def _run_pipeline_with_fake_claude(application_id: int, engine, claude) -> None:
    """Run process_application with the injected ClaudeService and a guarded render_pdf.

    - render.render_pdf is temporarily wrapped: any exception (missing Chromium)
      writes PDF_PLACEHOLDER bytes instead of failing the demo.
    - make_claude is temporarily overridden (on the claude service module and, if
      pipeline bound it by from-import, on the pipeline module) so the pipeline
      uses the injected fake service regardless of env.
    """
    original_render_pdf = render.render_pdf

    def guarded_render_pdf(html: str, out_path, page_size: str = "Letter") -> None:
        try:
            original_render_pdf(html, out_path, page_size=page_size)
        except Exception:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(PDF_PLACEHOLDER)

    patched_factories = []
    for module in (claude_service, pipeline):
        if hasattr(module, "make_claude"):
            patched_factories.append((module, module.make_claude))
            setattr(module, "make_claude", lambda _settings, _c=claude: _c)

    render.render_pdf = guarded_render_pdf
    try:
        pipeline.process_application(application_id, engine=engine)
    finally:
        render.render_pdf = original_render_pdf
        for module, original in patched_factories:
            setattr(module, "make_claude", original)
