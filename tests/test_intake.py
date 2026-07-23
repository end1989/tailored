"""Tests for backend/app/services/intake.py."""
from __future__ import annotations

import io

import docx
import pypdf

from backend.app.services.intake import extract_text


def test_extract_text_txt_bytes():
    kind, text = extract_text(
        "notes.txt", "Jordan Rivera\nSenior engineer notes.".encode("utf-8")
    )
    assert kind == "txt"
    assert text == "Jordan Rivera\nSenior engineer notes."


def test_extract_text_unknown_extension_defaults_to_txt():
    kind, text = extract_text("bio.md", b"# Bio\nBackend engineer.")
    assert kind == "txt"
    assert text == "# Bio\nBackend engineer."


def test_extract_text_docx_roundtrip():
    buffer = io.BytesIO()
    document = docx.Document()
    document.add_paragraph("Jordan Rivera")
    document.add_paragraph("Senior Software Engineer at Cascade Analytics")
    document.save(buffer)
    kind, text = extract_text("resume.docx", buffer.getvalue())
    assert kind == "docx"
    assert "Jordan Rivera" in text
    assert "Senior Software Engineer at Cascade Analytics" in text


def test_extract_text_pdf_via_stubbed_reader(monkeypatch):
    class StubPage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class StubReader:
        def __init__(self, stream) -> None:
            self.pages = [StubPage("Page one text"), StubPage("Page two text")]

    monkeypatch.setattr(pypdf, "PdfReader", StubReader)
    kind, text = extract_text("resume.pdf", b"%PDF-1.7 fake bytes")
    assert kind == "pdf"
    assert text == "Page one text\nPage two text"
