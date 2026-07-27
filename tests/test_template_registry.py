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


import base64
import re

from backend.app.services.render import _font_css, _load_css, render_resume_html


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


def _font_family_declarations(template: str) -> str:
    """The `font-family:` values in one template's own style.css.

    Read from disk rather than through `_load_css`, which prepends the generated
    @font-face block: its own `font-family:` line would make every check below
    trivially self-satisfying. Comments are stripped so a family named only in a
    header comment does not count as a reference.
    """
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return "\n".join(re.findall(r"font-family\s*:[^;}]*", stripped))


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
        declarations = _font_family_declarations(name)
        for face in manifest.fonts:
            assert face.family in declarations, (
                f"{name}/template.json embeds {face.family!r} but "
                f"{name}/style.css never names it in a font-family declaration. "
                "The inlined @font-face is unreachable and the template renders "
                "in a system fallback, silently."
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
    redistribution, and manifests are where families actually reach users."""
    text = _licences_text()
    embedded = {face.family for m in TEMPLATE_REGISTRY.values() for face in m.fonts}
    assert embedded, "no manifest embeds a font; this test would assert nothing"
    for family in sorted(embedded):
        assert family in text, f"{family} is embedded by a template but absent from LICENSES.md"


def test_every_vendored_family_a_stylesheet_asks_for_is_embedded():
    """The same disagreement from the other side: asked for but not embedded.

    render_pdf calls page.set_content with no base URL and Chromium has none of
    these families installed, so a stylesheet naming a vendored family that its
    manifest does not declare falls straight through to the next stack entry.
    """
    vendored = _vendored_families()
    assert vendored, "LICENSES.md lists no families; the parse above is broken"
    for name, manifest in TEMPLATE_REGISTRY.items():
        declarations = _font_family_declarations(name)
        embedded = {face.family for face in manifest.fonts}
        for family in sorted(vendored):
            if family in declarations:
                assert family in embedded, (
                    f"{name}/style.css asks for the vendored family {family!r} "
                    f"but {name}/template.json does not embed it. Chromium "
                    "cannot resolve it and falls back without an error."
                )
