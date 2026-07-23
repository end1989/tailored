from __future__ import annotations

from datetime import datetime

from sqlmodel import select

from backend.app.models import (
    Application,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
    SourceDocument,
    get_contact,
    get_findings,
    get_master_profile,
    get_parsed,
    get_resume,
    set_contact,
    set_master_profile,
    set_parsed,
    set_resume,
)
from backend.app.schemas import (
    Contact,
    ExperienceItem,
    ExperienceSection,
    LinkItem,
    MasterProfile,
    MPExperience,
    ParsedPosting,
    ResearchFindings,
    ResumeDoc,
    TaggedBullet,
)


def test_create_and_query_each_entity(session):
    profile = Profile(name="Ada Example")
    session.add(profile)
    session.commit()
    session.refresh(profile)

    doc = SourceDocument(
        profile_id=profile.id, filename="resume.pdf", kind="pdf", text="raw resume text"
    )
    job = Job(url="https://example.com/jobs/1")
    session.add(doc)
    session.add(job)
    session.commit()
    session.refresh(job)

    brief = ResearchBrief(job_id=job.id, depth="standard")
    app_row = Application(profile_id=profile.id, job_id=job.id)
    session.add(brief)
    session.add(app_row)
    session.commit()
    session.refresh(app_row)

    version = ApplicationVersion(
        application_id=app_row.id,
        version=1,
        resume_json="{}",
        cover_letter_md="Dear team,",
    )
    session.add(version)
    session.commit()

    assert session.exec(select(Profile)).one().name == "Ada Example"
    assert session.exec(select(SourceDocument)).one().kind == "pdf"
    assert session.exec(select(Job)).one().fetch_status == "pending"
    assert session.exec(select(ResearchBrief)).one().depth == "standard"
    assert session.exec(select(Application)).one().id == app_row.id
    assert session.exec(select(ApplicationVersion)).one().version == 1
    assert isinstance(profile.created_at, datetime)
    assert isinstance(app_row.updated_at, datetime)


def test_application_defaults(session):
    profile = Profile(name="Ada Example")
    job = Job(url="https://example.com/jobs/2")
    session.add(profile)
    session.add(job)
    session.commit()
    session.refresh(profile)
    session.refresh(job)

    app_row = Application(profile_id=profile.id, job_id=job.id)
    session.add(app_row)
    session.commit()
    session.refresh(app_row)

    assert app_row.status == "queued"
    assert app_row.version == 1
    assert app_row.template == "slate"
    assert app_row.error_message is None
    assert app_row.input_tokens == 0
    assert app_row.output_tokens == 0
    assert app_row.cost_usd == 0.0
    assert app_row.resume_json is None
    assert app_row.cover_letter_md is None
    assert app_row.export_dir is None


def test_job_defaults():
    job = Job(url="https://example.com/jobs/3")
    assert job.fetch_status == "pending"
    assert job.depth == "standard"
    assert job.raw_text is None
    assert job.parsed_json is None


def test_contact_and_master_profile_helpers_round_trip():
    p = Profile(name="Ada Example")
    # Empty JSON: sensible typed defaults, never a ValidationError.
    assert get_contact(p) == Contact(name="Ada Example")
    assert get_master_profile(p) == MasterProfile()

    contact = Contact(
        name="Ada Example",
        email="ada@example.com",
        phone="555-0100",
        links=[LinkItem(label="GitHub", url="https://github.com/ada")],
    )
    set_contact(p, contact)
    assert get_contact(p) == contact

    mp = MasterProfile(
        summary_notes="Backend engineer.",
        experiences=[
            MPExperience(
                company="Acme Corp",
                title="Software Engineer",
                start="2021-03",
                bullets=[TaggedBullet(text="Built APIs", tags=["python"])],
            )
        ],
    )
    set_master_profile(p, mp)
    assert get_master_profile(p) == mp


def test_job_parsed_helpers_round_trip():
    j = Job(url="https://example.com/jobs/4")
    assert get_parsed(j) is None
    parsed = ParsedPosting(
        title="Software Engineer",
        company="Acme Corp",
        company_domain="acme.example",
        must_haves=["Python"],
        keywords=["fastapi", "sqlite"],
    )
    set_parsed(j, parsed)
    assert get_parsed(j) == parsed


def test_research_findings_helper():
    r = ResearchBrief(job_id=1, depth="deep")
    assert get_findings(r) == ResearchFindings()
    r.findings_json = ResearchFindings(
        mission="Ship it", sources=["https://acme.example/about"]
    ).model_dump_json()
    found = get_findings(r)
    assert found.mission == "Ship it"
    assert found.sources == ["https://acme.example/about"]


def test_application_resume_helpers_round_trip():
    a = Application(profile_id=1, job_id=1)
    assert get_resume(a) is None
    resume = ResumeDoc(
        contact=Contact(name="Ada Example"),
        headline="Software Engineer",
        summary="Ships reliable software.",
        sections=[
            ExperienceSection(
                items=[
                    ExperienceItem(
                        company="Acme Corp", role="Software Engineer", start="2021-03"
                    )
                ]
            )
        ],
    )
    set_resume(a, resume)
    assert get_resume(a) == resume
