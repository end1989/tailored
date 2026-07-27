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
    default, and one inside `@supports` may never apply at all. (`_all_rules`
    descends into them, for the guards that do need to see them.)

    A prelude starts after the preceding `;`, so a statement at-rule -- `@charset
    "utf-8";`, `@import url(...);` -- is not read as part of the selector list of
    the rule that follows it.
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
                prelude = prelude[prelude.rfind(";") + 1 :]
                block_start = index + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                rules.append((prelude, stripped[block_start:index]))
                prelude_start = index + 1
    return rules


def _own_declarations(block: str) -> str:
    """`block` with any rules nested inside it removed, prelude and all.

    Only the declarations the block makes for its *own* selector are left, so a
    nested rule cannot smuggle its declarations up into the parent's.
    """
    kept: list[str] = []
    depth = 0
    for char in block:
        if char == "{":
            if depth == 0:
                # Drop the nested rule's prelude, back to the previous `;`.
                text = "".join(kept)
                kept = list(text[: text.rfind(";") + 1])
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth == 0:
            kept.append(char)
    return "".join(kept)


def _all_rules(css: str) -> list[tuple[str, str]]:
    """(selector prelude, own declarations) for every rule at every nesting depth.

    Unlike `_top_level_rules` this descends into at-rules. `@media print` is the
    medium `render_pdf` prints through -- Playwright's `page.pdf()` emulates
    print -- so a declaration in there restyles every exported PDF and has to be
    seen by any guard that claims a stylesheet still renders a given way.
    """
    rules: list[tuple[str, str]] = []
    for prelude, block in _top_level_rules(css):
        rules.append((prelude, _own_declarations(block)))
        if "{" in block:
            rules.extend(_all_rules(block))
    return rules


def _values(block: str, prop: str) -> list[str]:
    """Every value `prop` is given in `block`, in source order.

    All of them, not the first: a block may declare the same property twice and
    the later declaration is the one that renders.
    """
    matches = re.finditer(rf"(?<![\w-]){re.escape(prop)}\s*:\s*([^;}}]+)", block)
    return [value for value in (m.group(1).strip() for m in matches) if value]


def _body_font_family(css: str) -> str | None:
    """The family the document body ends up with, or None if it inherits the UA default.

    `html` and `:root` count alongside `body`: body inherits from them, so a
    family declared there is genuinely the document's typeface. A descendant
    selector such as `body .name` does not count -- it styles the descendant.

    The *last* such declaration is returned, not the first: these rules all have
    the same specificity, so CSS resolves them by source order. (Source order is
    as far as this goes -- it does not model specificity, which is why the
    Meridian guard below checks every declaration rather than trusting this to
    pick the winner.)
    """
    families = [
        value
        for prelude, block in _top_level_rules(css)
        if {part.strip() for part in prelude.split(",")} & _DOCUMENT_SELECTORS
        for value in _values(block, "font-family")
    ]
    return families[-1] if families else None


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
    # Equal specificity, so the later rule is the one that renders.
    assert _body_font_family("body { font-family: Inter; }\nbody { font-family: Georgia; }") == "Georgia"
    assert _body_font_family("body { font-family: Inter; font-family: Georgia; }") == "Georgia"
    # A statement at-rule ends in `;`; the next rule's prelude starts after it.
    assert _body_font_family('@charset "utf-8";\nbody { font-family: Georgia; }') == "Georgia"


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


def _declarations(css: str, selectors: str | frozenset[str], prop: str) -> list[str]:
    """Every value `prop` takes for `selectors`, in source order, at any depth.

    Every one, because a stylesheet is normally restyled by *adding* rules, not
    by editing declarations in place -- and reading only the first declaration
    reports the value that lost. Appending `.section-title { font-variant:
    normal; }` is an equal-specificity rule later in source order, so it wins the
    cascade; the same block inside `@media print` wins in every exported PDF.
    Both leave the first declaration untouched and both must be seen.

    Exact selector match: `.section-title em` is not `.section-title`.
    """
    wanted = frozenset({selectors}) if isinstance(selectors, str) else selectors
    return [
        value
        for prelude, block in _all_rules(css)
        if {part.strip() for part in prelude.split(",")} & wanted
        for value in _values(block, prop)
    ]


def _assert_meridian_identity(css: str) -> None:
    """Spec 3.1's Global Constraint, as assertions over a stylesheet.

    Factored out of the test so the mutation proof below can assert that the
    *whole guard* rejects a redrawn Meridian, not merely that a helper reports
    the override.
    """
    families = _declarations(css, _DOCUMENT_SELECTORS, "font-family")
    assert families, "meridian/style.css never sets a body typeface at all."
    for family in families:
        assert family.split(",")[0].strip() == "Georgia", (
            f"meridian's body typeface is {family!r}. Spec 3.1 fixes it as the "
            "Georgia stack; changing it changes every resume already exported "
            "with Meridian."
        )

    variants = _declarations(css, ".section-title", "font-variant")
    assert variants and all(value == "small-caps" for value in variants), (
        f"meridian's section titles are small caps by spec (found {variants!r}), "
        "not uppercase and not sentence case."
    )
    # `text-transform: uppercase` beats small caps to the glyphs, so an absent
    # declaration and an explicit `none` are the only ways to keep the spec'd look.
    transforms = _declarations(css, ".section-title", "text-transform")
    assert all(value == "none" for value in transforms), (
        f"meridian's section titles declare text-transform {transforms!r}, which "
        "overrides the small caps spec 3.1 fixes."
    )

    aligns = _declarations(css, ".resume-header", "text-align")
    assert aligns and all(value == "center" for value in aligns), (
        f"meridian's header is centered by spec (found {aligns!r})."
    )

    for selector in (".resume-header", ".section-title"):
        rules = _declarations(css, selector, "border-bottom")
        assert rules and all(rule.startswith("0.5pt solid") for rule in rules), (
            f"meridian's {selector} lost its 0.5pt hairline rule (found {rules!r}). "
            "The hairlines are named in spec 3.1."
        )


def test_meridian_keeps_its_visual_identity():
    _assert_meridian_identity(
        (TEMPLATES_DIR / "meridian" / "style.css").read_text(encoding="utf-8")
    )


def test_meridian_vendors_no_font():
    """Georgia is a system face. Embedding one would be bytes in every export
    that no glyph is ever drawn from, and it would change Meridian's typeface."""
    assert TEMPLATE_REGISTRY["meridian"].fonts == (), (
        "meridian/template.json declares fonts. It must stay empty: Georgia and "
        "its fallbacks are system fonts, so there is nothing to vendor."
    )


_MERIDIAN_REDRAW = (
    "body { font-family: Helvetica, Arial, sans-serif; }\n"
    ".section-title { font-variant: normal; text-transform: uppercase;\n"
    "                 border-bottom: 3pt double #000000; }\n"
    ".resume-header { text-align: left; border-bottom: 3pt double #000000; }\n"
)


@pytest.mark.parametrize("wrap", [
    pytest.param("{block}", id="appended-rule"),
    pytest.param("@media print {{\n{block}\n}}", id="print-only-override"),
])
def test_the_meridian_identity_guard_catches_an_appended_override(wrap):
    """The mutation the guard exists to catch, and the one it used to miss.

    A stylesheet is normally restyled by appending rules, not by editing the
    declaration on line 9. Both mutants below leave every original declaration
    intact and still redraw Meridian in Helvetica with uppercase headings, a
    left-aligned header and 3pt double rules -- the plain one everywhere, the
    `@media print` one in every exported PDF.
    """
    css = (TEMPLATES_DIR / "meridian" / "style.css").read_text(encoding="utf-8")
    mutant = css + wrap.format(block=_MERIDIAN_REDRAW)

    assert "Helvetica, Arial, sans-serif" in _declarations(
        mutant, _DOCUMENT_SELECTORS, "font-family"
    )
    assert "normal" in _declarations(mutant, ".section-title", "font-variant")
    assert "uppercase" in _declarations(mutant, ".section-title", "text-transform")
    assert "left" in _declarations(mutant, ".resume-header", "text-align")
    for selector in (".resume-header", ".section-title"):
        assert "3pt double #000000" in _declarations(mutant, selector, "border-bottom")

    with pytest.raises(AssertionError):
        _assert_meridian_identity(mutant)


def test_the_meridian_identity_guard_reads_the_declarations_it_claims_to():
    """Without this, `_declarations` could be weakened to a whole-file search, or
    back to first-match-wins, and the guard above would stay green, since
    Meridian satisfies it today."""
    assert _declarations(".section-title { font-variant: small-caps; }", ".section-title", "font-variant") == ["small-caps"]
    assert _declarations(".section-title em { font-variant: small-caps; }", ".section-title", "font-variant") == []
    assert _declarations("/* .a { text-align: center; } */", ".a", "text-align") == []
    assert _declarations(".a, .b { text-align: center; }", ".b", "text-align") == ["center"]
    assert _declarations(".a { color: red; }", ".a", "text-align") == []
    assert _declarations(".a { -webkit-text-align: left; }", ".a", "text-align") == []
    # A later rule of equal specificity wins the cascade; both must be reported.
    assert _declarations(".a { text-align: center; } .a { text-align: left; }", ".a", "text-align") == ["center", "left"]
    # So does a second declaration inside the same block.
    assert _declarations(".a { text-align: center; text-align: left; }", ".a", "text-align") == ["center", "left"]
    # At-rules are descended into, at any depth: `page.pdf()` emulates print.
    assert _declarations("@media print { .a { text-align: left; } }", ".a", "text-align") == ["left"]
    assert _declarations("@supports (color: red) { @media print { .a { text-align: left; } } }", ".a", "text-align") == ["left"]
    # ...but a nested rule's declarations stay its own.
    assert _declarations(".a { text-align: center; .b { text-align: left; } }", ".a", "text-align") == ["center"]
    assert _declarations(".a { text-align: center; .b { text-align: left; } }", ".b", "text-align") == ["left"]


# --- Plainwork's markup, and only Plainwork's -------------------------------
#
# Plainwork is the one template that includes `_resume_body_plain.html` instead
# of the canonical partial: stacked block elements, no flex container, because
# block flow is the most conservative thing a resume can hand to an unknown
# parser. A copy-pasted shell that includes the canonical body renders a
# perfectly good-looking Plainwork and leaves every other test in this suite
# green, since the two partials carry the same facts in the same order.


def test_plainwork_renders_through_the_block_flow_partial():
    html = render_resume_html(_fixture_resume(), "plainwork")
    assert 'class="item-head"' not in html, (
        "plainwork/template.html includes the canonical _resume_body.html, whose "
        "flex .item-head is the layout path this template exists to avoid."
    )
    assert 'class="primary"' in html, (
        "plainwork renders no .primary at all; the include resolved to something "
        "other than _resume_body_plain.html"
    )


@pytest.mark.parametrize(
    "template", [name for name in TEMPLATES if name != "plainwork"]
)
def test_every_other_template_renders_through_the_canonical_partial(template):
    """The inverse: the plain partial must not leak into the other templates.

    Their stylesheets all style `.item-head` and would silently stop applying.
    """
    assert 'class="item-head"' in render_resume_html(_fixture_resume(), template)


# --- Plainwork is plain, and stays plain ------------------------------------

_PLAINWORK_BANNED = (
    ("a border", r"(?<![\w-])border(?:-[a-z]+)*\s*:"),
    ("letter-spacing", r"(?<![\w-])letter-spacing\s*:"),
    ("flex or grid layout", r"(?<![\w-])display\s*:\s*(?:inline-)?(?:flex|grid)"),
    ("a visual transform", r"(?<![\w-])(?:transform|filter)\s*:"),
)


def test_plainwork_declares_none_of_the_decoration_it_exists_without():
    """Every absence in plainwork/style.css is a decision, so each is asserted.

    Matched on the property rather than as a bare substring: a substring search
    for "border" also fires on `box-sizing: border-box`, and one for a colour
    prefix such as "#c" fires on any legitimate hex that happens to start with
    it. A guard that cries wolf on valid CSS gets satisfied by mangling the
    stylesheet, which is worse than no guard.
    """
    css = re.sub(
        r"/\*.*?\*/",
        "",
        (TEMPLATES_DIR / "plainwork" / "style.css").read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    for label, pattern in _PLAINWORK_BANNED:
        match = re.search(pattern, css)
        assert match is None, (
            f"plainwork/style.css declares {label} ({match.group(0).strip()!r}). "
            "This template is deliberately undecorated: it is what gets exported "
            "into portals that parse badly."
        )
    colours = {value.lower() for value in re.findall(r"#[0-9a-fA-F]{3,8}", css)}
    assert colours <= {"#000", "#000000", "#fff", "#ffffff"}, (
        f"plainwork/style.css uses the colours {sorted(colours)}. It is black on "
        "white: grey text is the first thing a bad OCR path loses."
    )


@pytest.mark.parametrize(
    "css",
    (
        ".resume-header { border-bottom: 0.5pt solid #8a8a8a; }",
        ".resume-header { border  : none; }",
        ".name { letter-spacing: 0.08em; }",
        ".item-head { display: flex; }",
        ".item-head { display:inline-grid; }",
        ".name { transform: rotate(2deg); }",
    ),
)
def test_the_plainwork_decoration_guard_rejects(css):
    """No shipped stylesheet contains these, so without this the guard above
    could be reduced to a no-op and stay green."""
    assert any(
        re.search(pattern, css) for _label, pattern in _PLAINWORK_BANNED
    ), f"the plainwork guard does not catch {css!r}"


@pytest.mark.parametrize(
    "css",
    (
        "*, *::before { box-sizing: border-box; }",
        ".section-title { text-transform: uppercase; }",
        ".name { font-weight: 700; }",
        ":root { --measure: 100%; }",
    ),
)
def test_the_plainwork_decoration_guard_accepts_legitimate_css(css):
    found = [label for label, pattern in _PLAINWORK_BANNED if re.search(pattern, css)]
    assert not found, f"the plainwork guard is too broad: {css!r} flagged as {found}"


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
