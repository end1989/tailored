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

from pydantic import ValidationError
from sqlmodel import Session, select

from .app.api.templates import TEMPLATE_META
from .app.config import load_user_settings
from .app.models import (
    Application,
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
2. Fetch the job posting yourself (browse the URL with your own abilities - you
   can read login-walled postings the app cannot fetch).
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

        app.template = template
        session.add(app)
        session.commit()
        session.refresh(app)

        user_settings = load_user_settings(Path(data_dir))
        export_dir = render.export_application(
            app.id,
            resume_doc,
            app.cover_letter_md or "",
            contact,
            template,
            Path(data_dir),
            page_size=user_settings.get("page_size", "Letter"),
        )
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
