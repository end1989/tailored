from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.app.schemas import (
    CertificationItem,
    CertificationsSection,
    Contact,
    EducationItem,
    EducationSection,
    ExperienceItem,
    ExperienceSection,
    ExtrasSection,
    FetchResult,
    LinkItem,
    MasterProfile,
    MPCertification,
    MPEducation,
    MPExperience,
    MPProject,
    ProjectItem,
    ProjectsSection,
    ResumeDoc,
    SkillGroup,
    SkillsSection,
    TaggedBullet,
    UsageInfo,
)


def _sample_resume() -> ResumeDoc:
    # Deliberately scrambled section order: templates must handle any order,
    # and round-tripping must preserve it exactly.
    return ResumeDoc(
        contact=Contact(
            name="Ada Example",
            email="ada@example.com",
            phone="555-0100",
            location="Boise, ID",
            links=[LinkItem(label="GitHub", url="https://github.com/ada")],
        ),
        headline="Senior Software Engineer",
        summary="Backend engineer who ships reliable systems.",
        sections=[
            SkillsSection(
                groups=[SkillGroup(label="Languages", items=["Python", "TypeScript"])]
            ),
            ExperienceSection(
                items=[
                    ExperienceItem(
                        company="Acme Corp",
                        role="Software Engineer",
                        start="2021-03",
                        end=None,
                        location="Remote",
                        bullets=["Built the ingestion API."],
                    )
                ]
            ),
            ProjectsSection(
                items=[
                    ProjectItem(
                        name="Tailored",
                        description="Resume builder",
                        url="https://example.com/tailored",
                        bullets=["Wrote the renderer."],
                    )
                ]
            ),
            EducationSection(
                items=[
                    EducationItem(
                        institution="State University",
                        credential="B.S. Computer Science",
                        year="2015",
                    )
                ]
            ),
            CertificationsSection(
                items=[CertificationItem(name="AWS SAA", issuer="AWS", year="2022")]
            ),
            ExtrasSection(items=["Open-source maintainer"]),
        ],
    )


def test_resume_doc_json_round_trip_preserves_order_and_discriminates_types():
    doc = _sample_resume()
    data = json.loads(doc.model_dump_json())
    restored = ResumeDoc.model_validate(data)
    assert restored == doc
    assert [s.type for s in restored.sections] == [
        "skills",
        "experience",
        "projects",
        "education",
        "certifications",
        "extras",
    ]
    assert isinstance(restored.sections[0], SkillsSection)
    assert isinstance(restored.sections[1], ExperienceSection)
    assert isinstance(restored.sections[2], ProjectsSection)
    assert isinstance(restored.sections[3], EducationSection)
    assert isinstance(restored.sections[4], CertificationsSection)
    assert isinstance(restored.sections[5], ExtrasSection)
    # Nested payloads survive the trip.
    assert restored.sections[1].items[0].bullets == ["Built the ingestion API."]
    assert restored.contact.links[0].url == "https://github.com/ada"


def test_section_union_discriminates_from_plain_dicts():
    raw = {
        "contact": {"name": "Ada Example"},
        "headline": "Engineer",
        "summary": "Ships software.",
        "sections": [
            {"type": "extras", "title": "Additional", "items": ["Volunteers"]},
            {
                "type": "experience",
                "title": "Experience",
                "items": [
                    {"company": "Acme Corp", "role": "Engineer", "start": "2021"}
                ],
            },
        ],
    }
    doc = ResumeDoc.model_validate(raw)
    assert isinstance(doc.sections[0], ExtrasSection)
    assert isinstance(doc.sections[1], ExperienceSection)
    assert doc.sections[1].items[0].end is None


def test_master_profile_round_trip():
    mp = MasterProfile(
        summary_notes="Ten years of backend work.",
        experiences=[
            MPExperience(
                company="Acme Corp",
                title="Software Engineer",
                start="2021-03",
                end=None,
                location="Remote",
                bullets=[TaggedBullet(text="Built APIs", tags=["python", "fastapi"])],
            )
        ],
        projects=[
            MPProject(
                name="Tailored",
                description="Resume builder",
                url=None,
                bullets=[TaggedBullet(text="Wrote it", tags=["react"])],
            )
        ],
        skills=[SkillGroup(label="Languages", items=["Python"])],
        education=[
            MPEducation(
                institution="State University",
                credential="B.S. Computer Science",
                year="2015",
                detail=None,
            )
        ],
        certifications=[MPCertification(name="AWS SAA", issuer="AWS", year="2022")],
        extras=["Speaks Spanish"],
    )
    restored = MasterProfile.model_validate(json.loads(mp.model_dump_json()))
    assert restored == mp
    assert restored.experiences[0].bullets[0].tags == ["python", "fastapi"]


def test_usage_info_addition():
    a = UsageInfo(input_tokens=100, output_tokens=50, cost_usd=0.001)
    b = UsageInfo(input_tokens=25, output_tokens=75, cost_usd=0.0005)
    total = a + b
    assert total.input_tokens == 125
    assert total.output_tokens == 125
    assert total.cost_usd == 0.0015
    assert UsageInfo() + UsageInfo() == UsageInfo()


def test_fetch_result_literal_rejects_bad_status():
    ok = FetchResult(status="fetched", text="posting body")
    assert ok.status == "fetched"
    assert ok.reason == ""
    needs = FetchResult(status="needs_paste", reason="HTTP 403")
    assert needs.reason == "HTTP 403"
    with pytest.raises(ValidationError):
        FetchResult(status="error")
