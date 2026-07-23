from __future__ import annotations

from sqlmodel import Session, select

from ..config import get_settings, load_user_settings
from ..db import get_engine
from ..models import (
    Application,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
    _utcnow,
    get_contact,
    get_findings,
    get_master_profile,
    get_parsed,
    set_parsed,
)
from ..schemas import (
    Contact,
    MasterProfile,
    ParsedPosting,
    ResearchFindings,
    UsageInfo,
)
from . import fetcher, render
from .claude import ClaudeError, ClaudeService, make_claude
from .research import parse_posting, research_company
from .tailor import tailor_application, verify_truthfulness


def _set_status(session: Session, app: Application, status: str,
                error_message: str | None = None) -> None:
    """Commit a status change immediately so API pollers see progress."""
    app.status = status
    app.error_message = error_message
    app.updated_at = _utcnow()
    session.add(app)
    session.commit()
    session.refresh(app)


def _add_usage(app: Application, usage: UsageInfo) -> None:
    app.input_tokens += usage.input_tokens
    app.output_tokens += usage.output_tokens
    app.cost_usd = round(app.cost_usd + usage.cost_usd, 6)


def _run_from_research(session: Session, app: Application, job: Job,
                       claude: ClaudeService) -> None:
    """Researching -> tailoring -> rendering -> ready (Job.raw_text is set)."""
    profile = session.get(Profile, app.profile_id)
    if profile is None:
        raise ClaudeError(f"Profile {app.profile_id} not found")
    master = get_master_profile(profile)
    contact = get_contact(profile)

    _set_status(session, app, "researching")
    parsed, parse_usage = parse_posting(job.raw_text or "", claude)
    set_parsed(job, parsed)
    _add_usage(app, parse_usage)
    session.add(job)
    session.add(app)
    session.commit()

    findings: ResearchFindings | None = None
    research = research_company(parsed, job.depth, claude)
    if research is not None:  # depth "quick" returns None: no brief row
        findings, research_usage = research
        brief = ResearchBrief(
            job_id=job.id,
            depth=job.depth,
            findings_json=findings.model_dump_json(),
            input_tokens=research_usage.input_tokens,
            output_tokens=research_usage.output_tokens,
            cost_usd=research_usage.cost_usd,
        )
        _add_usage(app, research_usage)
        session.add(brief)
        session.add(app)
        session.commit()

    _tailor_and_render(session, app, master, contact, parsed, findings,
                       claude, feedback=None)


def _tailor_and_render(session: Session, app: Application,
                       master: MasterProfile, contact: Contact,
                       parsed: ParsedPosting,
                       findings: ResearchFindings | None,
                       claude: ClaudeService, feedback: str | None) -> None:
    _set_status(session, app, "tailoring")
    result, usage = tailor_application(
        master, contact, parsed, findings, app.template, claude,
        feedback=feedback,
    )
    violations = verify_truthfulness(result.resume, master)
    if violations:
        raise ClaudeError(
            "Truthfulness check failed: " + "; ".join(violations)
        )

    app.resume_json = result.resume.model_dump_json()
    app.cover_letter_md = result.cover_letter_md
    app.tailoring_notes = result.tailoring_notes
    _add_usage(app, usage)
    session.add(app)
    session.commit()
    session.refresh(app)

    snapshot = ApplicationVersion(
        application_id=app.id,
        version=app.version,
        resume_json=app.resume_json or "{}",
        cover_letter_md=app.cover_letter_md or "",
        tailoring_notes=app.tailoring_notes or "",
    )
    session.add(snapshot)
    session.commit()

    _set_status(session, app, "rendering")
    settings = get_settings()
    user_settings = load_user_settings(settings.data_dir)
    page_size = (user_settings or {}).get("page_size", "Letter")
    export_dir = render.export_application(
        app.id, result.resume, result.cover_letter_md, contact,
        app.template, settings.data_dir, page_size=page_size,
    )
    app.export_dir = str(export_dir)
    session.add(app)
    session.commit()

    _set_status(session, app, "ready")


def process_application(app_id: int, engine=None,
                        claude: ClaudeService | None = None) -> None:
    """Run the full stage machine for one application (synchronous).

    queued -> fetching -> researching -> tailoring -> rendering -> ready.
    Status is committed at every transition. needs_paste short-circuits;
    any exception lands the application in status="error".
    """
    engine = engine if engine is not None else get_engine()
    claude = claude if claude is not None else make_claude(get_settings())
    with Session(engine) as session:
        app = session.get(Application, app_id)
        if app is None:
            return
        try:
            job = session.get(Job, app.job_id)
            if job is None:
                raise ClaudeError(f"Job {app.job_id} not found")
            if not job.raw_text:  # skip fetch when text was pasted up front
                _set_status(session, app, "fetching")
                fetch_result = fetcher.fetch_posting(job.url)
                if fetch_result.status == "needs_paste":
                    job.fetch_status = "needs_paste"
                    session.add(job)
                    session.commit()
                    _set_status(session, app, "needs_paste")
                    return
                job.raw_text = fetch_result.text
                job.fetch_status = "fetched"
                session.add(job)
                session.commit()
            _run_from_research(session, app, job, claude)
        except Exception as exc:  # noqa: BLE001 - every failure is visible state
            _set_status(session, app, "error", error_message=str(exc))
