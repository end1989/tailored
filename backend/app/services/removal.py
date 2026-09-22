"""Permanent deletes that span several tables.

Every Application owns exactly one Job (batch create, MCP create_application
and queue_jobs each make a fresh Job per application), and the Job owns its
ResearchBrief rows, so removing an application removes those too.
"""
from __future__ import annotations

from sqlmodel import Session, select

from ..models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    Job,
    ResearchBrief,
)


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
