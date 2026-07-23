"""Tests for the four resume templates (Task 11)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.schemas import (
    CertificationItem,
    CertificationsSection,
    Contact,
    EducationItem,
    EducationSection,
    ExperienceItem,
    ExperienceSection,
    ExtrasSection,
    ProjectItem,
    ProjectsSection,
    ResumeDoc,
    SkillGroup,
    SkillsSection,
    TailorResult,
)
from backend.app.services.render import TEMPLATES, TEMPLATES_DIR, render_resume_html

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


def _fixture_resume() -> ResumeDoc:
    data = json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))
    return TailorResult.model_validate(data).resume


def _all_sections_resume() -> ResumeDoc:
    """A ResumeDoc containing ALL six section types."""
    return ResumeDoc(
        contact=Contact(
            name="Alex Chen",
            email="alex@example.com",
            phone="555-0111",
            location="Portland, OR",
        ),
        headline="Full-Stack Engineer",
        summary="Engineer who ships end to end.",
        sections=[
            ExperienceSection(
                items=[
                    ExperienceItem(
                        company="Initech",
                        role="Software Engineer",
                        start="2020",
                        end="2023",
                        location="Remote",
                        bullets=["Built the billing service."],
                    )
                ]
            ),
            ProjectsSection(
                items=[
                    ProjectItem(
                        name="OpenBoard",
                        description="Realtime collaborative whiteboard",
                        url="https://openboard.example.com",
                        bullets=["Grew to 10k users."],
                    )
                ]
            ),
            SkillsSection(
                groups=[SkillGroup(label="Languages", items=["Python", "Go"])]
            ),
            EducationSection(
                items=[
                    EducationItem(
                        institution="State University",
                        credential="B.S. Computer Science",
                        year="2019",
                        detail="Magna cum laude",
                    )
                ]
            ),
            CertificationsSection(
                items=[
                    CertificationItem(
                        name="AWS Solutions Architect Associate",
                        issuer="Amazon",
                        year="2022",
                    )
                ]
            ),
            ExtrasSection(items=["Open-source maintainer"]),
        ],
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_renders_fixture_resume(template):
    resume = _fixture_resume()
    html = render_resume_html(resume, template)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<style>" in html  # standalone: CSS inlined
    assert resume.contact.name in html
    for section in resume.sections:
        assert section.title in html


@pytest.mark.parametrize(
    "template,marker",
    [
        ("meridian", "Georgia"),
        ("terminal", "monospace"),
        ("signal", "#C2410C"),
    ],
)
def test_template_visual_identity(template, marker):
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    assert marker in css


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_renders_all_six_section_types(template):
    html = render_resume_html(_all_sections_resume(), template)
    for needle in (
        "Initech",
        "OpenBoard",
        "Languages",
        "State University",
        "AWS Solutions Architect Associate",
        "Open-source maintainer",
    ):
        assert needle in html
