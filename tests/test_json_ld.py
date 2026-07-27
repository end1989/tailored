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
    data = resume_json_ld(resume)
    roles = [item.role for s in resume.sections if s.type == "experience" for item in s.items]
    companies = [
        item.company for s in resume.sections if s.type == "experience" for item in s.items
    ]
    assert [o["@type"] for o in data["hasOccupation"]] == ["Occupation"] * len(roles)
    assert [o["name"] for o in data["hasOccupation"]] == roles
    assert [o["@type"] for o in data["worksFor"]] == ["Organization"] * len(companies)
    assert [o["name"] for o in data["worksFor"]] == companies


def test_json_ld_maps_education_and_certifications():
    resume = _resume()
    data = resume_json_ld(resume)
    for entry in data.get("alumniOf", []):
        assert entry["@type"] == "EducationalOrganization"
    for entry in data.get("hasCredential", []):
        assert entry["@type"] == "EducationalOccupationalCredential"


def test_json_ld_lists_skills_under_knows_about():
    resume = _resume()
    data = resume_json_ld(resume)
    expected = [
        item for s in resume.sections if s.type == "skills" for g in s.groups for item in g.items
    ]
    if expected:
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
