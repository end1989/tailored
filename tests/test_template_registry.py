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
