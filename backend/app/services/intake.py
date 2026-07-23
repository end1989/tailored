"""Intake service: uploaded documents -> master profile via one structured Claude call."""
from __future__ import annotations

import io
from pathlib import Path

import docx
import pypdf


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """Return (kind, text) for an uploaded file.

    kind by extension: .pdf via pypdf, .docx via python-docx, anything else
    utf-8 decoded as kind "txt". The "paste" kind is assigned by the API layer.
    """
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        reader = pypdf.PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return "pdf", text
    if suffix == ".docx":
        document = docx.Document(io.BytesIO(data))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        return "docx", text
    return "txt", data.decode("utf-8", errors="replace")
