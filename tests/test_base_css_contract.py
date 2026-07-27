"""base.css owns structure; style.css owns identity. This test keeps them apart."""
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


@pytest.mark.parametrize("prop", REQUIRED_PROPERTIES)
def test_base_css_defines_the_shared_property(prop):
    assert re.search(rf"^\s*{re.escape(prop)}\s*:", BASE_CSS, re.MULTILINE), (
        f"base.css must define {prop}; templates override its value, not its meaning"
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_style_does_not_declare_pagination(template):
    """Pagination is structural. A template that redefines it is a bug."""
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    for prop in ("break-inside", "page-break-inside"):
        assert not re.search(rf"(?<!-)\b{prop}\s*:", stripped), (
            f"{template}/style.css declares {prop}. Structure belongs in base.css; "
            "set --item-break instead if this template needs breakable items."
        )


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_style_does_not_reference_the_network(template):
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    assert "http://" not in css and "https://" not in css, (
        f"{template}/style.css references a URL. render_pdf sets content with no "
        "base URL, so the reference would be silently dropped."
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_style_does_not_use_multi_column_layout(template):
    """Two-column layouts, sidebars and grid placement destroy ATS parsing."""
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    for banned in ("column-count", "grid-template-columns", "position: absolute"):
        assert banned not in stripped, f"{template}/style.css uses {banned}"


def test_base_css_owns_item_pagination():
    assert "break-inside: var(--item-break)" in BASE_CSS
    assert "page-break-inside: var(--item-break)" in BASE_CSS
