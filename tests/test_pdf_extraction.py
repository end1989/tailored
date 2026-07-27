"""Every template must round-trip through PDF with its text intact and in order.

This is the test that converts "AI searchable" from an intention into something
that fails the build. The specific failure it exists to catch is an embedded
font subset shipped without a usable ToUnicode mapping: it renders correctly to
the eye and extracts as garbage to an ATS.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from backend.app.schemas import TailorResult
from backend.app.services.render import TEMPLATES, render_resume_html

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"

pytestmark = pytest.mark.pdf


def _fixture_resume():
    data = json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))
    return TailorResult.model_validate(data).resume


@pytest.fixture(scope="module")
def rendered_text(tmp_path_factory) -> dict[str, str]:
    """template name -> text extracted from its rendered PDF.

    One Chromium launch for all templates; render_pdf launches per call.
    """
    from playwright.sync_api import sync_playwright

    resume = _fixture_resume()
    out_dir = tmp_path_factory.mktemp("extraction")
    texts: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for name in TEMPLATES:
                page = browser.new_page()
                page.set_content(render_resume_html(resume, name), wait_until="load")
                pdf_path = out_dir / f"{name}.pdf"
                page.pdf(
                    path=str(pdf_path),
                    format="Letter",
                    print_background=True,
                    margin={
                        "top": "0.5in",
                        "right": "0.5in",
                        "bottom": "0.5in",
                        "left": "0.5in",
                    },
                )
                page.close()
                texts[name] = "\n".join(
                    pg.extract_text() for pg in PdfReader(str(pdf_path)).pages
                )
        finally:
            browser.close()
    return texts


@pytest.mark.parametrize("template", TEMPLATES)
def test_pdf_extraction_preserves_every_employer_title_and_date(
    rendered_text, template
):
    resume = _fixture_resume()
    text = rendered_text[template]
    for section in resume.sections:
        if section.type != "experience":
            continue
        for item in section.items:
            for field in (item.company, item.role, item.start):
                assert field in text, (
                    f"{template}: {field!r} missing from extracted PDF text. "
                    "The font subset or the markup has broken text extraction."
                )


@pytest.mark.parametrize("template", TEMPLATES)
def test_pdf_extraction_preserves_document_order(rendered_text, template):
    """Employers must appear in the PDF in the same order as in the document.

    An ATS reads top to bottom. A layout that visually reorders content relative
    to the extraction stream produces a resume that reads as nonsense to a parser
    even though it looks correct on screen.
    """
    resume = _fixture_resume()
    text = rendered_text[template]
    companies = [
        item.company
        for section in resume.sections
        if section.type == "experience"
        for item in section.items
    ]
    positions = [text.index(c) for c in companies]
    assert positions == sorted(positions), (
        f"{template}: employers extract out of document order. "
        f"expected {companies}, got positions {positions}"
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_pdf_extraction_preserves_contact_details(rendered_text, template):
    resume = _fixture_resume()
    text = rendered_text[template]
    assert resume.contact.name in text
    assert resume.contact.email in text
