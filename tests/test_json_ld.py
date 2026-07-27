"""schema.org JSON-LD in the HTML export. Additive; resume.txt is unchanged."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.app.schemas import ResumeDoc, TailorResult
from backend.app.services.render import (
    TEMPLATES,
    render_resume_html,
    resume_json_ld,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"
SCRIPT = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)


def _resume() -> ResumeDoc:
    data = json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))
    return TailorResult.model_validate(data).resume


def _embedded(html: str) -> dict:
    match = SCRIPT.search(html)
    assert match, "no JSON-LD block in the rendered HTML"
    return json.loads(match.group(1))


def _items(resume: ResumeDoc, section_type: str) -> list:
    return [
        item
        for section in resume.sections
        if section.type == section_type
        for item in section.items
    ]


def test_json_ld_describes_a_person():
    data = resume_json_ld(_resume())
    assert data["@context"] == "https://schema.org"
    assert data["@type"] == "Person"
    assert data["name"] == _resume().contact.name


def test_json_ld_carries_contact_details():
    resume = _resume()
    data = resume_json_ld(resume)
    assert data["email"] == resume.contact.email
    assert data["description"] == resume.summary
    assert data["jobTitle"] == resume.headline


def test_json_ld_maps_experience_to_occupation_and_organization():
    resume = _resume()
    items = _items(resume, "experience")
    assert items, "the fixture has no experience items; this test would assert nothing"
    data = resume_json_ld(resume)

    # Both properties go through the schema.org Role pattern: the property is
    # repeated on the Role, which carries the dates. See the docstring of
    # test_json_ld_dates_every_role_and_only_ends_the_ones_that_ended.
    assert [o["@type"] for o in data["hasOccupation"]] == ["Role"] * len(items)
    assert [o["hasOccupation"]["@type"] for o in data["hasOccupation"]] == [
        "Occupation"
    ] * len(items)
    assert [o["hasOccupation"]["name"] for o in data["hasOccupation"]] == [
        item.role for item in items
    ]

    assert [o["@type"] for o in data["worksFor"]] == ["OrganizationRole"] * len(items)
    assert [o["worksFor"]["@type"] for o in data["worksFor"]] == ["Organization"] * len(
        items
    )
    assert [o["worksFor"]["name"] for o in data["worksFor"]] == [
        item.company for item in items
    ]

    for item, entry in zip(items, data["hasOccupation"], strict=True):
        if item.location:
            assert entry["hasOccupation"]["occupationLocation"] == {
                "@type": "Place",
                "name": item.location,
            }
        else:
            assert "occupationLocation" not in entry["hasOccupation"]


def test_json_ld_dates_every_role_and_only_ends_the_ones_that_ended():
    """A past employer must not be asserted as a present one.

    schema.org defines worksFor as "Organizations that the person works for",
    and hasOccupation's definition says outright: "For past professions, use
    Role for expressing dates." Emitting a bare Organization per employer told
    every consumer - Google Rich Results, an ATS, an LLM parser - that the
    candidate holds all of those jobs simultaneously, right now. It also left
    the role, the employer and the dates in three places with nothing joining
    them, so the machine-readable block could not answer "who did what, when"
    at all.

    Each entry now carries roleName and startDate, and endDate only when the
    job actually ended, which is also what makes the two arrays joinable.
    """
    resume = _resume()
    items = _items(resume, "experience")
    assert any(item.end for item in items) and any(item.end is None for item in items), (
        "the fixture needs one ended role and one ongoing role, or this test "
        "cannot tell a date-qualified graph from an undated one"
    )
    data = resume_json_ld(resume)
    for item, occupation, employer in zip(
        items, data["hasOccupation"], data["worksFor"], strict=True
    ):
        for entry in (occupation, employer):
            assert entry["roleName"] == item.role
            assert entry["startDate"] == item.start
            if item.end:
                assert entry["endDate"] == item.end
            else:
                assert "endDate" not in entry


def test_json_ld_maps_education_and_certifications():
    """Non-vacuous by construction: it indexes the keys rather than .get()ing them.

    An earlier version iterated `data.get("alumniOf", [])` and asserted only on
    whatever entries it found, so deleting the entire education branch from
    resume_json_ld left the whole suite green while every HTML export silently
    lost its education structured data.
    """
    resume = _resume()
    education = _items(resume, "education")
    certifications = _items(resume, "certifications")
    assert education and certifications, (
        "the fixture must carry both an education and a certification item, or "
        "this test asserts nothing"
    )
    data = resume_json_ld(resume)

    assert [e["@type"] for e in data["alumniOf"]] == ["EducationalOrganization"] * len(
        education
    )
    assert [e["name"] for e in data["alumniOf"]] == [i.institution for i in education]

    expected_credentials = [
        (i.credential, i.institution, "EducationalOrganization") for i in education
    ] + [(i.name, i.issuer, "Organization") for i in certifications]
    assert len(data["hasCredential"]) == len(expected_credentials)
    for entry, (name, recognizer, recognizer_type) in zip(
        data["hasCredential"], expected_credentials, strict=True
    ):
        assert entry["@type"] == "EducationalOccupationalCredential"
        assert entry["name"] == name
        if recognizer:
            assert entry["recognizedBy"] == {
                "@type": recognizer_type,
                "name": recognizer,
            }
        else:
            assert "recognizedBy" not in entry


def test_json_ld_lists_skills_under_knows_about():
    resume = _resume()
    data = resume_json_ld(resume)
    expected = [
        item for s in resume.sections if s.type == "skills" for g in s.groups for item in g.items
    ]
    assert expected, "the fixture has no skills; this test would assert nothing"
    assert data["knowsAbout"] == expected


def test_json_ld_omits_keys_with_no_value():
    resume = _resume().model_copy(deep=True)
    resume.contact.phone = None
    resume.contact.location = None
    data = resume_json_ld(resume)
    assert "telephone" not in data
    assert "address" not in data


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_template_embeds_valid_json_ld(template):
    data = _embedded(render_resume_html(_resume(), template))
    assert data["@type"] == "Person"


def test_a_bullet_containing_a_script_tag_cannot_break_out():
    """The one place autoescaping is bypassed. It must not be an injection point."""
    resume = _resume().model_copy(deep=True)
    payload = '</script><script>alert("xss")</script>'
    for section in resume.sections:
        if section.type == "experience":
            section.items[0].bullets[0] = payload
            break
    html = render_resume_html(resume, "meridian")
    block = SCRIPT.search(html)
    assert block, "the injected payload terminated the script element early"
    assert "alert(" not in block.group(1) or "\\u003c" in block.group(1)
    assert "</script><script>" not in block.group(1)
    # and it is still parseable JSON
    json.loads(block.group(1))


def test_a_comment_opener_in_the_resume_cannot_open_a_comment():
    resume = _resume().model_copy(deep=True)
    resume.summary = "I reduced costs <!-- by a lot"
    html = render_resume_html(resume, "meridian")
    block = SCRIPT.search(html)
    assert block
    assert "<!--" not in block.group(1)
    assert json.loads(block.group(1))["description"] == resume.summary


def test_json_ld_is_absent_from_the_ats_text():
    """resume.txt is the canonical machine-readable artifact and is unchanged."""
    from backend.app.services.render import render_ats_text

    assert "schema.org" not in render_ats_text(_resume())
