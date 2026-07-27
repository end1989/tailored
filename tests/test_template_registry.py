"""The template registry: manifests on disk are the single source of truth."""
from __future__ import annotations

import json

import pytest

from backend.app.services.render import (
    TEMPLATE_REGISTRY,
    TEMPLATES,
    TEMPLATES_DIR,
    TemplateManifestError,
    load_registry,
)


def test_every_template_directory_has_a_manifest():
    dirs = {
        p.name
        for p in TEMPLATES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
        and p.name != "fonts"
    }
    assert dirs == set(TEMPLATE_REGISTRY)


def test_templates_tuple_is_derived_from_the_registry():
    assert TEMPLATES == tuple(TEMPLATE_REGISTRY)


def test_registry_is_ordered_by_the_manifest_order_field():
    orders = [m.order for m in TEMPLATE_REGISTRY.values()]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders), "two templates share an order value"


def test_meridian_is_first():
    assert TEMPLATES[0] == "meridian"


def test_manifest_name_matches_its_directory():
    for name, manifest in TEMPLATE_REGISTRY.items():
        assert manifest.name == name


def test_every_manifest_declares_a_known_structure():
    for manifest in TEMPLATE_REGISTRY.values():
        assert manifest.structure in ("experience-first", "projects-forward")


def test_every_declared_font_file_exists_on_disk():
    for manifest in TEMPLATE_REGISTRY.values():
        for face in manifest.fonts:
            path = TEMPLATES_DIR / "fonts" / face.file
            assert path.is_file(), f"{manifest.name} declares missing font {face.file}"


def test_malformed_manifest_raises_with_the_offending_path(tmp_path):
    """A silent skip would make a template vanish from the UI with no diagnosis."""
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "template.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(TemplateManifestError) as exc:
        load_registry(tmp_path)
    assert "broken" in str(exc.value)


def test_manifest_missing_a_required_field_raises(tmp_path):
    bad = tmp_path / "incomplete"
    bad.mkdir()
    (bad / "template.json").write_text(
        json.dumps({"name": "incomplete", "label": "Incomplete"}), encoding="utf-8"
    )
    with pytest.raises(TemplateManifestError) as exc:
        load_registry(tmp_path)
    assert "incomplete" in str(exc.value)


def test_manifest_name_disagreeing_with_its_directory_raises(tmp_path):
    bad = tmp_path / "alpha"
    bad.mkdir()
    (bad / "template.json").write_text(
        json.dumps(
            {
                "name": "beta",
                "label": "Beta",
                "description": "d",
                "best_for": "b",
                "structure": "experience-first",
                "order": 1,
                "fonts": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TemplateManifestError):
        load_registry(tmp_path)


def test_unknown_structure_value_raises(tmp_path):
    bad = tmp_path / "weird"
    bad.mkdir()
    (bad / "template.json").write_text(
        json.dumps(
            {
                "name": "weird",
                "label": "Weird",
                "description": "d",
                "best_for": "b",
                "structure": "sideways",
                "order": 1,
                "fonts": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TemplateManifestError):
        load_registry(tmp_path)


@pytest.mark.parametrize("fonts", (None, 12, True, "Inter", {"family": "Inter"}))
def test_a_non_list_fonts_value_raises_with_the_offending_path(tmp_path, fonts):
    """`"fonts": null` must fail the same way every other manifest defect does.

    The font loop used to iterate raw["fonts"] directly, so a null escaped as a
    bare TypeError with no path in it, and a string or object was iterated
    element-wise into a nonsense "missing key" message. Either way the one job
    of TemplateManifestError - name the file to fix - went undone.
    """
    bad = tmp_path / "nolist"
    bad.mkdir()
    (bad / "template.json").write_text(
        json.dumps(
            {
                "name": "nolist",
                "label": "No List",
                "description": "d",
                "best_for": "b",
                "structure": "experience-first",
                "order": 1,
                "fonts": fonts,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TemplateManifestError) as exc:
        load_registry(tmp_path)
    assert "nolist" in str(exc.value)
    assert "array" in str(exc.value)


import base64
import re

from backend.app.services.render import (
    FontFace,
    _font_css,
    _load_css,
    render_resume_html,
)


def test_font_css_is_empty_for_a_template_with_no_fonts():
    assert _font_css("meridian") == ""


def test_font_css_emits_one_face_per_declared_font():
    css = _font_css("slate")
    assert css.count("@font-face") == len(TEMPLATE_REGISTRY["slate"].fonts)


def test_font_css_inlines_the_bytes_as_a_data_uri():
    css = _font_css("slate")
    face = TEMPLATE_REGISTRY["slate"].fonts[0]
    raw = (TEMPLATES_DIR / "fonts" / face.file).read_bytes()
    assert base64.b64encode(raw).decode("ascii") in css
    assert "data:font/woff2;base64," in css
    assert "https://" not in css, "a render-time network reference would drop silently"


def test_font_css_never_inlines_the_same_file_twice():
    """A variable font covers several weights with one file. Emitting it once per
    weight would multiply the size of every exported HTML document."""
    for name in TEMPLATES:
        css = _font_css(name)
        payloads = re.findall(r"base64,([A-Za-z0-9+/=]+)\)", css)
        assert len(payloads) == len(set(payloads)), f"{name} inlines a font twice"


def test_font_css_is_cached_per_template():
    _font_css.cache_clear()
    _font_css("slate")
    _font_css("slate")
    assert _font_css.cache_info().hits >= 1


def test_load_css_puts_font_faces_ahead_of_the_template_style():
    _base, style = _load_css("slate")
    assert style.index("@font-face") < style.index("body")


def test_rendered_html_carries_the_font_faces():
    resume = _registry_fixture_resume()
    html = render_resume_html(resume, "slate")
    assert "data:font/woff2;base64," in html


def _registry_fixture_resume():
    import json as _json
    from pathlib import Path as _Path

    from backend.app.schemas import TailorResult

    fixtures = _Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"
    data = _json.loads((fixtures / "tailor.json").read_text(encoding="utf-8"))
    return TailorResult.model_validate(data).resume


# --- The manifest and the stylesheet must agree on the family name ---------
#
# Every test above inspects the CSS `_font_css` produces. None of them checks
# that anything *consumes* it, and that is the exact failure `_font_css` exists
# to prevent, seen from the other end: transpose one character in slate's
# `font-family: Inter, ...` and the whole suite stays green while every slate
# export renders in the Segoe UI fallback and still carries 128 KB of
# unreachable base64 Inter. Chromium does not report an unmatched family, so
# nothing downstream errors either.


def _families_in(css: str) -> frozenset[str]:
    """Every individual family name the `font-family:` declarations ask for.

    Split on commas and unquoted, so each name is compared whole. A substring
    test over the raw text cannot tell a family from a longer one that starts
    with the same words, and two of the families vendored here have exactly such
    a sibling on Google Fonts: `Inter Tight` and `IBM Plex Sans Condensed`. So
    that blind spot is not hypothetical - either name is one plausible edit away.

    Comments are stripped so a family named only in a header comment does not
    count as a reference.
    """
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    names = set()
    for value in re.findall(r"font-family\s*:([^;}]*)", stripped):
        for token in value.split(","):
            # An unquoted family name may contain spaces (`font-family: Inter
            # Tight, sans-serif`), so collapse runs of whitespace rather than
            # splitting on them.
            name = " ".join(token.strip().strip("\"'").split())
            if name:
                names.add(name)
    return frozenset(names)


def _font_families_named(template: str) -> frozenset[str]:
    """The families one template's own style.css asks for.

    Read from disk rather than through `_load_css`, which prepends the generated
    @font-face block: its own `font-family:` line would make every check below
    trivially self-satisfying.
    """
    return _families_in((TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8"))


def test_the_font_family_parse_does_not_confuse_a_family_with_a_longer_sibling():
    """`Inter Tight` is a real, separate, unvendored Google family.

    Both agreement tests below used to substring-search the raw declaration
    text, which reads `"Inter Tight"` as a reference to `Inter` and so goes
    green on a stylesheet asking for a family no manifest embeds and no
    @font-face defines - the exact silent fallback they exist to catch.
    """
    named = _families_in('body { font-family: "Inter Tight", "Segoe UI", sans-serif; }')
    assert named == {"Inter Tight", "Segoe UI", "sans-serif"}


def test_the_font_family_parse_ignores_a_family_named_only_in_a_comment():
    css = "/* font-family: Inter; */\nbody { font-family: Georgia, serif; }"
    assert _families_in(css) == {"Georgia", "serif"}


def _vendored_families() -> frozenset[str]:
    """Family display names from the fonts LICENSES.md provenance table.

    Used instead of a second hardcoded roster: tests/test_vendored_fonts.py
    already asserts that table and the binaries on disk agree in both
    directions, so this stays correct as families are added.
    """
    text = (TEMPLATES_DIR / "fonts" / "LICENSES.md").read_text(encoding="utf-8")
    return frozenset(
        row.split("|")[1].strip()
        for row in text.splitlines()
        if row.startswith("| ") and "http" in row
    )


def test_every_declared_font_family_is_named_in_the_template_stylesheet():
    """An embedded family the stylesheet never asks for is dead weight.

    The bytes ship in every export and no glyph of them is ever drawn.
    """
    for name, manifest in TEMPLATE_REGISTRY.items():
        named = _font_families_named(name)
        for face in manifest.fonts:
            assert face.family in named, (
                f"{name}/template.json embeds {face.family!r} but "
                f"{name}/style.css never names it in a font-family declaration; "
                f"it asks for {sorted(named)}. The inlined @font-face is "
                "unreachable and the template renders in a system fallback, "
                "silently."
            )


# --- The licence file must satisfy the licence ------------------------------
#
# OFL 1.1 condition 2 permits redistributing the font software "provided that
# each copy contains the above copyright notice and this license". Fourteen
# woff2 binaries are committed here and base64-inlined into every export, so
# LICENSES.md is the only place that notice and that licence can travel with
# them. A hyperlink to openfontlicense.org is neither: it carries no copyright
# notice at all, and a link is not a copy.

LICENCES_PATH = TEMPLATES_DIR / "fonts" / "LICENSES.md"


def _licences_text() -> str:
    return LICENCES_PATH.read_text(encoding="utf-8")


def _copyright_notices() -> dict[str, list[str]]:
    """Each `### Family` heading in LICENSES.md mapped to its Copyright lines.

    Structural rather than a bare substring count: it is what distinguishes
    "seven families each carry their own notice" from "one family carries seven".
    """
    notices: dict[str, list[str]] = {}
    current: str | None = None
    for line in _licences_text().splitlines():
        if line.startswith("### "):
            current = line[4:].strip()
            notices[current] = []
        elif line.startswith("## "):
            current = None
        elif current and line.strip().startswith("Copyright"):
            notices[current].append(line.strip())
    return notices


def test_the_licence_file_reproduces_the_full_ofl_text():
    """Not the title alone: the operative clauses have to be here verbatim."""
    text = _licences_text()
    assert "SIL OPEN FONT LICENSE Version 1.1" in text
    for clause in (
        "PREAMBLE",
        "DEFINITIONS",
        "PERMISSION",
        "Permission is hereby granted, free of charge",
        "contains the above copyright notice and this license",
        "TERMINATION",
        "DISCLAIMER",
        'THE FONT SOFTWARE IS PROVIDED "AS IS"',
    ):
        assert clause in text, f"LICENSES.md omits the OFL clause {clause!r}"


def test_every_vendored_family_carries_its_own_copyright_notice():
    """One notice per family. The OFL requires "the above copyright notice",
    which is the holder's own line, not a generic mention of the word."""
    families = _vendored_families()
    assert families, "LICENSES.md lists no families; the parse above is broken"
    notices = _copyright_notices()
    assert set(notices) == families, (
        "the copyright-notice sections and the provenance table disagree: "
        f"{families ^ set(notices)}"
    )
    for family, lines in sorted(notices.items()):
        assert lines, (
            f"{family} is vendored but LICENSES.md gives no copyright line for "
            "it. Fetch it from the family's own upstream licence file; do not "
            "invent one."
        )


def test_every_family_a_manifest_embeds_is_named_in_the_licence_file():
    """A family shipped in an export with no licence entry is an unaccounted
    redistribution, and manifests are where families actually reach users.

    Matched against the parsed provenance table rather than searched for in the
    file text: `"Inter" in text` is also satisfied by an entry for Inter Tight,
    and an entry for a different family is not a licence for this one.
    """
    listed = _vendored_families()
    embedded = {face.family for m in TEMPLATE_REGISTRY.values() for face in m.fonts}
    assert embedded, "no manifest embeds a font; this test would assert nothing"
    for family in sorted(embedded):
        assert family in listed, (
            f"{family} is embedded by a template but is not a row of the "
            f"LICENSES.md provenance table, which lists {sorted(listed)}."
        )


def test_every_vendored_family_a_stylesheet_asks_for_is_embedded():
    """The same disagreement from the other side: asked for but not embedded.

    render_pdf calls page.set_content with no base URL and Chromium has none of
    these families installed, so a stylesheet naming a vendored family that its
    manifest does not declare falls straight through to the next stack entry.
    """
    vendored = _vendored_families()
    assert vendored, "LICENSES.md lists no families; the parse above is broken"
    for name, manifest in TEMPLATE_REGISTRY.items():
        named = _font_families_named(name)
        embedded = {face.family for face in manifest.fonts}
        for family in sorted(vendored):
            if family in named:
                assert family in embedded, (
                    f"{name}/style.css asks for the vendored family {family!r} "
                    f"but {name}/template.json does not embed it. Chromium "
                    "cannot resolve it and falls back without an error."
                )


# --- The two serif templates ------------------------------------------------

SERIF_TEMPLATES = {
    "ledger": ("Ledger", 5, "Source Serif 4"),
    "quarto": ("Quarto", 6, "EB Garamond"),
}


@pytest.mark.parametrize("name", sorted(SERIF_TEMPLATES))
def test_the_serif_template_is_registered_with_its_own_family(name):
    """Both are new directories, and a directory is all they are until the
    manifest names them, the registry finds them and the stylesheet asks for the
    family the manifest embeds. Every other check in this suite is parametrised
    over TEMPLATES, so a template that failed to register would simply not be
    tested rather than fail."""
    label, order, family = SERIF_TEMPLATES[name]
    assert name in TEMPLATE_REGISTRY, (
        f"{name} is not in the registry; every check parametrised over "
        "TEMPLATES would silently skip it"
    )
    manifest = TEMPLATE_REGISTRY[name]
    assert (manifest.label, manifest.order) == (label, order)
    assert {face.family for face in manifest.fonts} == {family}
    assert family in _font_families_named(name)


# --- The dense one and the plain one ----------------------------------------


def test_dossier_is_registered_with_its_own_family():
    """The same registration guard the serifs get, for the same reason: a
    directory nothing registers is skipped by every check parametrised over
    TEMPLATES rather than failing one."""
    assert "dossier" in TEMPLATE_REGISTRY, (
        "dossier is not in the registry; every check parametrised over "
        "TEMPLATES would silently skip it"
    )
    manifest = TEMPLATE_REGISTRY["dossier"]
    assert (manifest.label, manifest.order) == ("Dossier", 7)
    assert {face.family for face in manifest.fonts} == {"Source Sans 3"}
    assert "Source Sans 3" in _font_families_named("dossier")


def test_plainwork_is_registered_and_embeds_no_font():
    """Plainwork's emptiness is the design, and nothing else in the suite asserts
    it: the font tests all read from the manifests, so a manifest that embeds
    nothing is invisible to them. An embedded face is one more variable between
    the document and a hostile parser, which is the one thing this template
    exists to minimise - and its stack is Arial, which the machine already has.
    """
    assert "plainwork" in TEMPLATE_REGISTRY, (
        "plainwork is not in the registry; every check parametrised over "
        "TEMPLATES would silently skip it"
    )
    manifest = TEMPLATE_REGISTRY["plainwork"]
    assert (manifest.label, manifest.order) == ("Plainwork", 8)
    assert manifest.fonts == (), (
        "plainwork/template.json embeds a font. It must stay empty: the "
        "template's whole purpose is handing a parser the fewest variables "
        "possible, and Arial and its fallbacks are system faces."
    )


# --- The manifest and the stylesheet must agree on the WEIGHTS too ----------
#
# The family checks above pair the two on the name and stop there. The weight is
# just as capable of disagreeing, and fails just as quietly. Every family here is
# a latin subset cut to the weight range `scripts/vendor_fonts.py` asked Google
# for, and four of the seven stop at 600. `font-weight: 700` against a face
# declared `400 600` raises nothing: the matching algorithm picks the only face
# there is, clamps the variation axis to its maximum, and Chromium may smear the
# rest on synthetically. The page looks near enough right that no render test can
# see it, and the weight the stylesheet wrote down is not the weight that prints.
#
# Resolving that request means resolving family, style and weight TOGETHER, and
# a stylesheet rarely declares all three in one block: terminal names
# `.skill-label`'s family in a list it shares with `.skill-items` and sets its
# weight two rules later, and every template sets a weight on `.item-head`-style
# containers that their `.secondary` children inherit. So the properties are
# accumulated per selector across every rule that names it, and a selector
# inherits from the ancestor its own text spells out, falling back to `body`.
#
# The parse is deliberately shallow, and these are its assumptions:
#   * rules are flat - a nested at-rule raises rather than being mis-read;
#   * a selector is matched by its literal text, so two different selectors that
#     reach the same element (`.secondary` and `.item-head .secondary`) are
#     treated as unrelated, and specificity never enters into it: within one
#     selector, document order decides;
#   * the only inheritance visible to a flat parse is the one a descendant
#     selector writes down. An element whose real DOM ancestor is styled under a
#     selector that does not appear in its own falls back to `body`.
#   * combinators other than descendant are rejected rather than guessed at.
# It is a guard against a stylesheet asking for a weight nobody vendored, not a
# cascade implementation.

_RULE_RE = re.compile(r"(?P<selector>[^{}]*)\{(?P<body>[^{}]*)\}")
_KEYWORD_WEIGHTS = {"normal": 400, "bold": 700}


def _rules(css: str) -> list[tuple[str, str]]:
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    for at_rule in ("@media", "@supports"):
        assert at_rule not in stripped, (
            f"{at_rule} nests rules inside rules and this parse is flat; it "
            "would read the at-rule's prelude as a declaration block. Rewrite "
            "_rules before a stylesheet uses one."
        )
    return [
        (match.group("selector").strip(), match.group("body"))
        for match in _RULE_RE.finditer(stripped)
    ]


def _last_value(body: str, prop: str) -> str | None:
    """The winning value of one property in one block: later declarations win."""
    values = re.findall(rf"(?<![\w-]){prop}\s*:([^;]*)", body)
    return values[-1].strip() if values else None


def _first_family(value: str) -> str:
    return " ".join(value.split(",")[0].strip().strip("\"'").split())


def _weight_number(value: str) -> int:
    if value in _KEYWORD_WEIGHTS:
        return _KEYWORD_WEIGHTS[value]
    assert value.isdigit(), (
        f"unreadable font-weight {value!r}: this check can only compare numeric "
        "weights against the range a manifest declares"
    )
    return int(value)


def _covers(face, weight: int) -> bool:
    """A face's `weight` is "400" or a range "400 600"; both are inclusive."""
    bounds = [int(part) for part in face.weight.split()]
    return bounds[0] <= weight <= bounds[-1]


_FONT_PROPS = ("font-family", "font-weight", "font-style")
_COMBINATORS = (">", "+", "~")


def _declared_font_properties(rules) -> dict[str, dict[str, str]]:
    """selector -> the font declarations that land on it, later rules winning.

    One selector may be written across several rules - terminal declares
    `.skill-label`'s family in a list shared with `.skill-items` and its weight
    in a block of its own - so reading a block in isolation would resolve the
    weight against the wrong family. The declarations accumulate instead.
    """
    declared: dict[str, dict[str, str]] = {}
    for selector_list, body in rules:
        values = {
            prop: value
            for prop in _FONT_PROPS
            if (value := _last_value(body, prop)) is not None
        }
        if not values:
            continue
        for part in selector_list.split(","):
            selector = " ".join(part.split())
            if not selector:
                continue
            assert not any(c in selector for c in _COMBINATORS), (
                f"{selector!r} uses a combinator. This resolver reads the prefix "
                "of a descendant selector as the context it inherits from, and "
                "would read a sibling's prefix as one too. Rewrite "
                "_inherits_from before a stylesheet uses one."
            )
            declared.setdefault(selector, {}).update(values)
    return declared


def _inherits_from(selector: str) -> str:
    """The context a selector inherits from: the ancestor its own text names.

    `.item-head .secondary` inherits from `.item-head`, `.resume-header::after`
    from `.resume-header`, and a bare class from nothing (i.e. from `body`).
    """
    if "::" in selector:
        return selector.rsplit("::", 1)[0]
    return " ".join(selector.split()[:-1])


def _computed_font(selector: str, declared: dict[str, dict[str, str]], root: dict) -> dict:
    chain = []
    current = selector
    while current:
        if current in declared:
            chain.append(declared[current])
        current = _inherits_from(current)
    computed = dict(root)
    for values in reversed(chain):
        computed.update(values)
    return computed


def _uncovered_weights(css: str, faces) -> list[str]:
    """Every (family, style, weight) the stylesheet asks for that no face serves.

    Families the manifest does not embed are skipped: a system stack carries
    whatever the machine has, and a *vendored* family named without being
    embedded already fails test_every_vendored_family_a_stylesheet_asks_for_is_embedded.
    """
    declared = _declared_font_properties(_rules(css))
    embedded = {face.family for face in faces}
    root = {"font-family": "", "font-weight": "400", "font-style": "normal"}
    root.update(declared.get("body", {}))

    missing: list[str] = []
    for selector in declared:
        computed = _computed_font(selector, declared, root)
        family_value = computed["font-family"]
        family = _first_family(family_value) if family_value else ""
        if family not in embedded:
            continue
        style = (
            "italic"
            if computed["font-style"].strip() in ("italic", "oblique")
            else "normal"
        )
        weight = _weight_number(computed["font-weight"].strip())
        if not any(
            face.family == family and face.style == style and _covers(face, weight)
            for face in faces
        ):
            missing.append(f"{selector} asks for {family} {style} {weight}")
    return missing


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_weight_a_stylesheet_asks_for_is_covered_by_an_embedded_face(template):
    manifest = TEMPLATE_REGISTRY[template]
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    uncovered = _uncovered_weights(css, manifest.fonts)
    assert not uncovered, (
        f"{template}/style.css asks for weights no embedded face covers: "
        f"{uncovered}. The declared faces are "
        f"{[(f.family, f.style, f.weight) for f in manifest.fonts]}. Vendor the "
        "missing weight or move the stylesheet inside the range - Chromium "
        "clamps to the nearest available weight without reporting anything."
    )


# The two headings are <h1 class="name"> and <h2 class="section-title">, and the
# UA stylesheet sets both to `bold`, i.e. 700. A template that leaves either at
# the default is asking a 400-600 face for a weight it does not have, without a
# single font-weight declaration in its stylesheet for the check above to read.


@pytest.mark.parametrize("template", TEMPLATES)
@pytest.mark.parametrize("heading", (".name", ".section-title"))
def test_the_heading_classes_declare_their_weight_explicitly(template, heading):
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    declared = any(
        any(part.strip() == heading for part in selector.split(","))
        and _last_value(body, "font-weight")
        for selector, body in _rules(css)
    )
    assert declared, (
        f"{template}/style.css never sets font-weight on {heading}, which is a "
        "heading element: it inherits the UA stylesheet's bold (700) rather "
        "than a weight this template chose, and 700 is outside the range of "
        "several of the vendored faces."
    )


# The weight guard has to actually catch what it claims to. Without these it can
# be reduced to a no-op - or quietly parse nothing at all - and the suite stays
# green, because no template on disk contains the thing it rejects.

_FAKE_FACES = (
    FontFace(family="Fake Serif", file="fake-normal.woff2", weight="400 600", style="normal"),
    FontFace(family="Fake Serif", file="fake-italic.woff2", weight="400", style="italic"),
    # A second family, static rather than variable, the way a mono companion is
    # usually cut: two discrete weights and nothing between or beyond them.
    FontFace(family="Fake Mono", file="fake-mono-400.woff2", weight="400", style="normal"),
    FontFace(family="Fake Mono", file="fake-mono-500.woff2", weight="500", style="normal"),
)
_FAKE_BODY = 'body { font-family: "Fake Serif", Georgia, serif; }\n'


@pytest.mark.parametrize(
    "css",
    (
        ".name { font-weight: 700; }",
        ".name { font-weight: bold; }",
        ".name { font-weight: 400; font-weight: 900; }",
        ".headline { font-style: italic; font-weight: 600; }",
        ".rule { font-family: 'Fake Serif'; font-weight: 300; }",
        # The family is declared for this selector in an EARLIER rule, in a list
        # shared with a sibling, and the weight in a rule of its own. Reading a
        # block in isolation resolves the second rule against body's family and
        # waves through a weight the family it really uses never vendored -
        # which is the exact shape terminal/style.css writes .skill-label in.
        '.mono, .mono-items { font-family: "Fake Mono", monospace; }\n'
        ".mono { font-weight: 600; }",
        # The family comes from the ancestor the selector itself names.
        '.card { font-family: "Fake Mono", monospace; }\n'
        ".card .label { font-weight: 600; }",
        # The weight comes from the ancestor the selector itself names: the
        # descendant turns it italic, and only the upright face reaches 600.
        ".item-head { font-weight: 600; }\n.item-head .secondary { font-style: italic; }",
    ),
)
def test_the_weight_guard_rejects(css):
    assert _uncovered_weights(_FAKE_BODY + css, _FAKE_FACES), (
        f"the weight guard does not catch {css!r}"
    )


@pytest.mark.parametrize(
    "css",
    (
        ".name { font-weight: 600; }",
        ".name { font-weight: normal; }",
        ".headline { font-style: italic; }",
        ".headline { font-style: italic; font-weight: 400; }",
        ".skills { font-family: 'Not Vendored', monospace; font-weight: 900; }",
        ".meta { color: #555; margin-left: auto; }",
        "/* .name { font-weight: 900; } */",
        '.mono, .mono-items { font-family: "Fake Mono", monospace; }\n'
        ".mono { font-weight: 500; }",
        '.card { font-family: "Fake Mono", monospace; }\n'
        ".card .label { font-weight: 500; }",
        ".item-head { font-weight: 400; }\n.item-head .secondary { font-style: italic; }",
    ),
)
def test_the_weight_guard_accepts_what_the_faces_serve(css):
    found = _uncovered_weights(_FAKE_BODY + css, _FAKE_FACES)
    assert not found, f"the weight guard is too strict: {css!r} flagged as {found}"


def test_the_weight_guard_names_the_family_the_element_really_resolves_to():
    """A report that names the wrong family sends the fix to the wrong font.

    `.mono` computes to Fake Mono, not to body's Fake Serif; blaming Fake Serif
    would point at a face that does cover 700 in some other template and read as
    a false alarm.
    """
    css = '.mono, .mono-items { font-family: "Fake Mono", monospace; }\n.mono { font-weight: 700; }'
    assert _uncovered_weights(_FAKE_BODY + css, _FAKE_FACES) == [
        ".mono asks for Fake Mono normal 700"
    ]


def test_the_weight_guard_refuses_to_parse_a_nested_at_rule():
    """Silently mis-reading @media would turn this whole check into noise."""
    with pytest.raises(AssertionError, match="@media"):
        _uncovered_weights("@media print { body { font-weight: 900; } }", _FAKE_FACES)
