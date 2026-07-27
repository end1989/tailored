"""Application routes: batch create, list/detail, paste, regenerate, content edit,
HTML preview, and export downloads."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import func
from sqlmodel import Session, select

from ..config import load_user_settings
from ..db import get_session
from ..models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    EVENT_KINDS,
    Job,
    Profile,
    ResearchBrief,
    STAGES,
    _utcnow,
    get_contact,
    get_findings,
    get_parsed,
    get_resume,
    set_resume,
)
from ..schemas import ResumeDoc
from ..services import pipeline, render
from ..services.render import TEMPLATES

router = APIRouter()

PROCESSING_STATUSES = ("fetching", "researching", "tailoring", "rendering")

DEPTHS = ("quick", "standard", "deep")
EXPORT_KINDS = (
    "resume.pdf",
    "resume.html",
    "resume.txt",
    "cover_letter.pdf",
    "cover_letter.txt",
)


# --- Serializers -----------------------------------------------------------


def application_summary(
    app_row: Application, job: Job, last_activity_at: datetime | None = None
) -> dict[str, Any]:
    parsed = get_parsed(job)
    return {
        "id": app_row.id,
        "profile_id": app_row.profile_id,
        "status": app_row.status,
        "stage": app_row.stage,
        "applied_at": app_row.applied_at.replace(tzinfo=timezone.utc).isoformat()
            if app_row.applied_at else None,
        "archived_at": app_row.archived_at.replace(tzinfo=timezone.utc).isoformat()
            if app_row.archived_at else None,
        "version": app_row.version,
        "template": app_row.template,
        "depth": job.depth,
        "url": job.url,
        "company": parsed.company if parsed is not None else None,
        "title": parsed.title if parsed is not None else None,
        "cost_usd": app_row.cost_usd,
        "created_at": app_row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "last_activity_at": (last_activity_at or app_row.created_at)
            .replace(tzinfo=timezone.utc).isoformat(),
        "error_message": app_row.error_message,
    }


def application_detail(
    session: Session, app_row: Application, job: Job
) -> dict[str, Any]:
    events = _events_for(session, app_row.id)
    detail = application_summary(
        app_row, job, events[0].occurred_at if events else None
    )
    resume = get_resume(app_row)
    parsed = get_parsed(job)
    brief = session.exec(
        select(ResearchBrief)
        .where(ResearchBrief.job_id == job.id)
        .order_by(ResearchBrief.id.desc())
    ).first()
    detail.update(
        {
            "resume": resume.model_dump() if resume is not None else None,
            "cover_letter_md": app_row.cover_letter_md,
            "tailoring_notes": app_row.tailoring_notes,
            "research": get_findings(brief).model_dump() if brief is not None else None,
            "parsed": parsed.model_dump() if parsed is not None else None,
            "raw_text_present": bool(job.raw_text),
            "events": [event_payload(e) for e in events],
        }
    )
    return detail


def _get_app_and_job(session: Session, application_id: int) -> tuple[Application, Job]:
    app_row = session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    job = session.get(Job, app_row.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found for application")
    return app_row, job


def _remove_export_dir(data_dir: Path, application_id: int) -> bool:
    """Delete data/exports/<application_id>/ recursively.

    The path is rebuilt from data_dir and the integer id -- never from the
    stored Application.export_dir string, which is user-visible state that
    could be stale or wrong. The containment check is defence in depth: it is
    unreachable through the route because application_id is typed int, but it
    protects any future caller -- it also rejects "", ".", and traversal like
    "5/../6", which an untyped caller could plausibly produce.

    A missing directory is not an error. Returns True if the directory was
    removed (or was already absent), False if removal was attempted but
    failed (e.g. a file held open by another process). Callers must not let
    that failure raise: by the time this runs, the DB rows are already
    committed as deleted, so an exception here would surface as a false
    "delete failed" while the application has in fact vanished. The
    containment refusal is the one exception that still raises -- it signals
    a programming error, not an operational one, and must stay loud.
    """
    data_dir = Path(data_dir).resolve()
    target = (data_dir / "exports" / str(application_id)).resolve()
    if not target.is_dir():
        return True
    if target.parent != data_dir / "exports":
        raise HTTPException(
            status_code=500, detail="refusing to delete outside the data directory"
        )
    try:
        shutil.rmtree(target)
    except OSError:
        return False
    return True


def _naive_utc(dt: datetime) -> datetime:
    """Project convention: datetimes are stored naive, in UTC."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def event_payload(ev: ApplicationEvent) -> dict[str, Any]:
    return {
        "id": ev.id,
        "application_id": ev.application_id,
        "kind": ev.kind,
        "body": ev.body,
        "occurred_at": ev.occurred_at.replace(tzinfo=timezone.utc).isoformat(),
        "created_at": ev.created_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def _events_for(session: Session, application_id: int) -> list[ApplicationEvent]:
    return list(session.exec(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .order_by(ApplicationEvent.occurred_at.desc(), ApplicationEvent.id.desc())
    ).all())


# --- Request bodies --------------------------------------------------------


class BatchJobIn(BaseModel):
    url: str
    depth: Optional[str] = None
    template: Optional[str] = None


class BatchRequest(BaseModel):
    profile_id: int
    jobs: list[BatchJobIn]
    default_depth: Optional[str] = None
    default_template: Optional[str] = None
    generate: bool = True


class PasteRequest(BaseModel):
    text: str


class RegenerateRequest(BaseModel):
    feedback: str = ""


class ContentUpdate(BaseModel):
    resume: Optional[dict] = None
    cover_letter_md: Optional[str] = None


class ApplicationPatch(BaseModel):
    stage: Optional[str] = None


class EventIn(BaseModel):
    kind: str
    body: str = ""
    occurred_at: Optional[datetime] = None


# --- Routes ----------------------------------------------------------------


@router.post("/applications/batch")
def create_batch(
    body: BatchRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    profile = session.get(Profile, body.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    if not body.jobs:
        raise HTTPException(status_code=422, detail="jobs must not be empty")

    user_settings = load_user_settings(request.app.state.settings.data_dir)
    fallback_depth = body.default_depth or user_settings.get("default_depth", "standard")
    fallback_template = body.default_template or user_settings.get(
        "default_template", "slate"
    )

    # Validate everything before creating anything (all-or-nothing).
    resolved: list[tuple[str, str, str]] = []
    for j in body.jobs:
        depth = j.depth or fallback_depth
        template = j.template or fallback_template
        if depth not in DEPTHS:
            raise HTTPException(
                status_code=422,
                detail=f"invalid depth {depth!r}; must be one of {list(DEPTHS)}",
            )
        if template not in TEMPLATES:
            raise HTTPException(
                status_code=422,
                detail=f"invalid template {template!r}; must be one of {list(TEMPLATES)}",
            )
        resolved.append((j.url, depth, template))

    results: list[dict[str, Any]] = []
    for url, depth, template in resolved:
        job = Job(url=url, depth=depth)
        session.add(job)
        session.commit()
        session.refresh(job)
        app_row = Application(
            profile_id=body.profile_id,
            job_id=job.id,
            template=template,
            status="queued" if body.generate else "not_started",
        )
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
        if body.generate:
            # Schedule through the module attribute so tests can monkeypatch pipeline.
            background_tasks.add_task(pipeline.process_application, app_row.id)
        results.append(application_detail(session, app_row, job))
    return results


@router.get("/applications")
def list_applications(
    profile_id: Optional[int] = None,
    stage: Optional[str] = None,
    archived: bool = False,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    if stage is not None and stage not in STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid stage {stage!r}; must be one of {list(STAGES)}",
        )
    stmt = select(Application)
    if profile_id is not None:
        stmt = stmt.where(Application.profile_id == profile_id)
    if stage is not None:
        stmt = stmt.where(Application.stage == stage)
    if archived:
        stmt = stmt.where(Application.archived_at.is_not(None))
    else:
        stmt = stmt.where(Application.archived_at.is_(None))
    rows = session.exec(stmt.order_by(Application.id.desc())).all()
    latest = dict(session.exec(
        select(ApplicationEvent.application_id,
               func.max(ApplicationEvent.occurred_at))
        .group_by(ApplicationEvent.application_id)
    ).all())
    out: list[dict[str, Any]] = []
    for app_row in rows:
        job = session.get(Job, app_row.job_id)
        if job is not None:
            out.append(application_summary(app_row, job, latest.get(app_row.id)))
    return out


@router.get("/applications/{application_id}")
def get_application(
    application_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    app_row, job = _get_app_and_job(session, application_id)
    return application_detail(session, app_row, job)


@router.patch("/applications/{application_id}")
def patch_application(
    application_id: int,
    body: ApplicationPatch,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Update tracker fields. `stage` is the job-hunt funnel and is deliberately
    independent of `status`, which is the generation pipeline."""
    app_row, job = _get_app_and_job(session, application_id)
    if body.stage is not None:
        if body.stage not in STAGES:
            raise HTTPException(
                status_code=422,
                detail=f"invalid stage {body.stage!r}; must be one of {list(STAGES)}",
            )
        if body.stage == "saved" and app_row.status == "ready":
            raise HTTPException(
                status_code=422,
                detail="cannot move a generated application back to 'saved'; "
                       "its documents already exist",
            )
        app_row.stage = body.stage
        if body.stage == "applied" and app_row.applied_at is None:
            app_row.applied_at = _utcnow()
        app_row.updated_at = _utcnow()
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
    return application_detail(session, app_row, job)


@router.post("/applications/{application_id}/archive")
def archive_application(
    application_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Reversible removal: drops off the dashboard, keeps rows and exports."""
    app_row, job = _get_app_and_job(session, application_id)
    app_row.archived_at = _utcnow()
    app_row.updated_at = _utcnow()
    session.add(app_row)
    session.commit()
    session.refresh(app_row)
    return application_detail(session, app_row, job)


@router.post("/applications/{application_id}/restore")
def restore_application(
    application_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    app_row, job = _get_app_and_job(session, application_id)
    app_row.archived_at = None
    app_row.updated_at = _utcnow()
    session.add(app_row)
    session.commit()
    session.refresh(app_row)
    return application_detail(session, app_row, job)


@router.post("/applications/{application_id}/paste")
def paste_text(
    application_id: int,
    body: PasteRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    app_row, job = _get_app_and_job(session, application_id)
    if app_row.status in PROCESSING_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"application is currently {app_row.status}; wait for it to finish",
        )
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")
    background_tasks.add_task(pipeline.resume_after_paste, app_row.id, body.text)
    return application_detail(session, app_row, job)


@router.post("/applications/{application_id}/regenerate")
def regenerate(
    application_id: int,
    body: RegenerateRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    app_row, job = _get_app_and_job(session, application_id)
    if app_row.status in PROCESSING_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"application is currently {app_row.status}; wait for it to finish",
        )
    if not body.feedback.strip():
        raise HTTPException(status_code=422, detail="feedback must not be empty")
    background_tasks.add_task(pipeline.regenerate_application, app_row.id, body.feedback)
    return application_detail(session, app_row, job)


@router.post("/applications/{application_id}/retry")
def retry(
    application_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Re-run the full pipeline for a failed (or stuck) application.

    Unlike /regenerate this works even before the posting has been parsed, so
    every error state has a working retry action (spec section 8).
    """
    app_row, job = _get_app_and_job(session, application_id)
    if app_row.status in PROCESSING_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"application is currently {app_row.status}; wait for it to finish",
        )
    app_row.status = "queued"
    app_row.error_message = None
    app_row.updated_at = _utcnow()
    session.add(app_row)
    session.commit()
    session.refresh(app_row)
    background_tasks.add_task(pipeline.process_application, app_row.id)
    return application_detail(session, app_row, job)


@router.post("/applications/{application_id}/generate")
def generate(
    application_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Start the pipeline for a saved job. /retry covers every other state."""
    app_row, job = _get_app_and_job(session, application_id)
    if app_row.status != "not_started":
        raise HTTPException(
            status_code=409,
            detail=f"application is {app_row.status!r}, not 'not_started'; "
                   "use /retry to re-run it",
        )
    app_row.status = "queued"
    app_row.error_message = None
    app_row.updated_at = _utcnow()
    session.add(app_row)
    session.commit()
    session.refresh(app_row)
    background_tasks.add_task(pipeline.process_application, app_row.id)
    return application_detail(session, app_row, job)


@router.put("/applications/{application_id}/content")
def update_content(
    application_id: int,
    body: ContentUpdate,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    app_row, job = _get_app_and_job(session, application_id)
    if body.resume is not None:
        try:
            resume_doc = ResumeDoc.model_validate(body.resume)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid resume document: {exc}"
            ) from exc
        set_resume(app_row, resume_doc)
    if body.cover_letter_md is not None:
        app_row.cover_letter_md = body.cover_letter_md
    app_row.updated_at = _utcnow()
    session.add(app_row)
    session.commit()
    session.refresh(app_row)

    resume_now = get_resume(app_row)
    if resume_now is not None:
        # Re-export synchronously. No Claude call. Called through the render
        # module attribute so tests can monkeypatch export_application.
        profile = session.get(Profile, app_row.profile_id)
        settings = request.app.state.settings
        user_settings = load_user_settings(settings.data_dir)
        export_dir = render.export_application(
            app_row.id,
            resume_now,
            app_row.cover_letter_md or "",
            get_contact(profile),
            app_row.template,
            settings.data_dir,
            page_size=user_settings.get("page_size", "Letter"),
        )
        app_row.export_dir = str(export_dir)
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
    return application_detail(session, app_row, job)


@router.get("/applications/{application_id}/preview")
def preview(
    application_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    app_row, _job = _get_app_and_job(session, application_id)
    resume = get_resume(app_row)
    if resume is None:
        raise HTTPException(status_code=404, detail="no resume generated yet")
    return HTMLResponse(render.render_resume_html(resume, app_row.template))


@router.get("/applications/{application_id}/exports/{kind}")
def download_export(
    application_id: int,
    kind: str,
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse:
    app_row, _job = _get_app_and_job(session, application_id)
    if kind not in EXPORT_KINDS:
        raise HTTPException(status_code=404, detail=f"unknown export kind {kind!r}")
    if app_row.export_dir:
        base = Path(app_row.export_dir)
    else:
        base = Path(request.app.state.settings.data_dir) / "exports" / str(app_row.id)
    path = base / kind
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"export {kind!r} not generated yet")
    return FileResponse(path, filename=kind)


@router.get("/applications/{application_id}/events")
def list_events(
    application_id: int, session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    _get_app_and_job(session, application_id)
    return [event_payload(e) for e in _events_for(session, application_id)]


@router.post("/applications/{application_id}/events")
def add_event(
    application_id: int, body: EventIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    _get_app_and_job(session, application_id)
    if body.kind not in EVENT_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"invalid kind {body.kind!r}; must be one of {list(EVENT_KINDS)}",
        )
    event = ApplicationEvent(
        application_id=application_id,
        kind=body.kind,
        body=body.body,
        occurred_at=_naive_utc(body.occurred_at) if body.occurred_at else _utcnow(),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event_payload(event)


@router.delete("/applications/{application_id}/events/{event_id}")
def delete_event(
    application_id: int, event_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    event = session.get(ApplicationEvent, event_id)
    if event is None or event.application_id != application_id:
        raise HTTPException(status_code=404, detail="event not found")
    session.delete(event)
    session.commit()
    return {"deleted": event_id}


@router.delete("/applications/{application_id}")
def delete_application(
    application_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Permanent, unrecoverable delete: rows, versions, timeline, and the
    exported files on disk. The reversible path is /archive."""
    app_row, _job = _get_app_and_job(session, application_id)
    if app_row.status in PROCESSING_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"application is currently {app_row.status}; wait for it to finish",
        )

    for event in session.exec(
        select(ApplicationEvent).where(ApplicationEvent.application_id == application_id)
    ).all():
        session.delete(event)
    for version in session.exec(
        select(ApplicationVersion)
        .where(ApplicationVersion.application_id == application_id)
    ).all():
        session.delete(version)
    session.delete(app_row)
    session.commit()

    exports_removed = _remove_export_dir(request.app.state.settings.data_dir, application_id)
    return {"deleted": application_id, "exports_removed": exports_removed}
