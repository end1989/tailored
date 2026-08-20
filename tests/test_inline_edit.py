"""Inline editing: the edit-mode render contract.

Edit mode adds attributes to the shared resume partials so the live preview can
be typed into directly. Two properties matter and are tested here:

1. Export is untouched. Every file that leaves the app is rendered with
   edit_mode off, and its markup must stay byte-identical to what it was
   before this feature existed (the golden files under tests/golden/).
2. The paths are stable and template-independent. One harvest function in the
   frontend reads every template, so all eight must emit the same path set for
   the same resume.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import backend.app.services.render as render_mod
from backend.app.schemas import (
    CertificationItem,
    CertificationsSection,
    Contact,
    EducationItem,
    EducationSection,
    ExperienceItem,
    ExperienceSection,
    ExtrasSection,
    LinkItem,
    ProjectItem,
    ProjectsSection,
    ResumeDoc,
    SkillGroup,
    SkillsSection,
)
from backend.app.services.render import TEMPLATES, render_resume_html

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# Attributes and classes that must never reach an exported file.
EDIT_MARKERS = (
    "data-edit-path",
    "data-node-path",
    "data-delete-path",
    "contenteditable",
    "data-locked",
    "edit-del",
)


def _full_resume() -> ResumeDoc:
    """One resume carrying every section type, so paths can be asserted exactly.

    Section order is fixed and the tests below index into it:
    0 experience, 1 skills, 2 projects, 3 education, 4 certifications, 5 extras.
    """
    return ResumeDoc(
        contact=Contact(
            name="Jane Doe",
            email="jane@example.com",
            phone="555-0100",
            location="Denver, CO",
            links=[LinkItem(label="GitHub", url="https://github.com/janedoe")],
        ),
        headline="Senior Backend Engineer",
        summary="Backend engineer with 8 years building APIs.",
        sections=[
            ExperienceSection(
                items=[
                    ExperienceItem(
                        company="Initech",
                        role="Staff Engineer",
                        start="2021",
                        end=None,
                        location="Remote",
                        bullets=[
                            "Led migration to event-driven architecture.",
                            "Cut p95 latency 40%.",
                        ],
                    ),
                    ExperienceItem(
                        company="Acme",
                        role="Backend Engineer",
                        start="2018",
                        end="2021",
                        bullets=["Built the billing service."],
                    ),
                ]
            ),
            SkillsSection(
                groups=[
                    SkillGroup(label="Languages", items=["Python", "Go"]),
                    SkillGroup(label="Data", items=["Postgres", "Kafka"]),
                ]
            ),
            ProjectsSection(
                items=[
                    ProjectItem(
                        name="VerifyMyAI",
                        description="Detects prompt injection in AI assistants.",
                        url="https://example.com/vmai",
                        bullets=["Open source, 400 stars."],
                    )
                ]
            ),
            EducationSection(
                items=[
                    EducationItem(
                        institution="State University",
                        credential="BS Computer Science",
                        year="2014",
                        detail="Focus on distributed systems.",
                    )
                ]
            ),
            CertificationsSection(
                items=[
                    CertificationItem(
                        name="AWS Solutions Architect", issuer="Amazon", year="2022"
                    )
                ]
            ),
            ExtrasSection(items=["Volunteer mentor, Code Club", "Conference speaker"]),
        ],
    )


def _attr_values(html: str, attr: str) -> list[str]:
    return re.findall(rf'{attr}="([^"]*)"', html)


def _tags_with(html: str, attr: str) -> list[str]:
    """Every opening tag carrying `attr`, so its other attributes can be read."""
    return [t for t in re.findall(r"<[a-zA-Z][^>]*>", html) if attr in t]


def _render_body(resume: ResumeDoc, partial: str, *, edit_mode: bool) -> str:
    tpl = render_mod._env.get_template(partial)
    return tpl.render(resume=resume, edit_mode=edit_mode)


# --- 1. Export is untouched ---------------------------------------------------


@pytest.mark.parametrize("partial", ["_resume_body.html", "_resume_body_plain.html"])
def test_export_markup_is_byte_identical_to_golden(partial: str) -> None:
    """The exported partial must not drift by so much as a space.

    The golden files were captured from the partials as they stood before inline
    editing existed. If this fails, edit-mode markup has leaked into the export
    path -- which would change every PDF the app has ever produced.
    """
    golden = (GOLDEN_DIR / partial).read_text(encoding="utf-8")
    assert _render_body(_full_resume(), partial, edit_mode=False) == golden


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_exported_html_carries_no_edit_markers(template: str) -> None:
    html = render_resume_html(_full_resume(), template)
    for marker in EDIT_MARKERS:
        assert marker not in html, f"{marker!r} leaked into exported {template} HTML"


def test_edit_css_is_absent_from_exported_html() -> None:
    assert ".edit-del" not in render_resume_html(_full_resume(), "slate")


# --- 2. Editable prose --------------------------------------------------------

EXPECTED_EDITABLE_PATHS = {
    "headline",
    "summary",
    "sections.0.title",
    "sections.0.items.0.bullets.0",
    "sections.0.items.0.bullets.1",
    "sections.0.items.1.bullets.0",
    "sections.1.title",
    "sections.1.groups.0.label",
    "sections.1.groups.0.items",
    "sections.1.groups.1.label",
    "sections.1.groups.1.items",
    "sections.2.title",
    "sections.2.items.0.description",
    "sections.2.items.0.bullets.0",
    "sections.3.title",
    "sections.3.items.0.detail",
    "sections.4.title",
    "sections.5.title",
    "sections.5.items.0",
    "sections.5.items.1",
}


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_edit_mode_marks_exactly_the_prose_fields_editable(template: str) -> None:
    """Every template emits the same editable path set, so one harvest reads all."""
    html = render_resume_html(_full_resume(), template, edit_mode=True)
    assert set(_attr_values(html, "data-edit-path")) == EXPECTED_EDITABLE_PATHS


def test_editable_elements_are_contenteditable_plaintext_only() -> None:
    html = render_resume_html(_full_resume(), "slate", edit_mode=True)
    tags = _tags_with(html, "data-edit-path")
    assert len(tags) == len(EXPECTED_EDITABLE_PATHS)
    for tag in tags:
        assert 'contenteditable="plaintext-only"' in tag, tag


def test_empty_prose_still_renders_an_editable_target() -> None:
    """A blank summary has to be clickable, or it can never be filled in."""
    resume = _full_resume()
    resume.summary = ""
    resume.sections[2].items[0].description = ""
    resume.sections[3].items[0].detail = None
    html = render_resume_html(resume, "slate", edit_mode=True)
    paths = set(_attr_values(html, "data-edit-path"))
    assert {"summary", "sections.2.items.0.description", "sections.3.items.0.detail"} <= paths
    # and stays absent from the export, where an empty element would print as a gap
    assert '<p class="summary"' not in render_resume_html(resume, "slate")


# --- 3. Locked profile anchors ------------------------------------------------


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_profile_anchors_are_locked_not_editable(template: str) -> None:
    """The truthfulness guard's fields cannot be typed into, so it cannot trip."""
    html = render_resume_html(_full_resume(), template, edit_mode=True)
    locked = _tags_with(html, "data-locked")
    for tag in locked:
        assert "contenteditable" not in tag, tag
        assert "data-edit-path" not in tag, tag
    # role, company, dates for two experience items; credential, institution,
    # year; certification name, issuer, year; project name and url; plus the
    # contact name and line.
    assert len(locked) >= 14


def test_locked_elements_explain_themselves_on_hover() -> None:
    html = render_resume_html(_full_resume(), "slate", edit_mode=True)
    for tag in _tags_with(html, "data-locked"):
        assert "Master Profile" in tag, tag


def test_experience_facts_are_locked_and_bullets_are_not() -> None:
    html = render_resume_html(_full_resume(), "slate", edit_mode=True)
    assert re.search(r'<span class="primary" data-locked[^>]*>Staff Engineer</span>', html)
    assert re.search(r'<span class="secondary" data-locked[^>]*>Initech</span>', html)
    assert 'data-edit-path="sections.0.items.0.bullets.0"' in html


# --- 4. Delete markers --------------------------------------------------------

EXPECTED_DELETE_PATHS = {
    "sections.0",
    "sections.0.items.0",
    "sections.0.items.0.bullets.0",
    "sections.0.items.0.bullets.1",
    "sections.0.items.1",
    "sections.0.items.1.bullets.0",
    "sections.1",
    "sections.1.groups.0",
    "sections.1.groups.1",
    "sections.2",
    "sections.2.items.0",
    "sections.2.items.0.bullets.0",
    "sections.3",
    "sections.3.items.0",
    "sections.4",
    "sections.4.items.0",
    "sections.5",
    "sections.5.items.0",
    "sections.5.items.1",
}


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_every_removable_thing_has_a_delete_marker(template: str) -> None:
    html = render_resume_html(_full_resume(), template, edit_mode=True)
    assert set(_attr_values(html, "data-delete-path")) == EXPECTED_DELETE_PATHS


def test_delete_marker_sits_outside_the_editable_text() -> None:
    """Harvest reads textContent of [data-edit-path]; a marker inside it would
    end up saved into the bullet."""
    html = render_resume_html(_full_resume(), "slate", edit_mode=True)
    match = re.search(
        r'<span[^>]*data-edit-path="sections\.0\.items\.0\.bullets\.0"[^>]*>(.*?)</span>',
        html,
        re.S,
    )
    assert match is not None
    assert "edit-del" not in match.group(1)
    assert match.group(1) == "Led migration to event-driven architecture."


# --- 5. Structural node paths (what harvest rebuilds arrays from) -------------


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_containers_carry_node_paths(template: str) -> None:
    html = render_resume_html(_full_resume(), template, edit_mode=True)
    assert set(_attr_values(html, "data-node-path")) == {
        "sections.0",
        "sections.0.items.0",
        "sections.0.items.1",
        "sections.1",
        "sections.1.groups.0",
        "sections.1.groups.1",
        "sections.2",
        "sections.2.items.0",
        "sections.3",
        "sections.3.items.0",
        "sections.4",
        "sections.4.items.0",
        "sections.5",
    }


def test_edit_mode_ships_its_own_stylesheet() -> None:
    html = render_resume_html(_full_resume(), "slate", edit_mode=True)
    assert ".edit-del" in html
    assert "[data-edit-path]" in html


def test_every_delete_marker_lands_inside_the_page() -> None:
    """The resume body runs edge to edge (page margins come from @page, not from
    padding), so a marker offset into the margin renders past the edge of the
    document and cannot be clicked. Entry markers therefore overlay the entry."""
    css = (render_mod.TEMPLATES_DIR / "edit_mode.css").read_text(encoding="utf-8")
    rule = css[css.index(".item[data-node-path] > .edit-del") :]
    rule = rule[: rule.index("}")]
    # Horizontal only: a negative top merely lifts the marker into the gap
    # above the entry, but a negative right pushes it past the page edge.
    offsets = re.findall(r"(?:right|left):\s*(-?[\d.]+)", rule)
    assert offsets, "the entry marker must be positioned horizontally"
    assert all(float(v) >= 0 for v in offsets), f"marker offset leaves the page: {rule}"
