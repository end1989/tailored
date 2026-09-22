"""Permanent deletes that span several tables.

Every Application owns exactly one Job (batch create, MCP create_application
and queue_jobs each make a fresh Job per application), and the Job owns its
ResearchBrief rows, so removing an application removes those too.
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, select

from ..models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
    SourceDocument,
    _utcnow,
    get_parsed,
)
from .pipeline import live_application_ids

logger = logging.getLogger(__name__)

# Statuses in which something may still be writing to the application: the
# pipeline (queued..rendering) or an MCP agent that parked it in tailoring.
ACTIVE_STATUSES = ("queued", "fetching", "researching", "tailoring", "rendering")
# The pipeline stamps updated_at on every transition, so a row in an active
# status that has not moved for this long is abandoned (a server restart kills
# background tasks; an agent can walk away from a parked row). Without a
# cutoff, one stuck row would make a person impossible to remove. A run live
# in this process's pipeline blocks however old its row is: one step (deep
# research) can outlast the cutoff, and a restart-killed run is never live.
STALE_AFTER = timedelta(minutes=15)


class RemovalBlocked(Exception):
    """Removing a person was refused and nothing was deleted.

    `detail` is the 409 body: {"message": str, "blocking": [{"id", "label",
    "status"}]}. For active work each entry is an application (label: its
    company, else its URL); for a locked export it is the application whose
    directory could not be moved (label: the path, status "locked").
    """

    def __init__(self, detail: dict):
        super().__init__(detail["message"])
        self.detail = detail


def delete_application_rows(session: Session, app_row: Application) -> None:
    """Delete one application's events, versions, research briefs (by job_id),
    job row and the application row. Does not commit and touches no files."""
    for event in session.exec(
        select(ApplicationEvent).where(ApplicationEvent.application_id == app_row.id)
    ).all():
        session.delete(event)
    for version in session.exec(
        select(ApplicationVersion)
        .where(ApplicationVersion.application_id == app_row.id)
    ).all():
        session.delete(version)
    for brief in session.exec(
        select(ResearchBrief).where(ResearchBrief.job_id == app_row.job_id)
    ).all():
        session.delete(brief)
    job = session.get(Job, app_row.job_id)
    session.delete(app_row)
    if job is not None:
        session.delete(job)


def _naive_utc(now: datetime | None) -> datetime:
    """`now` in the stored convention (naive UTC); the current time if None."""
    if now is None:
        return _utcnow()
    if now.tzinfo is None:
        return now
    return now.astimezone(timezone.utc).replace(tzinfo=None)


def blocking_applications(session: Session, profile_id: int,
                          now: datetime | None = None) -> list[Application]:
    """Applications of the profile in ACTIVE_STATUSES whose updated_at is
    within STALE_AFTER of now, plus any with a live pipeline run in this
    process, whatever their status or updated_at."""
    cutoff = _naive_utc(now) - STALE_AFTER
    rows = session.exec(
        select(Application)
        .where(Application.profile_id == profile_id)
        .order_by(Application.id)
    ).all()
    live = live_application_ids()
    return [
        row for row in rows
        if row.id in live
        or (row.status in ACTIVE_STATUSES and row.updated_at > cutoff)
    ]


def _label(session: Session, app_row: Application) -> str:
    job = session.get(Job, app_row.job_id)
    if job is None:
        return f"application {app_row.id}"
    parsed = get_parsed(job)
    if parsed is not None and parsed.company:
        return parsed.company
    return job.url


def _move_back(moved: list[tuple[Path, Path]], staging: Path) -> None:
    """Undo the staging renames, newest first, then drop the empty staging dir."""
    for source, target in reversed(moved):
        try:
            os.rename(target, source)
        except OSError:
            logger.exception("could not move %s back to %s", target, source)
    try:
        staging.rmdir()
    except OSError:
        pass  # absent, or not empty because a move back failed (logged above)


def remove_person(session: Session, data_dir: Path, profile: Profile,
                  now: datetime | None = None) -> dict:
    """Stage export dirs by rename into exports/.removing-<profile_id>/<id>
    (roll back and raise RemovalBlocked on any rename failure), delete rows in
    one transaction (applications via delete_application_rows, then the
    profile's SourceDocuments, then the profile), commit, then rmtree the
    staging dir (log, do not raise, on failure). Returns
    {"deleted": profile_id, "applications": n, "documents": m}."""
    profile_id = profile.id

    blocking = blocking_applications(session, profile_id, now)
    if blocking:
        raise RemovalBlocked({
            "message": "These applications are still being worked on. Wait "
                       "for them to finish, then try again.",
            "blocking": [
                {"id": row.id, "label": _label(session, row), "status": row.status}
                for row in blocking
            ],
        })

    apps = list(session.exec(
        select(Application)
        .where(Application.profile_id == profile_id)
        .order_by(Application.id)
    ).all())
    docs = list(session.exec(
        select(SourceDocument).where(SourceDocument.profile_id == profile_id)
    ).all())

    # Files first, by rename: a rename either happens or it does not, so a
    # directory Windows refuses to move (a file inside is open) stops the
    # removal while every earlier move can still be undone. Paths are built
    # from data_dir and integer ids only.
    exports_dir = Path(data_dir) / "exports"
    staging = exports_dir / f".removing-{profile_id}"
    if staging.exists():
        # Left by an earlier removal whose cleanup failed; its rows are gone.
        try:
            shutil.rmtree(staging)
        except OSError:
            logger.warning("could not clear leftover %s", staging, exc_info=True)
    moved: list[tuple[Path, Path]] = []
    for row in apps:
        source = exports_dir / str(row.id)
        if not source.is_dir():
            continue
        target = staging / str(row.id)
        try:
            staging.mkdir(parents=True, exist_ok=True)
            os.rename(source, target)
        except OSError as exc:
            _move_back(moved, staging)
            raise RemovalBlocked({
                "message": f"Could not remove the exported files for "
                           f"application {row.id}: a file appears to be open "
                           f"elsewhere (e.g. a PDF viewer). Close it and try "
                           f"again. Nothing was removed.",
                "blocking": [{
                    "id": row.id,
                    "label": str(exc.filename or source),
                    "status": "locked",
                }],
            }) from exc
        moved.append((source, target))

    try:
        for row in apps:
            delete_application_rows(session, row)
        for doc in docs:
            session.delete(doc)
        session.delete(profile)
        session.commit()
    except Exception:
        session.rollback()
        _move_back(moved, staging)
        raise

    if staging.exists():
        try:
            shutil.rmtree(staging)
        except OSError:
            logger.warning(
                "removed profile %s but could not delete %s; delete it by hand",
                profile_id, staging, exc_info=True,
            )

    return {"deleted": profile_id, "applications": len(apps), "documents": len(docs)}
