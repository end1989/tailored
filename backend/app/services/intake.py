"""Intake service: uploaded documents -> master profile via one structured Claude call."""
from __future__ import annotations

import io
from pathlib import Path

import docx
import pypdf
from pydantic import BaseModel

from ..schemas import Contact, MasterProfile, UsageInfo
from .claude import ClaudeService


class IntakeResult(BaseModel):
    contact: Contact
    master_profile: MasterProfile


INTAKE_SYSTEM = """You are an expert resume-intake analyst. You will receive the full text of one or more documents a person has provided about their career (resumes, CVs, notes, bios).

Extract EVERYTHING into the structured schema. Rules:

1. Capture every job: company, title, start and end dates (YYYY-MM when the month is known, otherwise YYYY; end is null only when the role is clearly current), and location when stated.
2. Capture every bullet/accomplishment under the job it belongs to. Keep numbers, percentages, and metrics VERBATIM - never round, estimate, or embellish them.
3. Tag each bullet with the skills and themes it demonstrates (lowercase, e.g. "python", "leadership", "performance", "testing"). Tags come only from what the bullet actually shows.
4. Capture all projects, skills (grouped sensibly), education, and certifications.
5. Anything that fits nowhere else (talks, publications, awards, volunteering) goes in extras.
6. NEVER invent, infer, or embellish facts. If a detail is not in the documents, leave it out. Do not create employers, titles, dates, degrees, certifications, tools, or metrics that are not explicitly present.
7. summary_notes: a brief factual synthesis of the person's background, written strictly from the documents.
8. contact: extract name, email, phone, location, and links exactly as they appear; use empty or null values for anything absent.

Multiple documents may overlap; merge duplicates, preferring the most detailed version of each fact."""


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


def _join_docs(docs: list[str]) -> str:
    parts = []
    for index, doc in enumerate(docs, start=1):
        parts.append(f"--- DOCUMENT {index} ---\n{doc.strip()}")
    return "\n\n".join(parts)


def build_master_profile(
    docs: list[str], claude: ClaudeService
) -> tuple[MasterProfile, Contact, UsageInfo]:
    """One structured call (task='intake') turning raw document texts into a master profile."""
    result, usage = claude.structured(
        task="intake",
        system=INTAKE_SYSTEM,
        user_content=_join_docs(docs),
        schema_model=IntakeResult,
    )
    assert isinstance(result, IntakeResult)
    return result.master_profile, result.contact, usage
