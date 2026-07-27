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
