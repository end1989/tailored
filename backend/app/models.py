from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from .schemas import Contact, MasterProfile, ParsedPosting, ResearchFindings, ResumeDoc


class Profile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    contact_json: str = "{}"
    master_profile_json: str = "{}"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SourceDocument(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profile.id")
    filename: str
    kind: str  # "pdf" | "docx" | "txt" | "paste"
    text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str
    raw_text: Optional[str] = None
    parsed_json: Optional[str] = None       # ParsedPosting
    fetch_status: str = "pending"           # "pending"|"fetched"|"needs_paste"|"pasted"
    depth: str = "standard"                 # "quick"|"standard"|"deep"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ResearchBrief(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id")
    depth: str
    findings_json: str = "{}"               # ResearchFindings
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profile.id")
    job_id: int = Field(foreign_key="job.id")
    template: str = "slate"
    status: str = "queued"
    error_message: Optional[str] = None
    version: int = 1
    resume_json: Optional[str] = None       # ResumeDoc
    cover_letter_md: Optional[str] = None
    tailoring_notes: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    export_dir: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ApplicationVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="application.id")
    version: int
    resume_json: str
    cover_letter_md: str
    tailoring_notes: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- Typed JSON helpers (TEXT columns <-> Pydantic objects) ---

def get_contact(p: Profile) -> Contact:
    # Contact.name is required, so an empty column falls back to the
    # profile's display name rather than raising ValidationError.
    if not p.contact_json or p.contact_json == "{}":
        return Contact(name=p.name)
    return Contact.model_validate_json(p.contact_json)


def set_contact(p: Profile, c: Contact) -> None:
    p.contact_json = c.model_dump_json()


def get_master_profile(p: Profile) -> MasterProfile:
    return MasterProfile.model_validate_json(p.master_profile_json or "{}")


def set_master_profile(p: Profile, mp: MasterProfile) -> None:
    p.master_profile_json = mp.model_dump_json()


def get_parsed(j: Job) -> ParsedPosting | None:
    if not j.parsed_json:
        return None
    return ParsedPosting.model_validate_json(j.parsed_json)


def set_parsed(j: Job, pp: ParsedPosting) -> None:
    j.parsed_json = pp.model_dump_json()


def get_findings(r: ResearchBrief) -> ResearchFindings:
    return ResearchFindings.model_validate_json(r.findings_json or "{}")


def get_resume(a: Application) -> ResumeDoc | None:
    if not a.resume_json:
        return None
    return ResumeDoc.model_validate_json(a.resume_json)


def set_resume(a: Application, r: ResumeDoc) -> None:
    a.resume_json = r.model_dump_json()
