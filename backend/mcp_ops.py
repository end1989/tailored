"""Business logic for the Tailored MCP server (backend/mcp_server.py).

Plain synchronous functions with no MCP imports, fully unit-testable.
Every function takes an explicit `engine` (and `data_dir` where exports are
written). Database sessions are short-lived per call and committed before
returning, because the web app polls the same SQLite file concurrently.

Failures an agent can correct raise McpOpsError; the exception message is
the agent-facing tool error text.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError
from sqlmodel import Session, select

from .app.api.templates import TEMPLATE_META
from .app.config import load_user_settings
from .app.models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
    get_contact,
    get_master_profile as _master_profile_of,
    get_parsed,
    get_resume,
    set_master_profile,
    set_parsed,
)
from .app.schemas import MPProject, ParsedPosting, ResearchFindings, ResumeDoc, SkillGroup
from .app.services import render
from .app.services.claude import strict_schema
from .app.services.pipeline import _mark_error, _set_status
from .app.services.style import check_style
from .app.services.tailor import verify_truthfulness


class McpOpsError(Exception):
    """Agent-correctable failure; the message becomes the MCP tool error text."""


# The five files export_application writes, in display order.
EXPORT_FILES = (
    "resume.pdf",
    "resume.html",
    "resume.txt",
    "cover_letter.pdf",
    "cover_letter.txt",
)

_WORKED_EXAMPLE = """[
  {"type": "experience", "title": "Experience", "items": [
    {"company": "Acme Corp", "role": "Senior Engineer", "start": "2021-03", "end": null,
     "location": "Remote", "bullets": ["Rebuilt the ingestion pipeline, cutting p95 latency 40%"]}
  ]},
  {"type": "skills", "title": "Skills", "groups": [
    {"label": "Languages", "items": ["Python", "TypeScript"]}
  ]},
  {"type": "education", "title": "Education", "items": [
    {"institution": "State University", "credential": "B.S. Computer Science", "year": "2016", "detail": null}
  ]}
]"""


def get_workflow_guide() -> str:
    """Complete agent-facing guide: workflow, truthfulness contract, JSON shapes."""
    resume_schema = json.dumps(strict_schema(ResumeDoc))
    parsed_schema = json.dumps(strict_schema(ParsedPosting))
    research_schema = json.dumps(strict_schema(ResearchFindings))
    return f"""TAILORED MCP WORKFLOW GUIDE
===========================

You are the intelligence for Tailored, a local resume-and-cover-letter builder.
You do the reading, researching, and writing; Tailored stores the results,
enforces truthfulness, and renders the print-ready exports.

WORKFLOW (call the tools in this order):
1. get_master_profile - read the candidate's contact info and master profile.
   The master profile is the single source of truth: the ONLY facts you may use.
2. Fetch the job posting. Escalate in this order, cheapest first:

   2a. DIRECT FETCH
       Fetch the URL with your normal tooling. If you get the posting text,
       you are done - go to step 3.

   2b. BROWSER ESCALATION - when the direct fetch is refused.
       Triggers: HTTP 401, 403 or 429; a bot check or CAPTCHA interstitial; a
       login wall; a consent gate; or a page whose extracted body is under
       about 400 characters, which usually means you received a JavaScript
       shell or a "please enable cookies" page rather than a posting. Many
       sites return HTTP 200 for those, so do not key this on status alone.

       Open the URL in the user's own browser (Claude in Chrome, or your
       client's equivalent), let it render, and read the page text. This uses
       the user's existing session, so postings behind a login they already
       hold are readable.

       Do not attempt to disguise automated traffic, defeat a CAPTCHA, or
       reach anything the user could not open themselves in their own browser.
       If the user is not logged in and the posting requires it, that is 2c.

   2c. ASK FOR A PASTE - only when both of the above failed.
       Working from the queue (next_pending_job gave you an application_id):
       call report_fetch_blocked(application_id, reason). The job moves to
       needs_paste and leaves the queue, and the reason lands on its timeline,
       so the user sees why this posting stalled and gets a paste box for it.
       Then move on to the next job. Do not stall the batch on one posting.

       Single job, no application yet (step 3 has not run, so you have no
       application_id): call queue_jobs(profile_id, [url]) first to create the
       saved job, then call report_fetch_blocked with the application_id it
       returns. Never guess an id or reuse one from another job - the report
       would land on the wrong application. Finally tell the user which URL
       needs pasting and why.
3. create_application(profile_id, url, posting_text) - register the job with the
   posting text you gathered. Returns the application_id for every later call.
   Optionally call list_templates first and pass template= to pick a visual
   style (default slate).
4. save_parsed_posting(application_id, parsed) - your structured analysis of the
   posting (ParsedPosting JSON below). The dashboard shows company/title from this.
5. Optionally research the company (its site, news, tech stack) and call
   save_research(application_id, findings) with ResearchFindings JSON.
6. Write the tailored resume and cover letter, then call
   save_tailored_resume(application_id, resume, cover_letter_md, tailoring_notes).
   On success Tailored renders and exports PDF, HTML, and ATS text.
7. get_application(application_id) - confirm status "ready" and list the exports.

Separately, to import a workspace portfolio scan straight into the master
profile itself (not a single application), call add_profile_evidence - it
additively merges agent-verified projects and skill groups into the profile.

WORKING THROUGH A LIST OF JOBS:
Call queue_jobs(profile_id, urls) once with every URL. It is free and instant -
no fetching, no model call, no cost - and each URL becomes a saved job on the
user's dashboard right away, so they can watch the list drain.

Then loop:
  job = next_pending_job(profile_id)   -> {{"application_id": <id>, "url": "<url>"}} or null
  if null: the queue is empty, you are finished.
  otherwise: fetch it (step 2 above), then save_parsed_posting, optionally
  save_research, then save_tailored_resume. Then ask for the next one.

Process one job to completion before starting the next. If you lose
context partway through a batch, that costs one job rather than twenty.

The queue lives in the database, not in your context. After a restart, or after
compacting, just call next_pending_job again: it returns the oldest job you have
not finished, so you resume exactly where you stopped. Do not start over.

If the user deletes a saved job while you are working, next_pending_job simply
stops returning it. That is correct - it is the user changing their mind, not an
error.

A job you report with report_fetch_blocked also leaves the queue: it moves to
needs_paste, the dashboard offers the user a paste box for it, and
next_pending_job hands you the next job instead of the blocked one.

TRUTHFULNESS CONTRACT (absolute, non-negotiable, enforced server-side):
- You may SELECT which experiences, projects, and bullets to include.
- You may REORDER sections, roles, and bullets to shift emphasis.
- You may REPHRASE bullet text for clarity and impact.
- You may do NOTHING else. NEVER invent employers, job titles, employment dates,
  degrees, certifications, tools, or metrics. Every company, role, start date,
  end date, institution, credential, and certification in your output must appear
  exactly as it does in the master profile. Every factual claim in every bullet
  must be supported by the master profile.
- Mirror the posting's vocabulary only where the master profile factually
  supports it. If the posting asks for something the candidate does not have,
  omit it - never fabricate it.
- save_tailored_resume validates structurally and rejects any resume containing
  experience/education/certification entries not present in the master profile -
  you will receive the violation list to correct. Exact-match rules: each
  experience item's (company, role, start, end) must equal a master-profile
  experience's (company, title, start, end); each education item's
  (institution, credential) and each certification's name must match exactly.

RESUME:
- headline: one line positioning the candidate for this specific role.
- summary: two to four sentences specific to this candidate and this posting -
  no generic filler.
- Templates differ in section order: call list_templates and match best_for to
  the role. Most templates lead with Experience; Terminal leads with Projects.
  Include Skills and Education sections whenever the master profile has content
  for them.

COVER LETTER (markdown, 3-5 short paragraphs):
- Open specific. If you saved research, the first paragraph must reference a
  concrete finding (mission, product, news item, or culture language). With no
  research, it must reference specific language from the posting itself.
- No boilerplate openings ("I am writing to apply...", "I was excited to see...").
- Ground every claim in facts from the master profile.

JSON SHAPES (strict: every object level carries "additionalProperties": false -
send exactly these fields, no extras):

ResumeDoc (the `resume` argument of save_tailored_resume):
{resume_schema}

ParsedPosting (the `parsed` argument of save_parsed_posting):
{parsed_schema}

ResearchFindings (the `findings` argument of save_research):
{research_schema}

WORKED EXAMPLE - a resume `sections` list (values illustrative; in real use
every company, role, date, degree, and certification must come from the master
profile verbatim):
{_WORKED_EXAMPLE}
"""


def _has_master_profile(profile: Profile) -> bool:
    mp = _master_profile_of(profile)
    return bool(mp.experiences or mp.projects or mp.skills or mp.education)


def list_profiles(engine) -> list[dict]:
    """All profiles: id, name, whether a master profile has been built."""
    with Session(engine) as session:
        profiles = session.exec(select(Profile).order_by(Profile.id)).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "has_master_profile": _has_master_profile(p),
            }
            for p in profiles
        ]


def get_master_profile(engine, profile_id: int | None = None) -> dict:
    """Contact + master profile for one profile.

    profile_id None resolves to the sole profile; ambiguous (multiple profiles)
    raises with a listing so the agent can pick one.
    """
    with Session(engine) as session:
        if profile_id is None:
            profiles = session.exec(select(Profile).order_by(Profile.id)).all()
            if not profiles:
                raise McpOpsError(
                    "No profiles exist yet. Create one in the Tailored web app "
                    "(upload a resume on the Profile screen) first."
                )
            if len(profiles) > 1:
                listing = "; ".join(f"id={p.id} name={p.name!r}" for p in profiles)
                raise McpOpsError(
                    "Multiple profiles exist - call again with profile_id. "
                    "Profiles: " + listing
                )
            profile = profiles[0]
        else:
            profile = session.get(Profile, profile_id)
            if profile is None:
                raise McpOpsError(
                    f"Profile {profile_id} not found. "
                    "Call list_profiles to see what exists."
                )
        return {
            "profile_id": profile.id,
            "name": profile.name,
            "contact": get_contact(profile).model_dump(),
            "master_profile": _master_profile_of(profile).model_dump(),
        }


def add_profile_evidence(
    engine,
    profile_id: int,
    projects: list[dict] | None = None,
    skill_groups: list[dict] | None = None,
    summary_note: str | None = None,
) -> dict:
    """Additively merge agent-verified portfolio evidence into a master profile.

    Never removes or overwrites existing content: projects are appended only
    when their name is new (case-insensitive), same-label skill groups have
    their items merged (deduped), and summary_note is appended to the existing
    summary_notes. Every incoming project/skill_group is validated before any
    write, so a bad payload changes nothing.
    """
    incoming_projects = projects or []
    incoming_groups = skill_groups or []

    with Session(engine) as session:
        profile = session.get(Profile, profile_id)
        if profile is None:
            raise McpOpsError(
                f"Profile {profile_id} not found. "
                "Call list_profiles to see what exists."
            )
        master = _master_profile_of(profile)

        # Validate EVERYTHING before mutating anything (all-or-nothing write).
        validated_projects: list[MPProject] = []
        for idx, proj in enumerate(incoming_projects):
            try:
                validated_projects.append(MPProject.model_validate(proj))
            except ValidationError as exc:
                raise McpOpsError(
                    f"projects[{idx}] failed MPProject validation: {exc}"
                ) from exc
        validated_groups: list[SkillGroup] = []
        for idx, grp in enumerate(incoming_groups):
            try:
                validated_groups.append(SkillGroup.model_validate(grp))
            except ValidationError as exc:
                raise McpOpsError(
                    f"skill_groups[{idx}] failed SkillGroup validation: {exc}"
                ) from exc

        # Projects: append only when the (stripped, case-insensitive) name is new.
        existing_names = {p.name.strip().lower() for p in master.projects}
        added_projects: list[str] = []
        skipped_projects: list[str] = []
        for proj in validated_projects:
            key = proj.name.strip().lower()
            if key in existing_names:
                skipped_projects.append(proj.name)
            else:
                master.projects.append(proj)
                existing_names.add(key)
                added_projects.append(proj.name)

        # Skill groups: merge into a same-label group, else append the group.
        existing_by_label = {g.label.strip().lower(): g for g in master.skills}
        groups_added: list[str] = []
        groups_merged: list[str] = []
        for grp in validated_groups:
            key = grp.label.strip().lower()
            existing = existing_by_label.get(key)
            if existing is None:
                grp.items = [item.strip() for item in grp.items]
                master.skills.append(grp)
                existing_by_label[key] = grp
                groups_added.append(grp.label)
            else:
                present = {i.strip().lower() for i in existing.items}
                for item in grp.items:
                    item_clean = item.strip()
                    if item_clean.lower() not in present:
                        existing.items.append(item_clean)
                        present.add(item_clean.lower())
                groups_merged.append(existing.label)

        # Summary note: append (blank-line join) when non-empty after strip.
        summary_appended = False
        if summary_note is not None and summary_note.strip():
            note = summary_note.strip()
            if master.summary_notes and master.summary_notes.strip():
                master.summary_notes = master.summary_notes + "\n\n" + note
            else:
                master.summary_notes = note
            summary_appended = True

        set_master_profile(profile, master)
        session.add(profile)
        session.commit()

        return {
            "profile_id": profile_id,
            "added_projects": added_projects,
            "skipped_projects": skipped_projects,
            "skill_groups_added": groups_added,
            "skill_groups_merged": groups_merged,
            "summary_appended": summary_appended,
            "master_profile": master.model_dump(),
        }


def list_templates() -> list[dict]:
    """Template gallery metadata (same as the web app's Templates page)."""
    return [dict(meta) for meta in TEMPLATE_META]


def create_application(
    engine, profile_id: int, url: str, posting_text: str, template: str = "slate"
) -> dict:
    """Create Job (posting text pasted by the agent) + Application in 'tailoring'."""
    if template not in render.TEMPLATES:
        raise McpOpsError(
            f"Unknown template {template!r}; expected one of "
            f"{list(render.TEMPLATES)}. Call list_templates for descriptions."
        )
    if not posting_text or not posting_text.strip():
        raise McpOpsError(
            "posting_text is empty - fetch the posting yourself and pass its full text."
        )
    with Session(engine) as session:
        profile = session.get(Profile, profile_id)
        if profile is None:
            raise McpOpsError(
                f"Profile {profile_id} not found. Call list_profiles to see what exists."
            )
        job = Job(
            url=url, raw_text=posting_text, fetch_status="pasted", depth="external"
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        app = Application(
            profile_id=profile_id, job_id=job.id, template=template,
            status="tailoring",
        )
        session.add(app)
        session.commit()
        session.refresh(app)
        return {
            "application_id": app.id,
            "status": app.status,
            "next": "save_parsed_posting, then save_tailored_resume",
        }


_ALLOWED_URL_SCHEMES = ("http", "https")


def _valid_url(url: str) -> bool:
    """A URL an agent could plausibly open. Deliberately permissive.

    There is no URL validation anywhere else in this project: the web batch
    route accepts any string. This exists only so that a typo or a stray line
    from a pasted list fails the whole batch loudly instead of creating a queue
    entry that can never be fetched. It is not a security boundary.
    """
    if not url or not url.strip():
        return False
    parsed = urlparse(url.strip())
    return parsed.scheme in _ALLOWED_URL_SCHEMES and bool(parsed.netloc)


def queue_jobs(engine, profile_id: int, urls: list[str]) -> list[dict]:
    """Register many job URLs at once, cheaply, for working through one by one.

    Creates one parked application per URL: status "not_started", stage
    "saved", no posting text, no pipeline run, no model call, no cost. They
    appear on the dashboard immediately and the user can watch them drain.

    All-or-nothing: if any URL is malformed the whole batch is rejected and
    nothing is created, matching the web batch route. A partial queue is worse
    than a rejected one, because the agent cannot tell which half landed.

    Returns one entry per INPUT url, in input order, so the caller never has to
    diff two lists. Entries already queued for this profile come back with
    status "skipped" and the existing application_id.
    """
    if not urls:
        raise McpOpsError("urls must not be empty - pass at least one job URL.")
    bad = [u for u in urls if not _valid_url(u)]
    if bad:
        raise McpOpsError(
            f"{len(bad)} malformed URL(s), so nothing was queued: {bad[:5]}. "
            "Every URL must be an absolute http or https address."
        )

    with Session(engine) as session:
        profile = session.get(Profile, profile_id)
        if profile is None:
            raise McpOpsError(
                f"Profile {profile_id} not found. Call list_profiles to see "
                "what exists."
            )

        # Existing, non-archived applications for this profile, by URL.
        # Archiving is how a user says "done with this", so an archived row
        # must not block re-queueing.
        existing: dict[str, int] = {}
        rows = session.exec(
            select(Application, Job)
            .where(Application.job_id == Job.id)
            .where(Application.profile_id == profile_id)
            .where(Application.archived_at.is_(None))
            .order_by(Application.id)
        ).all()
        # setdefault keeps the first hit, so with the ordering above a URL
        # that somehow has several live applications skips to the oldest.
        for app_row, job_row in rows:
            existing.setdefault(job_row.url, app_row.id)

        results: list[dict] = []
        for url in urls:
            url = url.strip()
            if url in existing:
                results.append(
                    {
                        "application_id": existing[url],
                        "url": url,
                        "status": "skipped",
                        "reason": "already queued for this profile",
                    }
                )
                continue
            # No explicit depth: the model default ("standard") applies.
            # These rows are generate-able from the dashboard (status
            # not_started is exactly what POST /generate accepts), and the
            # built-in pipeline can only dispatch quick/standard/deep -
            # "external" (create_application's marker for agent-gathered
            # text) would make research_company raise after the parse call
            # had already been paid for.
            job = Job(url=url)
            session.add(job)
            session.flush()  # assigns job.id; commits together with its application
            app_row = Application(
                profile_id=profile_id,
                job_id=job.id,
                status="not_started",
            )
            session.add(app_row)
            session.commit()
            session.refresh(app_row)
            # A duplicate later in the same list is a skip, not a second row.
            existing[url] = app_row.id
            results.append(
                {
                    "application_id": app_row.id,
                    "url": url,
                    "status": "not_started",
                }
            )
        return results


def next_pending_job(engine, profile_id: int) -> dict | None:
    """The oldest queued job for this profile, or None when the queue is empty.

    Returns None rather than raising on an empty queue: it makes your loop
    terminate on a plain condition rather than on an error.

    Does not lock or reserve the row. Tailored is a local, single-user
    application, so a claim protocol would guard a scenario that does not
    exist. If the user deletes a saved job mid-run, it simply stops being
    returned, which is correct.
    """
    with Session(engine) as session:
        row = session.exec(
            select(Application, Job)
            .where(Application.job_id == Job.id)
            .where(Application.profile_id == profile_id)
            .where(Application.status == "not_started")
            .where(Application.archived_at.is_(None))
            .order_by(Application.id)
        ).first()
        if row is None:
            return None
        app_row, job_row = row
        return {"application_id": app_row.id, "url": job_row.url}


def report_fetch_blocked(engine, application_id: int, reason: str) -> dict:
    """Record that a posting could not be read, and why.

    Call this when a direct fetch was refused AND opening the URL in the user's
    own browser also did not work. It marks the job blocked, moves a queued
    ("not_started") application to "needs_paste" so next_pending_job stops
    handing it back, and writes a note on the application's timeline - the
    user sees on the dashboard why this posting stalled and gets a paste box
    for exactly that posting.

    Without the status move, a blocked job would stay in the pending set and
    next_pending_job would return it forever: the batch loop would live-lock
    on the first refusal, which is the exact failure this tool exists to
    handle.

    Then move on to the next job. Do not stall the batch on one posting.
    """
    if not reason or not reason.strip():
        raise McpOpsError(
            "reason must not be empty - say what refused the fetch (a 403, a "
            "bot check, a login wall) so the user knows what to do."
        )
    with Session(engine) as session:
        app, job = _get_app_and_job(session, application_id)
        _reject_if_pipeline_active(app, application_id)
        # A posting we already hold the text for cannot be fetch-blocked. The
        # pipeline guard above covers rows the built-in pipeline is working on;
        # this covers the other misdirection - an application_id that points at
        # finished work. Without it, a wrong id overwrites a "pasted"/"fetched"
        # job with "blocked" and puts "Could not read the posting" on the
        # timeline of an application whose resume is already exported.
        #
        # Keyed on raw_text rather than status so that re-blocking stays a safe
        # no-op: a stubborn URL gets reported once, moves to needs_paste, and a
        # later batch over the same list must not raise on it. Refusing to
        # stall the batch is the whole point of this tool.
        if job.raw_text:
            raise McpOpsError(
                f"application {application_id} already has posting text, so it "
                "cannot be fetch-blocked - check the application_id. Blocked is "
                "for postings that could not be read at all."
            )
        job.fetch_status = "blocked"
        session.add(job)
        event = ApplicationEvent(
            application_id=app.id,
            kind="note",
            body=f"Could not read the posting: {reason.strip()}",
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        if app.status == "not_started":
            _set_status(session, app, "needs_paste")
        return {
            "application_id": app.id,
            "status": app.status,
            "fetch_status": job.fetch_status,
            "event_id": event.id,
        }


def set_application_template(
    engine, data_dir: Path, application_id: int, template: str
) -> dict:
    """Re-render an existing application in a different template.

    No Claude call and no cost: the stored resume and cover letter are unchanged.
    Section order is not revisited, because that was decided at tailoring time
    from the original template's structural hint.
    """
    if template not in render.TEMPLATES:
        raise McpOpsError(
            f"Unknown template {template!r}; expected one of "
            f"{list(render.TEMPLATES)}. Call list_templates for descriptions."
        )
    with Session(engine) as session:
        app, _job = _get_app_and_job(session, application_id)
        _reject_if_pipeline_active(app, application_id)
        resume_doc = get_resume(app)
        if resume_doc is None:
            raise McpOpsError(
                f"Application {application_id} has no tailored resume yet; "
                "nothing to re-render. Call save_tailored_resume first."
            )
        profile = session.get(Profile, app.profile_id)
        contact = get_contact(profile)

        user_settings = load_user_settings(Path(data_dir))
        # Render before committing anything: a row claiming a template its
        # exports were never rendered in would hand the agent the old PDF
        # under the new label.
        export_dir = render.export_application(
            app.id,
            resume_doc,
            app.cover_letter_md or "",
            contact,
            template,
            Path(data_dir),
            page_size=user_settings.get("page_size", "Letter"),
        )
        app.template = template
        app.export_dir = str(export_dir)
        session.add(app)
        session.commit()
        session.refresh(app)

        return {
            "application_id": app.id,
            "status": app.status,
            "version": app.version,
            "template": app.template,
            "export_dir": app.export_dir,
            "files": sorted(
                p.name for p in Path(export_dir).iterdir() if p.is_file()
            ),
        }


def _get_app_and_job(session: Session, application_id: int) -> tuple[Application, Job]:
    app = session.get(Application, application_id)
    if app is None:
        raise McpOpsError(
            f"Application {application_id} not found. "
            "create_application returns the id to use."
        )
    job = session.get(Job, app.job_id)
    if job is None:
        raise McpOpsError(f"Application {application_id} is missing its job row.")
    return app, job


# Statuses owned by the built-in pipeline (backend/app/services/pipeline.py).
# "tailoring" is deliberately excluded: it is the MCP parking state between
# create_application and save_tailored_resume, and the residual seconds-long
# overlap with the web pipeline's own tailoring step is accepted for a
# single-user local app.
_PIPELINE_ACTIVE_STATUSES = ("queued", "fetching", "researching", "rendering")


def _reject_if_pipeline_active(app: Application, application_id: int) -> None:
    if app.status in _PIPELINE_ACTIVE_STATUSES:
        raise McpOpsError(
            f"application {application_id} is currently {app.status} under "
            "the built-in pipeline - wait for it to finish or create a "
            "separate application for this agent run"
        )


def save_parsed_posting(engine, application_id: int, parsed: dict) -> dict:
    """Validate and store the agent's ParsedPosting analysis on the job."""
    try:
        posting = ParsedPosting.model_validate(parsed)
    except ValidationError as exc:
        raise McpOpsError(f"parsed failed ParsedPosting validation: {exc}") from exc
    with Session(engine) as session:
        app, job = _get_app_and_job(session, application_id)
        _reject_if_pipeline_active(app, application_id)
        set_parsed(job, posting)
        session.add(job)
        session.commit()
        return {
            "application_id": application_id,
            "company": posting.company,
            "title": posting.title,
            "status": app.status,
        }


def save_research(engine, application_id: int, findings: dict) -> dict:
    """Validate and store agent-performed company research as a ResearchBrief."""
    try:
        validated = ResearchFindings.model_validate(findings)
    except ValidationError as exc:
        raise McpOpsError(
            f"findings failed ResearchFindings validation: {exc}"
        ) from exc
    with Session(engine) as session:
        app, job = _get_app_and_job(session, application_id)
        _reject_if_pipeline_active(app, application_id)
        brief = ResearchBrief(
            job_id=job.id,
            depth="external",
            findings_json=validated.model_dump_json(),
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )
        session.add(brief)
        session.commit()
        session.refresh(brief)
        return {
            "application_id": application_id,
            "research_brief_id": brief.id,
            "status": app.status,
        }


def save_tailored_resume(
    engine,
    data_dir: Path,
    application_id: int,
    resume: dict,
    cover_letter_md: str,
    tailoring_notes: str = "",
) -> dict:
    """The truthfulness-gated write: validate, verify, snapshot, render, export.

    Validation or truthfulness failures raise before any state change - the
    application stays in "tailoring" so the agent can correct and retry.
    After the gate passes, any crash (e.g. during rendering) lands the
    application in status "error" (pipeline's _mark_error pattern), never a
    stuck "rendering".
    """
    try:
        resume_doc = ResumeDoc.model_validate(resume)
    except ValidationError as exc:
        raise McpOpsError(f"resume failed ResumeDoc validation: {exc}") from exc
    with Session(engine) as session:
        app, _job = _get_app_and_job(session, application_id)
        _reject_if_pipeline_active(app, application_id)
        profile = session.get(Profile, app.profile_id)
        if profile is None:
            raise McpOpsError(
                f"Application {application_id} is missing its profile row."
            )
        master = _master_profile_of(profile)
        contact = get_contact(profile)

        violations = verify_truthfulness(resume_doc, master)
        if violations:
            raise McpOpsError(
                "Truthfulness check failed:\n- "
                + "\n- ".join(violations)
                + "\nCorrect the resume to use only entries from the master "
                "profile and call this tool again."
            )

        style_violations = check_style(resume_doc, cover_letter_md)
        if style_violations:
            raise McpOpsError(
                "Style check failed:\n- "
                + "\n- ".join(style_violations)
                + "\nRewrite the flagged text in the candidate's own plain "
                "voice and call this tool again."
            )

        try:
            if app.resume_json:
                # A successful save already happened: regenerate semantics.
                app.version += 1
            app.resume_json = resume_doc.model_dump_json()
            app.cover_letter_md = cover_letter_md
            app.tailoring_notes = tailoring_notes
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
            user_settings = load_user_settings(Path(data_dir))
            export_dir = render.export_application(
                app.id, resume_doc, cover_letter_md, contact,
                app.template, Path(data_dir),
                page_size=user_settings.get("page_size", "Letter"),
            )
            app.export_dir = str(export_dir)
            session.add(app)
            session.commit()

            # The one place status drives stage: finishing generation moves a
            # parked job to drafted. Any other stage is the user's and is
            # left alone. Without this, every MCP-generated application
            # would sit in "saved" forever.
            if app.stage == "saved":
                app.stage = "drafted"
                session.add(app)
                session.commit()

            _set_status(session, app, "ready")
        except Exception as exc:  # noqa: BLE001 - every failure is visible state
            _mark_error(session, app, str(exc))
            raise McpOpsError(
                f"Saving failed after the truthfulness gate; application "
                f"{application_id} is now in status 'error': {exc}"
            ) from exc

        return {
            "status": app.status,
            "version": app.version,
            "export_dir": str(export_dir),
            "files": sorted(
                p.name for p in Path(export_dir).iterdir() if p.is_file()
            ),
        }


def get_application(engine, application_id: int) -> dict:
    """Status / version / error / export files for one application."""
    with Session(engine) as session:
        app, job = _get_app_and_job(session, application_id)
        parsed = get_parsed(job)
        files: list[str] = []
        if app.export_dir and Path(app.export_dir).is_dir():
            files = sorted(
                p.name for p in Path(app.export_dir).iterdir() if p.is_file()
            )
        return {
            "application_id": app.id,
            "status": app.status,
            "version": app.version,
            "template": app.template,
            "url": job.url,
            "company": parsed.company if parsed else None,
            "title": parsed.title if parsed else None,
            "error_message": app.error_message,
            "export_dir": app.export_dir,
            "files": files,
        }
