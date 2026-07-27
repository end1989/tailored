"""base.css owns structure; style.css owns identity. This test keeps them apart.

The banned-construct guards below match on the CSS *property*, with optional
whitespace and vendor prefixes, and they cover the shorthand spellings as well
as the longhands. An earlier version of this file tested three literal
substrings ("column-count", "grid-template-columns", "position: absolute"),
which let `columns: 2`, `grid-template: auto / 1fr 1fr` and `position:absolute`
through untouched - all three render exactly the two-column sidebar the
single-column constraint exists to forbid. `test_the_layout_guard_rejects`
and `test_the_network_guard_rejects` pin that class of gap shut: they feed
known-bad declarations through the same helpers the per-template tests use, so
a guard that stops catching something fails here first.
"""
from __future__ import annotations

import re

import pytest

from backend.app.services.render import TEMPLATES, TEMPLATES_DIR

BASE_CSS = (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")

REQUIRED_PROPERTIES = (
    "--fs-name",
    "--fs-headline",
    "--fs-section",
    "--fs-body",
    "--fs-meta",
    "--leading",
    "--measure",
    "--rule-weight",
    "--rule-color",
    "--item-break",
    "--space-1",
    "--space-2",
    "--space-3",
    "--space-4",
)

# Every pattern is anchored on the property name: `(?<![\w-])` stops
# `grid-template-columns` from being read as the `columns` shorthand, and the
# optional `-[a-z]+-` accepts vendor prefixes.
PAGINATION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("break-inside", r"(?<![\w-])break-inside\s*:"),
    ("page-break-inside", r"(?<![\w-])page-break-inside\s*:"),
)

BANNED_LAYOUT_PATTERNS: tuple[tuple[str, str], ...] = (
    # CSS multi-column. Any one of column-count / column-width / the `columns`
    # shorthand alone turns a block into columns; column-gap is shared with
    # flexbox and is legitimate.
    ("multi-column flow", r"(?<![\w-])(?:-[a-z]+-)?column-(?!gap\b)[a-z-]+\s*:"),
    ("multi-column flow", r"(?<![\w-])(?:-[a-z]+-)?columns\s*:"),
    # Grid track definition, longhand and both shorthands. `display: grid` and
    # `grid-gap` are not matched: a single-column grid preserves source order.
    ("grid track definition", r"(?<![\w-])grid(?:-template|-auto)?(?:-columns|-rows|-areas)?\s*:"),
    ("grid placement", r"(?<![\w-])grid-(?:column|row|area)(?:-start|-end)?\s*:"),
    ("grid-auto-flow", r"(?<![\w-])grid-auto-flow\s*:"),
    # Out-of-flow boxes: Chromium emits the PDF content stream in visual order,
    # so anything lifted out of normal flow can extract out of source order.
    ("out-of-flow positioning", r"(?<![\w-])position\s*:\s*(?:absolute|fixed)(?![\w-])"),
    ("float", r"(?<![\w-])float\s*:\s*(?!none\b)[a-z-]+"),
)

# render_pdf calls page.set_content(html) with no base URL, so *no* external
# reference resolves - not an absolute URL, not a protocol-relative one, not a
# relative path. Only a data: URI survives.
BANNED_NETWORK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("absolute URL", r"https?://"),
    ("unresolvable url() reference", r"url\(\s*(?!['\"]?data:)"),
    ("@import", r"(?<![\w-])@import\b"),
)


def _strip_comments(css: str) -> str:
    """Drop /* ... */. A commented-out declaration is inert in both directions."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _violations(css: str, patterns: tuple[tuple[str, str], ...]) -> list[str]:
    stripped = _strip_comments(css)
    return sorted(
        {
            f"{label}: {match.group(0).strip()!r}"
            for label, pattern in patterns
            for match in re.finditer(pattern, stripped)
        }
    )


def _style_css(template: str) -> str:
    return (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")


@pytest.mark.parametrize("prop", REQUIRED_PROPERTIES)
def test_base_css_defines_the_shared_property(prop):
    assert re.search(rf"^\s*{re.escape(prop)}\s*:", BASE_CSS, re.MULTILINE), (
        f"base.css must define {prop}; templates override its value, not its meaning"
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_style_does_not_declare_pagination(template):
    """Pagination is structural. A template that redefines it is a bug."""
    found = _violations(_style_css(template), PAGINATION_PATTERNS)
    assert not found, (
        f"{template}/style.css declares pagination {found}. Structure belongs in "
        "base.css; set --item-break instead if this template needs breakable items."
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_style_does_not_reference_the_network(template):
    found = _violations(_style_css(template), BANNED_NETWORK_PATTERNS)
    assert not found, (
        f"{template}/style.css references something unresolvable {found}. render_pdf "
        "sets content with no base URL, so the reference would be silently dropped. "
        "Inline it as a data: URI."
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_style_does_not_use_multi_column_layout(template):
    """Two-column layouts, sidebars and grid placement destroy ATS parsing."""
    found = _violations(_style_css(template), BANNED_LAYOUT_PATTERNS)
    assert not found, f"{template}/style.css breaks the single-column rule: {found}"


# --- The guards must actually catch what they claim to catch ----------------
#
# Without these, a guard can be quietly reduced to a no-op and the suite stays
# green, because no template contains the thing it is supposed to reject.

REJECTED_LAYOUT = (
    ".sidebar { position: absolute; top: 0; right: 0; width: 2in; }",
    ".sidebar { position:absolute; }",
    ".sidebar { position   :   fixed; }",
    ".two-col { display: grid; grid-template-columns: 1fr 1fr; }",
    ".two-col { display: grid; grid-template: auto / 1fr 1fr; }",
    ".two-col { display: grid; grid: auto-flow / 1fr 1fr; }",
    ".two-col { grid-template-areas: 'main aside'; }",
    ".two-col { grid-auto-flow: column; }",
    ".aside { grid-column: 2 / 3; }",
    ".aside { grid-area: sidebar; }",
    ".body { columns: 2; }",
    ".body { column-count: 2; }",
    ".body { column-width: 18em; }",
    ".body { -webkit-column-count: 2; }",
    ".meta { float: right; }",
    ".meta { float:  inline-end; }",
)

REJECTED_NETWORK = (
    "@import url(//fonts.googleapis.com/css2?family=Inter);",
    "@import url(https://fonts.googleapis.com/css2?family=Inter);",
    '@import "shared.css";',
    "@font-face { src: url(//fonts.gstatic.com/s/inter.woff2); }",
    "@font-face { src: url('../fonts/inter.woff2'); }",
    "@font-face { src: url(fonts/inter.woff2); }",
    ".header { background-image: url(http://example.com/rule.png); }",
)

# Legitimate CSS the templates already use, or plausibly will. A guard that
# flags any of these is too broad and would block Tasks 8-10.
ACCEPTED = (
    ".item-head { display: flex; flex-wrap: wrap; }",
    ".meta { margin-left: auto; }",
    ".contact-line { column-gap: 0.6em; row-gap: 0.2em; }",
    ".item-head { justify-content: space-between; }",
    ".rule { position: relative; }",
    ".stack { display: grid; grid-gap: 0.4rem; }",
    "@font-face { src: url(data:font/woff2;base64,d09GMgAB) format('woff2'); }",
    "@font-face { src: url('data:font/woff2;base64,d09GMgAB'); }",
    ".name { font-size: var(--fs-name); letter-spacing: 0.02em; }",
    "/* upstream: https://rsms.me/inter/ - vendored, not fetched */",
    "/* .legacy { position: absolute; } kept for reference */",
)


@pytest.mark.parametrize("css", REJECTED_LAYOUT)
def test_the_layout_guard_rejects(css):
    assert _violations(css, BANNED_LAYOUT_PATTERNS), (
        f"the single-column guard does not catch {css!r}"
    )


@pytest.mark.parametrize("css", REJECTED_NETWORK)
def test_the_network_guard_rejects(css):
    assert _violations(css, BANNED_NETWORK_PATTERNS), (
        f"the network guard does not catch {css!r}"
    )


@pytest.mark.parametrize("css", (".item { break-inside: auto; }", ".item{page-break-inside:avoid}"))
def test_the_pagination_guard_rejects(css):
    assert _violations(css, PAGINATION_PATTERNS), (
        f"the pagination guard does not catch {css!r}"
    )


@pytest.mark.parametrize("css", ACCEPTED)
def test_the_guards_accept_legitimate_css(css):
    found = (
        _violations(css, BANNED_LAYOUT_PATTERNS)
        + _violations(css, BANNED_NETWORK_PATTERNS)
        + _violations(css, PAGINATION_PATTERNS)
    )
    assert not found, f"guard is too broad: {css!r} flagged as {found}"


def test_base_css_owns_item_pagination():
    assert "break-inside: var(--item-break)" in BASE_CSS
    assert "page-break-inside: var(--item-break)" in BASE_CSS


def test_no_stylesheet_uses_tabular_figures():
    """`tnum` is banned everywhere, in base.css and in every template.

    Several families -- Inter among them -- make the hyphen-minus
    tabular-width under `tnum`, so minus signs align in a column of figures.
    That stretches every hyphen in the text it touches.

    It was tried twice and failed twice. On `body` it turned
    "monolith-to-services" into "monolith - to - services". Scoped to `.meta`
    it still hit project URLs and locations, because `.meta` carries those as
    well as dates -- and the date itself is "2021-03", so the one element the
    rule existed to align was being pulled apart by it.
    """
    sources = {"base.css": BASE_CSS}
    for name in TEMPLATES:
        sources[f"{name}/style.css"] = (
            TEMPLATES_DIR / name / "style.css"
        ).read_text(encoding="utf-8")
    for where, css in sources.items():
        stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        assert "font-variant-numeric" not in stripped, (
            f"{where} uses font-variant-numeric; tabular figures stretch every "
            "hyphen in the text they touch, including the dates in .meta"
        )
        assert "tnum" not in stripped, (
            f"{where} enables tnum via font-feature-settings, which has the "
            "same effect as font-variant-numeric: tabular-nums"
        )


@pytest.mark.parametrize("template", TEMPLATES)
def test_a_centred_header_also_centres_the_capped_summary(template):
    """A centred header over a left-flush summary block reads as a mistake.

    base.css caps .summary at --measure, so any template that centres its
    header must also give the summary auto side margins or the paragraph sits
    flush left with a third of the column empty beside it. This is a contract,
    not a per-template assertion: it holds for whichever templates choose a
    centred header.
    """
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    header = re.search(r"\.resume-header\s*\{([^}]*)\}", stripped, re.DOTALL)
    if not header or "center" not in header.group(1):
        return  # not a centred-header template; nothing to hold it to
    summary = re.search(r"\.summary\s*\{([^}]*)\}", stripped, re.DOTALL)
    assert summary, (
        f"{template} centres its header but never sets .summary, so the capped "
        "summary block will sit flush left under it"
    )
    assert "auto" in summary.group(1), (
        f"{template} centres its header but its .summary has no auto side "
        "margin, so the block sits flush left under a centred header"
    )
