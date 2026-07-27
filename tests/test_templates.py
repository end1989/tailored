"""Tests for the resume templates."""
from __future__ import annotations

import json
import re
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
from backend.app.services.render import (
    TEMPLATE_REGISTRY,
    TEMPLATES,
    TEMPLATES_DIR,
    render_resume_html,
)

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


# --- The body typeface must be set on the body ------------------------------
#
# base.css declares no font-family at all and `_font_css` emits only @font-face
# blocks, so a template's own style.css is the only thing standing between the
# resume and Chromium's UA serif. Searching the whole file for `font-family:`
# does not check that: a stylesheet that names its family only on `.name` -- or
# only inside its own @font-face block -- renders every bullet, heading and date
# in Times, in both the HTML and the PDF, while the suite stays green.

_DOCUMENT_SELECTORS = frozenset({"body", "html", ":root"})


def _top_level_rules(css: str) -> list[tuple[str, str]]:
    """(selector prelude, declaration block) for each rule at nesting depth 0.

    Comments are stripped first so a family named only in a header comment does
    not count. Nested rules are skipped deliberately: a body font-family that
    only applies inside `@media print` leaves the on-screen preview on the
    default, and one inside `@supports` may never apply at all.
    """
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    rules: list[tuple[str, str]] = []
    depth = 0
    prelude_start = 0
    block_start = 0
    for index, char in enumerate(stripped):
        if char == "{":
            if depth == 0:
                prelude = stripped[prelude_start:index]
                block_start = index + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                rules.append((prelude, stripped[block_start:index]))
                prelude_start = index + 1
    return rules


def _body_font_family(css: str) -> str | None:
    """The family the document body ends up with, or None if it inherits the UA default.

    `html` and `:root` count alongside `body`: body inherits from them, so a
    family declared there is genuinely the document's typeface. A descendant
    selector such as `body .name` does not count -- it styles the descendant.
    """
    for prelude, block in _top_level_rules(css):
        selectors = {part.strip() for part in prelude.split(",")}
        if not selectors & _DOCUMENT_SELECTORS:
            continue
        match = re.search(r"(?<![\w-])font-family\s*:\s*([^;}]+)", block)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return None


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_declares_its_own_body_typeface(template):
    """Every template must choose a typeface. Inheriting the default is not a design."""
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    assert _body_font_family(css), (
        f"{template}/style.css never declares font-family on body (or on the "
        "html/:root it inherits from), so the whole resume renders in "
        "Chromium's default serif. A font-family on .name or any other element "
        "does not set the body's typeface."
    )


def test_the_body_typeface_guard_rejects_a_family_declared_elsewhere():
    """Without this, the guard above can be reduced to a whole-file grep unnoticed.

    Every shipped stylesheet declares the family on body, so no template
    exercises the failing branch and the weakening would stay green.
    """
    assert _body_font_family("body { color: #111; }\n.name { font-family: Inter; }") is None
    assert _body_font_family("@font-face { font-family: Inter; src: url(data:x); }") is None
    assert _body_font_family("body .name { font-family: Inter; }") is None
    assert _body_font_family("/* body { font-family: Inter; } */\nbody { color: #111; }") is None
    assert _body_font_family("@media print { body { font-family: Inter; } }") is None
    assert _body_font_family("body { font-family: Inter, sans-serif; }") == "Inter, sans-serif"
    assert _body_font_family("html,\nbody {\n  font-family: Georgia, serif;\n}") == "Georgia, serif"


# --- Meridian's visual identity is frozen ------------------------------------
#
# "Meridian's visual identity does not change. Same Georgia stack, same small
# caps, same hairline rules, same centered header" is a Global Constraint of the
# plan (spec 3.1): it is the one template that predates the overhaul, and users
# have already exported resumes with it. The registry-driven tests above are
# deliberately generic - `test_template_declares_its_own_body_typeface` asks
# only that *some* family is declared - so nothing else in the suite fails if
# Meridian is redrawn in Helvetica with sentence-case headings. This is a
# single-template guard on purpose; the other templates are free to change.


def _declaration(css: str, selector: str, prop: str) -> str | None:
    """`prop`'s value in the top-level rule whose selector list contains `selector`.

    Top-level only, and exact selector match, for the same reasons as
    `_body_font_family`: a declaration nested in `@media print` does not style
    the preview, and `.section-title em` is not `.section-title`.
    """
    for prelude, block in _top_level_rules(css):
        if selector not in {part.strip() for part in prelude.split(",")}:
            continue
        match = re.search(rf"(?<![\w-]){re.escape(prop)}\s*:\s*([^;}}]+)", block)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return None


def test_meridian_keeps_its_visual_identity():
    css = (TEMPLATES_DIR / "meridian" / "style.css").read_text(encoding="utf-8")

    body = _body_font_family(css)
    assert body and body.split(",")[0].strip() == "Georgia", (
        f"meridian's body typeface is {body!r}. Spec 3.1 fixes it as the Georgia "
        "stack; changing it changes every resume already exported with Meridian."
    )
    assert _declaration(css, ".section-title", "font-variant") == "small-caps", (
        "meridian's section titles are small caps by spec, not uppercase and not "
        "sentence case."
    )
    assert _declaration(css, ".resume-header", "text-align") == "center", (
        "meridian's header is centered by spec."
    )
    for selector in (".resume-header", ".section-title"):
        rule = _declaration(css, selector, "border-bottom")
        assert rule and rule.startswith("0.5pt solid"), (
            f"meridian's {selector} lost its 0.5pt hairline rule (found {rule!r}). "
            "The hairlines are named in spec 3.1."
        )


def test_meridian_vendors_no_font():
    """Georgia is a system face. Embedding one would be bytes in every export
    that no glyph is ever drawn from, and it would change Meridian's typeface."""
    assert TEMPLATE_REGISTRY["meridian"].fonts == (), (
        "meridian/template.json declares fonts. It must stay empty: Georgia and "
        "its fallbacks are system fonts, so there is nothing to vendor."
    )


def test_the_meridian_identity_guard_reads_the_declaration_it_claims_to():
    """Without this, `_declaration` could be weakened to a whole-file search and
    the guard above would stay green, since Meridian satisfies it today."""
    assert _declaration(".section-title { font-variant: small-caps; }", ".section-title", "font-variant") == "small-caps"
    assert _declaration(".section-title em { font-variant: small-caps; }", ".section-title", "font-variant") is None
    assert _declaration("@media print { .a { text-align: center; } }", ".a", "text-align") is None
    assert _declaration("/* .a { text-align: center; } */", ".a", "text-align") is None
    assert _declaration(".a, .b { text-align: center; }", ".b", "text-align") == "center"
    assert _declaration(".a { color: red; }", ".a", "text-align") is None


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
