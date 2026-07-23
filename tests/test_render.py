"""Tests for backend/app/services/render.py (Task 10)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import backend.app.services.render as render_mod
from backend.app.schemas import (
    Contact,
    ExperienceItem,
    ExperienceSection,
    LinkItem,
    ResumeDoc,
    SkillGroup,
    SkillsSection,
    TailorResult,
)
from backend.app.services.render import (
    render_ats_text,
    render_cover_letter_html,
    render_pdf,
    render_resume_html,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


def _fixture_resume() -> ResumeDoc:
    data = json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))
    return TailorResult.model_validate(data).resume


def _small_resume() -> ResumeDoc:
    return ResumeDoc(
        contact=Contact(
            name="Jane Doe",
            email="jane@example.com",
            phone="555-0100",
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
                    )
                ]
            ),
            SkillsSection(
                groups=[SkillGroup(label="Languages", items=["Python", "TypeScript"])]
            ),
        ],
    )


def test_render_ats_text_exact():
    expected = (
        "JANE DOE\n"
        "jane@example.com | 555-0100\n"
        "GitHub: https://github.com/janedoe\n"
        "\n"
        "SENIOR BACKEND ENGINEER\n"
        "Backend engineer with 8 years building APIs.\n"
        "\n"
        "EXPERIENCE\n"
        "==========\n"
        "STAFF ENGINEER — Initech (2021–present) [Remote]\n"
        "- Led migration to event-driven architecture.\n"
        "- Cut p95 latency 40%.\n"
        "\n"
        "SKILLS\n"
        "======\n"
        "Languages: Python, TypeScript\n"
    )
    assert render_ats_text(_small_resume()) == expected


def test_render_resume_html_slate_contains_content():
    resume = _fixture_resume()
    html = render_resume_html(resume, "slate")
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<style>" in html  # CSS inlined -> standalone document
    assert resume.contact.name in html
    assert resume.headline in html
    for section in resume.sections:
        assert section.title in html
        if section.type == "experience":
            for item in section.items:
                assert item.company in html


def test_render_resume_html_escapes_html():
    resume = _small_resume()
    resume.sections[0].items[0].bullets.append(
        "Handled <script>alert('xss')</script> payloads"
    )
    html = render_resume_html(resume, "slate")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_cover_letter_html_converts_markdown():
    contact = _small_resume().contact
    md = "Dear Hiring Manager,\n\nI build **reliable** systems.\n\nSincerely,\n\nJane Doe"
    html = render_cover_letter_html(md, contact, "slate")
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<style>" in html
    assert "<strong>reliable</strong>" in html
    assert "<p>" in html
    assert "Jane Doe" in html


def test_render_cover_letter_html_escapes_raw_html():
    contact = Contact(name="Test Person", email="t@example.com")
    html_out = render_cover_letter_html(
        "Dear team,\n\n<script>alert(1)</script>\n\n**Sincerely**", contact, "slate"
    )
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "<strong>Sincerely</strong>" in html_out


def test_export_application_writes_five_files(tmp_path, monkeypatch):
    calls = []

    def fake_render_pdf(html, out_path, page_size="Letter"):
        calls.append((out_path, page_size))
        Path(out_path).write_bytes(b"%PDF-1.4 fake pdf for tests")

    monkeypatch.setattr(render_mod, "render_pdf", fake_render_pdf)
    resume = _small_resume()
    export_dir = render_mod.export_application(
        application_id=42,
        resume=resume,
        cover_md="Dear Hiring Manager,\n\nHello **there**.",
        contact=resume.contact,
        template="slate",
        data_dir=tmp_path,
    )
    assert export_dir == tmp_path / "exports" / "42"
    for name in (
        "resume.pdf",
        "resume.html",
        "resume.txt",
        "cover_letter.pdf",
        "cover_letter.txt",
    ):
        f = export_dir / name
        assert f.exists(), f"missing export: {name}"
        assert f.stat().st_size > 0, f"empty export: {name}"
    assert len(calls) == 2  # resume.pdf + cover_letter.pdf
    assert (export_dir / "cover_letter.txt").read_text(encoding="utf-8").startswith(
        "Dear Hiring Manager,"
    )


@pytest.mark.pdf
def test_render_pdf_produces_real_pdf(tmp_path):
    html = render_resume_html(_small_resume(), "slate")
    out = tmp_path / "resume.pdf"
    render_pdf(html, out, page_size="Letter")
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 1000
