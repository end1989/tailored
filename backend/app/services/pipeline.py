from __future__ import annotations

import functools
import threading
from collections import Counter
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable, Iterator

from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_engine
from ..models import (
    Application,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
    SourceDocument,
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
from .person_settings import settings_for
from .research import parse_posting, research_company
from .style import check_style
from .tailor import tailor_application, verify_truthfulness

if TYPE_CHECKING:
    from fastapi import BackgroundTasks

# Application ids with a pipeline run scheduled or in progress in this
# process, counted per id: two overlapping runs on one row (a retry on a row
# that is already queued) each hold it, so the first to finish cannot release
# the other. Person removal and single-application delete treat these as live
# however long their row has sat in one status (a deep-research step can
# outlast the staleness cutoff). A run killed by a restart is never here, so
# its stale row still clears. Background tasks run in a threadpool, hence the
# lock.
_live_counts: Counter[int] = Counter()
_live_lock = threading.Lock()


def live_application_ids() -> frozenset[int]:
    """Ids of applications with a pipeline run scheduled or in progress in
    this process."""
    with _live_lock:
        return frozenset(i for i, n in _live_counts.items() if n > 0)


def is_live(app_id: int) -> bool:
    with _live_lock:
        return _live_counts.get(app_id, 0) > 0


def _register(app_id: int) -> None:
    with _live_lock:
        _live_counts[app_id] += 1


def _release(app_id: int) -> None:
    """Drop one registration of app_id; the key goes when the count reaches 0."""
    with _live_lock:
        remaining = _live_counts.get(app_id, 0) - 1
        if remaining > 0:
            _live_counts[app_id] = remaining
        else:
            _live_counts.pop(app_id, None)


@contextmanager
def live_run(app_id: int) -> Iterator[None]:
    """Register app_id as live for the duration of the block, even if it raises."""
    _register(app_id)
    try:
        yield
    finally:
        _release(app_id)


def _run_then_release(func: Callable[..., Any], app_id: int, *args: Any) -> None:
    try:
        func(app_id, *args)
    finally:
        _release(app_id)


def schedule_run(background_tasks: BackgroundTasks, func: Callable[..., Any],
                 app_id: int, *args: Any) -> None:
    """Schedule func(app_id, *args) as a background task, with app_id live
    from now until the task finishes or raises.

    The task starts only after the response is sent, so registering here, not
    in the task, is what covers the gap in which a delete would otherwise see
    nothing running. Call it last in a route, after anything that can raise:
    a route that fails after scheduling never runs its tasks, and the id would
    stay live until restart."""
    _register(app_id)
    try:
        background_tasks.add_task(_run_then_release, func, app_id, *args)
    except BaseException:
        _release(app_id)
        raise


def _registers_live_run(func):
    """Run a pipeline entry point (first argument: app_id) inside live_run."""
    @functools.wraps(func)
    def wrapper(app_id: int, *args, **kwargs):
        with live_run(app_id):
            return func(app_id, *args, **kwargs)
    return wrapper


def _set_status(session: Session, app: Application, status: str,
                error_message: str | None = None) -> None:
    """Commit a status change immediately so API pollers see progress."""
    app.status = status
    app.error_message = error_message
    app.updated_at = _utcnow()
    session.add(app)
    session.commit()
    session.refresh(app)


def _mark_error(session: Session, app: Application, message: str) -> None:
    """Write status='error' even if the session's transaction has failed."""
    session.rollback()
    _set_status(session, app, "error", error_message=message)


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

    _tailor_and_render(session, app, profile, master, contact, parsed, findings,
                       claude, feedback=None)


def _style_retry_feedback(feedback: str | None, violations: list[str]) -> str:
    """The original feedback plus the style violations, for the single retry.

    A retry that does not say what was wrong is just a second dice roll, so the
    violations are passed back verbatim; they are written to be actionable.
    """
    block = (
        "STYLE VIOLATIONS in your previous attempt. Rewrite the flagged text "
        "in the candidate's own plain voice, keeping every fact unchanged:\n- "
        + "\n- ".join(violations)
    )
    return f"{feedback}\n\n{block}" if feedback else block


def _voice_for(session: Session, profile: Profile) -> tuple[str | None, str | None]:
    """(voice_sample, voice_notes) for a profile.

    The sample is the most recent document the user uploaded during intake:
    their own writing, already in the database. It is style-only, and
    verify_truthfulness is what makes that safe.
    """
    latest = session.exec(
        select(SourceDocument)
        .where(SourceDocument.profile_id == profile.id)
        .order_by(SourceDocument.id.desc())
    ).first()
    sample = latest.text if latest is not None and latest.text else None
    return sample, (profile.voice_notes or None)


def _tailor_and_render(session: Session, app: Application, profile: Profile,
                       master: MasterProfile, contact: Contact,
                       parsed: ParsedPosting,
                       findings: ResearchFindings | None,
                       claude: ClaudeService, feedback: str | None) -> None:
    _set_status(session, app, "tailoring")

    # One retry, never a loop. A second failure means something is wrong with
    # the rules or the model, and burning tokens in a cycle is worse than
    # surfacing it. Both gates run on every attempt: a retry that fixes an em
    # dash but invents an employer must still be rejected for inventing one.
    #
    # The profile is passed in rather than looked up again: both callers have
    # already fetched it and already raised a clear error if it was missing.
    voice_sample, voice_notes = _voice_for(session, profile)
    attempt_feedback = feedback
    result = None
    for attempt in (0, 1):
        result, usage = tailor_application(
            master, contact, parsed, findings, app.template, claude,
            feedback=attempt_feedback,
            voice_sample=voice_sample, voice_notes=voice_notes,
        )
        _add_usage(app, usage)
        # Commit the cost before the gates run. A gate raises, _mark_error
        # rolls back, and tokens already spent would otherwise vanish from the
        # ledger; the user paid for them either way.
        session.add(app)
        session.commit()

        violations = verify_truthfulness(result.resume, master)
        if violations:
            raise ClaudeError(
                "Truthfulness check failed: " + "; ".join(violations)
            )

        style_violations = check_style(result.resume, result.cover_letter_md)
        if not style_violations:
            break
        if attempt == 1:
            raise ClaudeError(
                "Style check failed: " + "; ".join(style_violations)
            )
        attempt_feedback = _style_retry_feedback(feedback, style_violations)

    app.resume_json = result.resume.model_dump_json()
    app.cover_letter_md = result.cover_letter_md
    app.tailoring_notes = result.tailoring_notes
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
    # The owner's page size (spec 5.2): `profile` is this application's owner.
    page_size = settings_for(settings.data_dir, profile).get("page_size", "Letter")
    export_dir = render.export_application(
        app.id, result.resume, result.cover_letter_md, contact,
        app.template, settings.data_dir, page_size=page_size,
    )
    app.export_dir = str(export_dir)
    session.add(app)
    session.commit()

    # The one place status drives stage: finishing generation moves a parked
    # job to drafted. Any other stage is the user's and is left alone.
    if app.stage == "saved":
        app.stage = "drafted"
        session.add(app)
        session.commit()

    _set_status(session, app, "ready")


@_registers_live_run
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
            _mark_error(session, app, str(exc))


@_registers_live_run
def resume_after_paste(app_id: int, text: str, engine=None,
                       claude: ClaudeService | None = None) -> None:
    """User pasted the posting text: store it and continue from researching."""
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
            job.raw_text = text
            job.fetch_status = "pasted"
            session.add(job)
            session.commit()
            _run_from_research(session, app, job, claude)
        except Exception as exc:  # noqa: BLE001
            _mark_error(session, app, str(exc))


@_registers_live_run
def regenerate_application(app_id: int, feedback: str, engine=None,
                           claude: ClaudeService | None = None) -> None:
    """Re-tailor with user feedback: version += 1, new snapshot, re-render."""
    engine = engine if engine is not None else get_engine()
    claude = claude if claude is not None else make_claude(get_settings())
    with Session(engine) as session:
        app = session.get(Application, app_id)
        if app is None:
            return
        try:
            job = session.get(Job, app.job_id)
            profile = session.get(Profile, app.profile_id)
            if job is None or profile is None:
                raise ClaudeError("Application is missing its job or profile row")
            parsed = get_parsed(job)
            if parsed is None:
                raise ClaudeError(
                    "Cannot regenerate before the posting has been parsed"
                )
            master = get_master_profile(profile)
            contact = get_contact(profile)
            findings: ResearchFindings | None = None
            brief = session.exec(
                select(ResearchBrief)
                .where(ResearchBrief.job_id == job.id)
                .order_by(ResearchBrief.id.desc())
            ).first()
            if brief is not None:
                findings = get_findings(brief)
            app.version += 1
            session.add(app)
            session.commit()
            session.refresh(app)
            _tailor_and_render(session, app, profile, master, contact, parsed,
                               findings, claude, feedback=feedback)
        except Exception as exc:  # noqa: BLE001
            _mark_error(session, app, str(exc))
