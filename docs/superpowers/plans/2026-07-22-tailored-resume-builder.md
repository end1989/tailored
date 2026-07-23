# Tailored — Resume & Cover Letter Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Execution order:** run tasks in the order 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 9, 12, 13, 14, 15, 16, 17, 18 — Task 9 (pipeline) depends on Task 10 (render service) and Task 11 (templates) and must be executed after them.

**Goal:** A generic, shareable local web app that turns job-posting URLs into tailored, truthful resumes and cover letters (PDF + HTML + ATS text) using the Claude API, per the approved spec at `docs/superpowers/specs/2026-07-22-tailored-resume-builder-design.md`.

**Architecture:** FastAPI backend (SQLite via SQLModel) with a four-stage async pipeline — fetch → research (Quick/Standard/Deep dial) → tailor (structured outputs, truthfulness guard) → render (Jinja → HTML → Playwright PDF + ATS text). React/Vite frontend served as committed static build so end users only need Python. All Claude calls go through one `ClaudeService` wrapper with a fixture-backed fake mode powering tests and an offline demo mode.

**Tech Stack:** Python 3.11+, FastAPI, SQLModel/SQLite, Anthropic Python SDK (`claude-opus-4-8`, adaptive thinking, structured outputs, `web_search_20260209`/`web_fetch_20260209`), httpx + trafilatura, Jinja2, Playwright (Chromium PDF), pypdf, python-docx, markdown; React 18 + Vite + TypeScript + react-router-dom; pytest + respx.

## Global Constraints

- Project root: `.` — new git repo created in Task 1.
- Model: `claude-opus-4-8` everywhere; `thinking={"type": "adaptive"}`; never `temperature`/`top_p`/`top_k`; never assistant prefill; structured outputs via `output_config={"format": {"type": "json_schema", ...}}`.
- Cost constants (Opus 4.8): input $5.00/MTok, output $25.00/MTok — defined once in `backend/app/services/claude.py`.
- Templates: exactly four — `meridian`, `slate`, `terminal`, `signal`; `slate` is the default. All consume identical `ResumeDoc` JSON.
- Enums (verbatim, backend + frontend): depth `quick|standard|deep`; application status `queued|fetching|researching|tailoring|rendering|ready|needs_paste|error`; job fetch_status `pending|fetched|needs_paste|pasted`; page size `Letter|A4`.
- Truthfulness: the tailor stage may select, reorder, and rephrase only; `verify_truthfulness()` structurally rejects any employer/title/date/education/certification not present in the master profile.
- Tests never call the real API — `ClaudeService(fake_mode=True)` with fixtures under `backend/app/fixtures/`. Playwright-dependent tests carry `@pytest.mark.pdf`; fast suite is `pytest -m "not pdf"`.
- End-user setup must remain: clone → `pip install -r requirements.txt` → `playwright install chromium` → set `ANTHROPIC_API_KEY` in `.env` → `python run.py`. Node.js is a dev-only dependency (`frontend/dist/` is committed).
- Demo mode (`TAILORED_FAKE=1`) must work fully offline with no API key.
- Every task ends in a git commit; commit messages use `feat:|test:|chore:` prefixes and end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

---

# Tailored — Shared Interface Contract (AUTHORITATIVE)

Every plan section MUST use these exact paths, names, types, and signatures verbatim.
If your section needs something not defined here, define it fully inside your own task's
"Produces" block — never reference an undefined symbol from another group.

## Global constraints

- Project root: `.` (all paths below relative to it)
- Python 3.11+; FastAPI; SQLModel; Pydantic v2; Anthropic Python SDK (`anthropic`)
- Model ID: `claude-opus-4-8` — always. Thinking: `{"type": "adaptive"}`. Never pass temperature/top_p/top_k. Never use assistant prefill.
- Structured outputs via `output_config={"format": {"type": "json_schema", "schema": ...}}` on `client.messages.create` (schemas from `Model.model_json_schema()`; every object level needs `additionalProperties: false` — provide a helper `strict_schema()` that walks the schema dict and adds it).
- Server tools: `{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}` and `{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8}` (research stage only). Handle `stop_reason == "pause_turn"` by re-sending (append assistant content, retry, cap 5 continuations).
- Cost constants: `COST_INPUT_PER_MTOK = 5.00`, `COST_OUTPUT_PER_MTOK = 25.00` (Opus 4.8), defined once in `backend/app/services/claude.py`.
- Frontend: React 18 + Vite + TypeScript, `react-router-dom`. No UI framework; hand-written CSS design system in `frontend/src/styles.css`. Built `frontend/dist/` is committed.
- Windows dev machine; commands in plan steps use PowerShell-compatible syntax (`;` separators, forward slashes OK in git/pytest args). Python venv assumed active; plain `pytest`, `python`, `npm` commands.
- Git: repo initialized in Task 1. Every task ends with a commit. Commit messages: `feat:|test:|chore:` prefixes. Each commit message body ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Tests: pytest; test files under `tests/` mirroring service names (`tests/test_fetcher.py` etc.). HTTP mocking with `respx`. DB tests use a `tmp_path` SQLite file via the `db_session` fixture from `tests/conftest.py` (defined in Task 1).
- NEVER hit the real Anthropic API in tests — always `ClaudeService(fake_mode=True, fixtures_dir=...)`.

## Directory layout

```
tailored/
├── run.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── pyproject.toml            # [tool.pytest.ini_options] only
├── docs/superpowers/specs/…  # spec + plan moved here in Task 1
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models.py         # ALL SQLModel entities in this single module
│   │   ├── schemas.py        # ALL Pydantic schemas in this single module
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── claude.py
│   │   │   ├── intake.py
│   │   │   ├── fetcher.py
│   │   │   ├── research.py
│   │   │   ├── tailor.py
│   │   │   ├── render.py
│   │   │   └── pipeline.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── profiles.py
│   │   │   ├── applications.py
│   │   │   └── settings.py
│   │   └── fixtures/
│   │       ├── parse_posting.json
│   │       ├── research_standard.json
│   │       ├── research_deep.json
│   │       ├── tailor.json
│   │       ├── intake.json
│   │       └── demo/         # seed data for demo mode
│   └── templates/
│       ├── base.css
│       ├── meridian/  (template.html, style.css)
│       ├── slate/     (template.html, style.css)
│       ├── terminal/  (template.html, style.css)
│       ├── signal/    (template.html, style.css)
│       └── cover_letter.html
├── frontend/
│   ├── package.json, vite.config.ts, tsconfig.json, index.html
│   ├── src/
│   │   ├── main.tsx, App.tsx, styles.css
│   │   ├── api.ts            # typed fetch client
│   │   ├── types.ts          # TS mirrors of backend schemas
│   │   └── screens/
│   │       ├── ProfileScreen.tsx      # onboarding + master profile editor
│   │       ├── DashboardScreen.tsx
│   │       ├── AddJobsScreen.tsx
│   │       ├── ApplicationScreen.tsx
│   │       └── SettingsScreen.tsx
│   └── dist/                 # committed build
├── tests/
│   ├── conftest.py
│   └── test_*.py
└── data/                     # gitignored; sqlite db, exports/, settings.json
```

## Enums / literals (use everywhere, backend and frontend)

- Depth: `"quick" | "standard" | "deep"`
- Template: `"meridian" | "slate" | "terminal" | "signal"` — `TEMPLATES = ("meridian", "slate", "terminal", "signal")` in `render.py`
- Application status: `"queued" | "fetching" | "researching" | "tailoring" | "rendering" | "ready" | "needs_paste" | "error"`
- Job fetch_status: `"pending" | "fetched" | "needs_paste" | "pasted"`
- SourceDocument kind: `"pdf" | "docx" | "txt" | "paste"`
- Page size: `"Letter" | "A4"`
- Export kinds: `"resume.pdf" | "resume.html" | "resume.txt" | "cover_letter.pdf" | "cover_letter.txt"`

## `backend/app/schemas.py` — COMPLETE, copy verbatim in Task 2

```python
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


class LinkItem(BaseModel):
    label: str
    url: str


class Contact(BaseModel):
    name: str
    email: str = ""
    phone: Optional[str] = None
    location: Optional[str] = None
    links: list[LinkItem] = Field(default_factory=list)


# --- Master profile (source of truth about a person) ---

class TaggedBullet(BaseModel):
    text: str
    tags: list[str] = Field(default_factory=list)


class MPExperience(BaseModel):
    company: str
    title: str
    start: str  # "YYYY-MM" or "YYYY"
    end: Optional[str] = None  # None means present
    location: Optional[str] = None
    bullets: list[TaggedBullet] = Field(default_factory=list)


class MPProject(BaseModel):
    name: str
    description: str = ""
    url: Optional[str] = None
    bullets: list[TaggedBullet] = Field(default_factory=list)


class SkillGroup(BaseModel):
    label: str
    items: list[str] = Field(default_factory=list)


class MPEducation(BaseModel):
    institution: str
    credential: str
    year: Optional[str] = None
    detail: Optional[str] = None


class MPCertification(BaseModel):
    name: str
    issuer: Optional[str] = None
    year: Optional[str] = None


class MasterProfile(BaseModel):
    summary_notes: str = ""
    experiences: list[MPExperience] = Field(default_factory=list)
    projects: list[MPProject] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    education: list[MPEducation] = Field(default_factory=list)
    certifications: list[MPCertification] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)


# --- Posting analysis + research ---

class ParsedPosting(BaseModel):
    title: str
    company: str
    company_domain: Optional[str] = None
    must_haves: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    seniority: Optional[str] = None
    tone: Optional[str] = None


class ResearchFindings(BaseModel):
    mission: str = ""
    products: list[str] = Field(default_factory=list)
    news: list[str] = Field(default_factory=list)
    tech_stack_signals: list[str] = Field(default_factory=list)
    culture_language: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


# --- Resume document (renderer contract) ---

class ExperienceItem(BaseModel):
    company: str
    role: str
    start: str
    end: Optional[str] = None
    location: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str
    description: str = ""
    url: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    institution: str
    credential: str
    year: Optional[str] = None
    detail: Optional[str] = None


class CertificationItem(BaseModel):
    name: str
    issuer: Optional[str] = None
    year: Optional[str] = None


class ExperienceSection(BaseModel):
    type: Literal["experience"] = "experience"
    title: str = "Experience"
    items: list[ExperienceItem] = Field(default_factory=list)


class ProjectsSection(BaseModel):
    type: Literal["projects"] = "projects"
    title: str = "Projects"
    items: list[ProjectItem] = Field(default_factory=list)


class SkillsSection(BaseModel):
    type: Literal["skills"] = "skills"
    title: str = "Skills"
    groups: list[SkillGroup] = Field(default_factory=list)


class EducationSection(BaseModel):
    type: Literal["education"] = "education"
    title: str = "Education"
    items: list[EducationItem] = Field(default_factory=list)


class CertificationsSection(BaseModel):
    type: Literal["certifications"] = "certifications"
    title: str = "Certifications"
    items: list[CertificationItem] = Field(default_factory=list)


class ExtrasSection(BaseModel):
    type: Literal["extras"] = "extras"
    title: str = "Additional"
    items: list[str] = Field(default_factory=list)


ResumeSection = Union[
    ExperienceSection,
    ProjectsSection,
    SkillsSection,
    EducationSection,
    CertificationsSection,
    ExtrasSection,
]


class ResumeDoc(BaseModel):
    contact: Contact
    headline: str
    summary: str
    sections: list[ResumeSection] = Field(default_factory=list)


class TailorResult(BaseModel):
    resume: ResumeDoc
    cover_letter_md: str
    tailoring_notes: str = ""


class UsageInfo(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: "UsageInfo") -> "UsageInfo":
        return UsageInfo(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 6),
        )


class FetchResult(BaseModel):
    status: Literal["fetched", "needs_paste"]
    text: str = ""
    reason: str = ""
```

## `backend/app/models.py` — entity fields (Task 3 writes complete module)

All JSON payloads stored as TEXT columns holding serialized Pydantic JSON; each entity
gets typed helpers. `datetime.utcnow` via `default_factory`.

```python
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
```

Helper functions in `models.py` (exact names):
`get_contact(p: Profile) -> Contact`, `set_contact(p, c)`, `get_master_profile(p) -> MasterProfile`,
`set_master_profile(p, mp)`, `get_parsed(j: Job) -> ParsedPosting | None`, `set_parsed(j, pp)`,
`get_findings(r: ResearchBrief) -> ResearchFindings`, `get_resume(a: Application) -> ResumeDoc | None`,
`set_resume(a, r)`.

## `backend/app/config.py` (Task 1)

```python
class Settings:  # simple class, reads env once; get_settings() cached accessor
    anthropic_api_key: str | None   # env ANTHROPIC_API_KEY
    data_dir: Path                  # env TAILORED_DATA_DIR, default <project>/data
    fake_mode: bool                 # env TAILORED_FAKE == "1"  (demo mode + tests)
    host: str = "127.0.0.1"        # env TAILORED_HOST
    port: int = 8547                # env TAILORED_PORT
def get_settings() -> Settings
def load_user_settings(data_dir: Path) -> dict   # data/settings.json: {"default_template": "slate", "default_depth": "standard", "page_size": "Letter"}
def save_user_settings(data_dir: Path, values: dict) -> dict
```

## `backend/app/db.py` (Task 1)

```python
def get_engine(db_path: Path | None = None)  # creates parent dirs; sqlite file data/tailored.db
def init_db(engine) -> None                  # SQLModel.metadata.create_all
def session_scope(engine) -> Iterator[Session]  # contextmanager
```
FastAPI dependency `get_session` yields a Session bound to the app-level engine
(`app.state.engine`).

## `backend/app/services/claude.py` (Task 4)

```python
COST_INPUT_PER_MTOK = 5.00
COST_OUTPUT_PER_MTOK = 25.00

def strict_schema(model_cls: type[BaseModel]) -> dict:
    """model_json_schema() with additionalProperties: false injected at every object level."""

class ClaudeError(Exception): ...

class ClaudeService:
    def __init__(self, api_key: str | None = None, fake_mode: bool = False,
                 fixtures_dir: Path | None = None): ...
    def structured(self, *, task: str, system: str, user_content: str,
                   schema_model: type[BaseModel], tools: list[dict] | None = None,
                   max_tokens: int = 16000) -> tuple[BaseModel, UsageInfo]:
        """
        fake_mode: loads fixtures_dir/<task>.json, validates into schema_model,
        returns UsageInfo(0, 0, 0.0).
        real mode: client.messages.create(model="claude-opus-4-8",
            thinking={"type": "adaptive"}, output_config={"format": {"type": "json_schema",
            "schema": strict_schema(schema_model)}}, tools=tools or omitted, stream via
            client.messages.stream + get_final_message() when max_tokens > 16000).
        Loops on stop_reason == "pause_turn" (max 5). Accumulates usage across iterations.
        Raises ClaudeError on refusal or unparseable output (message includes raw text).
        """

def make_claude(settings) -> ClaudeService  # honors settings.fake_mode; fixtures_dir = backend/app/fixtures
```

Fixture task names (files under `backend/app/fixtures/`): `intake`, `parse_posting`,
`research_standard`, `research_deep`, `tailor`.

## Services (Tasks 5–9)

```python
# intake.py (Task 5)
def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """returns (kind, text); kind by extension: .pdf via pypdf, .docx via python-docx, else utf-8 txt"""
def build_master_profile(docs: list[str], claude: ClaudeService) -> tuple[MasterProfile, Contact, UsageInfo]:
    """One structured() call, task='intake', schema_model=IntakeResult (defined in intake.py:
       class IntakeResult(BaseModel): contact: Contact; master_profile: MasterProfile)"""

# fetcher.py (Task 6)
def fetch_posting(url: str, timeout: float = 20.0) -> FetchResult
    # httpx GET, browser UA header; trafilatura.extract on 200 with text/html;
    # any exception / non-200 / empty extraction -> FetchResult(status="needs_paste", reason=...)

# research.py (Task 7)
def parse_posting(raw_text: str, claude: ClaudeService) -> tuple[ParsedPosting, UsageInfo]
def research_company(parsed: ParsedPosting, depth: str, claude: ClaudeService
                     ) -> tuple[ResearchFindings, UsageInfo] | None
    # quick -> None; standard -> web_fetch tool only, allowed_domains=[parsed.company_domain] when set;
    # deep -> web_search + web_fetch tools. task names: research_standard / research_deep

# tailor.py (Task 8)
def tailor_application(profile: MasterProfile, contact: Contact, parsed: ParsedPosting,
                       research: ResearchFindings | None, template: str,
                       claude: ClaudeService, feedback: str | None = None
                       ) -> tuple[TailorResult, UsageInfo]
def verify_truthfulness(resume: ResumeDoc, profile: MasterProfile) -> list[str]
    # structural guard: every ExperienceItem (company, role, start, end) must match an MPExperience
    # (company+title exact, start/end exact); every EducationItem/CertificationItem must exist in
    # the master profile. Returns list of violation strings; empty = pass.

# pipeline.py (Task 9)
def process_application(app_id: int, engine=None) -> None
    # sync; runs stages queued->fetching->researching->tailoring->rendering->ready
    # writes/commits status between stages; on needs_paste sets both Job.fetch_status and
    # Application.status; on exception sets status="error", error_message=str(exc)
    # accumulates UsageInfo onto Application (input/output/cost) and snapshots
    # ApplicationVersion after successful tailor; calls export_application at render stage
def resume_after_paste(app_id: int, text: str, engine=None) -> None
    # sets Job.raw_text, fetch_status="pasted", then continues pipeline from researching
def regenerate_application(app_id: int, feedback: str, engine=None) -> None
    # re-runs tailor (version += 1, new ApplicationVersion snapshot) + render
```

## `backend/app/services/render.py` (Task 10) + templates (Task 11)

```python
TEMPLATES = ("meridian", "slate", "terminal", "signal")
TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"  # backend/templates

def render_resume_html(resume: ResumeDoc, template: str) -> str
    # Jinja2 Environment(FileSystemLoader(TEMPLATES_DIR), autoescape=True);
    # renders "<template>/template.html" with {"resume": resume, "base_css": ..., "style_css": ...}
    # CSS inlined into <style> so HTML is standalone
def render_cover_letter_html(cover_md: str, contact: Contact, template: str) -> str
    # markdown -> HTML body via `markdown` lib, wrapped in cover_letter.html with same CSS
def render_ats_text(resume: ResumeDoc) -> str
    # deterministic plain text: NAME / contact line / HEADLINE / summary / sections with
    # ALL-CAPS headings underlined by '=' and items with '- ' bullets; no tabs; wrapped at nothing
def render_pdf(html: str, out_path: Path, page_size: str = "Letter") -> None
    # playwright sync API: chromium headless, set_content(html), page.pdf(path=..., format=page_size,
    # print_background=True, margin 0.5in all sides)
def export_application(application_id: int, resume: ResumeDoc, cover_md: str,
                       contact: Contact, template: str, data_dir: Path,
                       page_size: str = "Letter") -> Path
    # writes data_dir/exports/<application_id>/{resume.pdf,resume.html,resume.txt,
    # cover_letter.pdf,cover_letter.txt}; returns the export dir
```

Template HTML contract: each `template.html` iterates `resume.sections` and dispatches on
`section.type` (the six literals). Templates must render *any* section order. Jinja receives
the Pydantic object itself (attribute access).

## API routes (Tasks 12) — all JSON, prefix `/api`

| Method+Path | Request | Response |
|---|---|---|
| GET /api/health | — | `{"status": "ok"}` |
| GET /api/profiles | — | `[{id, name, contact, has_master_profile}]` |
| POST /api/profiles | `{name, contact?}` | profile detail |
| GET /api/profiles/{id} | — | `{id, name, contact, master_profile, documents: [{id, filename, kind}]}` |
| PUT /api/profiles/{id} | `{name?, contact?, master_profile?}` | profile detail |
| POST /api/profiles/{id}/documents | multipart file OR `{filename, text}` | `{id, filename, kind}` |
| POST /api/profiles/{id}/build | — | profile detail (runs intake over all documents; adds usage fields `{usage: {input_tokens, output_tokens, cost_usd}}`) |
| POST /api/applications/batch | `{profile_id, jobs: [{url, depth?, template?}], default_depth?, default_template?}` | `[application detail]` (creates Job+Application per URL, schedules pipeline via BackgroundTasks) |
| GET /api/applications?profile_id= | — | `[application summary]` = `{id, profile_id, status, version, template, depth, url, company, title, cost_usd, created_at, error_message}` |
| GET /api/applications/{id} | — | full detail: summary + `{resume, cover_letter_md, tailoring_notes, research, parsed, raw_text_present}` |
| POST /api/applications/{id}/paste | `{text}` | detail (schedules resume_after_paste) |
| PUT /api/applications/{id}/content | `{resume?, cover_letter_md?}` | detail (validates ResumeDoc, re-exports files; no API call) |
| POST /api/applications/{id}/regenerate | `{feedback}` | detail (schedules regenerate_application) |
| GET /api/applications/{id}/preview | — | `text/html` of current resume in its template |
| GET /api/applications/{id}/exports/{kind} | — | FileResponse; kind ∈ export kinds enum |
| GET /api/settings | — | `{api_key_set, fake_mode, default_template, default_depth, page_size}` |
| PUT /api/settings | `{default_template?, default_depth?, page_size?}` | same shape |

`main.py`: `create_app() -> FastAPI` mounts routers, creates engine (`app.state.engine`),
`init_db`, serves `frontend/dist` as static at `/` (SPA fallback to index.html), CORS
allow localhost. `run.py`: loads `.env` (python-dotenv), uvicorn on settings.host/port,
opens browser via `webbrowser.open` after 1s timer thread.

## Frontend contract (Tasks 14–17)

- `frontend/src/types.ts` mirrors: Contact, MasterProfile (+nested), ParsedPosting,
  ResearchFindings, ResumeDoc (+sections union with `type` discriminant), ApplicationSummary,
  ApplicationDetail, ProfileDetail, SettingsShape — field names identical to backend JSON.
- `frontend/src/api.ts`: `const API = "/api"`; typed functions matching the route table:
  `listProfiles`, `createProfile`, `getProfile`, `updateProfile`, `uploadDocument`,
  `buildProfile`, `createApplications`, `listApplications`, `getApplication`,
  `pasteJobText`, `updateContent`, `regenerate`, `getSettings`, `updateSettings`.
  Export/preview are plain `<a href>` / `<iframe src>` URLs: `/api/applications/{id}/preview`,
  `/api/applications/{id}/exports/{kind}`.
- Routes (react-router): `/` Dashboard, `/profiles` ProfileScreen, `/add` AddJobsScreen,
  `/applications/:id` ApplicationScreen, `/settings` SettingsScreen.
- Dashboard polls `listApplications` every 2000ms while any application status is not in
  `["ready", "error", "needs_paste"]`.
- Vite `server.proxy` forwards `/api` to `http://127.0.0.1:8547` for dev.

## Demo mode (Task 13)

`TAILORED_FAKE=1` → `make_claude` returns fake-mode service; on startup, if DB has no
profiles, seed from `backend/app/fixtures/demo/`: `profile.json` (Contact + MasterProfile)
and one ready application built by running the fake pipeline against
`demo/job_posting.txt`. Demo works fully offline, no API key.

## Fixture content requirements

Fixtures are realistic, not lorem ipsum: a plausible software-engineer master profile
(2 jobs, 4 bullets each with tags, 1 project, 2 skill groups, 1 education), a plausible
job posting parse, research findings, and a full TailorResult whose resume passes
`verify_truthfulness` against the fixture master profile. The `tailor.json` fixture's
resume MUST use only companies/titles/dates present in `intake.json`'s master profile.

## Plan section format (how to write your tasks)

Follow superpowers:writing-plans exactly: `### Task N: Name`, **Files** (Create/Modify/Test
exact paths), **Interfaces** (Consumes/Produces), then checkbox steps: write failing test
(with complete test code) → run test, expect FAIL (exact command + expected error) → write
implementation (complete code) → run test, expect PASS → commit (exact git command).
Multiple test-implement cycles per task are fine. No placeholders, no "TBD", no "similar to
Task N" — repeat code. Code blocks must be complete and runnable. Playwright-dependent
tests get `@pytest.mark.pdf` and the plan notes `pytest -m "not pdf"` for fast runs
(marker registered in pyproject.toml in Task 1).

---

# Foundation (Tasks 1–3)

All commands below run in PowerShell with the Python venv active. Because executors reset
the working directory between shell calls, every command block after the initial scaffold
explicitly prefixes `cd .;` — do not strip it.

### Task 1: Project scaffold & repo

**Files**

- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `README.md`
- Create: `run.py`
- Create: `backend\app\__init__.py`
- Create: `backend\app\config.py`
- Create: `backend\app\db.py`
- Create: `backend\app\main.py`
- Create: `docs\superpowers\specs\2026-07-22-tailored-resume-builder-design.md` (copied)
- Create: `docs\superpowers\plans\2026-07-22-tailored-resume-builder.md` (copied)
- Test: `tests\conftest.py`
- Test: `tests\test_config.py`
- Test: `tests\test_db.py`
- Test: `tests\test_health.py`

**Interfaces**

- Consumes: nothing (first task; creates the repo).
- Produces:
  - `backend.app.config`: `PROJECT_ROOT: Path`, `DEFAULT_USER_SETTINGS: dict`, `class Settings` (attrs `anthropic_api_key: str | None`, `data_dir: Path`, `fake_mode: bool`, `host: str`, `port: int`; constructor accepts keyword overrides `Settings(anthropic_api_key=..., data_dir=..., fake_mode=..., host=..., port=...)`, otherwise reads env `ANTHROPIC_API_KEY` / `TAILORED_DATA_DIR` / `TAILORED_FAKE` / `TAILORED_HOST` / `TAILORED_PORT`), `get_settings() -> Settings` (lru_cached), `load_user_settings(data_dir: Path) -> dict`, `save_user_settings(data_dir: Path, values: dict) -> dict` (defaults `{"default_template": "slate", "default_depth": "standard", "page_size": "Letter"}`, persisted to `<data_dir>/settings.json`, unknown keys ignored).
  - `backend.app.db`: `get_engine(db_path: Path | None = None)` (creates parent dirs; default `get_settings().data_dir / "tailored.db"`), `init_db(engine) -> None` (guarded `from . import models` so entities register once Task 3 lands, then `SQLModel.metadata.create_all`), `session_scope(engine) -> Iterator[Session]` (contextmanager, commit/rollback), `get_session(request: Request)` (FastAPI dependency yielding a `Session` bound to `request.app.state.engine`; exercised by API routes in Task 12).
  - `backend.app.main`: `create_app(settings: Settings | None = None, engine=None) -> FastAPI` — sets `app.state.settings`, `app.state.engine`, calls `init_db`, exposes `GET /api/health` returning `{"status": "ok"}`. Later tasks (12/13) extend this factory with routers, CORS, static frontend, and demo seeding.
  - `run.py`: `python run.py` entry point (dotenv → uvicorn → browser open on a 1s `threading.Timer`).
  - `tests/conftest.py` fixtures used by ALL later sections: `engine` (tmp_path SQLite file + `init_db`), `session` (`sqlmodel.Session` on that engine), `db_session` (alias of `session` — the contract refers to it by this name), `fake_settings` (`Settings` with `data_dir=tmp_path`, `fake_mode=True`, `anthropic_api_key=None`), `app` (`create_app(settings=fake_settings, engine=engine)`), `client` (`fastapi.testclient.TestClient` over `app`). Also inserts the project root into `sys.path` so `backend.app.*` imports resolve under pytest.
  - **Conftest ownership note:** Task 1 owns `tests/conftest.py`. Task 4 APPENDS a `claude_fake` fixture (fake-mode `ClaudeService`) to this same file; no other task modifies conftest.
  - pytest marker `pdf` registered in `pyproject.toml`; fast suite is `pytest -m "not pdf"`.

- [ ] **Step 1: Create the repo, scaffold files, and copy the docs (no tests for static metadata files)**

  Run:

  ```powershell
  New-Item -ItemType Directory -Force -Path . | Out-Null
  Set-Location .
  git init -b main
  New-Item -ItemType Directory -Force -Path backend\app, tests, docs\superpowers\specs, docs\superpowers\plans | Out-Null
  New-Item -ItemType File -Force -Path backend\app\__init__.py | Out-Null
  ```

  Create `.gitignore`:

  ```gitignore
  # runtime state (sqlite db, exports, settings.json)
  data/

  # python
  __pycache__/
  *.pyc
  .venv/
  .pytest_cache/

  # secrets
  .env

  # node (frontend/dist IS committed on purpose -- do not ignore it)
  frontend/node_modules/
  ```

  Create `requirements.txt`:

  ```text
  fastapi
  uvicorn[standard]
  sqlmodel
  pydantic>=2
  anthropic
  httpx
  trafilatura
  jinja2
  markdown
  playwright
  pypdf
  python-docx
  python-multipart
  python-dotenv
  pytest
  respx
  ```

  Create `pyproject.toml` (this file contains ONLY the pytest configuration — no build system, no project metadata):

  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  markers = ["pdf: requires playwright chromium"]
  ```

  Create `.env.example`:

  ```text
  ANTHROPIC_API_KEY=
  TAILORED_FAKE=0
  TAILORED_DATA_DIR=
  TAILORED_HOST=
  TAILORED_PORT=
  ```

  Create `README.md`:

  ```markdown
  # Tailored

  Turn job-posting URLs into tailored, truthful resumes and cover letters
  (PDF + HTML + ATS text) using the Claude API. Runs entirely on your machine.

  ## Setup

  1. `pip install -r requirements.txt`
  2. `playwright install chromium` (needed for PDF export)
  3. Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`
  4. `python run.py` — starts the server and opens your browser

  ## Demo mode

  Set `TAILORED_FAKE=1` in `.env` to explore the app fully offline with canned
  fixtures — no API key required.

  ## Development

  - Fast tests: `pytest -m "not pdf"`
  - Full tests (includes Playwright PDF rendering): `pytest`
  - Frontend dev: `cd frontend`, `npm install`, `npm run dev` (the built
    `frontend/dist/` is committed so end users only need Python)

  Design spec: `docs/superpowers/specs/2026-07-22-tailored-resume-builder-design.md`
  Implementation plan: `docs/superpowers/plans/2026-07-22-tailored-resume-builder.md`
  ```

  Copy the approved spec and the assembled plan into the repo:

  ```powershell
  # docs\superpowers\specs\2026-07-22-tailored-resume-builder-design.md
  # docs\superpowers\plans\2026-07-22-tailored-resume-builder.md
  ```

  Install dependencies (venv is already active). `playwright install chromium` can be deferred until Task 10 (the first `@pytest.mark.pdf` test) if you want to skip the browser download now:

  ```powershell
  cd .; pip install -r requirements.txt
  ```

  Commit:

  ```powershell
  cd .; git add -A; git commit -m "chore: scaffold tailored repo (gitignore, deps, pytest config, docs)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

- [ ] **Step 2: Write failing tests for config**

  Create `tests\conftest.py` (minimal for now — the full fixture set is added in Step 12 of this task once `main.py` exists; the `sys.path` shim is required because `pyproject.toml` deliberately contains only `testpaths`/`markers`):

  ```python
  from __future__ import annotations

  import sys
  from pathlib import Path

  PROJECT_ROOT = Path(__file__).resolve().parents[1]
  if str(PROJECT_ROOT) not in sys.path:
      sys.path.insert(0, str(PROJECT_ROOT))
  ```

  Create `tests\test_config.py`:

  ```python
  from __future__ import annotations

  from backend.app.config import (
      DEFAULT_USER_SETTINGS,
      PROJECT_ROOT,
      Settings,
      load_user_settings,
      save_user_settings,
  )

  ENV_VARS = [
      "ANTHROPIC_API_KEY",
      "TAILORED_DATA_DIR",
      "TAILORED_FAKE",
      "TAILORED_HOST",
      "TAILORED_PORT",
  ]


  def test_settings_reads_env(monkeypatch, tmp_path):
      monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
      monkeypatch.setenv("TAILORED_DATA_DIR", str(tmp_path / "custom"))
      monkeypatch.setenv("TAILORED_FAKE", "1")
      monkeypatch.setenv("TAILORED_HOST", "0.0.0.0")
      monkeypatch.setenv("TAILORED_PORT", "9000")
      s = Settings()
      assert s.anthropic_api_key == "sk-test-123"
      assert s.data_dir == tmp_path / "custom"
      assert s.fake_mode is True
      assert s.host == "0.0.0.0"
      assert s.port == 9000


  def test_settings_defaults(monkeypatch):
      for var in ENV_VARS:
          monkeypatch.delenv(var, raising=False)
      s = Settings()
      assert s.anthropic_api_key is None
      assert s.data_dir == PROJECT_ROOT / "data"
      assert s.fake_mode is False
      assert s.host == "127.0.0.1"
      assert s.port == 8547


  def test_settings_kwargs_override_env(monkeypatch, tmp_path):
      monkeypatch.setenv("TAILORED_FAKE", "0")
      monkeypatch.setenv("TAILORED_PORT", "9000")
      s = Settings(data_dir=tmp_path, fake_mode=True, port=1234)
      assert s.data_dir == tmp_path
      assert s.fake_mode is True
      assert s.port == 1234


  def test_settings_explicit_none_api_key_beats_env(monkeypatch):
      monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-ignored")
      s = Settings(anthropic_api_key=None)
      assert s.anthropic_api_key is None


  def test_user_settings_defaults_when_missing(tmp_path):
      values = load_user_settings(tmp_path)
      assert values == {
          "default_template": "slate",
          "default_depth": "standard",
          "page_size": "Letter",
      }
      assert values == DEFAULT_USER_SETTINGS
      assert values is not DEFAULT_USER_SETTINGS  # must be a copy


  def test_user_settings_round_trip(tmp_path):
      saved = save_user_settings(tmp_path, {"default_template": "terminal", "page_size": "A4"})
      assert saved["default_template"] == "terminal"
      assert saved["page_size"] == "A4"
      assert saved["default_depth"] == "standard"
      assert (tmp_path / "settings.json").exists()
      loaded = load_user_settings(tmp_path)
      assert loaded == saved


  def test_save_ignores_unknown_keys(tmp_path):
      saved = save_user_settings(tmp_path, {"default_depth": "deep", "bogus": 1})
      assert "bogus" not in saved
      assert saved["default_depth"] == "deep"
  ```

- [ ] **Step 3: Run config tests — expect FAIL**

  ```powershell
  cd .; pytest tests/test_config.py -v
  ```

  Expected failure (collection error):

  ```text
  ERROR tests/test_config.py - ModuleNotFoundError: No module named 'backend.app.config'
  ```

- [ ] **Step 4: Implement config**

  Create `backend\app\config.py` (complete file):

  ```python
  from __future__ import annotations

  import json
  import os
  from functools import lru_cache
  from pathlib import Path

  # backend/app/config.py -> parents[2] == project root (tailored/)
  PROJECT_ROOT = Path(__file__).resolve().parents[2]

  DEFAULT_USER_SETTINGS = {
      "default_template": "slate",
      "default_depth": "standard",
      "page_size": "Letter",
  }

  _UNSET = object()


  class Settings:
      """Simple settings object. Reads env once at construction; keyword
      arguments override the environment (used by tests / fixtures)."""

      def __init__(
          self,
          anthropic_api_key: object = _UNSET,
          data_dir: Path | str | None = None,
          fake_mode: bool | None = None,
          host: str | None = None,
          port: int | None = None,
      ) -> None:
          if anthropic_api_key is _UNSET:
              self.anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY") or None
          else:
              self.anthropic_api_key = anthropic_api_key  # type: ignore[assignment]

          if data_dir is not None:
              self.data_dir = Path(data_dir)
          else:
              env_data_dir = os.environ.get("TAILORED_DATA_DIR", "")
              self.data_dir = Path(env_data_dir) if env_data_dir else PROJECT_ROOT / "data"

          if fake_mode is not None:
              self.fake_mode = fake_mode
          else:
              self.fake_mode = os.environ.get("TAILORED_FAKE") == "1"

          self.host = host if host is not None else os.environ.get("TAILORED_HOST", "127.0.0.1")

          if port is not None:
              self.port = port
          else:
              env_port = os.environ.get("TAILORED_PORT", "")
              self.port = int(env_port) if env_port else 8547


  @lru_cache(maxsize=1)
  def get_settings() -> Settings:
      return Settings()


  def load_user_settings(data_dir: Path) -> dict:
      """Read <data_dir>/settings.json merged over defaults. Unknown or
      malformed content falls back to defaults. Always returns a fresh dict."""
      path = Path(data_dir) / "settings.json"
      values = dict(DEFAULT_USER_SETTINGS)
      if path.exists():
          try:
              stored = json.loads(path.read_text(encoding="utf-8"))
          except (json.JSONDecodeError, OSError):
              stored = {}
          if isinstance(stored, dict):
              values.update({k: v for k, v in stored.items() if k in DEFAULT_USER_SETTINGS})
      return values


  def save_user_settings(data_dir: Path, values: dict) -> dict:
      """Merge known keys from `values` into the persisted settings and return
      the resulting full settings dict."""
      path = Path(data_dir) / "settings.json"
      path.parent.mkdir(parents=True, exist_ok=True)
      current = load_user_settings(data_dir)
      current.update({k: v for k, v in values.items() if k in DEFAULT_USER_SETTINGS})
      path.write_text(json.dumps(current, indent=2), encoding="utf-8")
      return current
  ```

- [ ] **Step 5: Run config tests — expect PASS**

  ```powershell
  cd .; pytest tests/test_config.py -v
  ```

  Expected: `7 passed`.

- [ ] **Step 6: Commit config**

  ```powershell
  cd .; git add -A; git commit -m "feat: env-driven Settings and persisted user settings (config.py)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

- [ ] **Step 7: Write failing tests for the database layer**

  Create `tests\test_db.py`. Note: `models.py` does not exist until Task 3, so this test
  registers its own throwaway SQLModel table (`ScaffoldProbe`) to prove `init_db` creates
  everything registered on `SQLModel.metadata`. `init_db` also attempts a guarded import of
  `backend.app.models` so the real entities auto-register from Task 3 onward.

  ```python
  from __future__ import annotations

  from typing import Optional

  import pytest
  from fastapi import Depends, FastAPI
  from fastapi.testclient import TestClient
  from sqlalchemy import inspect
  from sqlmodel import Field, Session, SQLModel, select

  from backend.app.db import get_engine, get_session, init_db, session_scope


  class ScaffoldProbe(SQLModel, table=True):
      id: Optional[int] = Field(default=None, primary_key=True)
      label: str = ""


  def test_init_db_creates_tables_and_parent_dirs(tmp_path):
      engine = get_engine(tmp_path / "nested" / "dir" / "probe.db")
      init_db(engine)
      tables = inspect(engine).get_table_names()
      assert len(tables) > 0
      assert "scaffoldprobe" in tables
      assert (tmp_path / "nested" / "dir" / "probe.db").exists()


  def test_session_scope_commits(tmp_path):
      engine = get_engine(tmp_path / "probe.db")
      init_db(engine)
      with session_scope(engine) as s:
          s.add(ScaffoldProbe(label="hello"))
      with Session(engine) as s:
          rows = s.exec(select(ScaffoldProbe)).all()
      assert len(rows) == 1
      assert rows[0].label == "hello"


  def test_session_scope_rolls_back_on_error(tmp_path):
      engine = get_engine(tmp_path / "probe.db")
      init_db(engine)
      with pytest.raises(RuntimeError):
          with session_scope(engine) as s:
              s.add(ScaffoldProbe(label="doomed"))
              raise RuntimeError("boom")
      with Session(engine) as s:
          rows = s.exec(select(ScaffoldProbe)).all()
      assert rows == []


  def test_get_session_dependency_uses_app_state_engine(tmp_path):
      engine = get_engine(tmp_path / "dep.db")
      init_db(engine)
      probe_app = FastAPI()
      probe_app.state.engine = engine

      @probe_app.get("/probe-count")
      def probe_count(session: Session = Depends(get_session)) -> dict:
          count = len(session.exec(select(ScaffoldProbe)).all())
          return {"count": count}

      client = TestClient(probe_app)
      resp = client.get("/probe-count")
      assert resp.status_code == 200
      assert resp.json() == {"count": 0}
  ```

- [ ] **Step 8: Run db tests — expect FAIL**

  ```powershell
  cd .; pytest tests/test_db.py -v
  ```

  Expected failure (collection error):

  ```text
  ERROR tests/test_db.py - ModuleNotFoundError: No module named 'backend.app.db'
  ```

- [ ] **Step 9: Implement the database layer**

  Create `backend\app\db.py` (complete file):

  ```python
  from __future__ import annotations

  from contextlib import contextmanager
  from pathlib import Path
  from typing import Iterator

  from fastapi import Request
  from sqlmodel import Session, SQLModel, create_engine

  from .config import get_settings


  def get_engine(db_path: Path | None = None):
      """SQLite engine for the given file (default data/tailored.db).
      Creates parent directories as needed."""
      if db_path is None:
          db_path = get_settings().data_dir / "tailored.db"
      db_path = Path(db_path)
      db_path.parent.mkdir(parents=True, exist_ok=True)
      return create_engine(
          f"sqlite:///{db_path}",
          connect_args={"check_same_thread": False},
      )


  def init_db(engine) -> None:
      """Create all tables registered on SQLModel.metadata. Imports the models
      module (when it exists) so entity tables register before create_all."""
      try:
          from . import models  # noqa: F401  (registers SQLModel table classes)
      except ImportError:
          # Task 1/2: models.py not written yet; tables come from whatever is
          # already registered on the shared metadata.
          pass
      SQLModel.metadata.create_all(engine)


  @contextmanager
  def session_scope(engine) -> Iterator[Session]:
      """Commit on success, rollback on exception, always close."""
      session = Session(engine)
      try:
          yield session
          session.commit()
      except Exception:
          session.rollback()
          raise
      finally:
          session.close()


  def get_session(request: Request) -> Iterator[Session]:
      """FastAPI dependency: yields a Session bound to the app-level engine
      (request.app.state.engine)."""
      with session_scope(request.app.state.engine) as session:
          yield session
  ```

- [ ] **Step 10: Run db tests — expect PASS**

  ```powershell
  cd .; pytest tests/test_db.py -v
  ```

  Expected: `4 passed`.

- [ ] **Step 11: Commit db layer**

  ```powershell
  cd .; git add -A; git commit -m "feat: sqlite engine, init_db, session_scope, get_session dependency (db.py)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

- [ ] **Step 12: Write failing health test + full conftest fixture set**

  Create `tests\test_health.py`:

  ```python
  from __future__ import annotations


  def test_health_returns_ok(client):
      resp = client.get("/api/health")
      assert resp.status_code == 200
      assert resp.json() == {"status": "ok"}
  ```

  REPLACE `tests\conftest.py` with the full version (complete file — this is the
  canonical fixture set every later section relies on; Task 4 appends a `claude_fake`
  fixture to the end of this file and nothing else touches it):

  ```python
  from __future__ import annotations

  import sys
  from pathlib import Path

  PROJECT_ROOT = Path(__file__).resolve().parents[1]
  if str(PROJECT_ROOT) not in sys.path:
      sys.path.insert(0, str(PROJECT_ROOT))

  import pytest
  from fastapi.testclient import TestClient
  from sqlmodel import Session

  from backend.app.config import Settings
  from backend.app.db import get_engine, init_db
  from backend.app.main import create_app


  @pytest.fixture()
  def engine(tmp_path):
      """Fresh tmp SQLite file with all registered tables created."""
      eng = get_engine(tmp_path / "test.db")
      init_db(eng)
      return eng


  @pytest.fixture()
  def session(engine):
      with Session(engine) as s:
          yield s


  @pytest.fixture()
  def db_session(session):
      """Contract alias for the `session` fixture."""
      return session


  @pytest.fixture()
  def fake_settings(tmp_path):
      """Settings isolated from the environment: tmp data_dir, fake mode on."""
      return Settings(
          anthropic_api_key=None,
          data_dir=tmp_path,
          fake_mode=True,
          host="127.0.0.1",
          port=8547,
      )


  @pytest.fixture()
  def app(engine, fake_settings):
      return create_app(settings=fake_settings, engine=engine)


  @pytest.fixture()
  def client(app):
      return TestClient(app)
  ```

- [ ] **Step 13: Run the whole suite — expect FAIL**

  ```powershell
  cd .; pytest -v
  ```

  Expected failure (conftest cannot import the app factory, so collection errors out):

  ```text
  ImportError while loading conftest '...\tests\conftest.py'.
  ...
  E   ModuleNotFoundError: No module named 'backend.app.main'
  ```

- [ ] **Step 14: Implement the minimal app factory**

  Create `backend\app\main.py` (complete file — Tasks 12/13 later extend this factory
  with routers, CORS, static frontend serving, and demo seeding):

  ```python
  from __future__ import annotations

  from fastapi import FastAPI

  from .config import Settings, get_settings
  from .db import get_engine, init_db


  def create_app(settings: Settings | None = None, engine=None) -> FastAPI:
      """App factory. `settings`/`engine` are injectable for tests; defaults
      come from the environment (get_settings) and data_dir/tailored.db."""
      settings = settings if settings is not None else get_settings()
      app = FastAPI(title="Tailored")
      app.state.settings = settings
      app.state.engine = (
          engine if engine is not None else get_engine(settings.data_dir / "tailored.db")
      )
      init_db(app.state.engine)

      @app.get("/api/health")
      def health() -> dict:
          return {"status": "ok"}

      return app
  ```

- [ ] **Step 15: Run the whole suite — expect PASS**

  ```powershell
  cd .; pytest -v
  ```

  Expected: `12 passed` (7 config + 4 db + 1 health).

- [ ] **Step 16: Write the launcher and smoke-check it imports**

  Create `run.py` (complete file):

  ```python
  from __future__ import annotations

  import threading
  import webbrowser

  import uvicorn
  from dotenv import load_dotenv

  load_dotenv()

  from backend.app.config import get_settings  # noqa: E402
  from backend.app.main import create_app  # noqa: E402


  def main() -> None:
      settings = get_settings()
      app = create_app(settings=settings)
      url = f"http://{settings.host}:{settings.port}"
      threading.Timer(1.0, webbrowser.open, args=(url,)).start()
      uvicorn.run(app, host=settings.host, port=settings.port)


  if __name__ == "__main__":
      main()
  ```

  Smoke-check (must exit 0 with no traceback; it must NOT start the server, since
  `main()` only runs under `__main__`):

  ```powershell
  cd .; python -c "import run"
  ```

- [ ] **Step 17: Commit app factory, fixtures, and launcher**

  ```powershell
  cd .; git add -A; git commit -m "feat: app factory with /api/health, shared pytest fixtures, run.py launcher" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

### Task 2: Schemas

**Files**

- Create: `backend\app\schemas.py`
- Test: `tests\test_schemas.py`

**Interfaces**

- Consumes: `tests/conftest.py` path shim from Task 1 (no fixtures needed — pure Pydantic tests).
- Produces: `backend.app.schemas` — the contract's COMPLETE schema module, verbatim: `LinkItem`, `Contact`, `TaggedBullet`, `MPExperience`, `MPProject`, `SkillGroup`, `MPEducation`, `MPCertification`, `MasterProfile`, `ParsedPosting`, `ResearchFindings`, `ExperienceItem`, `ProjectItem`, `EducationItem`, `CertificationItem`, `ExperienceSection`, `ProjectsSection`, `SkillsSection`, `EducationSection`, `CertificationsSection`, `ExtrasSection`, `ResumeSection` (union), `ResumeDoc`, `TailorResult`, `UsageInfo` (with `__add__`), `FetchResult`. Every later section imports from this module.

- [ ] **Step 1: Write failing schema tests**

  Create `tests\test_schemas.py`:

  ```python
  from __future__ import annotations

  import json

  import pytest
  from pydantic import ValidationError

  from backend.app.schemas import (
      CertificationItem,
      CertificationsSection,
      Contact,
      EducationItem,
      EducationSection,
      ExperienceItem,
      ExperienceSection,
      ExtrasSection,
      FetchResult,
      LinkItem,
      MasterProfile,
      MPCertification,
      MPEducation,
      MPExperience,
      MPProject,
      ProjectItem,
      ProjectsSection,
      ResumeDoc,
      SkillGroup,
      SkillsSection,
      TaggedBullet,
      UsageInfo,
  )


  def _sample_resume() -> ResumeDoc:
      # Deliberately scrambled section order: templates must handle any order,
      # and round-tripping must preserve it exactly.
      return ResumeDoc(
          contact=Contact(
              name="Ada Example",
              email="ada@example.com",
              phone="555-0100",
              location="Boise, ID",
              links=[LinkItem(label="GitHub", url="https://github.com/ada")],
          ),
          headline="Senior Software Engineer",
          summary="Backend engineer who ships reliable systems.",
          sections=[
              SkillsSection(
                  groups=[SkillGroup(label="Languages", items=["Python", "TypeScript"])]
              ),
              ExperienceSection(
                  items=[
                      ExperienceItem(
                          company="Acme Corp",
                          role="Software Engineer",
                          start="2021-03",
                          end=None,
                          location="Remote",
                          bullets=["Built the ingestion API."],
                      )
                  ]
              ),
              ProjectsSection(
                  items=[
                      ProjectItem(
                          name="Tailored",
                          description="Resume builder",
                          url="https://example.com/tailored",
                          bullets=["Wrote the renderer."],
                      )
                  ]
              ),
              EducationSection(
                  items=[
                      EducationItem(
                          institution="State University",
                          credential="B.S. Computer Science",
                          year="2015",
                      )
                  ]
              ),
              CertificationsSection(
                  items=[CertificationItem(name="AWS SAA", issuer="AWS", year="2022")]
              ),
              ExtrasSection(items=["Open-source maintainer"]),
          ],
      )


  def test_resume_doc_json_round_trip_preserves_order_and_discriminates_types():
      doc = _sample_resume()
      data = json.loads(doc.model_dump_json())
      restored = ResumeDoc.model_validate(data)
      assert restored == doc
      assert [s.type for s in restored.sections] == [
          "skills",
          "experience",
          "projects",
          "education",
          "certifications",
          "extras",
      ]
      assert isinstance(restored.sections[0], SkillsSection)
      assert isinstance(restored.sections[1], ExperienceSection)
      assert isinstance(restored.sections[2], ProjectsSection)
      assert isinstance(restored.sections[3], EducationSection)
      assert isinstance(restored.sections[4], CertificationsSection)
      assert isinstance(restored.sections[5], ExtrasSection)
      # Nested payloads survive the trip.
      assert restored.sections[1].items[0].bullets == ["Built the ingestion API."]
      assert restored.contact.links[0].url == "https://github.com/ada"


  def test_section_union_discriminates_from_plain_dicts():
      raw = {
          "contact": {"name": "Ada Example"},
          "headline": "Engineer",
          "summary": "Ships software.",
          "sections": [
              {"type": "extras", "title": "Additional", "items": ["Volunteers"]},
              {
                  "type": "experience",
                  "title": "Experience",
                  "items": [
                      {"company": "Acme Corp", "role": "Engineer", "start": "2021"}
                  ],
              },
          ],
      }
      doc = ResumeDoc.model_validate(raw)
      assert isinstance(doc.sections[0], ExtrasSection)
      assert isinstance(doc.sections[1], ExperienceSection)
      assert doc.sections[1].items[0].end is None


  def test_master_profile_round_trip():
      mp = MasterProfile(
          summary_notes="Ten years of backend work.",
          experiences=[
              MPExperience(
                  company="Acme Corp",
                  title="Software Engineer",
                  start="2021-03",
                  end=None,
                  location="Remote",
                  bullets=[TaggedBullet(text="Built APIs", tags=["python", "fastapi"])],
              )
          ],
          projects=[
              MPProject(
                  name="Tailored",
                  description="Resume builder",
                  url=None,
                  bullets=[TaggedBullet(text="Wrote it", tags=["react"])],
              )
          ],
          skills=[SkillGroup(label="Languages", items=["Python"])],
          education=[
              MPEducation(
                  institution="State University",
                  credential="B.S. Computer Science",
                  year="2015",
                  detail=None,
              )
          ],
          certifications=[MPCertification(name="AWS SAA", issuer="AWS", year="2022")],
          extras=["Speaks Spanish"],
      )
      restored = MasterProfile.model_validate(json.loads(mp.model_dump_json()))
      assert restored == mp
      assert restored.experiences[0].bullets[0].tags == ["python", "fastapi"]


  def test_usage_info_addition():
      a = UsageInfo(input_tokens=100, output_tokens=50, cost_usd=0.001)
      b = UsageInfo(input_tokens=25, output_tokens=75, cost_usd=0.0005)
      total = a + b
      assert total.input_tokens == 125
      assert total.output_tokens == 125
      assert total.cost_usd == 0.0015
      assert UsageInfo() + UsageInfo() == UsageInfo()


  def test_fetch_result_literal_rejects_bad_status():
      ok = FetchResult(status="fetched", text="posting body")
      assert ok.status == "fetched"
      assert ok.reason == ""
      needs = FetchResult(status="needs_paste", reason="HTTP 403")
      assert needs.reason == "HTTP 403"
      with pytest.raises(ValidationError):
          FetchResult(status="error")
  ```

- [ ] **Step 2: Run schema tests — expect FAIL**

  ```powershell
  cd .; pytest tests/test_schemas.py -v
  ```

  Expected failure (collection error):

  ```text
  ERROR tests/test_schemas.py - ModuleNotFoundError: No module named 'backend.app.schemas'
  ```

- [ ] **Step 3: Implement schemas (contract module, verbatim)**

  Create `backend\app\schemas.py` — this is the contract's COMPLETE module, copied
  exactly (complete file):

  ```python
  from __future__ import annotations

  from typing import Literal, Optional, Union

  from pydantic import BaseModel, Field


  class LinkItem(BaseModel):
      label: str
      url: str


  class Contact(BaseModel):
      name: str
      email: str = ""
      phone: Optional[str] = None
      location: Optional[str] = None
      links: list[LinkItem] = Field(default_factory=list)


  # --- Master profile (source of truth about a person) ---

  class TaggedBullet(BaseModel):
      text: str
      tags: list[str] = Field(default_factory=list)


  class MPExperience(BaseModel):
      company: str
      title: str
      start: str  # "YYYY-MM" or "YYYY"
      end: Optional[str] = None  # None means present
      location: Optional[str] = None
      bullets: list[TaggedBullet] = Field(default_factory=list)


  class MPProject(BaseModel):
      name: str
      description: str = ""
      url: Optional[str] = None
      bullets: list[TaggedBullet] = Field(default_factory=list)


  class SkillGroup(BaseModel):
      label: str
      items: list[str] = Field(default_factory=list)


  class MPEducation(BaseModel):
      institution: str
      credential: str
      year: Optional[str] = None
      detail: Optional[str] = None


  class MPCertification(BaseModel):
      name: str
      issuer: Optional[str] = None
      year: Optional[str] = None


  class MasterProfile(BaseModel):
      summary_notes: str = ""
      experiences: list[MPExperience] = Field(default_factory=list)
      projects: list[MPProject] = Field(default_factory=list)
      skills: list[SkillGroup] = Field(default_factory=list)
      education: list[MPEducation] = Field(default_factory=list)
      certifications: list[MPCertification] = Field(default_factory=list)
      extras: list[str] = Field(default_factory=list)


  # --- Posting analysis + research ---

  class ParsedPosting(BaseModel):
      title: str
      company: str
      company_domain: Optional[str] = None
      must_haves: list[str] = Field(default_factory=list)
      nice_to_haves: list[str] = Field(default_factory=list)
      keywords: list[str] = Field(default_factory=list)
      seniority: Optional[str] = None
      tone: Optional[str] = None


  class ResearchFindings(BaseModel):
      mission: str = ""
      products: list[str] = Field(default_factory=list)
      news: list[str] = Field(default_factory=list)
      tech_stack_signals: list[str] = Field(default_factory=list)
      culture_language: list[str] = Field(default_factory=list)
      sources: list[str] = Field(default_factory=list)


  # --- Resume document (renderer contract) ---

  class ExperienceItem(BaseModel):
      company: str
      role: str
      start: str
      end: Optional[str] = None
      location: Optional[str] = None
      bullets: list[str] = Field(default_factory=list)


  class ProjectItem(BaseModel):
      name: str
      description: str = ""
      url: Optional[str] = None
      bullets: list[str] = Field(default_factory=list)


  class EducationItem(BaseModel):
      institution: str
      credential: str
      year: Optional[str] = None
      detail: Optional[str] = None


  class CertificationItem(BaseModel):
      name: str
      issuer: Optional[str] = None
      year: Optional[str] = None


  class ExperienceSection(BaseModel):
      type: Literal["experience"] = "experience"
      title: str = "Experience"
      items: list[ExperienceItem] = Field(default_factory=list)


  class ProjectsSection(BaseModel):
      type: Literal["projects"] = "projects"
      title: str = "Projects"
      items: list[ProjectItem] = Field(default_factory=list)


  class SkillsSection(BaseModel):
      type: Literal["skills"] = "skills"
      title: str = "Skills"
      groups: list[SkillGroup] = Field(default_factory=list)


  class EducationSection(BaseModel):
      type: Literal["education"] = "education"
      title: str = "Education"
      items: list[EducationItem] = Field(default_factory=list)


  class CertificationsSection(BaseModel):
      type: Literal["certifications"] = "certifications"
      title: str = "Certifications"
      items: list[CertificationItem] = Field(default_factory=list)


  class ExtrasSection(BaseModel):
      type: Literal["extras"] = "extras"
      title: str = "Additional"
      items: list[str] = Field(default_factory=list)


  ResumeSection = Union[
      ExperienceSection,
      ProjectsSection,
      SkillsSection,
      EducationSection,
      CertificationsSection,
      ExtrasSection,
  ]


  class ResumeDoc(BaseModel):
      contact: Contact
      headline: str
      summary: str
      sections: list[ResumeSection] = Field(default_factory=list)


  class TailorResult(BaseModel):
      resume: ResumeDoc
      cover_letter_md: str
      tailoring_notes: str = ""


  class UsageInfo(BaseModel):
      input_tokens: int = 0
      output_tokens: int = 0
      cost_usd: float = 0.0

      def __add__(self, other: "UsageInfo") -> "UsageInfo":
          return UsageInfo(
              input_tokens=self.input_tokens + other.input_tokens,
              output_tokens=self.output_tokens + other.output_tokens,
              cost_usd=round(self.cost_usd + other.cost_usd, 6),
          )


  class FetchResult(BaseModel):
      status: Literal["fetched", "needs_paste"]
      text: str = ""
      reason: str = ""
  ```

- [ ] **Step 4: Run schema tests — expect PASS**

  ```powershell
  cd .; pytest tests/test_schemas.py -v
  ```

  Expected: `5 passed`. Then confirm nothing regressed:

  ```powershell
  cd .; pytest -v
  ```

  Expected: `17 passed`.

- [ ] **Step 5: Commit schemas**

  ```powershell
  cd .; git add -A; git commit -m "feat: complete pydantic schema module (resume doc, master profile, usage, fetch result)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

### Task 3: DB models

**Files**

- Create: `backend\app\models.py`
- Test: `tests\test_models.py`

**Interfaces**

- Consumes: `session` fixture (Task 1 conftest); `backend.app.schemas` symbols `Contact`, `LinkItem`, `MasterProfile`, `MPExperience`, `TaggedBullet`, `ParsedPosting`, `ResearchFindings`, `ResumeDoc`, `ExperienceSection`, `ExperienceItem` (Task 2). `init_db`'s guarded `from . import models` (written in Task 1) now succeeds, so the conftest `engine` fixture automatically creates these tables — no db.py change needed.
- Produces: `backend.app.models` — SQLModel entities `Profile`, `SourceDocument`, `Job`, `ResearchBrief`, `Application`, `ApplicationVersion` and typed JSON helpers `get_contact(p: Profile) -> Contact` (returns `Contact(name=p.name)` when `contact_json` is empty/`"{}"`, since `Contact.name` is required), `set_contact(p: Profile, c: Contact) -> None`, `get_master_profile(p: Profile) -> MasterProfile`, `set_master_profile(p: Profile, mp: MasterProfile) -> None`, `get_parsed(j: Job) -> ParsedPosting | None`, `set_parsed(j: Job, pp: ParsedPosting) -> None`, `get_findings(r: ResearchBrief) -> ResearchFindings`, `get_resume(a: Application) -> ResumeDoc | None`, `set_resume(a: Application, r: ResumeDoc) -> None`. All JSON payloads stored as TEXT columns holding serialized Pydantic JSON (`model_dump_json` / `model_validate_json`).

- [ ] **Step 1: Write failing model tests**

  Create `tests\test_models.py`:

  ```python
  from __future__ import annotations

  from datetime import datetime

  from sqlmodel import select

  from backend.app.models import (
      Application,
      ApplicationVersion,
      Job,
      Profile,
      ResearchBrief,
      SourceDocument,
      get_contact,
      get_findings,
      get_master_profile,
      get_parsed,
      get_resume,
      set_contact,
      set_master_profile,
      set_parsed,
      set_resume,
  )
  from backend.app.schemas import (
      Contact,
      ExperienceItem,
      ExperienceSection,
      LinkItem,
      MasterProfile,
      MPExperience,
      ParsedPosting,
      ResearchFindings,
      ResumeDoc,
      TaggedBullet,
  )


  def test_create_and_query_each_entity(session):
      profile = Profile(name="Ada Example")
      session.add(profile)
      session.commit()
      session.refresh(profile)

      doc = SourceDocument(
          profile_id=profile.id, filename="resume.pdf", kind="pdf", text="raw resume text"
      )
      job = Job(url="https://example.com/jobs/1")
      session.add(doc)
      session.add(job)
      session.commit()
      session.refresh(job)

      brief = ResearchBrief(job_id=job.id, depth="standard")
      app_row = Application(profile_id=profile.id, job_id=job.id)
      session.add(brief)
      session.add(app_row)
      session.commit()
      session.refresh(app_row)

      version = ApplicationVersion(
          application_id=app_row.id,
          version=1,
          resume_json="{}",
          cover_letter_md="Dear team,",
      )
      session.add(version)
      session.commit()

      assert session.exec(select(Profile)).one().name == "Ada Example"
      assert session.exec(select(SourceDocument)).one().kind == "pdf"
      assert session.exec(select(Job)).one().fetch_status == "pending"
      assert session.exec(select(ResearchBrief)).one().depth == "standard"
      assert session.exec(select(Application)).one().id == app_row.id
      assert session.exec(select(ApplicationVersion)).one().version == 1
      assert isinstance(profile.created_at, datetime)
      assert isinstance(app_row.updated_at, datetime)


  def test_application_defaults(session):
      profile = Profile(name="Ada Example")
      job = Job(url="https://example.com/jobs/2")
      session.add(profile)
      session.add(job)
      session.commit()
      session.refresh(profile)
      session.refresh(job)

      app_row = Application(profile_id=profile.id, job_id=job.id)
      session.add(app_row)
      session.commit()
      session.refresh(app_row)

      assert app_row.status == "queued"
      assert app_row.version == 1
      assert app_row.template == "slate"
      assert app_row.error_message is None
      assert app_row.input_tokens == 0
      assert app_row.output_tokens == 0
      assert app_row.cost_usd == 0.0
      assert app_row.resume_json is None
      assert app_row.cover_letter_md is None
      assert app_row.export_dir is None


  def test_job_defaults():
      job = Job(url="https://example.com/jobs/3")
      assert job.fetch_status == "pending"
      assert job.depth == "standard"
      assert job.raw_text is None
      assert job.parsed_json is None


  def test_contact_and_master_profile_helpers_round_trip():
      p = Profile(name="Ada Example")
      # Empty JSON: sensible typed defaults, never a ValidationError.
      assert get_contact(p) == Contact(name="Ada Example")
      assert get_master_profile(p) == MasterProfile()

      contact = Contact(
          name="Ada Example",
          email="ada@example.com",
          phone="555-0100",
          links=[LinkItem(label="GitHub", url="https://github.com/ada")],
      )
      set_contact(p, contact)
      assert get_contact(p) == contact

      mp = MasterProfile(
          summary_notes="Backend engineer.",
          experiences=[
              MPExperience(
                  company="Acme Corp",
                  title="Software Engineer",
                  start="2021-03",
                  bullets=[TaggedBullet(text="Built APIs", tags=["python"])],
              )
          ],
      )
      set_master_profile(p, mp)
      assert get_master_profile(p) == mp


  def test_job_parsed_helpers_round_trip():
      j = Job(url="https://example.com/jobs/4")
      assert get_parsed(j) is None
      parsed = ParsedPosting(
          title="Software Engineer",
          company="Acme Corp",
          company_domain="acme.example",
          must_haves=["Python"],
          keywords=["fastapi", "sqlite"],
      )
      set_parsed(j, parsed)
      assert get_parsed(j) == parsed


  def test_research_findings_helper():
      r = ResearchBrief(job_id=1, depth="deep")
      assert get_findings(r) == ResearchFindings()
      r.findings_json = ResearchFindings(
          mission="Ship it", sources=["https://acme.example/about"]
      ).model_dump_json()
      found = get_findings(r)
      assert found.mission == "Ship it"
      assert found.sources == ["https://acme.example/about"]


  def test_application_resume_helpers_round_trip():
      a = Application(profile_id=1, job_id=1)
      assert get_resume(a) is None
      resume = ResumeDoc(
          contact=Contact(name="Ada Example"),
          headline="Software Engineer",
          summary="Ships reliable software.",
          sections=[
              ExperienceSection(
                  items=[
                      ExperienceItem(
                          company="Acme Corp", role="Software Engineer", start="2021-03"
                      )
                  ]
              )
          ],
      )
      set_resume(a, resume)
      assert get_resume(a) == resume
  ```

- [ ] **Step 2: Run model tests — expect FAIL**

  ```powershell
  cd .; pytest tests/test_models.py -v
  ```

  Expected failure (collection error):

  ```text
  ERROR tests/test_models.py - ModuleNotFoundError: No module named 'backend.app.models'
  ```

- [ ] **Step 3: Implement the models module**

  Create `backend\app\models.py` (complete file):

  ```python
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
  ```

- [ ] **Step 4: Run model tests — expect PASS, then the full suite**

  ```powershell
  cd .; pytest tests/test_models.py -v
  ```

  Expected: `7 passed`. (The `engine` fixture's `init_db` now imports `backend.app.models`
  via the guarded import written in Task 1, so all six tables exist on the tmp SQLite file.)

  ```powershell
  cd .; pytest -v
  ```

  Expected: `24 passed` (12 foundation + 5 schemas + 7 models).

- [ ] **Step 5: Commit models**

  ```powershell
  cd .; git add -A; git commit -m "feat: sqlmodel entities and typed json helpers (models.py)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

---

# Section: Claude Service & Intake (Tasks 4–5)

> Working directory for every command: `.`. Every command below starts with an explicit `cd` because agent shells reset cwd. Python venv is active; `pytest`, `python`, `git` are on PATH.
>
> Depends on Tasks 1–3 having landed: git repo + `pyproject.toml` with `[tool.pytest.ini_options]` containing `testpaths` and the `pdf` marker (Task 1); `backend.app.*` imports resolve via the sys.path shim at the top of `tests/conftest.py` (Task 1) — do not add a `pythonpath` key to `pyproject.toml`. Also landed: `backend/app/__init__.py`, `backend/app/schemas.py` (Task 2, verbatim from the contract), and `tests/conftest.py` with the `db_session` fixture (Task 1). `anthropic`, `pypdf`, and `python-docx` are in `requirements.txt` from Task 1; if any is missing, `pip install anthropic pypdf python-docx` and add them to `requirements.txt` before starting.
>
> None of the tests below touch the real Anthropic API. The real-mode code path in `ClaudeService` is exercised only through its pure helpers (`compute_cost`, `strict_schema`) — that is deliberate per the global constraint "NEVER hit the real Anthropic API in tests".

---

### Task 4: ClaudeService (wrapper, fake mode, fixtures, cost tracking)

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/claude.py`
- Create: `backend/app/fixtures/intake.json`
- Create: `backend/app/fixtures/parse_posting.json`
- Create: `backend/app/fixtures/research_standard.json`
- Create: `backend/app/fixtures/research_deep.json`
- Create: `backend/app/fixtures/tailor.json`
- Modify: `tests/conftest.py` (append `claude_fake` fixture — do not rewrite existing content)
- Test: `tests/test_claude.py`

**Interfaces:**
- Consumes:
  - `backend.app.schemas`: `UsageInfo`, `ParsedPosting`, `ResearchFindings`, `TailorResult`, `ResumeDoc` (Task 2)
  - `tests/conftest.py` existing content (Task 1) — appended to only
- Produces (all in `backend/app/services/claude.py` unless noted):
  - `MODEL_ID = "claude-opus-4-8"` (module constant)
  - `COST_INPUT_PER_MTOK = 5.00`, `COST_OUTPUT_PER_MTOK = 25.00`
  - `MAX_PAUSE_TURN_CONTINUATIONS = 5` (module constant)
  - `compute_cost(input_tokens: int, output_tokens: int) -> float` — pure cost function, rounded to 6 decimal places; used by real mode and by later sections for any cost math
  - `strict_schema(model_cls: type[BaseModel]) -> dict`
  - `class ClaudeError(Exception)`
  - `class ClaudeService` — `__init__(self, api_key: str | None = None, fake_mode: bool = False, fixtures_dir: Path | None = None)`; public attribute `calls: list[dict]` where every `structured()` invocation (both modes) appends `{"task", "system", "user_content", "tools", "schema_model_name"}` — later sections' tests assert prompts/tools through this; method `structured(*, task: str, system: str, user_content: str, schema_model: type[BaseModel], tools: list[dict] | None = None, max_tokens: int = 16000) -> tuple[BaseModel, UsageInfo]`
  - `make_claude(settings) -> ClaudeService`
  - pytest fixture `claude_fake` in `tests/conftest.py` returning `ClaudeService(fake_mode=True, fixtures_dir=<repo>/backend/app/fixtures)` — used by Tasks 5, 7, 8, 9, 12, 13 tests
  - Fixture files `backend/app/fixtures/{intake,parse_posting,research_standard,research_deep,tailor}.json` — the canonical fake-mode/demo data; `tailor.json`'s resume uses only companies/titles/dates/education/certifications present in `intake.json` (Task 8's truthfulness test depends on this)

- [ ] **Step 1: Write failing tests for cost helpers and strict_schema**

  Create `tests/test_claude.py` with exactly this content:

  ```python
  """Tests for backend/app/services/claude.py."""
  from __future__ import annotations

  from pydantic import BaseModel

  from backend.app.schemas import ResumeDoc
  from backend.app.services.claude import (
      COST_INPUT_PER_MTOK,
      COST_OUTPUT_PER_MTOK,
      compute_cost,
      strict_schema,
  )


  class _Inner(BaseModel):
      value: str


  class _Outer(BaseModel):
      name: str
      inner: _Inner
      rows: list[_Inner]


  def _assert_all_object_nodes_strict(node) -> None:
      """Recursively assert every JSON-schema object node has additionalProperties=False."""
      if isinstance(node, dict):
          if node.get("type") == "object" or "properties" in node:
              assert node.get("additionalProperties") is False, (
                  f"object node missing additionalProperties=False: {node}"
              )
          for value in node.values():
              _assert_all_object_nodes_strict(value)
      elif isinstance(node, list):
          for item in node:
              _assert_all_object_nodes_strict(item)


  def test_cost_constants():
      assert COST_INPUT_PER_MTOK == 5.00
      assert COST_OUTPUT_PER_MTOK == 25.00


  def test_compute_cost_exact():
      assert compute_cost(0, 0) == 0.0
      assert compute_cost(1_000_000, 0) == 5.0
      assert compute_cost(0, 1_000_000) == 25.0
      # 123,456 in @ $5/MTok = 0.61728; 78,900 out @ $25/MTok = 1.9725
      assert compute_cost(123_456, 78_900) == 2.58978


  def test_compute_cost_rounds_six_decimals():
      # 7 input tokens -> 0.000035; 3 output tokens -> 0.000075; total 0.00011
      assert compute_cost(7, 3) == 0.00011
      assert compute_cost(1, 0) == 0.000005


  def test_strict_schema_marks_top_level_nested_and_defs():
      schema = strict_schema(_Outer)
      assert schema["additionalProperties"] is False
      assert schema["$defs"]["_Inner"]["additionalProperties"] is False
      _assert_all_object_nodes_strict(schema)


  def test_strict_schema_on_resumedoc_covers_all_defs():
      schema = strict_schema(ResumeDoc)
      assert schema["additionalProperties"] is False
      for def_schema in schema["$defs"].values():
          _assert_all_object_nodes_strict(def_schema)
      _assert_all_object_nodes_strict(schema)
  ```

- [ ] **Step 2: Run test, expect FAIL (module does not exist)**

  ```powershell
  cd .; pytest tests/test_claude.py -v
  ```

  Expected failure (collection error):

  ```
  ERROR tests/test_claude.py - ModuleNotFoundError: No module named 'backend.app.services'
  ```

- [ ] **Step 3: Implement cost helpers and strict_schema**

  Create `backend/app/services/__init__.py` as an empty file (zero bytes is fine, or a single comment line):

  ```python
  ```

  Create `backend/app/services/claude.py` with exactly this content (this file is fully replaced in Step 8 — that is intentional):

  ```python
  """Claude API wrapper: structured outputs, fake mode, usage/cost tracking."""
  from __future__ import annotations

  from typing import Any

  from pydantic import BaseModel

  MODEL_ID = "claude-opus-4-8"
  COST_INPUT_PER_MTOK = 5.00
  COST_OUTPUT_PER_MTOK = 25.00
  MAX_PAUSE_TURN_CONTINUATIONS = 5


  def compute_cost(input_tokens: int, output_tokens: int) -> float:
      """USD cost for a call at Opus 4.8 rates, rounded to 6 decimal places."""
      return round(
          input_tokens / 1e6 * COST_INPUT_PER_MTOK
          + output_tokens / 1e6 * COST_OUTPUT_PER_MTOK,
          6,
      )


  def _mark_objects_strict(node: Any) -> None:
      """Recursively add additionalProperties: false to every object node ($defs included)."""
      if isinstance(node, dict):
          if node.get("type") == "object" or "properties" in node:
              node["additionalProperties"] = False
          for value in list(node.values()):
              _mark_objects_strict(value)
      elif isinstance(node, list):
          for item in node:
              _mark_objects_strict(item)


  def strict_schema(model_cls: type[BaseModel]) -> dict:
      """model_json_schema() with additionalProperties: false injected at every object level."""
      schema = model_cls.model_json_schema()
      _mark_objects_strict(schema)
      return schema


  class ClaudeError(Exception):
      """Raised on refusals, unparseable output, missing fixtures, or exhausted continuations."""
  ```

- [ ] **Step 4: Run test, expect PASS**

  ```powershell
  cd .; pytest tests/test_claude.py -v
  ```

  Expected: `5 passed`.

- [ ] **Step 5: Commit cycle 1**

  ```powershell
  cd .; git add backend/app/services/__init__.py backend/app/services/claude.py tests/test_claude.py; git commit -m "feat: claude service cost constants, compute_cost, strict_schema" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

- [ ] **Step 6: Write failing tests for ClaudeService fake mode, call recording, and make_claude**

  Replace the entire contents of `tests/test_claude.py` with:

  ```python
  """Tests for backend/app/services/claude.py."""
  from __future__ import annotations

  import pytest
  from pydantic import BaseModel

  from backend.app.schemas import (
      ParsedPosting,
      ResearchFindings,
      ResumeDoc,
      TailorResult,
      UsageInfo,
  )
  from backend.app.services.claude import (
      COST_INPUT_PER_MTOK,
      COST_OUTPUT_PER_MTOK,
      ClaudeError,
      compute_cost,
      make_claude,
      strict_schema,
  )


  class _Inner(BaseModel):
      value: str


  class _Outer(BaseModel):
      name: str
      inner: _Inner
      rows: list[_Inner]


  def _assert_all_object_nodes_strict(node) -> None:
      """Recursively assert every JSON-schema object node has additionalProperties=False."""
      if isinstance(node, dict):
          if node.get("type") == "object" or "properties" in node:
              assert node.get("additionalProperties") is False, (
                  f"object node missing additionalProperties=False: {node}"
              )
          for value in node.values():
              _assert_all_object_nodes_strict(value)
      elif isinstance(node, list):
          for item in node:
              _assert_all_object_nodes_strict(item)


  def test_cost_constants():
      assert COST_INPUT_PER_MTOK == 5.00
      assert COST_OUTPUT_PER_MTOK == 25.00


  def test_compute_cost_exact():
      assert compute_cost(0, 0) == 0.0
      assert compute_cost(1_000_000, 0) == 5.0
      assert compute_cost(0, 1_000_000) == 25.0
      # 123,456 in @ $5/MTok = 0.61728; 78,900 out @ $25/MTok = 1.9725
      assert compute_cost(123_456, 78_900) == 2.58978


  def test_compute_cost_rounds_six_decimals():
      # 7 input tokens -> 0.000035; 3 output tokens -> 0.000075; total 0.00011
      assert compute_cost(7, 3) == 0.00011
      assert compute_cost(1, 0) == 0.000005


  def test_strict_schema_marks_top_level_nested_and_defs():
      schema = strict_schema(_Outer)
      assert schema["additionalProperties"] is False
      assert schema["$defs"]["_Inner"]["additionalProperties"] is False
      _assert_all_object_nodes_strict(schema)


  def test_strict_schema_on_resumedoc_covers_all_defs():
      schema = strict_schema(ResumeDoc)
      assert schema["additionalProperties"] is False
      for def_schema in schema["$defs"].values():
          _assert_all_object_nodes_strict(def_schema)
      _assert_all_object_nodes_strict(schema)


  def test_fake_mode_returns_validated_model_and_zero_usage(claude_fake):
      parsed, usage = claude_fake.structured(
          task="parse_posting",
          system="You parse postings.",
          user_content="raw posting text here",
          schema_model=ParsedPosting,
      )
      assert isinstance(parsed, ParsedPosting)
      assert parsed.title == "Senior Backend Engineer"
      assert parsed.company == "Northwind Labs"
      assert parsed.company_domain == "northwindlabs.com"
      assert usage == UsageInfo(input_tokens=0, output_tokens=0, cost_usd=0.0)


  def test_fake_mode_records_calls(claude_fake):
      tools = [{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8}]
      claude_fake.structured(
          task="research_standard",
          system="Research the company.",
          user_content="ParsedPosting JSON here",
          schema_model=ResearchFindings,
          tools=tools,
      )
      assert len(claude_fake.calls) == 1
      assert claude_fake.calls[0] == {
          "task": "research_standard",
          "system": "Research the company.",
          "user_content": "ParsedPosting JSON here",
          "tools": tools,
          "schema_model_name": "ResearchFindings",
      }


  def test_fake_mode_all_fixtures_validate(claude_fake):
      standard, _ = claude_fake.structured(
          task="research_standard", system="s", user_content="u",
          schema_model=ResearchFindings,
      )
      deep, _ = claude_fake.structured(
          task="research_deep", system="s", user_content="u",
          schema_model=ResearchFindings,
      )
      tailor, _ = claude_fake.structured(
          task="tailor", system="s", user_content="u", schema_model=TailorResult,
      )
      assert standard.mission
      assert deep.news and deep.sources
      assert tailor.resume.contact.name == "Jordan Rivera"
      assert tailor.cover_letter_md
      assert len(claude_fake.calls) == 3


  def test_fake_mode_missing_fixture_raises(claude_fake):
      with pytest.raises(ClaudeError):
          claude_fake.structured(
              task="does_not_exist", system="s", user_content="u",
              schema_model=ParsedPosting,
          )


  def test_make_claude_honors_fake_mode():
      class FakeSettings:
          fake_mode = True
          anthropic_api_key = None

      class RealSettings:
          fake_mode = False
          anthropic_api_key = "sk-test-123"

      fake_service = make_claude(FakeSettings())
      assert fake_service.fake_mode is True
      assert fake_service.fixtures_dir is not None
      assert (fake_service.fixtures_dir / "parse_posting.json").exists()

      real_service = make_claude(RealSettings())
      assert real_service.fake_mode is False
      assert real_service.api_key == "sk-test-123"
      assert real_service.fixtures_dir == fake_service.fixtures_dir
  ```

- [ ] **Step 7: Run test, expect FAIL (make_claude / fake mode not implemented)**

  ```powershell
  cd .; pytest tests/test_claude.py -v
  ```

  Expected failure (collection error — the import line asks for names that do not exist yet):

  ```
  ERROR tests/test_claude.py - ImportError: cannot import name 'ClaudeError' from 'backend.app.services.claude'
  ```

  (If `ClaudeError` already resolves, the reported missing name will be `make_claude` — either way the file fails to import.)

- [ ] **Step 8: Implement ClaudeService (fake + real), make_claude, all five fixtures, and the claude_fake conftest fixture**

  8a. Replace the entire contents of `backend/app/services/claude.py` with:

  ```python
  """Claude API wrapper: structured outputs, fake mode, usage/cost tracking.

  All Claude traffic in the app goes through ClaudeService.structured().
  fake_mode loads canned JSON fixtures (tests + offline demo mode) and records
  every call on .calls so tests can assert on prompts/tools.
  """
  from __future__ import annotations

  import json
  from pathlib import Path
  from typing import Any

  from pydantic import BaseModel, ValidationError

  from ..schemas import UsageInfo

  MODEL_ID = "claude-opus-4-8"
  COST_INPUT_PER_MTOK = 5.00
  COST_OUTPUT_PER_MTOK = 25.00
  MAX_PAUSE_TURN_CONTINUATIONS = 5


  def compute_cost(input_tokens: int, output_tokens: int) -> float:
      """USD cost for a call at Opus 4.8 rates, rounded to 6 decimal places."""
      return round(
          input_tokens / 1e6 * COST_INPUT_PER_MTOK
          + output_tokens / 1e6 * COST_OUTPUT_PER_MTOK,
          6,
      )


  def _mark_objects_strict(node: Any) -> None:
      """Recursively add additionalProperties: false to every object node ($defs included)."""
      if isinstance(node, dict):
          if node.get("type") == "object" or "properties" in node:
              node["additionalProperties"] = False
          for value in list(node.values()):
              _mark_objects_strict(value)
      elif isinstance(node, list):
          for item in node:
              _mark_objects_strict(item)


  def strict_schema(model_cls: type[BaseModel]) -> dict:
      """model_json_schema() with additionalProperties: false injected at every object level."""
      schema = model_cls.model_json_schema()
      _mark_objects_strict(schema)
      return schema


  class ClaudeError(Exception):
      """Raised on refusals, unparseable output, missing fixtures, or exhausted continuations."""


  class ClaudeService:
      """Wrapper around the Anthropic client with a fixture-backed fake mode.

      .calls records every structured() invocation (both modes) as
      {"task", "system", "user_content", "tools", "schema_model_name"}
      so tests can assert on exactly what would be sent to the API.
      """

      def __init__(
          self,
          api_key: str | None = None,
          fake_mode: bool = False,
          fixtures_dir: Path | None = None,
      ) -> None:
          self.api_key = api_key
          self.fake_mode = fake_mode
          self.fixtures_dir = Path(fixtures_dir) if fixtures_dir is not None else None
          self.calls: list[dict] = []
          self._client = None

      def _get_client(self):
          if self._client is None:
              import anthropic

              self._client = anthropic.Anthropic(api_key=self.api_key)
          return self._client

      def structured(
          self,
          *,
          task: str,
          system: str,
          user_content: str,
          schema_model: type[BaseModel],
          tools: list[dict] | None = None,
          max_tokens: int = 16000,
      ) -> tuple[BaseModel, UsageInfo]:
          self.calls.append(
              {
                  "task": task,
                  "system": system,
                  "user_content": user_content,
                  "tools": tools,
                  "schema_model_name": schema_model.__name__,
              }
          )
          if self.fake_mode:
              return self._structured_fake(task=task, schema_model=schema_model)
          return self._structured_real(
              task=task,
              system=system,
              user_content=user_content,
              schema_model=schema_model,
              tools=tools,
              max_tokens=max_tokens,
          )

      def _structured_fake(
          self, *, task: str, schema_model: type[BaseModel]
      ) -> tuple[BaseModel, UsageInfo]:
          if self.fixtures_dir is None:
              raise ClaudeError("fake_mode requires fixtures_dir")
          fixture_path = self.fixtures_dir / f"{task}.json"
          if not fixture_path.exists():
              raise ClaudeError(f"[{task}] no fixture at {fixture_path}")
          raw = fixture_path.read_text(encoding="utf-8")
          try:
              payload = json.loads(raw)
          except json.JSONDecodeError as exc:
              raise ClaudeError(
                  f"[{task}] fixture {fixture_path} is not valid JSON: {exc}"
              ) from exc
          try:
              model = schema_model.model_validate(payload)
          except ValidationError as exc:
              raise ClaudeError(
                  f"[{task}] fixture {fixture_path} failed "
                  f"{schema_model.__name__} validation: {exc}"
              ) from exc
          return model, UsageInfo(input_tokens=0, output_tokens=0, cost_usd=0.0)

      def _structured_real(
          self,
          *,
          task: str,
          system: str,
          user_content: str,
          schema_model: type[BaseModel],
          tools: list[dict] | None,
          max_tokens: int,
      ) -> tuple[BaseModel, UsageInfo]:
          import anthropic

          client = self._get_client()
          messages: list[dict] = [{"role": "user", "content": user_content}]
          total_input = 0
          total_output = 0
          message = None
          for _ in range(1 + MAX_PAUSE_TURN_CONTINUATIONS):
              kwargs: dict = {
                  "model": MODEL_ID,
                  "max_tokens": max_tokens,
                  "system": system,
                  "messages": messages,
                  "thinking": {"type": "adaptive"},
                  "output_config": {
                      "format": {
                          "type": "json_schema",
                          "schema": strict_schema(schema_model),
                      }
                  },
              }
              if tools:
                  kwargs["tools"] = tools
              try:
                  with client.messages.stream(**kwargs) as stream:
                      message = stream.get_final_message()
              except anthropic.RateLimitError as exc:
                  raise ClaudeError(
                      f"[{task}] Anthropic rate limit reached - wait a minute "
                      f"and retry ({exc})"
                  ) from exc
              except anthropic.APIConnectionError as exc:
                  raise ClaudeError(
                      f"[{task}] could not reach the Anthropic API - check "
                      f"your network ({exc})"
                  ) from exc
              except anthropic.APIStatusError as exc:
                  raise ClaudeError(
                      f"[{task}] Anthropic API error "
                      f"(HTTP {exc.status_code}) - {exc.message}"
                  ) from exc
              total_input += message.usage.input_tokens
              total_output += message.usage.output_tokens
              if message.stop_reason == "pause_turn":
                  messages = messages + [
                      {"role": "assistant", "content": message.content}
                  ]
                  continue
              break
          if message is None:
              raise ClaudeError(f"[{task}] no response from API")
          if message.stop_reason == "pause_turn":
              raise ClaudeError(
                  f"[{task}] still pause_turn after "
                  f"{MAX_PAUSE_TURN_CONTINUATIONS} continuations"
              )
          if message.stop_reason == "refusal":
              raise ClaudeError(f"[{task}] model refused (stop_reason=refusal)")
          text = ""
          for block in message.content:
              if getattr(block, "type", None) == "text":
                  text = block.text
          if not text:
              raise ClaudeError(
                  f"[{task}] response contained no text block "
                  f"(stop_reason={message.stop_reason})"
              )
          try:
              payload = json.loads(text)
          except json.JSONDecodeError as exc:
              raise ClaudeError(
                  f"[{task}] response was not valid JSON: {exc}; "
                  f"raw text: {text[:2000]}"
              ) from exc
          try:
              model = schema_model.model_validate(payload)
          except ValidationError as exc:
              raise ClaudeError(
                  f"[{task}] response failed {schema_model.__name__} "
                  f"validation: {exc}; raw text: {text[:2000]}"
              ) from exc
          usage = UsageInfo(
              input_tokens=total_input,
              output_tokens=total_output,
              cost_usd=compute_cost(total_input, total_output),
          )
          return model, usage


  def make_claude(settings) -> ClaudeService:
      """Factory honoring Settings.fake_mode; fixtures always at backend/app/fixtures."""
      fixtures_dir = Path(__file__).resolve().parents[1] / "fixtures"
      if getattr(settings, "fake_mode", False):
          return ClaudeService(fake_mode=True, fixtures_dir=fixtures_dir)
      return ClaudeService(
          api_key=getattr(settings, "anthropic_api_key", None),
          fake_mode=False,
          fixtures_dir=fixtures_dir,
      )
  ```

  Note on the exception mapping in `_structured_real`: the ordering is most-specific first — `anthropic.RateLimitError` is a subclass of `anthropic.APIStatusError`, so it must be caught before it. The Anthropic SDK's built-in retry/backoff for 429 and 5xx responses is already active by default (`max_retries=2`), so these handlers only fire after the SDK has exhausted its own retries; they turn raw SDK tracebacks into friendly `ClaudeError` messages that the pipeline stores in `Application.error_message` (spec section 8).

  8b. Create the fixtures directory:

  ```powershell
  cd .; New-Item -ItemType Directory -Force backend/app/fixtures | Out-Null
  ```

  All five JSON files below are ASCII-only; save them as UTF-8 **without BOM** (the file-write tool default; do NOT use `Set-Content -Encoding utf8` on Windows PowerShell 5, which adds a BOM that breaks `json.loads`).

  8c. Create `backend/app/fixtures/intake.json` with exactly this content:

  ```json
  {
    "contact": {
      "name": "Jordan Rivera",
      "email": "jordan.rivera@example.com",
      "phone": "+1 (555) 210-4477",
      "location": "Portland, OR",
      "links": [
        {"label": "GitHub", "url": "https://github.com/jordanrivera"},
        {"label": "LinkedIn", "url": "https://www.linkedin.com/in/jordan-rivera-dev"}
      ]
    },
    "master_profile": {
      "summary_notes": "Backend-focused software engineer with 8 years of experience building Python services, REST APIs, and data-heavy systems on PostgreSQL and AWS. Track record of performance work, service decomposition, CI/CD ownership, and mentoring.",
      "experiences": [
        {
          "company": "Cascade Analytics",
          "title": "Senior Software Engineer",
          "start": "2021-03",
          "end": null,
          "location": "Portland, OR",
          "bullets": [
            {
              "text": "Designed and shipped a FastAPI event-ingestion service handling 40M events/day with p99 latency under 120ms",
              "tags": ["python", "fastapi", "apis", "performance", "scalability"]
            },
            {
              "text": "Led decomposition of a monolithic Django app into 6 domain services on PostgreSQL, cutting deploy time from 45 minutes to 8 minutes",
              "tags": ["architecture", "postgresql", "microservices", "leadership"]
            },
            {
              "text": "Introduced contract tests and CI quality gates with pytest and GitHub Actions, reducing production incidents by 35%",
              "tags": ["testing", "ci-cd", "pytest", "reliability"]
            },
            {
              "text": "Mentored 3 junior engineers through weekly design reviews and pairing rotations",
              "tags": ["mentorship", "leadership", "communication"]
            }
          ]
        },
        {
          "company": "Brightline Software",
          "title": "Software Engineer",
          "start": "2018-06",
          "end": "2021-02",
          "location": "Seattle, WA",
          "bullets": [
            {
              "text": "Built Flask REST APIs powering a customer billing portal used by 12,000 accounts",
              "tags": ["python", "flask", "apis", "billing"]
            },
            {
              "text": "Optimized slow PostgreSQL reporting queries, cutting nightly batch runtime from 4 hours to 50 minutes",
              "tags": ["postgresql", "sql", "performance"]
            },
            {
              "text": "Containerized 9 legacy services with Docker and built the Compose-based local development environment",
              "tags": ["docker", "devops", "developer-experience"]
            },
            {
              "text": "Implemented Stripe webhook processing with idempotent handlers and dead-letter retries",
              "tags": ["payments", "stripe", "reliability", "event-driven"]
            }
          ]
        }
      ],
      "projects": [
        {
          "name": "queuelite",
          "description": "Open-source lightweight Python task queue backed by SQLite",
          "url": "https://github.com/jordanrivera/queuelite",
          "bullets": [
            {
              "text": "Built a polling worker with visibility timeouts and at-least-once delivery guarantees",
              "tags": ["python", "concurrency", "sqlite", "queues"]
            },
            {
              "text": "Published to PyPI with full type hints; 400+ GitHub stars",
              "tags": ["open-source", "python"]
            }
          ]
        }
      ],
      "skills": [
        {
          "label": "Languages & Frameworks",
          "items": ["Python", "TypeScript", "SQL", "FastAPI", "Flask"]
        },
        {
          "label": "Infrastructure & Tools",
          "items": ["PostgreSQL", "Docker", "GitHub Actions", "Redis", "AWS (ECS, S3, RDS)"]
        }
      ],
      "education": [
        {
          "institution": "University of Washington",
          "credential": "B.S. Computer Science",
          "year": "2018",
          "detail": "Focus in distributed systems"
        }
      ],
      "certifications": [
        {
          "name": "AWS Certified Developer - Associate",
          "issuer": "Amazon Web Services",
          "year": "2023"
        }
      ],
      "extras": [
        "Speaker, PyCascades 2024: \"SQLite in Production\"",
        "Maintainer of two pytest plugins"
      ]
    }
  }
  ```

  8d. Create `backend/app/fixtures/parse_posting.json` with exactly this content:

  ```json
  {
    "title": "Senior Backend Engineer",
    "company": "Northwind Labs",
    "company_domain": "northwindlabs.com",
    "must_haves": [
      "5+ years building backend services in Python",
      "Production experience designing and operating REST APIs",
      "Strong PostgreSQL skills including query optimization",
      "Experience owning CI/CD pipelines and deployment automation"
    ],
    "nice_to_haves": [
      "FastAPI in production",
      "Event-driven or queue-based architectures",
      "AWS (ECS, RDS)",
      "Mentoring junior engineers"
    ],
    "keywords": [
      "Python",
      "FastAPI",
      "PostgreSQL",
      "REST",
      "microservices",
      "CI/CD",
      "AWS",
      "observability",
      "event-driven"
    ],
    "seniority": "senior",
    "tone": "pragmatic, engineering-driven, ownership-focused"
  }
  ```

  8e. Create `backend/app/fixtures/research_standard.json` with exactly this content:

  ```json
  {
    "mission": "Northwind Labs builds logistics-visibility software that gives mid-market shippers real-time tracking of freight across road, rail, and ocean.",
    "products": [
      "Northwind Track - real-time shipment visibility platform",
      "Northwind Signals - delay-prediction API for supply chain teams"
    ],
    "news": [],
    "tech_stack_signals": [
      "Careers page lists Python and PostgreSQL for backend roles",
      "About page describes an API-first platform running on AWS"
    ],
    "culture_language": [
      "Ship small, ship often",
      "Customer-obsessed",
      "Engineers own their services end to end"
    ],
    "sources": [
      "https://northwindlabs.com/about",
      "https://northwindlabs.com/careers"
    ]
  }
  ```

  8f. Create `backend/app/fixtures/research_deep.json` with exactly this content:

  ```json
  {
    "mission": "Northwind Labs builds logistics-visibility software that gives mid-market shippers real-time tracking of freight across road, rail, and ocean.",
    "products": [
      "Northwind Track - real-time shipment visibility platform",
      "Northwind Signals - delay-prediction API for supply chain teams",
      "Northwind Atlas - vetted carrier network directory launched January 2026"
    ],
    "news": [
      "Raised a $28M Series B (April 2026) led by Foundry Group to expand the Signals prediction platform",
      "Launched Northwind Atlas in January 2026 and onboarded 4,000 carriers in the first quarter",
      "Engineering blog (March 2026) details migrating event ingestion from Celery to a Postgres-backed queue"
    ],
    "tech_stack_signals": [
      "Python 3.12 + FastAPI microservices per the engineering blog",
      "PostgreSQL as the primary datastore, including queue workloads",
      "AWS ECS deployments with GitHub Actions CI",
      "OpenTelemetry tracing rollout described in a 2026 blog post"
    ],
    "culture_language": [
      "Ship small, ship often",
      "Customer-obsessed",
      "Engineers own their services end to end",
      "Written design docs before major changes"
    ],
    "sources": [
      "https://northwindlabs.com/about",
      "https://northwindlabs.com/blog/postgres-queue-migration",
      "https://northwindlabs.com/careers",
      "https://techcrunch.com/2026/04/14/northwind-labs-raises-28m-series-b/"
    ]
  }
  ```

  8g. Create `backend/app/fixtures/tailor.json` with exactly this content. INVARIANT (tested in Task 8): every experience `company`/`role`/`start`/`end`, every education item, and every certification below is copied verbatim from `intake.json`'s master profile (`role` here equals `title` there). Do not edit one file without the other.

  ```json
  {
    "resume": {
      "contact": {
        "name": "Jordan Rivera",
        "email": "jordan.rivera@example.com",
        "phone": "+1 (555) 210-4477",
        "location": "Portland, OR",
        "links": [
          {"label": "GitHub", "url": "https://github.com/jordanrivera"},
          {"label": "LinkedIn", "url": "https://www.linkedin.com/in/jordan-rivera-dev"}
        ]
      },
      "headline": "Senior Backend Engineer - Python, FastAPI, PostgreSQL",
      "summary": "Backend engineer with 8 years shipping Python services and REST APIs on PostgreSQL and AWS. Led a monolith-to-services decomposition, built a FastAPI pipeline handling 40M events/day, and owns CI/CD end to end - a direct match for Northwind Labs' Python platform and its engineers-own-their-services culture.",
      "sections": [
        {
          "type": "experience",
          "title": "Experience",
          "items": [
            {
              "company": "Cascade Analytics",
              "role": "Senior Software Engineer",
              "start": "2021-03",
              "end": null,
              "location": "Portland, OR",
              "bullets": [
                "Designed and shipped a FastAPI event-ingestion service handling 40M events/day with p99 latency under 120ms",
                "Led decomposition of a monolithic Django app into 6 domain services on PostgreSQL, cutting deploy time from 45 minutes to 8 minutes",
                "Introduced contract tests and CI quality gates with pytest and GitHub Actions, reducing production incidents by 35%",
                "Mentored 3 junior engineers through weekly design reviews and pairing rotations"
              ]
            },
            {
              "company": "Brightline Software",
              "role": "Software Engineer",
              "start": "2018-06",
              "end": "2021-02",
              "location": "Seattle, WA",
              "bullets": [
                "Built Flask REST APIs powering a customer billing portal used by 12,000 accounts",
                "Optimized slow PostgreSQL reporting queries, cutting nightly batch runtime from 4 hours to 50 minutes",
                "Implemented Stripe webhook processing with idempotent handlers and dead-letter retries"
              ]
            }
          ]
        },
        {
          "type": "projects",
          "title": "Projects",
          "items": [
            {
              "name": "queuelite",
              "description": "Open-source lightweight Python task queue backed by SQLite",
              "url": "https://github.com/jordanrivera/queuelite",
              "bullets": [
                "Built a polling worker with visibility timeouts and at-least-once delivery guarantees",
                "Published to PyPI with full type hints; 400+ GitHub stars"
              ]
            }
          ]
        },
        {
          "type": "skills",
          "title": "Skills",
          "groups": [
            {
              "label": "Languages & Frameworks",
              "items": ["Python", "TypeScript", "SQL", "FastAPI", "Flask"]
            },
            {
              "label": "Infrastructure & Tools",
              "items": ["PostgreSQL", "Docker", "GitHub Actions", "Redis", "AWS (ECS, S3, RDS)"]
            }
          ]
        },
        {
          "type": "education",
          "title": "Education",
          "items": [
            {
              "institution": "University of Washington",
              "credential": "B.S. Computer Science",
              "year": "2018",
              "detail": "Focus in distributed systems"
            }
          ]
        },
        {
          "type": "certifications",
          "title": "Certifications",
          "items": [
            {
              "name": "AWS Certified Developer - Associate",
              "issuer": "Amazon Web Services",
              "year": "2023"
            }
          ]
        }
      ]
    },
    "cover_letter_md": "Dear Northwind Labs hiring team,\n\nYour March engineering post about replacing Celery with a Postgres-backed queue caught my attention - I built and open-sourced queuelite, a SQLite-backed task queue with visibility timeouts and at-least-once delivery, so I have lived with exactly the tradeoffs that migration involves.\n\nAt Cascade Analytics I designed a FastAPI ingestion service that handles 40M events/day at a p99 under 120ms, and led the decomposition of a Django monolith into six PostgreSQL-backed services - the same Python/FastAPI/PostgreSQL stack your blog describes. I also own our CI/CD: the contract tests and GitHub Actions gates I introduced cut production incidents by 35%.\n\n\"Ship small, ship often\" matches how I already work - the 45-to-8-minute deploy improvement above existed precisely so we could. I would welcome the chance to bring that bias for small, safe releases to the Signals platform as it scales after your Series B.\n\nThank you for your consideration,\n\nJordan Rivera",
    "tailoring_notes": "Led with the Cascade Analytics FastAPI ingestion work because the posting and Northwind's engineering blog emphasize Python/FastAPI event pipelines at scale. Kept the PostgreSQL optimization and CI/CD bullets prominent to hit the must-haves, and surfaced the queuelite project because the company publicly migrated to a Postgres-backed queue. Dropped the Docker containerization bullet from Brightline to keep the resume to one page. All employers, titles, dates, education, and the AWS certification are verbatim from the master profile."
  }
  ```

  8h. Append the following block to the END of `tests/conftest.py` (leave everything Task 1 wrote untouched; the duplicate `pytest`/`Path` imports are harmless if already present above):

  ```python
  from pathlib import Path

  import pytest

  from backend.app.services.claude import ClaudeService

  FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


  @pytest.fixture
  def claude_fake() -> ClaudeService:
      """Fixture-backed ClaudeService; never touches the network."""
      return ClaudeService(fake_mode=True, fixtures_dir=FIXTURES_DIR)
  ```

- [ ] **Step 9: Run test, expect PASS**

  ```powershell
  cd .; pytest tests/test_claude.py -v
  ```

  Expected: `10 passed`.

- [ ] **Step 10: Run the fast suite, then commit cycle 2**

  ```powershell
  cd .; pytest -m "not pdf"
  ```

  Expected: all collected tests pass (Tasks 1–3 suites plus the 10 above), `0 failed`.

  ```powershell
  cd .; git add backend/app/services/claude.py backend/app/fixtures tests/test_claude.py tests/conftest.py; git commit -m "feat: ClaudeService fake/real modes, fixtures, make_claude factory" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

---

### Task 5: Intake (document text extraction + master-profile build)

**Files:**
- Create: `backend/app/services/intake.py`
- Test: `tests/test_intake.py`

**Interfaces:**
- Consumes:
  - `backend.app.services.claude.ClaudeService` and the `claude_fake` pytest fixture (Task 4)
  - `backend/app/fixtures/intake.json` (Task 4)
  - `backend.app.schemas`: `Contact`, `MasterProfile`, `UsageInfo` (Task 2)
  - Libraries: `pypdf`, `python-docx` (imported as `docx`)
- Produces (all in `backend/app/services/intake.py`):
  - `class IntakeResult(BaseModel)` with fields `contact: Contact`, `master_profile: MasterProfile` — the structured-output schema for task `"intake"`; Task 12's `POST /api/profiles/{id}/build` consumes `build_master_profile`, and Task 5's tests validate `intake.json` against this model
  - `INTAKE_SYSTEM: str` — the intake system prompt (verbatim below)
  - `extract_text(filename: str, data: bytes) -> tuple[str, str]` — returns `(kind, text)`; `kind` is `"pdf" | "docx" | "txt"` (the `"paste"` kind is assigned by the API layer in Task 12, not here)
  - `build_master_profile(docs: list[str], claude: ClaudeService) -> tuple[MasterProfile, Contact, UsageInfo]`

- [ ] **Step 1: Write failing tests for extract_text**

  Create `tests/test_intake.py` with exactly this content:

  ```python
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
  ```

  (The monkeypatch works because `intake.py` does `import pypdf` and calls `pypdf.PdfReader(...)` as an attribute lookup at call time — patching the `pypdf` module attribute intercepts it.)

- [ ] **Step 2: Run test, expect FAIL (module does not exist)**

  ```powershell
  cd .; pytest tests/test_intake.py -v
  ```

  Expected failure (collection error):

  ```
  ERROR tests/test_intake.py - ModuleNotFoundError: No module named 'backend.app.services.intake'
  ```

- [ ] **Step 3: Implement extract_text**

  Create `backend/app/services/intake.py` with exactly this content (fully replaced in Step 8 — intentional):

  ```python
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
  ```

- [ ] **Step 4: Run test, expect PASS**

  ```powershell
  cd .; pytest tests/test_intake.py -v
  ```

  Expected: `4 passed`.

- [ ] **Step 5: Commit cycle 1**

  ```powershell
  cd .; git add backend/app/services/intake.py tests/test_intake.py; git commit -m "feat: intake extract_text for pdf/docx/txt uploads" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

- [ ] **Step 6: Write failing tests for IntakeResult and build_master_profile**

  Replace the entire contents of `tests/test_intake.py` with:

  ```python
  """Tests for backend/app/services/intake.py."""
  from __future__ import annotations

  import io

  import docx
  import pypdf

  from backend.app.schemas import Contact, MasterProfile, UsageInfo
  from backend.app.services.intake import (
      INTAKE_SYSTEM,
      IntakeResult,
      build_master_profile,
      extract_text,
  )


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


  def test_intake_result_shape():
      assert set(IntakeResult.model_fields) == {"contact", "master_profile"}


  def test_build_master_profile_returns_fixture_backed_profile(claude_fake):
      docs = [
          "JORDAN RIVERA\nSenior Software Engineer\n...full resume text...",
          "Extra career notes",
      ]
      profile, contact, usage = build_master_profile(docs, claude_fake)
      assert isinstance(profile, MasterProfile)
      assert isinstance(contact, Contact)
      assert contact.name == "Jordan Rivera"
      assert [e.company for e in profile.experiences] == [
          "Cascade Analytics",
          "Brightline Software",
      ]
      assert all(len(e.bullets) == 4 for e in profile.experiences)
      assert all(b.tags for e in profile.experiences for b in e.bullets)
      assert usage == UsageInfo(input_tokens=0, output_tokens=0, cost_usd=0.0)


  def test_build_master_profile_records_intake_call(claude_fake):
      build_master_profile(["Doc A body", "Doc B body"], claude_fake)
      call = claude_fake.calls[-1]
      assert call["task"] == "intake"
      assert call["schema_model_name"] == "IntakeResult"
      assert call["tools"] is None
      assert "--- DOCUMENT 1 ---" in call["user_content"]
      assert "Doc A body" in call["user_content"]
      assert "--- DOCUMENT 2 ---" in call["user_content"]
      assert "Doc B body" in call["user_content"]
      assert call["system"] == INTAKE_SYSTEM
      assert "NEVER invent" in INTAKE_SYSTEM
      assert "VERBATIM" in INTAKE_SYSTEM
  ```

- [ ] **Step 7: Run test, expect FAIL (names not implemented)**

  ```powershell
  cd .; pytest tests/test_intake.py -v
  ```

  Expected failure (collection error):

  ```
  ERROR tests/test_intake.py - ImportError: cannot import name 'INTAKE_SYSTEM' from 'backend.app.services.intake'
  ```

- [ ] **Step 8: Implement IntakeResult, INTAKE_SYSTEM, and build_master_profile**

  Replace the entire contents of `backend/app/services/intake.py` with:

  ```python
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
  ```

- [ ] **Step 9: Run test, expect PASS**

  ```powershell
  cd .; pytest tests/test_intake.py -v
  ```

  Expected: `7 passed`.

- [ ] **Step 10: Run the fast suite, then commit cycle 2**

  ```powershell
  cd .; pytest -m "not pdf"
  ```

  Expected: all collected tests pass (including the 10 from `tests/test_claude.py`), `0 failed`.

  ```powershell
  cd .; git add backend/app/services/intake.py tests/test_intake.py; git commit -m "feat: build_master_profile intake call with IntakeResult schema" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

---

# Section 3 — Stage Services & Pipeline (Tasks 6–9)

All commands run from the project root `.` (each command includes the `cd`; the Python venv is assumed active). Tasks 6–9 assume Tasks 1–5 are complete: schemas (`backend/app/schemas.py`), models (`backend/app/models.py`), config/db (`backend/app/config.py`, `backend/app/db.py`), `ClaudeService` + fixture files under `backend/app/fixtures/` (Task 4), and the intake service with `IntakeResult` (Task 5). `tests/conftest.py` (Task 1) provides the `engine` and `fake_settings` fixtures used below and puts the project root on `sys.path` so `backend.app.*` imports work.

**Local `claude_fake` fixture convention for this section:** each test file below defines its own `claude_fake` fixture built on a `RecordingClaude` subclass of `ClaudeService` that delegates each `structured()` call to the real fake-mode loader and then records the call's full kwargs. Task 4's base `ClaudeService.structured()` already appends one record to `self.calls` per invocation, so the subclass must NOT append a second entry (and must NOT re-initialize `self.calls` in `__init__`): it calls `super().structured(...)` first and then overwrites `self.calls[-1]` with the kwargs dict, keeping exactly one entry per logical call. A module-level fixture shadows any same-named conftest fixture, so these tests do not depend on the exact shape of the `claude_fake` fixture Task 4 appends to conftest — only on the contract-defined `ClaudeService` constructor and `structured()` signature. The class is repeated verbatim in each test file on purpose (no cross-file test imports).

None of this section's tests require Playwright/Chromium — `render_pdf` is monkeypatched in Task 9 — so no `@pytest.mark.pdf` markers appear here and everything runs under `pytest -m "not pdf"`.

---

### Task 6: Fetcher

**Files**

- Create: `backend/app/services/fetcher.py`
- Test: `tests/test_fetcher.py`

**Interfaces**

- Consumes:
  - `FetchResult` from `backend/app/schemas.py` (Task 2) — `status: Literal["fetched", "needs_paste"]`, `text: str = ""`, `reason: str = ""`.
  - `httpx`, `trafilatura`, `respx` from `requirements.txt` (Task 1).
- Produces:
  - `fetch_posting(url: str, timeout: float = 20.0) -> FetchResult` (contract signature).
  - `BROWSER_HEADERS: dict[str, str]` — module constant with a realistic browser UA (internal; nothing else imports it, but the pipeline test suite may reference the module).
  - Behavior contract: HTTP 200 + `content-type` containing `text/html` → `trafilatura.extract(resp.text, include_comments=False)`; non-200 → `needs_paste` with reason `"HTTP <code>"`; any exception → `needs_paste` with reason `str(exc)`; empty/`None` extraction → `needs_paste` with reason `"no extractable text"`; 200 with non-HTML content-type → `needs_paste` with reason `"unsupported content-type: <ct>"`.

**Steps**

- [ ] **Step 1: Verify HTTP/extraction dependencies are installed**

  ```powershell
  cd .; python -c "import httpx, trafilatura, respx; print('deps ok')"
  ```

  Expect `deps ok`. If this fails, run `pip install -r requirements.txt` (Task 1 added `httpx`, `trafilatura`, and `respx` to `requirements.txt`) and re-run.

- [ ] **Step 2: Write the failing tests**

  Create `tests/test_fetcher.py` with exactly this content:

  ```python
  from __future__ import annotations

  import httpx
  import pytest
  import respx

  from backend.app.services.fetcher import fetch_posting

  JOB_URL = "https://jobs.example.com/senior-backend"

  JOB_HTML = """<!doctype html>
  <html>
  <head><title>Senior Backend Engineer - Acme Robotics</title></head>
  <body>
  <header><nav>Home | Careers | About</nav></header>
  <main>
  <article>
  <h1>Senior Backend Engineer</h1>
  <p>Acme Robotics builds the fleet telemetry platform that keeps thousands of
  warehouse robots moving. We are hiring a Senior Backend Engineer to own our
  ingestion pipeline end to end, from device firmware payloads to the analytics
  API our customers rely on every day.</p>
  <p>You will design and operate Python services with FastAPI, model data in
  PostgreSQL, and deploy to AWS with infrastructure as code. You will mentor two
  junior engineers and help shape our engineering culture as the team doubles
  over the next year.</p>
  <p>Requirements: five or more years of professional Python experience, deep
  knowledge of FastAPI or Django, strong SQL and PostgreSQL skills, and
  production experience operating services on AWS.</p>
  <p>Nice to have: Kubernetes, Terraform, Kafka, and prior robotics or IoT
  experience. We offer a hybrid schedule out of Portland, Oregon.</p>
  </article>
  </main>
  <footer>Copyright Acme Robotics</footer>
  </body>
  </html>"""


  @respx.mock
  def test_200_html_returns_fetched_with_extracted_text():
      respx.get(JOB_URL).mock(
          return_value=httpx.Response(
              200, text=JOB_HTML, headers={"content-type": "text/html; charset=utf-8"}
          )
      )
      result = fetch_posting(JOB_URL)
      assert result.status == "fetched"
      assert "fleet telemetry platform" in result.text
      assert result.reason == ""


  @respx.mock
  def test_403_returns_needs_paste_with_http_reason():
      respx.get(JOB_URL).mock(return_value=httpx.Response(403, text="Forbidden"))
      result = fetch_posting(JOB_URL)
      assert result.status == "needs_paste"
      assert result.reason == "HTTP 403"
      assert result.text == ""


  @respx.mock
  def test_connect_error_returns_needs_paste():
      respx.get(JOB_URL).mock(side_effect=httpx.ConnectError("connection refused"))
      result = fetch_posting(JOB_URL)
      assert result.status == "needs_paste"
      assert "connection refused" in result.reason


  @respx.mock
  def test_200_empty_body_returns_needs_paste_no_extractable_text():
      respx.get(JOB_URL).mock(
          return_value=httpx.Response(
              200, text="", headers={"content-type": "text/html"}
          )
      )
      result = fetch_posting(JOB_URL)
      assert result.status == "needs_paste"
      assert result.reason == "no extractable text"


  @respx.mock
  def test_200_non_html_content_type_returns_needs_paste():
      respx.get(JOB_URL).mock(
          return_value=httpx.Response(
              200, text='{"jobs": []}', headers={"content-type": "application/json"}
          )
      )
      result = fetch_posting(JOB_URL)
      assert result.status == "needs_paste"
      assert result.reason.startswith("unsupported content-type:")
  ```

- [ ] **Step 3: Run the tests — expect FAIL**

  ```powershell
  cd .; pytest tests/test_fetcher.py -v
  ```

  Expected failure: collection error `ModuleNotFoundError: No module named 'backend.app.services.fetcher'` (or `ImportError: cannot import name 'fetch_posting'` if an empty placeholder file exists).

- [ ] **Step 4: Write the implementation**

  Create `backend/app/services/fetcher.py` with exactly this content:

  ```python
  from __future__ import annotations

  import httpx
  import trafilatura

  from ..schemas import FetchResult

  BROWSER_HEADERS = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
      ),
      "Accept": (
          "text/html,application/xhtml+xml,application/xml;q=0.9,"
          "image/avif,image/webp,*/*;q=0.8"
      ),
      "Accept-Language": "en-US,en;q=0.9",
  }


  def fetch_posting(url: str, timeout: float = 20.0) -> FetchResult:
      """Fetch a job posting URL and extract readable text.

      Never raises: every failure mode collapses to
      FetchResult(status="needs_paste", reason=...), which the pipeline maps to
      the needs_paste flow (user pastes the posting text manually).
      """
      try:
          with httpx.Client(
              follow_redirects=True, headers=BROWSER_HEADERS, timeout=timeout
          ) as client:
              resp = client.get(url)
      except Exception as exc:  # noqa: BLE001 - any transport error -> paste flow
          return FetchResult(status="needs_paste", reason=str(exc))

      if resp.status_code != 200:
          return FetchResult(status="needs_paste", reason=f"HTTP {resp.status_code}")

      content_type = resp.headers.get("content-type", "")
      if "text/html" not in content_type:
          return FetchResult(
              status="needs_paste",
              reason=f"unsupported content-type: {content_type or 'unknown'}",
          )

      extracted = trafilatura.extract(resp.text, include_comments=False)
      if not extracted:
          return FetchResult(status="needs_paste", reason="no extractable text")

      return FetchResult(status="fetched", text=extracted)
  ```

- [ ] **Step 5: Run the tests — expect PASS**

  ```powershell
  cd .; pytest tests/test_fetcher.py -v
  ```

  Expect all 5 tests to pass.

- [ ] **Step 6: Commit**

  ```powershell
  cd .; git add tests/test_fetcher.py backend/app/services/fetcher.py; git commit -m "feat: posting fetcher with trafilatura extraction and needs_paste fallback" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

---

### Task 7: Research

**Files**

- Create: `backend/app/services/research.py`
- Test: `tests/test_research.py`

**Interfaces**

- Consumes:
  - `ParsedPosting`, `ResearchFindings`, `UsageInfo` from `backend/app/schemas.py` (Task 2).
  - `ClaudeService` from `backend/app/services/claude.py` (Task 4) — constructor `ClaudeService(api_key=None, fake_mode=False, fixtures_dir=None)`, method `structured(*, task, system, user_content, schema_model, tools=None, max_tokens=16000) -> tuple[BaseModel, UsageInfo]`.
  - Fixture files `backend/app/fixtures/parse_posting.json`, `research_standard.json`, `research_deep.json` (Task 4).
- Produces:
  - `parse_posting(raw_text: str, claude: ClaudeService) -> tuple[ParsedPosting, UsageInfo]` (contract signature).
  - `research_company(parsed: ParsedPosting, depth: str, claude: ClaudeService) -> tuple[ResearchFindings, UsageInfo] | None` (contract signature; `"quick"` → `None`).
  - Prompt constants `PARSE_POSTING_SYSTEM`, `RESEARCH_STANDARD_SYSTEM`, `RESEARCH_DEEP_SYSTEM` (verbatim below; Task 9 does not import them but the implementer must keep them module-level).

**Steps**

- [ ] **Step 1: Write the failing test for `parse_posting`**

  Create `tests/test_research.py` with exactly this content:

  ```python
  from __future__ import annotations

  from pathlib import Path

  import pytest

  from backend.app.schemas import ParsedPosting, ResearchFindings, UsageInfo
  from backend.app.services.claude import ClaudeService
  from backend.app.services.research import parse_posting

  FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


  class RecordingClaude(ClaudeService):
      """Fake-mode ClaudeService that records every structured() call's kwargs."""

      def __init__(self, fixtures_dir: Path):
          super().__init__(fake_mode=True, fixtures_dir=fixtures_dir)

      def structured(self, *, task, system, user_content, schema_model,
                     tools=None, max_tokens=16000):
          result = super().structured(
              task=task, system=system, user_content=user_content,
              schema_model=schema_model, tools=tools, max_tokens=max_tokens,
          )
          self.calls[-1] = {
              "task": task,
              "system": system,
              "user_content": user_content,
              "schema_model": schema_model,
              "tools": tools,
              "max_tokens": max_tokens,
          }
          return result


  @pytest.fixture()
  def claude_fake() -> RecordingClaude:
      return RecordingClaude(FIXTURES_DIR)


  RAW_POSTING = (
      "Senior Backend Engineer\n"
      "Acme Robotics - Portland, OR (hybrid)\n\n"
      "Acme Robotics builds fleet telemetry for warehouse robots. We are hiring a "
      "Senior Backend Engineer to own our ingestion pipeline.\n\n"
      "Requirements: 5+ years Python, FastAPI or Django, PostgreSQL, AWS.\n"
      "Nice to have: Kubernetes, Terraform, Kafka.\n"
      "Visit https://acmerobotics.example.com for more.\n"
  )


  def test_parse_posting_returns_fixture_and_records_call(claude_fake):
      parsed, usage = parse_posting(RAW_POSTING, claude_fake)
      assert isinstance(parsed, ParsedPosting)
      assert parsed.title
      assert parsed.company
      assert isinstance(usage, UsageInfo)
      assert usage.input_tokens == 0 and usage.output_tokens == 0
      assert len(claude_fake.calls) == 1
      call = claude_fake.calls[0]
      assert call["task"] == "parse_posting"
      assert call["user_content"] == RAW_POSTING
      assert call["schema_model"] is ParsedPosting
      assert call["tools"] is None
  ```

- [ ] **Step 2: Run the test — expect FAIL**

  ```powershell
  cd .; pytest tests/test_research.py -v
  ```

  Expected failure: collection error `ModuleNotFoundError: No module named 'backend.app.services.research'` (or `ImportError: cannot import name 'parse_posting'` if a placeholder exists).

- [ ] **Step 3: Implement `parse_posting`**

  Create `backend/app/services/research.py` with exactly this content:

  ```python
  from __future__ import annotations

  from ..schemas import ParsedPosting, ResearchFindings, UsageInfo
  from .claude import ClaudeService

  PARSE_POSTING_SYSTEM = """You are a job-posting analyst. You will receive the raw text of a single job posting. Extract a structured summary of it.

  Rules:
  - title: the job title exactly as the posting states it.
  - company: the hiring company's name. If the posting is via a recruiting agency, name the hiring company when identifiable, otherwise the agency.
  - company_domain: the company's primary website domain (bare domain like "acme.com" - no scheme, no path, no "www." prefix) if it appears in the posting or is unambiguous from the company name; otherwise null.
  - must_haves: hard requirements (skills, years of experience, credentials) the posting treats as mandatory.
  - nice_to_haves: preferred or bonus qualifications.
  - keywords: the concrete skills, tools, technologies, and domain terms the posting emphasizes - the vocabulary an applicant-tracking system would scan for.
  - seniority: one short phrase (for example "senior", "mid-level", "staff", "entry-level"), or null if unclear.
  - tone: one short phrase describing the posting's voice (for example "formal corporate", "casual startup", "mission-driven"), or null if unclear.
  - Use only information present in the posting text. Never invent requirements."""


  def parse_posting(raw_text: str, claude: ClaudeService) -> tuple[ParsedPosting, UsageInfo]:
      parsed, usage = claude.structured(
          task="parse_posting",
          system=PARSE_POSTING_SYSTEM,
          user_content=raw_text,
          schema_model=ParsedPosting,
      )
      assert isinstance(parsed, ParsedPosting)
      return parsed, usage
  ```

  Note: the triple-quoted prompt lines above are indented for plan readability; in the actual file the constant starts at column 0 and the prompt lines have no leading indentation (copy the block and dedent so `PARSE_POSTING_SYSTEM = """You are...` begins at column 0). The same applies to every prompt constant in this section.

- [ ] **Step 4: Run the test — expect PASS**

  ```powershell
  cd .; pytest tests/test_research.py -v
  ```

  Expect 1 passing test.

- [ ] **Step 5: Commit the parse cycle**

  ```powershell
  cd .; git add tests/test_research.py backend/app/services/research.py; git commit -m "feat: posting parser (parse_posting) with structured output" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

- [ ] **Step 6: Write the failing tests for `research_company`**

  In `tests/test_research.py`, replace the import line

  ```python
  from backend.app.services.research import parse_posting
  ```

  with

  ```python
  from backend.app.services.research import parse_posting, research_company
  ```

  and append to the end of the file:

  ```python
  PARSED = ParsedPosting(
      title="Senior Backend Engineer",
      company="Acme Robotics",
      company_domain="acmerobotics.example.com",
      must_haves=["5+ years Python", "PostgreSQL"],
      nice_to_haves=["Kubernetes"],
      keywords=["Python", "FastAPI", "AWS"],
      seniority="senior",
      tone="casual startup",
  )


  def test_quick_returns_none_with_zero_calls(claude_fake):
      assert research_company(PARSED, "quick", claude_fake) is None
      assert claude_fake.calls == []


  def test_standard_uses_single_web_fetch_tool_with_allowed_domains(claude_fake):
      result = research_company(PARSED, "standard", claude_fake)
      assert result is not None
      findings, usage = result
      assert isinstance(findings, ResearchFindings)
      assert isinstance(usage, UsageInfo)
      assert len(claude_fake.calls) == 1
      call = claude_fake.calls[0]
      assert call["task"] == "research_standard"
      assert call["schema_model"] is ResearchFindings
      assert isinstance(call["tools"], list) and len(call["tools"]) == 1
      tool = call["tools"][0]
      assert tool["type"] == "web_fetch_20260209"
      assert tool["name"] == "web_fetch"
      assert tool["max_uses"] == 8
      assert tool["allowed_domains"] == ["acmerobotics.example.com"]


  def test_standard_without_domain_omits_allowed_domains(claude_fake):
      parsed = PARSED.model_copy(update={"company_domain": None})
      result = research_company(parsed, "standard", claude_fake)
      assert result is not None
      tool = claude_fake.calls[0]["tools"][0]
      assert "allowed_domains" not in tool


  def test_deep_uses_search_then_fetch_tools(claude_fake):
      result = research_company(PARSED, "deep", claude_fake)
      assert result is not None
      findings, _usage = result
      assert isinstance(findings, ResearchFindings)
      call = claude_fake.calls[0]
      assert call["task"] == "research_deep"
      assert [t["type"] for t in call["tools"]] == [
          "web_search_20260209",
          "web_fetch_20260209",
      ]
      assert [t["max_uses"] for t in call["tools"]] == [8, 8]
  ```

- [ ] **Step 7: Run the tests — expect FAIL**

  ```powershell
  cd .; pytest tests/test_research.py -v
  ```

  Expected failure: collection error `ImportError: cannot import name 'research_company' from 'backend.app.services.research'`.

- [ ] **Step 8: Implement `research_company`**

  Append to the end of `backend/app/services/research.py` (dedent the prompt constants to column 0 as noted in Step 3):

  ```python
  RESEARCH_STANDARD_SYSTEM = """You are researching a company to help tailor a job application. You have the web_fetch tool, restricted to the company's own website. Fetch the homepage and one or two obvious pages (about, products, careers) within the tool's use limit.

  Report only what the company's own site says:
  - mission: how the company describes its purpose, in one or two sentences.
  - products: the main products or services it offers, as short phrases.
  - culture_language: distinctive words and phrases the company uses to describe itself and how it works.
  - tech_stack_signals: technologies the site explicitly mentions, if any.
  - news: leave empty unless the site itself highlights recent announcements.
  - sources: the exact URLs you fetched.

  If a fetch fails or the domain is unavailable, fill in what you can from the posting context and leave the rest empty. Never invent facts."""

  RESEARCH_DEEP_SYSTEM = """You are researching a company in depth to help tailor a high-priority job application. You have web_search and web_fetch tools with limited uses - spend them deliberately: the company's own site first, then recent news, then engineering blog / tech-stack sources.

  Report:
  - mission: the company's stated purpose.
  - products: the main products or services it offers.
  - news: notable items from roughly the last 12 months (funding, launches, partnerships, leadership changes), each as one short sentence.
  - tech_stack_signals: languages, frameworks, and infrastructure mentioned in engineering blogs, job postings, talks, or public repositories.
  - culture_language: distinctive vocabulary the company uses about itself, its values, and how it works.
  - sources: the URL of every page you actually used. Every claim above must be traceable to one of these sources. Never invent facts or URLs."""


  def _research_user_content(parsed: ParsedPosting) -> str:
      return (
          "Company: " + parsed.company + "\n"
          "Company domain: " + (parsed.company_domain or "unknown") + "\n"
          "Role being applied for: " + parsed.title + "\n\n"
          "Parsed posting JSON:\n" + parsed.model_dump_json(indent=2)
      )


  def research_company(
      parsed: ParsedPosting, depth: str, claude: ClaudeService
  ) -> tuple[ResearchFindings, UsageInfo] | None:
      if depth == "quick":
          return None
      if depth == "standard":
          tool: dict = {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8}
          if parsed.company_domain:
              tool["allowed_domains"] = [parsed.company_domain]
          findings, usage = claude.structured(
              task="research_standard",
              system=RESEARCH_STANDARD_SYSTEM,
              user_content=_research_user_content(parsed),
              schema_model=ResearchFindings,
              tools=[tool],
          )
          assert isinstance(findings, ResearchFindings)
          return findings, usage
      if depth == "deep":
          tools: list[dict] = [
              {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
              {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8},
          ]
          findings, usage = claude.structured(
              task="research_deep",
              system=RESEARCH_DEEP_SYSTEM,
              user_content=_research_user_content(parsed),
              schema_model=ResearchFindings,
              tools=tools,
          )
          assert isinstance(findings, ResearchFindings)
          return findings, usage
      raise ValueError(f"Unknown research depth: {depth!r}")
  ```

- [ ] **Step 9: Run the tests — expect PASS**

  ```powershell
  cd .; pytest tests/test_research.py -v
  ```

  Expect 5 passing tests.

- [ ] **Step 10: Commit the research cycle**

  ```powershell
  cd .; git add tests/test_research.py backend/app/services/research.py; git commit -m "feat: company research service with quick/standard/deep depth dial" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

---

### Task 8: Tailor

**Files**

- Create: `backend/app/services/tailor.py`
- Test: `tests/test_tailor.py`

**Interfaces**

- Consumes:
  - `Contact`, `MasterProfile`, `MPExperience`, `TaggedBullet`, `ParsedPosting`, `ResearchFindings`, `ResumeDoc`, `TailorResult`, `UsageInfo` from `backend/app/schemas.py` (Task 2).
  - `ClaudeService` from `backend/app/services/claude.py` (Task 4).
  - `IntakeResult` from `backend/app/services/intake.py` (Task 5) — `class IntakeResult(BaseModel): contact: Contact; master_profile: MasterProfile`.
  - Fixture files `backend/app/fixtures/intake.json` and `backend/app/fixtures/tailor.json` (Task 4). The contract's fixture invariant — the `tailor.json` resume uses only companies/titles/dates/education/certifications present in `intake.json`'s master profile — is enforced by this task's tests.
- Produces:
  - `tailor_application(profile: MasterProfile, contact: Contact, parsed: ParsedPosting, research: ResearchFindings | None, template: str, claude: ClaudeService, feedback: str | None = None) -> tuple[TailorResult, UsageInfo]` (contract signature). One `structured()` call, `task="tailor"`, `schema_model=TailorResult`, `max_tokens=32000` (>16000 so real mode streams per the ClaudeService contract).
  - `verify_truthfulness(resume: ResumeDoc, profile: MasterProfile) -> list[str]` (contract signature): every `ExperienceItem` `(company, role, start, end)` must exactly match an `MPExperience` `(company, title, start, end)`; every `EducationItem` `(institution, credential)` and every `CertificationItem` `name` must exist in the master profile. Returns violation strings; empty list = pass.
  - `TAILOR_SYSTEM` prompt constant (verbatim below).
  - User-content markers Task 9's tests rely on: the assembled `user_content` contains the literal blocks `MASTER PROFILE`, `RESEARCH FINDINGS:` (with the literal word `none` when no research), `TEMPLATE: <name> (structural hint: projects-forward|experience-first)`, and — only when feedback is given — `REGENERATION FEEDBACK`.

**Steps**

- [ ] **Step 1: Write the failing tests for `tailor_application`**

  Create `tests/test_tailor.py` with exactly this content:

  ```python
  from __future__ import annotations

  from pathlib import Path

  import pytest

  from backend.app.schemas import (
      Contact,
      MasterProfile,
      MPExperience,
      ParsedPosting,
      ResearchFindings,
      TaggedBullet,
      TailorResult,
      UsageInfo,
  )
  from backend.app.services.claude import ClaudeService
  from backend.app.services.tailor import tailor_application

  FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


  class RecordingClaude(ClaudeService):
      """Fake-mode ClaudeService that records every structured() call's kwargs."""

      def __init__(self, fixtures_dir: Path):
          super().__init__(fake_mode=True, fixtures_dir=fixtures_dir)

      def structured(self, *, task, system, user_content, schema_model,
                     tools=None, max_tokens=16000):
          result = super().structured(
              task=task, system=system, user_content=user_content,
              schema_model=schema_model, tools=tools, max_tokens=max_tokens,
          )
          self.calls[-1] = {
              "task": task,
              "system": system,
              "user_content": user_content,
              "schema_model": schema_model,
              "tools": tools,
              "max_tokens": max_tokens,
          }
          return result


  @pytest.fixture()
  def claude_fake() -> RecordingClaude:
      return RecordingClaude(FIXTURES_DIR)


  CONTACT = Contact(name="Test Person", email="tp@example.com")

  PROFILE = MasterProfile(
      summary_notes="Backend engineer, 8 years, Python and cloud infrastructure.",
      experiences=[
          MPExperience(
              company="Acme Robotics",
              title="Senior Backend Engineer",
              start="2021-03",
              end=None,
              location="Portland, OR",
              bullets=[
                  TaggedBullet(
                      text="Built telemetry ingestion services in Python",
                      tags=["python", "backend"],
                  )
              ],
          )
      ],
  )

  PARSED = ParsedPosting(
      title="Staff Engineer",
      company="Initech",
      company_domain="initech.example.com",
      must_haves=["Python", "PostgreSQL"],
      keywords=["Python", "FastAPI"],
  )


  def test_tailor_returns_result_and_records_one_call(claude_fake):
      result, usage = tailor_application(PROFILE, CONTACT, PARSED, None, "slate", claude_fake)
      assert isinstance(result, TailorResult)
      assert isinstance(usage, UsageInfo)
      assert len(claude_fake.calls) == 1
      call = claude_fake.calls[0]
      assert call["task"] == "tailor"
      assert call["schema_model"] is TailorResult
      assert call["max_tokens"] == 32000
      assert call["tools"] is None
      assert "TRUTHFULNESS RUBRIC" in call["system"]
      assert "NEVER invent employers" in call["system"]


  def test_user_content_assembly_without_research(claude_fake):
      tailor_application(PROFILE, CONTACT, PARSED, None, "slate", claude_fake)
      uc = claude_fake.calls[-1]["user_content"]
      assert "MASTER PROFILE" in uc
      assert "Test Person" in uc
      assert "Acme Robotics" in uc
      assert "RESEARCH FINDINGS:\nnone" in uc
      assert "experience-first" in uc
      assert "REGENERATION FEEDBACK" not in uc


  def test_terminal_template_gets_projects_forward_hint(claude_fake):
      tailor_application(PROFILE, CONTACT, PARSED, None, "terminal", claude_fake)
      assert "projects-forward" in claude_fake.calls[-1]["user_content"]


  def test_research_findings_included_when_provided(claude_fake):
      findings = ResearchFindings(
          mission="Make warehouse robots reliable",
          sources=["https://initech.example.com/about"],
      )
      tailor_application(PROFILE, CONTACT, PARSED, findings, "slate", claude_fake)
      uc = claude_fake.calls[-1]["user_content"]
      assert "Make warehouse robots reliable" in uc
      assert "RESEARCH FINDINGS:\nnone" not in uc


  def test_feedback_lands_in_user_content(claude_fake):
      tailor_application(
          PROFILE, CONTACT, PARSED, None, "slate", claude_fake,
          feedback="Lead with the migration project",
      )
      uc = claude_fake.calls[-1]["user_content"]
      assert "REGENERATION FEEDBACK" in uc
      assert "Lead with the migration project" in uc
  ```

- [ ] **Step 2: Run the tests — expect FAIL**

  ```powershell
  cd .; pytest tests/test_tailor.py -v
  ```

  Expected failure: collection error `ModuleNotFoundError: No module named 'backend.app.services.tailor'` (or `ImportError: cannot import name 'tailor_application'` if a placeholder exists).

- [ ] **Step 3: Implement `tailor_application`**

  Create `backend/app/services/tailor.py` with exactly this content (dedent the `TAILOR_SYSTEM` prompt to column 0 in the actual file, as in Task 7):

  ```python
  from __future__ import annotations

  from ..schemas import (
      Contact,
      MasterProfile,
      ParsedPosting,
      ResearchFindings,
      TailorResult,
      UsageInfo,
  )
  from .claude import ClaudeService

  TAILOR_SYSTEM = """You are an expert resume writer producing a tailored resume and cover letter for one specific job application.

  TRUTHFULNESS RUBRIC (absolute, non-negotiable):
  - You may SELECT which experiences, projects, and bullets to include.
  - You may REORDER sections, roles, and bullets to shift emphasis.
  - You may REPHRASE bullet text for clarity and impact.
  - You may do NOTHING else. NEVER invent employers, job titles, employment dates, degrees, certifications, tools, or metrics. Every company, role, start date, end date, institution, credential, and certification in your output must appear exactly as it does in the master profile. Every factual claim in every bullet must be supported by the master profile.
  - Mirror the posting's vocabulary only where the master profile factually supports it. If the posting asks for something the candidate does not have, omit it - never fabricate it.

  RESUME:
  - Select the experiences, projects, and bullets most relevant to the parsed posting; trim what does not serve this application.
  - headline: one line positioning the candidate for this specific role.
  - summary: two to four sentences specific to this candidate and this posting - no generic filler.
  - Respect the template structural hint given in the input: the "terminal" template is projects-forward (a Projects section leads, before Experience); every other template is experience-first (Experience leads). Include Skills and Education sections whenever the master profile has content for them.

  COVER LETTER (markdown, 3-5 short paragraphs):
  - Open specific. When research findings are provided, the first paragraph must reference a concrete finding (mission, product, news item, or culture language). When no research is provided, the first paragraph must reference specific language from the posting itself.
  - No boilerplate openings ("I am writing to apply...", "I was excited to see...").
  - Ground every claim in facts from the master profile.

  TAILORING NOTES:
  - In tailoring_notes, briefly explain what you chose to emphasize and why, referencing the posting's requirements.

  If a REGENERATION FEEDBACK block is present in the input, treat it as the highest-priority instruction that is consistent with the truthfulness rubric."""


  def _structural_hint(template: str) -> str:
      return "projects-forward" if template == "terminal" else "experience-first"


  def tailor_application(
      profile: MasterProfile,
      contact: Contact,
      parsed: ParsedPosting,
      research: ResearchFindings | None,
      template: str,
      claude: ClaudeService,
      feedback: str | None = None,
  ) -> tuple[TailorResult, UsageInfo]:
      parts = [
          "MASTER PROFILE (single source of truth - the only facts you may use):\n"
          + profile.model_dump_json(indent=2),
          "CONTACT (copy into resume.contact unchanged):\n"
          + contact.model_dump_json(indent=2),
          "PARSED JOB POSTING:\n" + parsed.model_dump_json(indent=2),
          "RESEARCH FINDINGS:\n"
          + (research.model_dump_json(indent=2) if research is not None else "none"),
          "TEMPLATE: " + template + " (structural hint: " + _structural_hint(template) + ")",
      ]
      if feedback:
          parts.append(
              "REGENERATION FEEDBACK (apply within the truthfulness rubric):\n" + feedback
          )
      result, usage = claude.structured(
          task="tailor",
          system=TAILOR_SYSTEM,
          user_content="\n\n".join(parts),
          schema_model=TailorResult,
          max_tokens=32000,
      )
      assert isinstance(result, TailorResult)
      return result, usage
  ```

- [ ] **Step 4: Run the tests — expect PASS**

  ```powershell
  cd .; pytest tests/test_tailor.py -v
  ```

  Expect 5 passing tests.

- [ ] **Step 5: Commit the tailor cycle**

  ```powershell
  cd .; git add tests/test_tailor.py backend/app/services/tailor.py; git commit -m "feat: tailor service with verbatim truthfulness rubric prompt" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

- [ ] **Step 6: Write the failing tests for `verify_truthfulness` (fixture invariant)**

  In `tests/test_tailor.py`, replace the import line

  ```python
  from backend.app.services.tailor import tailor_application
  ```

  with

  ```python
  from backend.app.services.tailor import tailor_application, verify_truthfulness
  ```

  and append to the end of the file:

  ```python
  def _load_intake(claude_fake):
      from backend.app.services.intake import IntakeResult

      intake, _usage = claude_fake.structured(
          task="intake", system="fixture-load", user_content="fixture-load",
          schema_model=IntakeResult,
      )
      return intake


  def test_fixture_tailor_result_passes_truthfulness(claude_fake):
      intake = _load_intake(claude_fake)
      result, _usage = tailor_application(
          intake.master_profile, intake.contact, PARSED, None, "slate", claude_fake
      )
      assert verify_truthfulness(result.resume, intake.master_profile) == []


  def test_single_changed_company_yields_exactly_one_violation(claude_fake):
      intake = _load_intake(claude_fake)
      result, _usage = tailor_application(
          intake.master_profile, intake.contact, PARSED, None, "slate", claude_fake
      )
      bad = result.resume.model_copy(deep=True)
      experience_sections = [s for s in bad.sections if s.type == "experience"]
      assert experience_sections and experience_sections[0].items
      experience_sections[0].items[0].company = "Fake Corp"
      violations = verify_truthfulness(bad, intake.master_profile)
      assert len(violations) == 1
      assert "Fake Corp" in violations[0]
  ```

  Note: `test_fixture_tailor_result_passes_truthfulness` loads both `intake.json` and `tailor.json` through the fake service, which makes the contract's fixture invariant an executable test — if Task 4's `tailor.json` resume names any employer/title/date/education/certification absent from `intake.json`'s master profile, this test fails and the *fixtures* must be corrected (not this verifier).

- [ ] **Step 7: Run the tests — expect FAIL**

  ```powershell
  cd .; pytest tests/test_tailor.py -v
  ```

  Expected failure: collection error `ImportError: cannot import name 'verify_truthfulness' from 'backend.app.services.tailor'`.

- [ ] **Step 8: Implement `verify_truthfulness`**

  First, in `backend/app/services/tailor.py`, replace the schemas import block

  ```python
  from ..schemas import (
      Contact,
      MasterProfile,
      ParsedPosting,
      ResearchFindings,
      TailorResult,
      UsageInfo,
  )
  ```

  with

  ```python
  from ..schemas import (
      Contact,
      MasterProfile,
      ParsedPosting,
      ResearchFindings,
      ResumeDoc,
      TailorResult,
      UsageInfo,
  )
  ```

  Then append to the end of the file:

  ```python
  def verify_truthfulness(resume: ResumeDoc, profile: MasterProfile) -> list[str]:
      """Structural guard against invented facts.

      Exact-match rules (contract): every ExperienceItem (company, role, start, end)
      must match an MPExperience (company+title exact, start/end exact); every
      EducationItem must match a master-profile education entry on
      (institution, credential); every CertificationItem must match a
      master-profile certification by name. Returns human-readable violation
      strings; an empty list means the resume passes.
      """
      violations: list[str] = []
      allowed_experiences = {
          (e.company, e.title, e.start, e.end) for e in profile.experiences
      }
      allowed_education = {(e.institution, e.credential) for e in profile.education}
      allowed_certifications = {c.name for c in profile.certifications}

      for section in resume.sections:
          if section.type == "experience":
              for item in section.items:
                  key = (item.company, item.role, item.start, item.end)
                  if key not in allowed_experiences:
                      violations.append(
                          f"Experience '{item.role}' at '{item.company}' "
                          f"({item.start} to {item.end or 'present'}) does not match "
                          "any master-profile experience"
                      )
          elif section.type == "education":
              for item in section.items:
                  if (item.institution, item.credential) not in allowed_education:
                      violations.append(
                          f"Education '{item.credential}' at '{item.institution}' "
                          "does not match any master-profile education entry"
                      )
          elif section.type == "certifications":
              for item in section.items:
                  if item.name not in allowed_certifications:
                      violations.append(
                          f"Certification '{item.name}' does not match any "
                          "master-profile certification"
                      )
      return violations
  ```

- [ ] **Step 9: Run the tests — expect PASS**

  ```powershell
  cd .; pytest tests/test_tailor.py -v
  ```

  Expect 7 passing tests. If `test_fixture_tailor_result_passes_truthfulness` fails, fix the fixture files (`backend/app/fixtures/tailor.json` must only use companies/titles/dates/education/certifications present in `backend/app/fixtures/intake.json`) — do not weaken the verifier.

- [ ] **Step 10: Commit the truthfulness cycle**

  ```powershell
  cd .; git add tests/test_tailor.py backend/app/services/tailor.py; git commit -m "feat: structural truthfulness verifier enforcing fixture invariant" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

---

### Task 9: Pipeline

> **Ordering prerequisite:** this task's tests exercise the real render service and templates — only `render_pdf` is faked. `backend/app/services/render.py` (Task 10) and the template files under `backend/templates/` (Task 11) MUST be implemented and committed before running this task's test steps. If executing the plan strictly in task-number order, defer Task 9 until Tasks 10–11 are done, then return here. (`pipeline.py` imports `render` at module level, so even collection fails without it.)

**Files**

- Create: `backend/app/services/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces**

- Consumes:
  - `get_settings`, `load_user_settings` from `backend/app/config.py`; `get_engine` from `backend/app/db.py` (Task 1).
  - `engine` and `fake_settings` pytest fixtures from `tests/conftest.py` (Task 1): `engine` is a tmp-file SQLite engine with tables created; `fake_settings` is a `Settings(anthropic_api_key=None, data_dir=tmp_path, fake_mode=True, host="127.0.0.1", port=8547)`.
  - Entities + helpers from `backend/app/models.py` (Task 3): `Profile`, `Job`, `ResearchBrief`, `Application`, `ApplicationVersion`, `get_contact`, `set_contact`, `get_master_profile`, `set_master_profile`, `get_parsed`, `set_parsed`, `get_findings`.
  - `ClaudeError`, `ClaudeService`, `make_claude` from `backend/app/services/claude.py` (Task 4); `IntakeResult` from `backend/app/services/intake.py` (Task 5).
  - `fetch_posting` via module attribute `fetcher.fetch_posting` (Task 6 — accessed through the module so tests can monkeypatch it).
  - `parse_posting`, `research_company` (Task 7); `tailor_application`, `verify_truthfulness` (Task 8).
  - `render.export_application(application_id, resume, cover_md, contact, template, data_dir, page_size="Letter") -> Path` and `render.render_pdf(html, out_path, page_size="Letter")` (Task 10 — see ordering prerequisite; `export_application` must resolve `render_pdf` from module globals at call time so a monkeypatch on `backend.app.services.render.render_pdf` takes effect).
- Produces (contract signatures extended with an optional `claude` injection parameter — callers that pass only `app_id`, like the Task 12 API layer, are unaffected):
  - `process_application(app_id: int, engine=None, claude: ClaudeService | None = None) -> None` — defaults: `engine = get_engine()`, `claude = make_claude(get_settings())`. Stage machine `queued -> fetching -> researching -> tailoring -> rendering -> ready`, committing status after every transition so pollers see progress. Fetch stage is skipped when `Job.raw_text` is already set. A `needs_paste` fetch result sets `Job.fetch_status = "needs_paste"` AND `Application.status = "needs_paste"` and returns. Research stage stores a `ResearchBrief` row (skipped for depth `quick`). Tailor stage runs `verify_truthfulness` and raises `ClaudeError` listing the violations on failure. Usage is accumulated onto the `Application` (input_tokens/output_tokens/cost_usd). An `ApplicationVersion` snapshot is written after each successful tailor. Render stage calls `render.export_application` and stores `Application.export_dir`. Any exception → `status="error"`, `error_message=str(exc)`.
  - `resume_after_paste(app_id: int, text: str, engine=None, claude: ClaudeService | None = None) -> None` — sets `Job.raw_text = text`, `Job.fetch_status = "pasted"`, then continues the pipeline from the researching stage.
  - `regenerate_application(app_id: int, feedback: str, engine=None, claude: ClaudeService | None = None) -> None` — `version += 1`, re-tailors with the feedback (reusing the latest stored `ResearchBrief` findings when present), snapshots a new `ApplicationVersion`, re-renders.

**Steps**

- [ ] **Step 1: Write the failing tests for `process_application`**

  Create `tests/test_pipeline.py` with exactly this content:

  ```python
  from __future__ import annotations

  from pathlib import Path

  import pytest
  from sqlmodel import Session, select

  from backend.app.models import (
      Application,
      ApplicationVersion,
      Job,
      Profile,
      ResearchBrief,
      set_contact,
      set_master_profile,
  )
  from backend.app.schemas import FetchResult
  from backend.app.services import fetcher, pipeline, render
  from backend.app.services.claude import ClaudeService
  from backend.app.services.intake import IntakeResult

  FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"

  POSTING_TEXT = (
      "Senior Backend Engineer at Acme Robotics. Build the fleet telemetry "
      "platform. Requirements: 5+ years Python, FastAPI, PostgreSQL, AWS. "
      "Nice to have: Kubernetes, Terraform."
  )


  class RecordingClaude(ClaudeService):
      """Fake-mode ClaudeService that records every structured() call's kwargs."""

      def __init__(self, fixtures_dir: Path):
          super().__init__(fake_mode=True, fixtures_dir=fixtures_dir)

      def structured(self, *, task, system, user_content, schema_model,
                     tools=None, max_tokens=16000):
          result = super().structured(
              task=task, system=system, user_content=user_content,
              schema_model=schema_model, tools=tools, max_tokens=max_tokens,
          )
          self.calls[-1] = {
              "task": task,
              "system": system,
              "user_content": user_content,
              "schema_model": schema_model,
              "tools": tools,
              "max_tokens": max_tokens,
          }
          return result


  @pytest.fixture()
  def claude_fake() -> RecordingClaude:
      return RecordingClaude(FIXTURES_DIR)


  @pytest.fixture()
  def pipeline_settings(fake_settings, monkeypatch):
      """Route pipeline.get_settings() to the tmp-dir Settings from conftest."""
      monkeypatch.setattr(pipeline, "get_settings", lambda: fake_settings)
      return fake_settings


  @pytest.fixture()
  def fetched_ok(monkeypatch):
      monkeypatch.setattr(
          fetcher, "fetch_posting",
          lambda url, timeout=20.0: FetchResult(status="fetched", text=POSTING_TEXT),
      )


  @pytest.fixture()
  def pdf_faked(monkeypatch):
      """Replace Playwright PDF rendering with a fake PDF byte-write.

      HTML/txt exports stay real; only chromium is avoided.
      """

      def _fake_pdf(html: str, out_path, page_size: str = "Letter") -> None:
          out = Path(out_path)
          out.parent.mkdir(parents=True, exist_ok=True)
          out.write_bytes(b"%PDF-1.4 fake")

      monkeypatch.setattr(render, "render_pdf", _fake_pdf)


  def seed_application(engine, claude_fake, depth="standard", template="slate") -> int:
      """Create Profile (from the intake fixture) + Job + queued Application."""
      intake, _usage = claude_fake.structured(
          task="intake", system="seed", user_content="seed", schema_model=IntakeResult
      )
      with Session(engine) as session:
          profile = Profile(name="Test User")
          set_contact(profile, intake.contact)
          set_master_profile(profile, intake.master_profile)
          session.add(profile)
          session.commit()
          session.refresh(profile)
          job = Job(url="https://jobs.example.com/senior-backend", depth=depth)
          session.add(job)
          session.commit()
          session.refresh(job)
          app = Application(profile_id=profile.id, job_id=job.id, template=template)
          session.add(app)
          session.commit()
          session.refresh(app)
          return app.id


  def test_process_application_reaches_ready_with_exports(
      engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
  ):
      app_id = seed_application(engine, claude_fake, depth="standard")
      pipeline.process_application(app_id, engine=engine, claude=claude_fake)

      with Session(engine) as session:
          app = session.get(Application, app_id)
          assert app.status == "ready"
          assert app.error_message is None
          assert app.version == 1
          assert app.resume_json
          assert app.cover_letter_md
          assert isinstance(app.input_tokens, int)
          assert isinstance(app.output_tokens, int)
          assert isinstance(app.cost_usd, float)
          assert app.export_dir
          export_dir = Path(app.export_dir)

          job = session.get(Job, app.job_id)
          assert job.fetch_status == "fetched"
          assert job.raw_text == POSTING_TEXT
          assert job.parsed_json

          briefs = session.exec(
              select(ResearchBrief).where(ResearchBrief.job_id == job.id)
          ).all()
          assert len(briefs) == 1

          versions = session.exec(
              select(ApplicationVersion).where(
                  ApplicationVersion.application_id == app_id
              )
          ).all()
          assert len(versions) == 1
          assert versions[0].version == 1

      assert (export_dir / "resume.html").read_text(encoding="utf-8")
      assert (export_dir / "resume.txt").read_text(encoding="utf-8")
      assert (export_dir / "cover_letter.txt").read_text(encoding="utf-8")
      assert (export_dir / "resume.pdf").read_bytes() == b"%PDF-1.4 fake"
      assert (export_dir / "cover_letter.pdf").read_bytes() == b"%PDF-1.4 fake"

      tasks = [c["task"] for c in claude_fake.calls]
      assert tasks == ["intake", "parse_posting", "research_standard", "tailor"]


  def test_quick_depth_skips_research(
      engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
  ):
      app_id = seed_application(engine, claude_fake, depth="quick")
      pipeline.process_application(app_id, engine=engine, claude=claude_fake)

      with Session(engine) as session:
          app = session.get(Application, app_id)
          assert app.status == "ready"
          job = session.get(Job, app.job_id)
          briefs = session.exec(
              select(ResearchBrief).where(ResearchBrief.job_id == job.id)
          ).all()
          assert briefs == []

      tasks = [c["task"] for c in claude_fake.calls]
      assert "research_standard" not in tasks
      assert "research_deep" not in tasks


  def test_needs_paste_short_circuits(
      engine, claude_fake, pipeline_settings, pdf_faked, monkeypatch
  ):
      monkeypatch.setattr(
          fetcher, "fetch_posting",
          lambda url, timeout=20.0: FetchResult(status="needs_paste", reason="HTTP 403"),
      )
      app_id = seed_application(engine, claude_fake)
      pipeline.process_application(app_id, engine=engine, claude=claude_fake)

      with Session(engine) as session:
          app = session.get(Application, app_id)
          assert app.status == "needs_paste"
          job = session.get(Job, app.job_id)
          assert job.fetch_status == "needs_paste"

      tasks = [c["task"] for c in claude_fake.calls]
      assert tasks == ["intake"]  # only the seeding call; no pipeline API calls


  def test_truthfulness_failure_sets_error(
      engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
  ):
      monkeypatch.setattr(
          pipeline, "verify_truthfulness",
          lambda resume, profile: [
              "Experience 'CTO' at 'Fake Corp' (2020 to 2024) does not match "
              "any master-profile experience"
          ],
      )
      app_id = seed_application(engine, claude_fake)
      pipeline.process_application(app_id, engine=engine, claude=claude_fake)

      with Session(engine) as session:
          app = session.get(Application, app_id)
          assert app.status == "error"
          assert "Fake Corp" in (app.error_message or "")
  ```

- [ ] **Step 2: Run the tests — expect FAIL**

  ```powershell
  cd .; pytest tests/test_pipeline.py -v
  ```

  Expected failure: collection error `ImportError: cannot import name 'pipeline' from 'backend.app.services'` / `ModuleNotFoundError: No module named 'backend.app.services.pipeline'`. (If the error instead mentions `render`, Tasks 10–11 are not done yet — see the ordering prerequisite above.)

- [ ] **Step 3: Implement the stage machine (`process_application`)**

  Create `backend/app/services/pipeline.py` with exactly this content (the `select`, `get_parsed`, and `get_findings` imports are used by the functions added in Step 6):

  ```python
  from __future__ import annotations

  from datetime import datetime

  from sqlmodel import Session, select

  from ..config import get_settings, load_user_settings
  from ..db import get_engine
  from ..models import (
      Application,
      ApplicationVersion,
      Job,
      Profile,
      ResearchBrief,
      get_contact,
      get_findings,
      get_master_profile,
      get_parsed,
      set_parsed,
  )
  from ..schemas import (
      Contact,
      MasterProfile,
      ParsedPosting,
      ResearchFindings,
      UsageInfo,
  )
  from . import fetcher, render
  from .claude import ClaudeError, ClaudeService, make_claude
  from .research import parse_posting, research_company
  from .tailor import tailor_application, verify_truthfulness


  def _set_status(session: Session, app: Application, status: str,
                  error_message: str | None = None) -> None:
      """Commit a status change immediately so API pollers see progress."""
      app.status = status
      app.error_message = error_message
      app.updated_at = datetime.utcnow()
      session.add(app)
      session.commit()
      session.refresh(app)


  def _add_usage(app: Application, usage: UsageInfo) -> None:
      app.input_tokens += usage.input_tokens
      app.output_tokens += usage.output_tokens
      app.cost_usd = round(app.cost_usd + usage.cost_usd, 6)


  def _run_from_research(session: Session, app: Application, job: Job,
                         claude: ClaudeService) -> None:
      """Researching -> tailoring -> rendering -> ready (Job.raw_text is set)."""
      profile = session.get(Profile, app.profile_id)
      if profile is None:
          raise ClaudeError(f"Profile {app.profile_id} not found")
      master = get_master_profile(profile)
      contact = get_contact(profile)

      _set_status(session, app, "researching")
      parsed, parse_usage = parse_posting(job.raw_text or "", claude)
      set_parsed(job, parsed)
      _add_usage(app, parse_usage)
      session.add(job)
      session.add(app)
      session.commit()

      findings: ResearchFindings | None = None
      research = research_company(parsed, job.depth, claude)
      if research is not None:  # depth "quick" returns None: no brief row
          findings, research_usage = research
          brief = ResearchBrief(
              job_id=job.id,
              depth=job.depth,
              findings_json=findings.model_dump_json(),
              input_tokens=research_usage.input_tokens,
              output_tokens=research_usage.output_tokens,
              cost_usd=research_usage.cost_usd,
          )
          _add_usage(app, research_usage)
          session.add(brief)
          session.add(app)
          session.commit()

      _tailor_and_render(session, app, master, contact, parsed, findings,
                         claude, feedback=None)


  def _tailor_and_render(session: Session, app: Application,
                         master: MasterProfile, contact: Contact,
                         parsed: ParsedPosting,
                         findings: ResearchFindings | None,
                         claude: ClaudeService, feedback: str | None) -> None:
      _set_status(session, app, "tailoring")
      result, usage = tailor_application(
          master, contact, parsed, findings, app.template, claude,
          feedback=feedback,
      )
      violations = verify_truthfulness(result.resume, master)
      if violations:
          raise ClaudeError(
              "Truthfulness check failed: " + "; ".join(violations)
          )

      app.resume_json = result.resume.model_dump_json()
      app.cover_letter_md = result.cover_letter_md
      app.tailoring_notes = result.tailoring_notes
      _add_usage(app, usage)
      session.add(app)
      session.commit()
      session.refresh(app)

      snapshot = ApplicationVersion(
          application_id=app.id,
          version=app.version,
          resume_json=app.resume_json or "{}",
          cover_letter_md=app.cover_letter_md or "",
          tailoring_notes=app.tailoring_notes or "",
      )
      session.add(snapshot)
      session.commit()

      _set_status(session, app, "rendering")
      settings = get_settings()
      user_settings = load_user_settings(settings.data_dir)
      page_size = (user_settings or {}).get("page_size", "Letter")
      export_dir = render.export_application(
          app.id, result.resume, result.cover_letter_md, contact,
          app.template, settings.data_dir, page_size=page_size,
      )
      app.export_dir = str(export_dir)
      session.add(app)
      session.commit()

      _set_status(session, app, "ready")


  def process_application(app_id: int, engine=None,
                          claude: ClaudeService | None = None) -> None:
      """Run the full stage machine for one application (synchronous).

      queued -> fetching -> researching -> tailoring -> rendering -> ready.
      Status is committed at every transition. needs_paste short-circuits;
      any exception lands the application in status="error".
      """
      engine = engine if engine is not None else get_engine()
      claude = claude if claude is not None else make_claude(get_settings())
      with Session(engine) as session:
          app = session.get(Application, app_id)
          if app is None:
              return
          try:
              job = session.get(Job, app.job_id)
              if job is None:
                  raise ClaudeError(f"Job {app.job_id} not found")
              if not job.raw_text:  # skip fetch when text was pasted up front
                  _set_status(session, app, "fetching")
                  fetch_result = fetcher.fetch_posting(job.url)
                  if fetch_result.status == "needs_paste":
                      job.fetch_status = "needs_paste"
                      session.add(job)
                      session.commit()
                      _set_status(session, app, "needs_paste")
                      return
                  job.raw_text = fetch_result.text
                  job.fetch_status = "fetched"
                  session.add(job)
                  session.commit()
              _run_from_research(session, app, job, claude)
          except Exception as exc:  # noqa: BLE001 - every failure is visible state
              _set_status(session, app, "error", error_message=str(exc))
  ```

- [ ] **Step 4: Run the tests — expect PASS**

  ```powershell
  cd .; pytest tests/test_pipeline.py -v
  ```

  Expect 4 passing tests.

- [ ] **Step 5: Commit the stage-machine cycle**

  ```powershell
  cd .; git add tests/test_pipeline.py backend/app/services/pipeline.py; git commit -m "feat: application pipeline stage machine with per-stage status commits" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

- [ ] **Step 6: Write the failing tests for `resume_after_paste` and `regenerate_application`**

  Append to the end of `tests/test_pipeline.py`:

  ```python
  def test_resume_after_paste_completes_needs_paste_application(
      engine, claude_fake, pipeline_settings, pdf_faked, monkeypatch
  ):
      monkeypatch.setattr(
          fetcher, "fetch_posting",
          lambda url, timeout=20.0: FetchResult(status="needs_paste", reason="HTTP 403"),
      )
      app_id = seed_application(engine, claude_fake)
      pipeline.process_application(app_id, engine=engine, claude=claude_fake)

      with Session(engine) as session:
          assert session.get(Application, app_id).status == "needs_paste"

      pipeline.resume_after_paste(app_id, POSTING_TEXT, engine=engine, claude=claude_fake)

      with Session(engine) as session:
          app = session.get(Application, app_id)
          assert app.status == "ready"
          assert app.export_dir
          job = session.get(Job, app.job_id)
          assert job.fetch_status == "pasted"
          assert job.raw_text == POSTING_TEXT


  def test_regenerate_bumps_version_and_snapshots(
      engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
  ):
      app_id = seed_application(engine, claude_fake)
      pipeline.process_application(app_id, engine=engine, claude=claude_fake)
      pipeline.regenerate_application(
          app_id, "Lead with the migration project", engine=engine, claude=claude_fake
      )

      with Session(engine) as session:
          app = session.get(Application, app_id)
          assert app.status == "ready"
          assert app.version == 2
          versions = session.exec(
              select(ApplicationVersion)
              .where(ApplicationVersion.application_id == app_id)
              .order_by(ApplicationVersion.version)
          ).all()
          assert [v.version for v in versions] == [1, 2]

      tailor_calls = [c for c in claude_fake.calls if c["task"] == "tailor"]
      assert len(tailor_calls) == 2
      assert "Lead with the migration project" in tailor_calls[-1]["user_content"]
  ```

- [ ] **Step 7: Run the tests — expect FAIL**

  ```powershell
  cd .; pytest tests/test_pipeline.py -v
  ```

  Expected failure: the two new tests fail with `AttributeError: module 'backend.app.services.pipeline' has no attribute 'resume_after_paste'` (and `... 'regenerate_application'`); the first four still pass.

- [ ] **Step 8: Implement `resume_after_paste` and `regenerate_application`**

  Append to the end of `backend/app/services/pipeline.py`:

  ```python
  def resume_after_paste(app_id: int, text: str, engine=None,
                         claude: ClaudeService | None = None) -> None:
      """User pasted the posting text: store it and continue from researching."""
      engine = engine if engine is not None else get_engine()
      claude = claude if claude is not None else make_claude(get_settings())
      with Session(engine) as session:
          app = session.get(Application, app_id)
          if app is None:
              return
          try:
              job = session.get(Job, app.job_id)
              if job is None:
                  raise ClaudeError(f"Job {app.job_id} not found")
              job.raw_text = text
              job.fetch_status = "pasted"
              session.add(job)
              session.commit()
              _run_from_research(session, app, job, claude)
          except Exception as exc:  # noqa: BLE001
              _set_status(session, app, "error", error_message=str(exc))


  def regenerate_application(app_id: int, feedback: str, engine=None,
                             claude: ClaudeService | None = None) -> None:
      """Re-tailor with user feedback: version += 1, new snapshot, re-render."""
      engine = engine if engine is not None else get_engine()
      claude = claude if claude is not None else make_claude(get_settings())
      with Session(engine) as session:
          app = session.get(Application, app_id)
          if app is None:
              return
          try:
              job = session.get(Job, app.job_id)
              profile = session.get(Profile, app.profile_id)
              if job is None or profile is None:
                  raise ClaudeError("Application is missing its job or profile row")
              parsed = get_parsed(job)
              if parsed is None:
                  raise ClaudeError(
                      "Cannot regenerate before the posting has been parsed"
                  )
              master = get_master_profile(profile)
              contact = get_contact(profile)
              findings: ResearchFindings | None = None
              brief = session.exec(
                  select(ResearchBrief)
                  .where(ResearchBrief.job_id == job.id)
                  .order_by(ResearchBrief.id.desc())
              ).first()
              if brief is not None:
                  findings = get_findings(brief)
              app.version += 1
              session.add(app)
              session.commit()
              session.refresh(app)
              _tailor_and_render(session, app, master, contact, parsed,
                                 findings, claude, feedback=feedback)
          except Exception as exc:  # noqa: BLE001
              _set_status(session, app, "error", error_message=str(exc))
  ```

- [ ] **Step 9: Run the tests — expect PASS**

  ```powershell
  cd .; pytest tests/test_pipeline.py -v
  ```

  Expect 6 passing tests.

- [ ] **Step 10: Run the fast suite to confirm nothing in Tasks 1–8 regressed**

  ```powershell
  cd .; pytest -m "not pdf" -v
  ```

  Expect all collected tests to pass.

- [ ] **Step 11: Commit the paste/regenerate cycle**

  ```powershell
  cd .; git add tests/test_pipeline.py backend/app/services/pipeline.py; git commit -m "feat: paste-resume and regenerate pipeline entry points" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

---

## Section 4: Render Service & Templates (Tasks 10–11)

All commands run from the project root `.` with the Python venv active (PowerShell). This section assumes (from earlier tasks): `jinja2`, `markdown`, `playwright`, `pytest` are installed via Task 1's `requirements.txt`; the `pdf` pytest marker is registered in `pyproject.toml` (Task 1); `tests/conftest.py` (Task 1) puts the project root on `sys.path` so `backend.app.*` imports resolve; `backend/app/schemas.py` exists verbatim from the contract (Task 2); `backend/app/fixtures/tailor.json` exists and validates into `TailorResult` (Task 4).

Note on autoescape: the contract says `autoescape=True`; this section uses `select_autoescape()`, which enables autoescaping for all `.html` templates (every template here) — functionally identical for this codebase. Trusted CSS/HTML values (`base_css`, `style_css`, `body_html`) are marked `| safe` inside the templates; all resume/contact data stays escaped.

Unicode note: the ATS text format uses an em dash (`—`, `\u2014`) between role/company and name/description, and an en dash (`–`, `\u2013`) between start/end dates. Python source uses `\u2014`/`\u2013` escapes so the exact bytes never depend on editor encoding. Template files use the literal characters and are read as UTF-8.

---

### Task 10: Render service + Slate template + cover letter template

**Files:**
- Create: `backend/app/services/render.py`
- Create: `backend/templates/base.css`
- Create: `backend/templates/slate/template.html`
- Create: `backend/templates/slate/style.css`
- Create: `backend/templates/cover_letter.html`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `Contact`, `LinkItem`, `ResumeDoc`, `TailorResult`, `ExperienceItem`, `ExperienceSection`, `SkillGroup`, `SkillsSection` from `backend/app/schemas.py` (Task 2); fixture file `backend/app/fixtures/tailor.json` (Task 4, shape `TailorResult`); `pdf` pytest marker registered in `pyproject.toml` (Task 1).
- Produces: `TEMPLATES: tuple`, `TEMPLATES_DIR: Path`, `render_resume_html(resume: ResumeDoc, template: str) -> str`, `render_cover_letter_html(cover_md: str, contact: Contact, template: str) -> str`, `render_ats_text(resume: ResumeDoc) -> str`, `render_pdf(html: str, out_path: Path, page_size: str = "Letter") -> None`, `export_application(application_id: int, resume: ResumeDoc, cover_md: str, contact: Contact, template: str, data_dir: Path, page_size: str = "Letter") -> Path` — all in `backend/app/services/render.py` (consumed by Task 9 pipeline and Task 12 API). Also `backend/templates/base.css` (shared structural CSS consumed by Task 11 templates), the `slate` template, and `backend/templates/cover_letter.html`.

ATS text layout (deterministic; the test below pins it as an exact literal):

```
NAME (uppercased)
email | phone | location        <- " | "-joined, only fields that are present/truthy
label: url                      <- one line per contact link
(blank line)
HEADLINE (uppercased)
summary
(blank line before every section)
SECTION TITLE (uppercased)
==============                  <- '=' repeated len(title) times
per-item lines:
  experience:     ROLE — Company (start–end) [location]   then "- bullet" per bullet
                  (ROLE uppercased; end None -> "present"; "[location]" only if present)
  projects:       Name — description (— part only if description non-empty)
                  then "- bullet" per bullet, then url on its own line if present
  skills:         Label: a, b, c
  education:      Credential, Institution (year) — detail   ((year)/— detail only if present)
  certifications: Name — Issuer (year)                      (— Issuer/(year) only if present)
  extras:         - item
Final output ends with exactly one trailing "\n". No tabs, no wrapping.
```

- [ ] **Step 1: Write failing tests for the render service**

Write `tests/test_render.py` with exactly this content:

```python
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
        "STAFF ENGINEER \u2014 Initech (2021\u2013present) [Remote]\n"
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
```

For reference, the exact ATS output the first test pins (what the escaped string renders as; `\u2014` = `—`, `\u2013` = `–`):

```
JANE DOE
jane@example.com | 555-0100
GitHub: https://github.com/janedoe

SENIOR BACKEND ENGINEER
Backend engineer with 8 years building APIs.

EXPERIENCE
==========
STAFF ENGINEER — Initech (2021–present) [Remote]
- Led migration to event-driven architecture.
- Cut p95 latency 40%.

SKILLS
======
Languages: Python, TypeScript
```

- [ ] **Step 2: Run tests — expect FAIL (module does not exist)**

```powershell
cd .; pytest tests/test_render.py -m "not pdf" -v
```

Expected failure: collection error —

```
ERROR tests/test_render.py
ModuleNotFoundError: No module named 'backend.app.services.render'
```

- [ ] **Step 3: Implement the render service (complete module)**

Write `backend/app/services/render.py` with exactly this content:

```python
"""Rendering: ResumeDoc -> standalone HTML (Jinja) -> PDF (Playwright) + ATS text.

Templates live in backend/templates/: a shared structural base.css plus one
directory per template (template.html + style.css). CSS is inlined into a
<style> tag so every rendered HTML document is fully standalone.
"""
from __future__ import annotations

from pathlib import Path

import markdown as markdown_lib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..schemas import Contact, ResumeDoc

TEMPLATES = ("meridian", "slate", "terminal", "signal")
TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(),
)


def _load_css(template: str) -> tuple[str, str]:
    """Return (base_css, style_css) for a template; raise on unknown template."""
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template {template!r}; expected one of {TEMPLATES}")
    base_css = (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")
    style_css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    return base_css, style_css


def render_resume_html(resume: ResumeDoc, template: str) -> str:
    """Render a ResumeDoc into a fully standalone HTML document."""
    base_css, style_css = _load_css(template)
    tpl = _env.get_template(f"{template}/template.html")
    return tpl.render(resume=resume, base_css=base_css, style_css=style_css)


def render_cover_letter_html(cover_md: str, contact: Contact, template: str) -> str:
    """Markdown cover letter -> standalone HTML in the chosen template's style."""
    base_css, style_css = _load_css(template)
    body_html = markdown_lib.markdown(cover_md)
    tpl = _env.get_template("cover_letter.html")
    return tpl.render(
        body_html=body_html, contact=contact, base_css=base_css, style_css=style_css
    )


def render_ats_text(resume: ResumeDoc) -> str:
    """Deterministic ATS-safe plain text. No tabs, no wrapping.

    Layout:
      NAME (upper)
      email | phone | location   (present fields only, " | "-joined)
      label: url                 (one line per link)
      <blank>
      HEADLINE (upper)
      summary
      <blank before each section>
      TITLE (upper)
      '=' * len(title)
      items (per-type formats; see per-branch code below)
    Ends with exactly one trailing newline.
    """
    lines: list[str] = []
    c = resume.contact
    lines.append(c.name.upper())
    contact_bits = [b for b in (c.email, c.phone, c.location) if b]
    if contact_bits:
        lines.append(" | ".join(contact_bits))
    for link in c.links:
        lines.append(f"{link.label}: {link.url}")
    lines.append("")
    lines.append(resume.headline.upper())
    lines.append(resume.summary)

    for section in resume.sections:
        lines.append("")
        lines.append(section.title.upper())
        lines.append("=" * len(section.title))
        if section.type == "experience":
            for item in section.items:
                head = (
                    f"{item.role.upper()} \u2014 {item.company} "
                    f"({item.start}\u2013{item.end or 'present'})"
                )
                if item.location:
                    head += f" [{item.location}]"
                lines.append(head)
                for bullet in item.bullets:
                    lines.append(f"- {bullet}")
        elif section.type == "projects":
            for item in section.items:
                head = item.name
                if item.description:
                    head += f" \u2014 {item.description}"
                lines.append(head)
                for bullet in item.bullets:
                    lines.append(f"- {bullet}")
                if item.url:
                    lines.append(item.url)
        elif section.type == "skills":
            for group in section.groups:
                lines.append(f"{group.label}: {', '.join(group.items)}")
        elif section.type == "education":
            for item in section.items:
                line = f"{item.credential}, {item.institution}"
                if item.year:
                    line += f" ({item.year})"
                if item.detail:
                    line += f" \u2014 {item.detail}"
                lines.append(line)
        elif section.type == "certifications":
            for item in section.items:
                line = item.name
                if item.issuer:
                    line += f" \u2014 {item.issuer}"
                if item.year:
                    line += f" ({item.year})"
                lines.append(line)
        elif section.type == "extras":
            for item in section.items:
                lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def render_pdf(html: str, out_path: Path, page_size: str = "Letter") -> None:
    """Print HTML to PDF via headless Chromium (Playwright sync API)."""
    from playwright.sync_api import sync_playwright  # lazy: fast tests never need it

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(
                path=str(out_path),
                format=page_size,
                print_background=True,
                margin={
                    "top": "0.5in",
                    "right": "0.5in",
                    "bottom": "0.5in",
                    "left": "0.5in",
                },
            )
        finally:
            browser.close()


def export_application(
    application_id: int,
    resume: ResumeDoc,
    cover_md: str,
    contact: Contact,
    template: str,
    data_dir: Path,
    page_size: str = "Letter",
) -> Path:
    """Write the five export files for an application; return the export dir.

    Files under <data_dir>/exports/<application_id>/:
      resume.pdf, resume.html, resume.txt (ATS), cover_letter.pdf,
      cover_letter.txt (the raw markdown).
    """
    export_dir = Path(data_dir) / "exports" / str(application_id)
    export_dir.mkdir(parents=True, exist_ok=True)

    resume_html = render_resume_html(resume, template)
    cover_html = render_cover_letter_html(cover_md, contact, template)
    ats_text = render_ats_text(resume)

    (export_dir / "resume.html").write_text(resume_html, encoding="utf-8")
    (export_dir / "resume.txt").write_text(ats_text, encoding="utf-8")
    (export_dir / "cover_letter.txt").write_text(cover_md, encoding="utf-8")
    render_pdf(resume_html, export_dir / "resume.pdf", page_size=page_size)
    render_pdf(cover_html, export_dir / "cover_letter.pdf", page_size=page_size)
    return export_dir
```

- [ ] **Step 4: Run tests — expect the ATS test to PASS, the HTML tests to FAIL (templates missing)**

```powershell
cd .; pytest tests/test_render.py -m "not pdf" -v
```

Expected: `1 passed, 4 failed, 1 deselected`. The ATS test passes; the four HTML/export tests fail with:

```
FileNotFoundError: [Errno 2] No such file or directory: '...\\backend\\templates\\base.css'
```

- [ ] **Step 5: Create base.css, the Slate template, and the cover letter template**

Write `backend/templates/base.css` with exactly this content:

```css
/* ============================================================
   base.css — shared structural system for ALL resume templates.
   Templates layer visual identity (fonts, color, rules) in their
   own style.css; this file owns reset, page setup, spacing scale,
   section grammar, and print/pagination behavior.
   ============================================================ */

/* --- Reset --- */
*,
*::before,
*::after {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

/* --- Page setup --- */
@page {
  size: Letter;
  margin: 0.5in;
}

html {
  font-size: 10.5pt;
}

body {
  line-height: 1.35;
  color: #111111;
  background: #ffffff;
}

a {
  color: inherit;
  text-decoration: none;
}

img {
  max-width: 100%;
}

/* --- Spacing scale --- */
:root {
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.85rem;
  --space-4: 1.4rem;
}

/* --- Section grammar --- */
.resume-header {
  margin-bottom: var(--space-4);
}

.section {
  margin-bottom: var(--space-4);
}

.section-title {
  margin-bottom: var(--space-2);
  break-after: avoid;
  page-break-after: avoid;
}

.item {
  margin-bottom: var(--space-3);
  break-inside: avoid;
  page-break-inside: avoid;
}

.item:last-child {
  margin-bottom: 0;
}

.item-head {
  margin-bottom: var(--space-1);
}

.bullets {
  margin-left: 1.1em;
  list-style: disc outside;
}

.bullets li {
  margin-bottom: var(--space-1);
}

/* --- Widow/orphan control --- */
h1,
h2,
h3 {
  break-after: avoid;
  page-break-after: avoid;
}

p {
  orphans: 2;
  widows: 2;
}

/* --- Print --- */
@media print {
  body {
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
}
```

Write `backend/templates/slate/template.html` with exactly this content (UTF-8; the date separator is a literal en dash):

```html
{# Slate — clean contemporary sans. General-purpose default. #}
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ resume.contact.name }} — Resume</title>
<style>
{{ base_css | safe }}
{{ style_css | safe }}
</style>
</head>
<body>
<header class="resume-header">
  <h1 class="name">{{ resume.contact.name }}</h1>
  <p class="headline">{{ resume.headline }}</p>
  <p class="contact-line">
    {{ [resume.contact.email, resume.contact.phone, resume.contact.location] | select | join(" · ") }}
    {%- for link in resume.contact.links %} · {{ link.label }}: {{ link.url }}{% endfor %}
  </p>
  {% if resume.summary %}<p class="summary">{{ resume.summary }}</p>{% endif %}
</header>

{% for section in resume.sections %}
<section class="section section-{{ section.type }}">
  <h2 class="section-title">{{ section.title }}</h2>

  {% if section.type == "experience" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.role }}</span>
        <span class="secondary">{{ item.company }}</span>
        <span class="meta">{{ item.start }}–{{ item.end or "Present" }}{% if item.location %} · {{ item.location }}{% endif %}</span>
      </div>
      {% if item.bullets %}
      <ul class="bullets">
        {% for bullet in item.bullets %}<li>{{ bullet }}</li>{% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "projects" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.name }}</span>
        {% if item.description %}<span class="secondary">{{ item.description }}</span>{% endif %}
        {% if item.url %}<span class="meta">{{ item.url }}</span>{% endif %}
      </div>
      {% if item.bullets %}
      <ul class="bullets">
        {% for bullet in item.bullets %}<li>{{ bullet }}</li>{% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "skills" %}
    {% for group in section.groups %}
    <div class="item skill-group">
      <span class="skill-label">{{ group.label }}:</span>
      <span class="skill-items">{{ group.items | join(", ") }}</span>
    </div>
    {% endfor %}

  {% elif section.type == "education" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.credential }}</span>
        <span class="secondary">{{ item.institution }}</span>
        {% if item.year %}<span class="meta">{{ item.year }}</span>{% endif %}
      </div>
      {% if item.detail %}<p class="detail">{{ item.detail }}</p>{% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "certifications" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.name }}</span>
        {% if item.issuer %}<span class="secondary">{{ item.issuer }}</span>{% endif %}
        {% if item.year %}<span class="meta">{{ item.year }}</span>{% endif %}
      </div>
    </div>
    {% endfor %}

  {% elif section.type == "extras" %}
    <ul class="bullets extras">
      {% for item in section.items %}<li>{{ item }}</li>{% endfor %}
    </ul>
  {% endif %}
</section>
{% endfor %}
</body>
</html>
```

Write `backend/templates/slate/style.css` with exactly this content:

```css
/* ============================================================
   Slate — clean contemporary sans. General-purpose default.
   System font stack, strong hierarchy, subtle rules between
   sections.
   ============================================================ */

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, sans-serif;
  color: #1a202c;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}

.name {
  font-size: 21pt;
  font-weight: 700;
  letter-spacing: -0.015em;
}

.headline {
  font-size: 11pt;
  font-weight: 600;
  color: #2d3748;
  margin-top: var(--space-1);
}

.contact-line {
  font-size: 9pt;
  color: #4a5568;
  margin-top: var(--space-2);
}

.summary {
  font-size: 9.5pt;
  color: #2d3748;
  margin-top: var(--space-2);
  max-width: 46em;
}

.section {
  border-top: 1px solid #cbd5e0;
  padding-top: var(--space-2);
}

.section-title {
  font-size: 9.5pt;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: #2d3748;
}

.item {
  break-inside: avoid;
  page-break-inside: avoid;
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
}

.item-head .primary {
  font-size: 10.5pt;
  font-weight: 600;
}

.item-head .secondary {
  font-size: 10pt;
  color: #2d3748;
}

.item-head .meta {
  margin-left: auto;
  font-size: 9pt;
  color: #718096;
}

.bullets,
.detail {
  font-size: 9.5pt;
}

.skill-group {
  font-size: 9.5pt;
}

.skill-label {
  font-weight: 600;
}
```

Write `backend/templates/cover_letter.html` with exactly this content:

```html
{# Cover letter — shared shell; visual identity comes from the chosen template's style.css. #}
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ contact.name }} — Cover Letter</title>
<style>
{{ base_css | safe }}
{{ style_css | safe }}
/* Cover-letter-specific layout on top of the template identity */
.cover-header {
  margin-bottom: var(--space-4);
}
.cover-body {
  font-size: 10pt;
  max-width: 48em;
}
.cover-body p {
  margin-bottom: var(--space-3);
}
</style>
</head>
<body>
<header class="resume-header cover-header">
  <h1 class="name">{{ contact.name }}</h1>
  <p class="contact-line">
    {{ [contact.email, contact.phone, contact.location] | select | join(" · ") }}
    {%- for link in contact.links %} · {{ link.label }}: {{ link.url }}{% endfor %}
  </p>
</header>
<main class="cover-body">
{{ body_html | safe }}
</main>
</body>
</html>
```

- [ ] **Step 6: Run the fast tests — expect PASS**

```powershell
cd .; pytest tests/test_render.py -m "not pdf" -v
```

Expected: `5 passed, 1 deselected`.

- [ ] **Step 7: Run the real PDF smoke test — expect PASS**

If Chromium was never installed on this machine, install it once first:

```powershell
cd .; playwright install chromium
```

Then:

```powershell
cd .; pytest tests/test_render.py -m pdf -v
```

Expected: `1 passed, 5 deselected` (a real one-page PDF is produced; the file starts with `%PDF`).

- [ ] **Step 8: Commit**

```powershell
cd .; git add backend/app/services/render.py backend/templates/base.css backend/templates/slate/template.html backend/templates/slate/style.css backend/templates/cover_letter.html tests/test_render.py; git commit -m "feat: render service with slate template, cover letter, ATS text, PDF export" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: Meridian, Terminal, and Signal templates

**Files:**
- Create: `backend/templates/meridian/template.html`
- Create: `backend/templates/meridian/style.css`
- Create: `backend/templates/terminal/template.html`
- Create: `backend/templates/terminal/style.css`
- Create: `backend/templates/signal/template.html`
- Create: `backend/templates/signal/style.css`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: `TEMPLATES`, `TEMPLATES_DIR`, `render_resume_html` from `backend/app/services/render.py` (Task 10); `backend/templates/base.css` (Task 10); schemas `Contact`, `ResumeDoc`, `TailorResult`, `ExperienceItem`, `ExperienceSection`, `ProjectItem`, `ProjectsSection`, `SkillGroup`, `SkillsSection`, `EducationItem`, `EducationSection`, `CertificationItem`, `CertificationsSection`, `ExtrasSection` from `backend/app/schemas.py` (Task 2); fixture `backend/app/fixtures/tailor.json` (Task 4).
- Produces: the `meridian`, `terminal`, and `signal` template files. No new Python symbols. After this task, every member of `TEMPLATES` renders (consumed by Task 12's preview/exports routes and Task 13 demo mode).

Each `template.html` is a complete standalone file repeating the full six-type dispatch — no Jinja `include`/`extends`; only `base.css` is shared (inlined by the render service). Visual identities: meridian = classic understated serif (Georgia/Times stack, small-caps section titles, hairline rules, near-black on white, generous margins); terminal = technical (ui-monospace accents for skills/dates, sans body, left border accent on section titles, stronger project-name treatment so projects read forward); signal = bold (large headline, single accent `#C2410C` as name underline bar + section markers, confident whitespace). Every style.css: `print-color-adjust: exact`, no fixed heights, `break-inside: avoid` on `.item`.

- [ ] **Step 1: Write failing tests for all four templates**

Write `tests/test_templates.py` with exactly this content:

```python
"""Tests for the four resume templates (Task 11)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.schemas import (
    CertificationItem,
    CertificationsSection,
    Contact,
    EducationItem,
    EducationSection,
    ExperienceItem,
    ExperienceSection,
    ExtrasSection,
    ProjectItem,
    ProjectsSection,
    ResumeDoc,
    SkillGroup,
    SkillsSection,
    TailorResult,
)
from backend.app.services.render import TEMPLATES, TEMPLATES_DIR, render_resume_html

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


def _fixture_resume() -> ResumeDoc:
    data = json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))
    return TailorResult.model_validate(data).resume


def _all_sections_resume() -> ResumeDoc:
    """A ResumeDoc containing ALL six section types."""
    return ResumeDoc(
        contact=Contact(
            name="Alex Chen",
            email="alex@example.com",
            phone="555-0111",
            location="Portland, OR",
        ),
        headline="Full-Stack Engineer",
        summary="Engineer who ships end to end.",
        sections=[
            ExperienceSection(
                items=[
                    ExperienceItem(
                        company="Initech",
                        role="Software Engineer",
                        start="2020",
                        end="2023",
                        location="Remote",
                        bullets=["Built the billing service."],
                    )
                ]
            ),
            ProjectsSection(
                items=[
                    ProjectItem(
                        name="OpenBoard",
                        description="Realtime collaborative whiteboard",
                        url="https://openboard.example.com",
                        bullets=["Grew to 10k users."],
                    )
                ]
            ),
            SkillsSection(
                groups=[SkillGroup(label="Languages", items=["Python", "Go"])]
            ),
            EducationSection(
                items=[
                    EducationItem(
                        institution="State University",
                        credential="B.S. Computer Science",
                        year="2019",
                        detail="Magna cum laude",
                    )
                ]
            ),
            CertificationsSection(
                items=[
                    CertificationItem(
                        name="AWS Solutions Architect Associate",
                        issuer="Amazon",
                        year="2022",
                    )
                ]
            ),
            ExtrasSection(items=["Open-source maintainer"]),
        ],
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_renders_fixture_resume(template):
    resume = _fixture_resume()
    html = render_resume_html(resume, template)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<style>" in html  # standalone: CSS inlined
    assert resume.contact.name in html
    for section in resume.sections:
        assert section.title in html


@pytest.mark.parametrize(
    "template,marker",
    [
        ("meridian", "Georgia"),
        ("terminal", "monospace"),
        ("signal", "#C2410C"),
    ],
)
def test_template_visual_identity(template, marker):
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    assert marker in css


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_renders_all_six_section_types(template):
    html = render_resume_html(_all_sections_resume(), template)
    for needle in (
        "Initech",
        "OpenBoard",
        "Languages",
        "State University",
        "AWS Solutions Architect Associate",
        "Open-source maintainer",
    ):
        assert needle in html
```

- [ ] **Step 2: Run tests — expect FAIL for meridian/terminal/signal**

```powershell
cd .; pytest tests/test_templates.py -v
```

Expected: `2 passed, 9 failed` — the two `slate` params pass; every meridian/terminal/signal test fails with:

```
FileNotFoundError: [Errno 2] No such file or directory: '...\\backend\\templates\\meridian\\style.css'
```

(and the matching `terminal\\style.css` / `signal\\style.css` paths).

- [ ] **Step 3: Create the Meridian template**

Write `backend/templates/meridian/template.html` with exactly this content:

```html
{# Meridian — classic understated serif. Corporate, finance, healthcare, government. #}
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ resume.contact.name }} — Resume</title>
<style>
{{ base_css | safe }}
{{ style_css | safe }}
</style>
</head>
<body>
<header class="resume-header">
  <h1 class="name">{{ resume.contact.name }}</h1>
  <p class="headline">{{ resume.headline }}</p>
  <p class="contact-line">
    {{ [resume.contact.email, resume.contact.phone, resume.contact.location] | select | join(" · ") }}
    {%- for link in resume.contact.links %} · {{ link.label }}: {{ link.url }}{% endfor %}
  </p>
  {% if resume.summary %}<p class="summary">{{ resume.summary }}</p>{% endif %}
</header>

{% for section in resume.sections %}
<section class="section section-{{ section.type }}">
  <h2 class="section-title">{{ section.title }}</h2>

  {% if section.type == "experience" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.role }}</span>
        <span class="secondary">{{ item.company }}</span>
        <span class="meta">{{ item.start }}–{{ item.end or "Present" }}{% if item.location %} · {{ item.location }}{% endif %}</span>
      </div>
      {% if item.bullets %}
      <ul class="bullets">
        {% for bullet in item.bullets %}<li>{{ bullet }}</li>{% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "projects" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.name }}</span>
        {% if item.description %}<span class="secondary">{{ item.description }}</span>{% endif %}
        {% if item.url %}<span class="meta">{{ item.url }}</span>{% endif %}
      </div>
      {% if item.bullets %}
      <ul class="bullets">
        {% for bullet in item.bullets %}<li>{{ bullet }}</li>{% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "skills" %}
    {% for group in section.groups %}
    <div class="item skill-group">
      <span class="skill-label">{{ group.label }}:</span>
      <span class="skill-items">{{ group.items | join(", ") }}</span>
    </div>
    {% endfor %}

  {% elif section.type == "education" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.credential }}</span>
        <span class="secondary">{{ item.institution }}</span>
        {% if item.year %}<span class="meta">{{ item.year }}</span>{% endif %}
      </div>
      {% if item.detail %}<p class="detail">{{ item.detail }}</p>{% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "certifications" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.name }}</span>
        {% if item.issuer %}<span class="secondary">{{ item.issuer }}</span>{% endif %}
        {% if item.year %}<span class="meta">{{ item.year }}</span>{% endif %}
      </div>
    </div>
    {% endfor %}

  {% elif section.type == "extras" %}
    <ul class="bullets extras">
      {% for item in section.items %}<li>{{ item }}</li>{% endfor %}
    </ul>
  {% endif %}
</section>
{% endfor %}
</body>
</html>
```

Write `backend/templates/meridian/style.css` with exactly this content:

```css
/* ============================================================
   Meridian — classic understated serif.
   Corporate, finance, healthcare, government.
   Georgia/Times stack, small-caps section titles, hairline
   rules, near-black on white, generous margins.
   ============================================================ */

body {
  font-family: Georgia, "Times New Roman", Times, serif;
  color: #161616;
  line-height: 1.4;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}

.resume-header {
  text-align: center;
  padding-bottom: var(--space-3);
  border-bottom: 0.5pt solid #8a8a8a;
}

.name {
  font-size: 19pt;
  font-weight: 400;
  letter-spacing: 0.05em;
}

.headline {
  font-size: 10.5pt;
  font-style: italic;
  color: #3a3a3a;
  margin-top: var(--space-1);
}

.contact-line {
  font-size: 9pt;
  color: #3a3a3a;
  margin-top: var(--space-2);
}

.summary {
  font-size: 10pt;
  margin-top: var(--space-3);
  text-align: left;
}

.section-title {
  font-size: 10.5pt;
  font-weight: 400;
  font-variant: small-caps;
  letter-spacing: 0.14em;
  color: #161616;
  border-bottom: 0.5pt solid #8a8a8a;
  padding-bottom: 2px;
}

.item {
  break-inside: avoid;
  page-break-inside: avoid;
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
}

.item-head .primary {
  font-size: 10.5pt;
  font-weight: 700;
}

.item-head .secondary {
  font-size: 10pt;
  font-style: italic;
  color: #2c2c2c;
}

.item-head .meta {
  margin-left: auto;
  font-size: 9pt;
  color: #555555;
}

.bullets,
.detail,
.skill-group {
  font-size: 9.5pt;
}

.skill-label {
  font-weight: 700;
}
```

- [ ] **Step 4: Run the Meridian tests — expect PASS**

```powershell
cd .; pytest tests/test_templates.py -k meridian -v
```

Expected: `3 passed, 8 deselected`.

- [ ] **Step 5: Create the Terminal template**

Write `backend/templates/terminal/template.html` with exactly this content:

```html
{# Terminal — technical: mono accents, projects-forward. Engineering, data. #}
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ resume.contact.name }} — Resume</title>
<style>
{{ base_css | safe }}
{{ style_css | safe }}
</style>
</head>
<body>
<header class="resume-header">
  <h1 class="name">{{ resume.contact.name }}</h1>
  <p class="headline">{{ resume.headline }}</p>
  <p class="contact-line">
    {{ [resume.contact.email, resume.contact.phone, resume.contact.location] | select | join(" · ") }}
    {%- for link in resume.contact.links %} · {{ link.label }}: {{ link.url }}{% endfor %}
  </p>
  {% if resume.summary %}<p class="summary">{{ resume.summary }}</p>{% endif %}
</header>

{% for section in resume.sections %}
<section class="section section-{{ section.type }}">
  <h2 class="section-title">{{ section.title }}</h2>

  {% if section.type == "experience" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.role }}</span>
        <span class="secondary">{{ item.company }}</span>
        <span class="meta">{{ item.start }}–{{ item.end or "Present" }}{% if item.location %} · {{ item.location }}{% endif %}</span>
      </div>
      {% if item.bullets %}
      <ul class="bullets">
        {% for bullet in item.bullets %}<li>{{ bullet }}</li>{% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "projects" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.name }}</span>
        {% if item.description %}<span class="secondary">{{ item.description }}</span>{% endif %}
        {% if item.url %}<span class="meta">{{ item.url }}</span>{% endif %}
      </div>
      {% if item.bullets %}
      <ul class="bullets">
        {% for bullet in item.bullets %}<li>{{ bullet }}</li>{% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "skills" %}
    {% for group in section.groups %}
    <div class="item skill-group">
      <span class="skill-label">{{ group.label }}:</span>
      <span class="skill-items">{{ group.items | join(", ") }}</span>
    </div>
    {% endfor %}

  {% elif section.type == "education" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.credential }}</span>
        <span class="secondary">{{ item.institution }}</span>
        {% if item.year %}<span class="meta">{{ item.year }}</span>{% endif %}
      </div>
      {% if item.detail %}<p class="detail">{{ item.detail }}</p>{% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "certifications" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.name }}</span>
        {% if item.issuer %}<span class="secondary">{{ item.issuer }}</span>{% endif %}
        {% if item.year %}<span class="meta">{{ item.year }}</span>{% endif %}
      </div>
    </div>
    {% endfor %}

  {% elif section.type == "extras" %}
    <ul class="bullets extras">
      {% for item in section.items %}<li>{{ item }}</li>{% endfor %}
    </ul>
  {% endif %}
</section>
{% endfor %}
</body>
</html>
```

Write `backend/templates/terminal/style.css` with exactly this content:

```css
/* ============================================================
   Terminal — technical. Engineering, data.
   Sans body with ui-monospace accents (skills, dates), left
   border accent on section titles, projects read forward.
   ============================================================ */

body {
  font-family: "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: #14171c;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}

.name {
  font-size: 20pt;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.headline {
  font-family: ui-monospace, "Cascadia Code", Consolas, Menlo, monospace;
  font-size: 10pt;
  color: #2f3742;
  margin-top: var(--space-1);
}

.contact-line {
  font-family: ui-monospace, "Cascadia Code", Consolas, Menlo, monospace;
  font-size: 8.5pt;
  color: #49525e;
  margin-top: var(--space-2);
}

.summary {
  font-size: 9.5pt;
  color: #2f3742;
  margin-top: var(--space-2);
  max-width: 48em;
}

.section-title {
  font-size: 9.5pt;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #14171c;
  border-left: 3px solid #14171c;
  padding-left: var(--space-2);
}

.item {
  break-inside: avoid;
  page-break-inside: avoid;
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
}

.item-head .primary {
  font-size: 10.5pt;
  font-weight: 600;
}

.item-head .secondary {
  font-size: 9.5pt;
  color: #2f3742;
}

.item-head .meta {
  margin-left: auto;
  font-family: ui-monospace, "Cascadia Code", Consolas, Menlo, monospace;
  font-size: 8.5pt;
  color: #5b6470;
}

/* Projects read forward: heavier, mono name treatment */
.section-projects .item-head .primary {
  font-family: ui-monospace, "Cascadia Code", Consolas, Menlo, monospace;
  font-size: 11pt;
  font-weight: 700;
}

.bullets,
.detail {
  font-size: 9.5pt;
}

.skill-group {
  font-size: 9.5pt;
}

.skill-label {
  font-weight: 700;
}

.skill-items {
  font-family: ui-monospace, "Cascadia Code", Consolas, Menlo, monospace;
  font-size: 9pt;
}
```

- [ ] **Step 6: Run the Terminal tests — expect PASS**

```powershell
cd .; pytest tests/test_templates.py -k terminal -v
```

Expected: `3 passed, 8 deselected`.

- [ ] **Step 7: Create the Signal template**

Write `backend/templates/signal/template.html` with exactly this content:

```html
{# Signal — bold headline treatment, accent color. Design, marketing, creative. #}
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ resume.contact.name }} — Resume</title>
<style>
{{ base_css | safe }}
{{ style_css | safe }}
</style>
</head>
<body>
<header class="resume-header">
  <h1 class="name">{{ resume.contact.name }}</h1>
  <p class="headline">{{ resume.headline }}</p>
  <p class="contact-line">
    {{ [resume.contact.email, resume.contact.phone, resume.contact.location] | select | join(" · ") }}
    {%- for link in resume.contact.links %} · {{ link.label }}: {{ link.url }}{% endfor %}
  </p>
  {% if resume.summary %}<p class="summary">{{ resume.summary }}</p>{% endif %}
</header>

{% for section in resume.sections %}
<section class="section section-{{ section.type }}">
  <h2 class="section-title">{{ section.title }}</h2>

  {% if section.type == "experience" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.role }}</span>
        <span class="secondary">{{ item.company }}</span>
        <span class="meta">{{ item.start }}–{{ item.end or "Present" }}{% if item.location %} · {{ item.location }}{% endif %}</span>
      </div>
      {% if item.bullets %}
      <ul class="bullets">
        {% for bullet in item.bullets %}<li>{{ bullet }}</li>{% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "projects" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.name }}</span>
        {% if item.description %}<span class="secondary">{{ item.description }}</span>{% endif %}
        {% if item.url %}<span class="meta">{{ item.url }}</span>{% endif %}
      </div>
      {% if item.bullets %}
      <ul class="bullets">
        {% for bullet in item.bullets %}<li>{{ bullet }}</li>{% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "skills" %}
    {% for group in section.groups %}
    <div class="item skill-group">
      <span class="skill-label">{{ group.label }}:</span>
      <span class="skill-items">{{ group.items | join(", ") }}</span>
    </div>
    {% endfor %}

  {% elif section.type == "education" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.credential }}</span>
        <span class="secondary">{{ item.institution }}</span>
        {% if item.year %}<span class="meta">{{ item.year }}</span>{% endif %}
      </div>
      {% if item.detail %}<p class="detail">{{ item.detail }}</p>{% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "certifications" %}
    {% for item in section.items %}
    <div class="item">
      <div class="item-head">
        <span class="primary">{{ item.name }}</span>
        {% if item.issuer %}<span class="secondary">{{ item.issuer }}</span>{% endif %}
        {% if item.year %}<span class="meta">{{ item.year }}</span>{% endif %}
      </div>
    </div>
    {% endfor %}

  {% elif section.type == "extras" %}
    <ul class="bullets extras">
      {% for item in section.items %}<li>{{ item }}</li>{% endfor %}
    </ul>
  {% endif %}
</section>
{% endfor %}
</body>
</html>
```

Write `backend/templates/signal/style.css` with exactly this content:

```css
/* ============================================================
   Signal — bold. Design, marketing, creative.
   Large headline, one accent color #C2410C (name underline bar
   + section markers), confident whitespace.
   ============================================================ */

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, sans-serif;
  color: #1c1917;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}

.resume-header {
  margin-bottom: calc(var(--space-4) * 1.3);
}

.name {
  display: inline-block;
  font-size: 27pt;
  font-weight: 800;
  letter-spacing: -0.02em;
  border-bottom: 4px solid #C2410C;
  padding-bottom: 3px;
}

.headline {
  font-size: 12pt;
  font-weight: 600;
  color: #44403c;
  margin-top: var(--space-2);
}

.contact-line {
  font-size: 9pt;
  color: #57534e;
  margin-top: var(--space-2);
}

.summary {
  font-size: 10pt;
  color: #292524;
  margin-top: var(--space-3);
  max-width: 44em;
}

.section {
  margin-bottom: calc(var(--space-4) * 1.15);
}

.section-title {
  font-size: 10pt;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: #1c1917;
}

.section-title::before {
  content: "";
  display: inline-block;
  width: 0.6em;
  height: 0.6em;
  background: #C2410C;
  margin-right: var(--space-2);
}

.item {
  break-inside: avoid;
  page-break-inside: avoid;
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
}

.item-head .primary {
  font-size: 11pt;
  font-weight: 700;
}

.item-head .secondary {
  font-size: 10pt;
  color: #44403c;
}

.item-head .meta {
  margin-left: auto;
  font-size: 9pt;
  color: #78716c;
}

.bullets,
.detail {
  font-size: 9.5pt;
}

.skill-group {
  font-size: 9.5pt;
}

.skill-label {
  font-weight: 700;
  color: #1c1917;
}
```

- [ ] **Step 8: Run the Signal tests — expect PASS**

```powershell
cd .; pytest tests/test_templates.py -k signal -v
```

Expected: `3 passed, 8 deselected`.

- [ ] **Step 9: Run the full template suite and the whole fast suite — expect PASS**

```powershell
cd .; pytest tests/test_templates.py -v
```

Expected: `11 passed`.

```powershell
cd .; pytest -m "not pdf"
```

Expected: all collected tests pass (pdf-marked tests deselected).

- [ ] **Step 10: Commit**

```powershell
cd .; git add backend/templates/meridian backend/templates/terminal backend/templates/signal tests/test_templates.py; git commit -m "feat: add meridian, terminal, and signal resume templates" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

# Section 05 — API layer, demo mode, and launcher (Tasks 12–13)

All commands run from the project root `.` with the Python venv active. Every `pytest` invocation below is PowerShell-syntax.

**Cross-section assumptions used in this section** (from the contract; flagged so the implementer can adapt if an earlier task differed slightly):

1. Task 1's `tests/conftest.py` inserts the PROJECT ROOT into `sys.path` (there is no `pythonpath` entry in `pyproject.toml`), so all tests import `backend.app.*` — e.g. `from backend.app.main import create_app`, `from backend.app.services import pipeline` — exactly like every other section. Never import the package as `app.*`: that would be a second module identity for the same files and double-register the SQLModel tables (`Table "profile" is already defined`).
2. `app.config.Settings` is a no-argument class that reads env vars (`ANTHROPIC_API_KEY`, `TAILORED_DATA_DIR`, `TAILORED_FAKE`, `TAILORED_HOST`, `TAILORED_PORT`) at construction; tests set env via `monkeypatch.setenv` then construct `Settings()`. If Task 1's `Settings` takes constructor arguments instead, construct it with equivalent values — do not change any assertion.
3. `app.db.get_session` is the FastAPI dependency from Task 1 that yields a `Session` bound to `request.app.state.engine`.
4. Task 12 rewrites `backend/app/main.py` completely; `GET /api/health` moves into `api_router` (same path, same `{"status": "ok"}` body), so any earlier health test keeps passing.
5. Task 13's demo fixtures MUST agree with the Task 4 fixtures: `fixtures/demo/profile.json`'s `master_profile` must contain the same companies/titles/dates as `backend/app/fixtures/intake.json` (the `tailor.json` fixture resume is verified against the demo profile by `verify_truthfulness` during the demo pipeline run), and `fixtures/demo/job_posting.txt` must describe the same company/title as `backend/app/fixtures/parse_posting.json` (Northwind Labs / Senior Software Engineer). Concrete file contents are given below; **if the Task 4 fixtures differ, copy `intake.json`'s `contact` + `master_profile` into `demo/profile.json` verbatim and align the posting text** — duplication is expected and allowed.

---

### Task 12: API routers (profiles, applications, settings) wired into create_app

**Files**

- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/profiles.py`
- Create: `backend/app/api/applications.py`
- Create: `backend/app/api/settings.py`
- Modify: `backend/app/main.py` (full rewrite shown below)
- Modify: `requirements.txt` (ensure `python-multipart` present — needed for multipart uploads)
- Test: `tests/test_api.py`

**Interfaces**

- Consumes:
  - `app.config`: `Settings`, `get_settings`, `load_user_settings(data_dir)`, `save_user_settings(data_dir, values)` (Task 1)
  - `app.db`: `get_engine`, `init_db`, `get_session` (Task 1)
  - `app.models`: `Profile`, `SourceDocument`, `Job`, `Application`, `ResearchBrief`, `get_contact`, `set_contact`, `get_master_profile`, `set_master_profile`, `get_parsed`, `get_findings`, `get_resume`, `set_resume` (Task 3)
  - `app.schemas`: `Contact`, `MasterProfile`, `ResumeDoc`, `UsageInfo` (Task 2)
  - `app.services.claude.make_claude` (Task 4)
  - `app.services.intake`: `extract_text`, `build_master_profile` (Task 5) — always called through the `intake` module attribute so tests can monkeypatch
  - `app.services.pipeline`: `process_application`, `resume_after_paste`, `regenerate_application` (Task 9) — always scheduled through the `pipeline` module attribute so tests can monkeypatch
  - `app.services.render`: `TEMPLATES`, `render_resume_html`, `export_application` (Task 10) — `render_resume_html`/`export_application` called through the `render` module attribute
- Produces:
  - `backend/app/api/__init__.py`: `api_router` — `APIRouter(prefix="/api")` containing `GET /health` plus the profiles/applications/settings routers
  - `backend/app/api/profiles.py`: `router`; `profile_detail(session, profile) -> dict`
  - `backend/app/api/applications.py`: `router`; `application_summary(app_row: Application, job: Job) -> dict`; `application_detail(session: Session, app_row: Application, job: Job) -> dict`; `DEPTHS = ("quick", "standard", "deep")`; `EXPORT_KINDS = ("resume.pdf", "resume.html", "resume.txt", "cover_letter.pdf", "cover_letter.txt")`; `POST /applications/{application_id}/retry` — beyond the contract route table (defined fully here): re-queues an errored application (`status = "queued"`, `error_message = None`) and re-schedules `pipeline.process_application`, giving every failure a working retry action even before the posting has been parsed (spec section 8; `regenerate` alone cannot cover parse/research-stage errors because Task 9's `regenerate_application` rejects unparsed postings). **Cross-section requirement:** Task 14's `api.ts` must add `retryApplication(id: number)` calling this route, and Task 17's ApplicationScreen must show a "Retry" button inside its `status === 'error'` alert that calls it and bumps `pollNonce`.
  - `backend/app/api/settings.py`: `router`; `PAGE_SIZES = ("Letter", "A4")`
  - `backend/app/main.py`: `create_app(settings: Settings | None = None, engine=None) -> FastAPI` setting `app.state.settings`, `app.state.engine`, `app.state.claude` (Task 13 and the frontend tasks rely on this exact signature)

#### Cycle A — profile routes

- [ ] **Step 1: Write failing tests for the profile routes**

Create `tests/test_api.py` with exactly this content:

```python
"""API route tests (Task 12). All pipeline work is monkeypatched - no Claude, no network."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db import get_engine
from backend.app.main import create_app
from backend.app.schemas import Contact, MasterProfile, MPExperience, TaggedBullet, UsageInfo
from backend.app.services import intake, pipeline, render

CONTACT = {
    "name": "Avery Kim",
    "email": "avery.kim@example.com",
    "phone": "(206) 555-0142",
    "location": "Seattle, WA",
    "links": [{"label": "GitHub", "url": "https://github.com/averykim"}],
}

VALID_RESUME = {
    "contact": {
        "name": "Avery Kim",
        "email": "avery.kim@example.com",
        "phone": None,
        "location": "Seattle, WA",
        "links": [],
    },
    "headline": "Senior Software Engineer",
    "summary": "Backend engineer with eight years of Python service experience.",
    "sections": [
        {
            "type": "experience",
            "title": "Experience",
            "items": [
                {
                    "company": "Meridian Analytics",
                    "role": "Senior Software Engineer",
                    "start": "2021-03",
                    "end": None,
                    "location": "Remote",
                    "bullets": ["Designed and shipped a FastAPI event-ingestion service."],
                }
            ],
        },
        {
            "type": "skills",
            "title": "Skills",
            "groups": [{"label": "Languages", "items": ["Python", "TypeScript"]}],
        },
    ],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILORED_FAKE", "1")
    monkeypatch.setenv("TAILORED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings()
    engine = get_engine(tmp_path / "test.db")
    app = create_app(settings=settings, engine=engine)

    calls = {"process": [], "paste": [], "regenerate": []}
    monkeypatch.setattr(
        pipeline, "process_application",
        lambda app_id, engine=None: calls["process"].append(app_id))
    monkeypatch.setattr(
        pipeline, "resume_after_paste",
        lambda app_id, text, engine=None: calls["paste"].append((app_id, text)))
    monkeypatch.setattr(
        pipeline, "regenerate_application",
        lambda app_id, feedback, engine=None: calls["regenerate"].append((app_id, feedback)))

    # Plain TestClient (no context manager): startup hooks never run, so the
    # demo seeding added in Task 13 cannot pollute these tests.
    test_client = TestClient(app)
    test_client.calls = calls
    return test_client


def make_profile(client) -> int:
    resp = client.post("/api/profiles", json={"name": "Avery Kim", "contact": CONTACT})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_profile_crud(client):
    assert client.get("/api/profiles").json() == []

    pid = make_profile(client)
    listing = client.get("/api/profiles").json()
    assert len(listing) == 1
    assert listing[0]["id"] == pid
    assert listing[0]["name"] == "Avery Kim"
    assert listing[0]["contact"]["email"] == "avery.kim@example.com"
    assert listing[0]["has_master_profile"] is False

    detail = client.get(f"/api/profiles/{pid}").json()
    assert detail["id"] == pid
    assert detail["master_profile"]["experiences"] == []
    assert detail["documents"] == []

    mp = {
        "summary_notes": "Backend engineer.",
        "experiences": [{
            "company": "Meridian Analytics", "title": "Senior Software Engineer",
            "start": "2021-03", "end": None, "location": "Remote",
            "bullets": [{"text": "Built APIs", "tags": ["python"]}],
        }],
        "projects": [], "skills": [], "education": [], "certifications": [], "extras": [],
    }
    updated = client.put(f"/api/profiles/{pid}", json={"name": "Avery K.", "master_profile": mp})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Avery K."
    assert updated.json()["master_profile"]["experiences"][0]["company"] == "Meridian Analytics"
    assert client.get("/api/profiles").json()[0]["has_master_profile"] is True

    assert client.get("/api/profiles/9999").status_code == 404
    assert client.put("/api/profiles/9999", json={"name": "x"}).status_code == 404


def test_document_upload_multipart_and_json(client):
    pid = make_profile(client)

    multipart = client.post(
        f"/api/profiles/{pid}/documents",
        files={"file": ("resume.txt", b"Avery Kim resume body", "text/plain")})
    assert multipart.status_code == 200, multipart.text
    body = multipart.json()
    assert body["filename"] == "resume.txt"
    assert body["kind"] == "txt"

    pasted = client.post(
        f"/api/profiles/{pid}/documents",
        json={"filename": "notes.txt", "text": "Extra career notes"})
    assert pasted.status_code == 200
    assert pasted.json()["kind"] == "paste"

    empty = client.post(f"/api/profiles/{pid}/documents", json={"filename": "x.txt", "text": ""})
    assert empty.status_code == 422

    detail = client.get(f"/api/profiles/{pid}").json()
    assert len(detail["documents"]) == 2
    assert client.post(
        "/api/profiles/9999/documents", json={"filename": "a", "text": "b"}).status_code == 404


def test_build_master_profile(client, monkeypatch):
    pid = make_profile(client)
    assert client.post(f"/api/profiles/{pid}/build").status_code == 422  # no documents yet

    client.post(f"/api/profiles/{pid}/documents",
                json={"filename": "resume.txt", "text": "Avery resume text"})

    mp = MasterProfile(
        summary_notes="Backend engineer",
        experiences=[MPExperience(
            company="Meridian Analytics", title="Senior Software Engineer", start="2021-03",
            bullets=[TaggedBullet(text="Built APIs", tags=["python"])])],
    )
    contact = Contact(name="Avery Kim", email="avery.kim@example.com")
    recorded = {}

    def fake_build(docs, claude):
        recorded["docs"] = list(docs)
        return mp, contact, UsageInfo(input_tokens=1000, output_tokens=500, cost_usd=0.0175)

    monkeypatch.setattr(intake, "build_master_profile", fake_build)
    resp = client.post(f"/api/profiles/{pid}/build")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert recorded["docs"] == ["Avery resume text"]
    assert body["master_profile"]["experiences"][0]["company"] == "Meridian Analytics"
    assert body["usage"] == {"input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.0175}
```

- [ ] **Step 2: Run the tests — expect FAIL**

```powershell
cd .; pytest tests/test_api.py -v
```

Expected failure: a collection-time import error such as `ModuleNotFoundError: No module named 'backend.app.api'` or `ImportError: cannot import name 'api_router' from 'backend.app.api'` — or, if Task 1 left a scaffold `create_app`, `TypeError: create_app() got an unexpected keyword argument 'settings'` / assertion failures like `assert 404 == 200` because the profile routes do not exist. Any of these confirms the tests fail before implementation.

- [ ] **Step 3: Implement the profiles router and rewrite main.py**

First make sure `python-multipart` is installed and recorded (idempotent):

```powershell
cd .
if (-not (Select-String -Path requirements.txt -Pattern "python-multipart" -Quiet)) { Add-Content requirements.txt "python-multipart" }
pip install python-multipart
```

Create `backend/app/api/__init__.py` (cycle-A version; the applications/settings routers are added in later cycles of this task):

```python
"""API router aggregation. All routes live under the /api prefix."""
from __future__ import annotations

from fastapi import APIRouter

from . import profiles

api_router = APIRouter(prefix="/api")


@api_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


api_router.include_router(profiles.router)
```

Create `backend/app/api/profiles.py`:

```python
"""Profile CRUD, source-document upload, and master-profile build routes."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import (
    Profile,
    SourceDocument,
    get_contact,
    get_master_profile,
    set_contact,
    set_master_profile,
)
from ..schemas import Contact, MasterProfile
from ..services import intake

router = APIRouter()


class ProfileCreate(BaseModel):
    name: str
    contact: Optional[Contact] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    contact: Optional[Contact] = None
    master_profile: Optional[MasterProfile] = None


def _has_master_profile(profile: Profile) -> bool:
    mp = get_master_profile(profile)
    return bool(mp.experiences or mp.projects or mp.skills or mp.education)


def profile_detail(session: Session, profile: Profile) -> dict[str, Any]:
    docs = session.exec(
        select(SourceDocument).where(SourceDocument.profile_id == profile.id)
    ).all()
    return {
        "id": profile.id,
        "name": profile.name,
        "contact": get_contact(profile).model_dump(),
        "master_profile": get_master_profile(profile).model_dump(),
        "documents": [
            {"id": d.id, "filename": d.filename, "kind": d.kind} for d in docs
        ],
    }


def _get_profile_or_404(session: Session, profile_id: int) -> Profile:
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return profile


@router.get("/profiles")
def list_profiles(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    profiles = session.exec(select(Profile)).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "contact": get_contact(p).model_dump(),
            "has_master_profile": _has_master_profile(p),
        }
        for p in profiles
    ]


@router.post("/profiles")
def create_profile(
    body: ProfileCreate, session: Session = Depends(get_session)
) -> dict[str, Any]:
    profile = Profile(name=body.name)
    set_contact(profile, body.contact or Contact(name=body.name))
    set_master_profile(profile, MasterProfile())
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile_detail(session, profile)


@router.get("/profiles/{profile_id}")
def get_profile(
    profile_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    profile = _get_profile_or_404(session, profile_id)
    return profile_detail(session, profile)


@router.put("/profiles/{profile_id}")
def update_profile(
    profile_id: int, body: ProfileUpdate, session: Session = Depends(get_session)
) -> dict[str, Any]:
    profile = _get_profile_or_404(session, profile_id)
    if body.name is not None:
        profile.name = body.name
    if body.contact is not None:
        set_contact(profile, body.contact)
    if body.master_profile is not None:
        set_master_profile(profile, body.master_profile)
    profile.updated_at = datetime.utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile_detail(session, profile)


@router.post("/profiles/{profile_id}/documents")
async def add_document(
    profile_id: int, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    _get_profile_or_404(session, profile_id)
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            raise HTTPException(status_code=422, detail="multipart field 'file' is required")
        data = await upload.read()
        filename = upload.filename or "upload.txt"
        kind, text = intake.extract_text(filename, data)
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(
                status_code=422, detail="expected a multipart file or a JSON body"
            )
        text = (body.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="'text' must be a non-empty string")
        filename = body.get("filename") or "pasted.txt"
        kind = "paste"
    doc = SourceDocument(profile_id=profile_id, filename=filename, kind=kind, text=text)
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return {"id": doc.id, "filename": doc.filename, "kind": doc.kind}


@router.post("/profiles/{profile_id}/build")
def build_profile(
    profile_id: int, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    profile = _get_profile_or_404(session, profile_id)
    docs = session.exec(
        select(SourceDocument).where(SourceDocument.profile_id == profile_id)
    ).all()
    if not docs:
        raise HTTPException(status_code=422, detail="upload at least one document first")
    master, contact, usage = intake.build_master_profile(
        [d.text for d in docs], request.app.state.claude
    )
    set_master_profile(profile, master)
    set_contact(profile, contact)
    profile.updated_at = datetime.utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    detail = profile_detail(session, profile)
    detail["usage"] = usage.model_dump()
    return detail
```

Rewrite `backend/app/main.py` completely (this replaces any Task 1 scaffold; `GET /api/health` now lives in `api_router` at the same path with the same body, so earlier health tests keep passing):

```python
"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .config import Settings, get_settings
from .db import get_engine, init_db
from .services.claude import make_claude


def create_app(settings: Settings | None = None, engine=None) -> FastAPI:
    settings = settings or get_settings()
    if engine is None:
        engine = get_engine(settings.data_dir / "tailored.db")
    init_db(engine)

    app = FastAPI(title="Tailored")
    app.state.settings = settings
    app.state.engine = engine
    app.state.claude = make_claude(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            f"http://{settings.host}:{settings.port}",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    return app
```

- [ ] **Step 4: Run the tests — expect PASS**

```powershell
cd .; pytest tests/test_api.py -v
```

Expected: `test_health`, `test_profile_crud`, `test_document_upload_multipart_and_json`, `test_build_master_profile` all pass (4 passed).

- [ ] **Step 5: Commit cycle A**

```powershell
cd .
git add backend/app/api backend/app/main.py tests/test_api.py requirements.txt
git commit -m "feat: profile API routes with document upload and intake build" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

#### Cycle B — application routes (batch, list, detail, paste, regenerate, retry, content, preview, exports)

- [ ] **Step 6: Append failing tests for the application routes**

Append exactly this to the end of `tests/test_api.py`:

```python
def make_application(client, pid: int, **job_kwargs) -> int:
    job = {"url": "https://jobs.example.com/posting", **job_kwargs}
    resp = client.post("/api/applications/batch", json={"profile_id": pid, "jobs": [job]})
    assert resp.status_code == 200, resp.text
    return resp.json()[0]["id"]


def test_batch_creates_applications_and_schedules(client):
    pid = make_profile(client)
    resp = client.post("/api/applications/batch", json={
        "profile_id": pid,
        "jobs": [
            {"url": "https://jobs.example.com/a"},
            {"url": "https://jobs.example.com/b", "depth": "deep", "template": "terminal"},
        ],
        "default_depth": "quick",
    })
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 2
    assert all(item["status"] == "queued" for item in items)
    assert items[0]["depth"] == "quick"        # from default_depth
    assert items[0]["template"] == "slate"     # from user-settings default
    assert items[1]["depth"] == "deep"
    assert items[1]["template"] == "terminal"
    assert items[0]["url"] == "https://jobs.example.com/a"
    assert items[0]["company"] is None and items[0]["title"] is None
    assert items[0]["cost_usd"] == 0.0
    assert items[0]["error_message"] is None

    ids = [item["id"] for item in items]
    assert client.calls["process"] == ids  # one scheduled pipeline call per application

    listing = client.get(f"/api/applications?profile_id={pid}").json()
    assert [row["id"] for row in listing] == sorted(ids, reverse=True)
    assert client.get("/api/applications?profile_id=9999").json() == []

    detail = client.get(f"/api/applications/{ids[0]}").json()
    assert detail["resume"] is None
    assert detail["parsed"] is None
    assert detail["research"] is None
    assert detail["cover_letter_md"] is None
    assert detail["raw_text_present"] is False
    assert client.get("/api/applications/99999").status_code == 404
    assert client.post(
        "/api/applications/batch",
        json={"profile_id": 9999, "jobs": [{"url": "https://x"}]}).status_code == 404


def test_batch_rejects_bad_enums(client):
    pid = make_profile(client)
    bad_depth = client.post("/api/applications/batch", json={
        "profile_id": pid, "jobs": [{"url": "https://x", "depth": "ultra"}]})
    assert bad_depth.status_code == 422
    bad_template = client.post("/api/applications/batch", json={
        "profile_id": pid, "jobs": [{"url": "https://x", "template": "comic-sans"}]})
    assert bad_template.status_code == 422
    assert client.calls["process"] == []  # nothing scheduled on validation failure


def test_paste_schedules_resume_after_paste(client):
    pid = make_profile(client)
    app_id = make_application(client, pid)
    assert client.post(
        f"/api/applications/{app_id}/paste", json={"text": "   "}).status_code == 422
    resp = client.post(
        f"/api/applications/{app_id}/paste", json={"text": "Pasted posting body"})
    assert resp.status_code == 200
    assert client.calls["paste"] == [(app_id, "Pasted posting body")]
    assert client.post(
        "/api/applications/9999/paste", json={"text": "x"}).status_code == 404


def test_regenerate_requires_feedback(client):
    pid = make_profile(client)
    app_id = make_application(client, pid)
    assert client.post(
        f"/api/applications/{app_id}/regenerate", json={"feedback": ""}).status_code == 422
    assert client.post(
        f"/api/applications/{app_id}/regenerate", json={}).status_code == 422
    ok = client.post(
        f"/api/applications/{app_id}/regenerate",
        json={"feedback": "More emphasis on Postgres"})
    assert ok.status_code == 200
    assert client.calls["regenerate"] == [(app_id, "More emphasis on Postgres")]


def test_retry_requeues_and_reschedules(client):
    pid = make_profile(client)
    app_id = make_application(client, pid)
    resp = client.post(f"/api/applications/{app_id}/retry")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["error_message"] is None
    # one schedule from batch creation plus one from the retry
    assert client.calls["process"] == [app_id, app_id]
    assert client.post("/api/applications/99999/retry").status_code == 404


def test_content_edit(client, monkeypatch):
    pid = make_profile(client)
    app_id = make_application(client, pid)

    bad = client.put(
        f"/api/applications/{app_id}/content",
        json={"resume": {"headline": "missing contact"}})
    assert bad.status_code == 422

    exports = []

    def fake_export(application_id, resume, cover_md, contact, template, data_dir,
                    page_size="Letter"):
        out = Path(data_dir) / "exports" / str(application_id)
        out.mkdir(parents=True, exist_ok=True)
        exports.append((application_id, template, page_size))
        return out

    monkeypatch.setattr(render, "export_application", fake_export)
    before = len(client.calls["process"]) + len(client.calls["regenerate"])
    resp = client.put(
        f"/api/applications/{app_id}/content",
        json={"resume": VALID_RESUME, "cover_letter_md": "Dear Northwind team,"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resume"]["headline"] == "Senior Software Engineer"
    assert body["cover_letter_md"] == "Dear Northwind team,"
    assert exports == [(app_id, "slate", "Letter")]
    # editing content never triggers a Claude/pipeline call
    assert len(client.calls["process"]) + len(client.calls["regenerate"]) == before


def test_preview(client, monkeypatch):
    pid = make_profile(client)
    app_id = make_application(client, pid)
    assert client.get(f"/api/applications/{app_id}/preview").status_code == 404

    monkeypatch.setattr(
        render, "export_application",
        lambda *args, **kwargs: Path(client.app.state.settings.data_dir)
        / "exports" / str(app_id))
    client.put(f"/api/applications/{app_id}/content", json={"resume": VALID_RESUME})
    resp = client.get(f"/api/applications/{app_id}/preview")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Avery Kim" in resp.text


def test_export_downloads(client):
    pid = make_profile(client)
    app_id = make_application(client, pid)
    # unknown kind -> 404
    assert client.get(
        f"/api/applications/{app_id}/exports/resume.docx").status_code == 404
    # known kind but not generated yet -> 404
    assert client.get(
        f"/api/applications/{app_id}/exports/resume.pdf").status_code == 404

    export_dir = Path(client.app.state.settings.data_dir) / "exports" / str(app_id)
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "resume.txt").write_text("AVERY KIM", encoding="utf-8")
    ok = client.get(f"/api/applications/{app_id}/exports/resume.txt")
    assert ok.status_code == 200
    assert ok.text == "AVERY KIM"
```

- [ ] **Step 7: Run the tests — expect FAIL**

```powershell
cd .; pytest tests/test_api.py -v
```

Expected: the four cycle-A tests still pass; every new test fails with `assert 404 == 200` (plus the response text `{"detail":"Not Found"}`) because no `/api/applications/...` routes exist yet.

- [ ] **Step 8: Implement the applications router**

Create `backend/app/api/applications.py`:

```python
"""Application routes: batch create, list/detail, paste, regenerate, content edit,
HTML preview, and export downloads."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ValidationError
from sqlmodel import Session, select

from ..config import load_user_settings
from ..db import get_session
from ..models import (
    Application,
    Job,
    Profile,
    ResearchBrief,
    get_contact,
    get_findings,
    get_parsed,
    get_resume,
    set_resume,
)
from ..schemas import ResumeDoc
from ..services import pipeline, render
from ..services.render import TEMPLATES

router = APIRouter()

DEPTHS = ("quick", "standard", "deep")
EXPORT_KINDS = (
    "resume.pdf",
    "resume.html",
    "resume.txt",
    "cover_letter.pdf",
    "cover_letter.txt",
)


# --- Serializers -----------------------------------------------------------


def application_summary(app_row: Application, job: Job) -> dict[str, Any]:
    parsed = get_parsed(job)
    return {
        "id": app_row.id,
        "profile_id": app_row.profile_id,
        "status": app_row.status,
        "version": app_row.version,
        "template": app_row.template,
        "depth": job.depth,
        "url": job.url,
        "company": parsed.company if parsed is not None else None,
        "title": parsed.title if parsed is not None else None,
        "cost_usd": app_row.cost_usd,
        "created_at": app_row.created_at.isoformat(),
        "error_message": app_row.error_message,
    }


def application_detail(
    session: Session, app_row: Application, job: Job
) -> dict[str, Any]:
    detail = application_summary(app_row, job)
    resume = get_resume(app_row)
    parsed = get_parsed(job)
    brief = session.exec(
        select(ResearchBrief)
        .where(ResearchBrief.job_id == job.id)
        .order_by(ResearchBrief.id.desc())
    ).first()
    detail.update(
        {
            "resume": resume.model_dump() if resume is not None else None,
            "cover_letter_md": app_row.cover_letter_md,
            "tailoring_notes": app_row.tailoring_notes,
            "research": get_findings(brief).model_dump() if brief is not None else None,
            "parsed": parsed.model_dump() if parsed is not None else None,
            "raw_text_present": bool(job.raw_text),
        }
    )
    return detail


def _get_app_and_job(session: Session, application_id: int) -> tuple[Application, Job]:
    app_row = session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    job = session.get(Job, app_row.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found for application")
    return app_row, job


# --- Request bodies --------------------------------------------------------


class BatchJobIn(BaseModel):
    url: str
    depth: Optional[str] = None
    template: Optional[str] = None


class BatchRequest(BaseModel):
    profile_id: int
    jobs: list[BatchJobIn]
    default_depth: Optional[str] = None
    default_template: Optional[str] = None


class PasteRequest(BaseModel):
    text: str


class RegenerateRequest(BaseModel):
    feedback: str = ""


class ContentUpdate(BaseModel):
    resume: Optional[dict] = None
    cover_letter_md: Optional[str] = None


# --- Routes ----------------------------------------------------------------


@router.post("/applications/batch")
def create_batch(
    body: BatchRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    profile = session.get(Profile, body.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    if not body.jobs:
        raise HTTPException(status_code=422, detail="jobs must not be empty")

    user_settings = load_user_settings(request.app.state.settings.data_dir)
    fallback_depth = body.default_depth or user_settings.get("default_depth", "standard")
    fallback_template = body.default_template or user_settings.get(
        "default_template", "slate"
    )

    # Validate everything before creating anything (all-or-nothing).
    resolved: list[tuple[str, str, str]] = []
    for j in body.jobs:
        depth = j.depth or fallback_depth
        template = j.template or fallback_template
        if depth not in DEPTHS:
            raise HTTPException(
                status_code=422,
                detail=f"invalid depth {depth!r}; must be one of {list(DEPTHS)}",
            )
        if template not in TEMPLATES:
            raise HTTPException(
                status_code=422,
                detail=f"invalid template {template!r}; must be one of {list(TEMPLATES)}",
            )
        resolved.append((j.url, depth, template))

    results: list[dict[str, Any]] = []
    for url, depth, template in resolved:
        job = Job(url=url, depth=depth)
        session.add(job)
        session.commit()
        session.refresh(job)
        app_row = Application(
            profile_id=body.profile_id, job_id=job.id, template=template, status="queued"
        )
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
        # Schedule through the module attribute so tests can monkeypatch pipeline.
        background_tasks.add_task(pipeline.process_application, app_row.id)
        results.append(application_detail(session, app_row, job))
    return results


@router.get("/applications")
def list_applications(
    profile_id: Optional[int] = None, session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    stmt = select(Application)
    if profile_id is not None:
        stmt = stmt.where(Application.profile_id == profile_id)
    rows = session.exec(stmt.order_by(Application.id.desc())).all()
    out: list[dict[str, Any]] = []
    for app_row in rows:
        job = session.get(Job, app_row.job_id)
        if job is not None:
            out.append(application_summary(app_row, job))
    return out


@router.get("/applications/{application_id}")
def get_application(
    application_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    app_row, job = _get_app_and_job(session, application_id)
    return application_detail(session, app_row, job)


@router.post("/applications/{application_id}/paste")
def paste_text(
    application_id: int,
    body: PasteRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    app_row, job = _get_app_and_job(session, application_id)
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")
    background_tasks.add_task(pipeline.resume_after_paste, app_row.id, body.text)
    return application_detail(session, app_row, job)


@router.post("/applications/{application_id}/regenerate")
def regenerate(
    application_id: int,
    body: RegenerateRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    app_row, job = _get_app_and_job(session, application_id)
    if not body.feedback.strip():
        raise HTTPException(status_code=422, detail="feedback must not be empty")
    background_tasks.add_task(pipeline.regenerate_application, app_row.id, body.feedback)
    return application_detail(session, app_row, job)


@router.post("/applications/{application_id}/retry")
def retry(
    application_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Re-run the full pipeline for a failed (or stuck) application.

    Unlike /regenerate this works even before the posting has been parsed, so
    every error state has a working retry action (spec section 8).
    """
    app_row, job = _get_app_and_job(session, application_id)
    app_row.status = "queued"
    app_row.error_message = None
    app_row.updated_at = datetime.utcnow()
    session.add(app_row)
    session.commit()
    session.refresh(app_row)
    background_tasks.add_task(pipeline.process_application, app_row.id)
    return application_detail(session, app_row, job)


@router.put("/applications/{application_id}/content")
def update_content(
    application_id: int,
    body: ContentUpdate,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    app_row, job = _get_app_and_job(session, application_id)
    if body.resume is not None:
        try:
            resume_doc = ResumeDoc.model_validate(body.resume)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid resume document: {exc}"
            ) from exc
        set_resume(app_row, resume_doc)
    if body.cover_letter_md is not None:
        app_row.cover_letter_md = body.cover_letter_md
    app_row.updated_at = datetime.utcnow()
    session.add(app_row)
    session.commit()
    session.refresh(app_row)

    resume_now = get_resume(app_row)
    if resume_now is not None:
        # Re-export synchronously. No Claude call. Called through the render
        # module attribute so tests can monkeypatch export_application.
        profile = session.get(Profile, app_row.profile_id)
        settings = request.app.state.settings
        user_settings = load_user_settings(settings.data_dir)
        export_dir = render.export_application(
            app_row.id,
            resume_now,
            app_row.cover_letter_md or "",
            get_contact(profile),
            app_row.template,
            settings.data_dir,
            page_size=user_settings.get("page_size", "Letter"),
        )
        app_row.export_dir = str(export_dir)
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
    return application_detail(session, app_row, job)


@router.get("/applications/{application_id}/preview")
def preview(
    application_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    app_row, _job = _get_app_and_job(session, application_id)
    resume = get_resume(app_row)
    if resume is None:
        raise HTTPException(status_code=404, detail="no resume generated yet")
    return HTMLResponse(render.render_resume_html(resume, app_row.template))


@router.get("/applications/{application_id}/exports/{kind}")
def download_export(
    application_id: int,
    kind: str,
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse:
    app_row, _job = _get_app_and_job(session, application_id)
    if kind not in EXPORT_KINDS:
        raise HTTPException(status_code=404, detail=f"unknown export kind {kind!r}")
    if app_row.export_dir:
        base = Path(app_row.export_dir)
    else:
        base = Path(request.app.state.settings.data_dir) / "exports" / str(app_row.id)
    path = base / kind
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"export {kind!r} not generated yet")
    return FileResponse(path, filename=kind)
```

Rewrite `backend/app/api/__init__.py` to include the new router:

```python
"""API router aggregation. All routes live under the /api prefix."""
from __future__ import annotations

from fastapi import APIRouter

from . import applications, profiles

api_router = APIRouter(prefix="/api")


@api_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


api_router.include_router(profiles.router)
api_router.include_router(applications.router)
```

- [ ] **Step 9: Run the tests — expect PASS**

```powershell
cd .; pytest tests/test_api.py -v
```

Expected: all 12 tests pass (4 from cycle A + 8 new).

- [ ] **Step 10: Commit cycle B**

```powershell
cd .
git add backend/app/api tests/test_api.py
git commit -m "feat: application API routes with batch create, content edit, preview, exports" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

#### Cycle C — settings routes

- [ ] **Step 11: Append failing tests for the settings routes**

Append exactly this to the end of `tests/test_api.py`:

```python
def test_settings_round_trip(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json() == {
        "api_key_set": False,      # ANTHROPIC_API_KEY deleted in the fixture
        "fake_mode": True,         # TAILORED_FAKE=1 in the fixture
        "default_template": "slate",
        "default_depth": "standard",
        "page_size": "Letter",
    }

    updated = client.put(
        "/api/settings", json={"default_template": "terminal", "page_size": "A4"})
    assert updated.status_code == 200
    body = updated.json()
    assert body["default_template"] == "terminal"
    assert body["default_depth"] == "standard"
    assert body["page_size"] == "A4"

    again = client.get("/api/settings").json()  # persisted in data/settings.json
    assert again["default_template"] == "terminal"
    assert again["page_size"] == "A4"

    assert client.put(
        "/api/settings", json={"default_depth": "extreme"}).status_code == 422
    assert client.put(
        "/api/settings", json={"default_template": "papyrus"}).status_code == 422
    assert client.put(
        "/api/settings", json={"page_size": "Legal"}).status_code == 422
```

- [ ] **Step 12: Run the tests — expect FAIL**

```powershell
cd .; pytest tests/test_api.py::test_settings_round_trip -v
```

Expected failure: `assert 404 == 200` — `/api/settings` does not exist yet.

- [ ] **Step 13: Implement the settings router and final api_router**

Create `backend/app/api/settings.py`:

```python
"""Settings routes: read/write user defaults, report API-key and fake-mode status."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import load_user_settings, save_user_settings
from ..services.render import TEMPLATES

router = APIRouter()

DEPTHS = ("quick", "standard", "deep")
PAGE_SIZES = ("Letter", "A4")


class SettingsUpdate(BaseModel):
    default_template: Optional[str] = None
    default_depth: Optional[str] = None
    page_size: Optional[str] = None


def _settings_payload(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    user = load_user_settings(settings.data_dir)
    return {
        "api_key_set": bool(settings.anthropic_api_key),
        "fake_mode": settings.fake_mode,
        "default_template": user.get("default_template", "slate"),
        "default_depth": user.get("default_depth", "standard"),
        "page_size": user.get("page_size", "Letter"),
    }


@router.get("/settings")
def read_settings(request: Request) -> dict[str, Any]:
    return _settings_payload(request)


@router.put("/settings")
def write_settings(body: SettingsUpdate, request: Request) -> dict[str, Any]:
    if body.default_template is not None and body.default_template not in TEMPLATES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid template {body.default_template!r}; must be one of {list(TEMPLATES)}",
        )
    if body.default_depth is not None and body.default_depth not in DEPTHS:
        raise HTTPException(
            status_code=422,
            detail=f"invalid depth {body.default_depth!r}; must be one of {list(DEPTHS)}",
        )
    if body.page_size is not None and body.page_size not in PAGE_SIZES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid page size {body.page_size!r}; must be one of {list(PAGE_SIZES)}",
        )
    settings = request.app.state.settings
    current = load_user_settings(settings.data_dir)
    for key in ("default_template", "default_depth", "page_size"):
        value = getattr(body, key)
        if value is not None:
            current[key] = value
    save_user_settings(settings.data_dir, current)
    return _settings_payload(request)
```

Rewrite `backend/app/api/__init__.py` (final version for this task):

```python
"""API router aggregation. All routes live under the /api prefix."""
from __future__ import annotations

from fastapi import APIRouter

from . import applications, profiles, settings

api_router = APIRouter(prefix="/api")


@api_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


api_router.include_router(profiles.router)
api_router.include_router(applications.router)
api_router.include_router(settings.router)
```

- [ ] **Step 14: Run the full API test file and the fast suite — expect PASS**

```powershell
cd .; pytest tests/test_api.py -v
cd .; pytest -m "not pdf"
```

Expected: all 13 tests in `tests/test_api.py` pass, and the whole fast suite stays green.

- [ ] **Step 15: Commit cycle C**

```powershell
cd .
git add backend/app/api tests/test_api.py
git commit -m "feat: settings API routes and full api_router wiring" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 13: Demo seed, static SPA serving, and launcher

**Files**

- Create: `backend/app/demo.py`
- Create: `backend/app/fixtures/demo/profile.json`
- Create: `backend/app/fixtures/demo/job_posting.txt`
- Create: `frontend/dist/index.html` (placeholder; the real build in Task 17 overwrites it)
- Modify: `backend/app/main.py` (two full rewrites shown below — lifespan seeding, then SPA serving)
- Modify: `run.py` (final version, full contents below)
- Test: `tests/test_demo.py`

**Interfaces**

- Consumes:
  - `app.main.create_app(settings, engine)` (Task 12, this section)
  - `app.config`: `Settings`, `get_settings` (Task 1); `app.db`: `get_engine`, `init_db`, `session_scope` (Task 1)
  - `app.models`: `Profile`, `Job`, `Application`, `set_contact`, `set_master_profile` (Task 3)
  - `app.schemas`: `Contact`, `MasterProfile` (Task 2)
  - `app.services.claude`: `make_claude` (Task 4)
  - `app.services.pipeline.process_application` (Task 9)
  - `app.services.render.render_pdf` (Task 10) — wrapped with a placeholder-PDF guard during demo seeding
- Produces:
  - `backend/app/demo.py`: `seed_demo(engine, claude, data_dir) -> None`; `DEMO_JOB_URL = "https://careers.northwindlabs.example/jobs/senior-software-engineer"`; `PDF_PLACEHOLDER = b"%PDF-1.4\n% demo placeholder"`
  - `backend/app/main.py` final: `create_app(settings=None, engine=None)` with lifespan demo seeding (when `settings.fake_mode`) and SPA fallback route; module constant `FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"`
  - `frontend/dist/index.html` placeholder (Task 17's build replaces it)
  - `run.py` final launcher (dotenv, banner, browser timer, uvicorn)

#### Cycle 1 — demo seeding on startup

- [ ] **Step 1: Write failing tests for demo seeding**

Create `tests/test_demo.py` with exactly this content:

```python
"""Demo-mode seeding and SPA serving tests (Task 13). Fully offline."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from backend.app import config
from backend.app.config import Settings
from backend.app.db import get_engine, session_scope
from backend.app.main import create_app
from backend.app.models import Application, Profile
from backend.app.services import render


@pytest.fixture
def demo_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILORED_FAKE", "1")
    monkeypatch.setenv("TAILORED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # The pipeline may consult the cached settings accessor internally; make sure
    # it re-reads the env vars set above.
    if hasattr(config.get_settings, "cache_clear"):
        config.get_settings.cache_clear()
    # Skip Chromium for speed; the demo path must survive render_pdf failure anyway.
    monkeypatch.setattr(
        render,
        "render_pdf",
        lambda html, out_path, page_size="Letter": Path(out_path).write_bytes(
            b"%PDF-1.4\n%test"
        ),
    )
    settings = Settings()
    engine = get_engine(tmp_path / "demo.db")
    return settings, engine


def test_startup_seeds_demo_and_reaches_ready(demo_env):
    settings, engine = demo_env
    app = create_app(settings=settings, engine=engine)
    with TestClient(app) as client:  # context manager -> lifespan/startup runs
        profiles = client.get("/api/profiles").json()
        assert len(profiles) == 1
        assert profiles[0]["has_master_profile"] is True

        apps = client.get("/api/applications").json()
        assert len(apps) == 1
        assert apps[0]["status"] == "ready"
        assert apps[0]["company"] == "Northwind Labs"

        detail = client.get(f"/api/applications/{apps[0]['id']}").json()
        assert detail["resume"] is not None
        assert detail["cover_letter_md"]
        assert detail["raw_text_present"] is True


def test_second_startup_does_not_duplicate(demo_env):
    settings, engine = demo_env
    with TestClient(create_app(settings=settings, engine=engine)):
        pass
    with TestClient(create_app(settings=settings, engine=engine)):
        pass
    with session_scope(engine) as session:
        assert len(session.exec(select(Profile)).all()) == 1
        assert len(session.exec(select(Application)).all()) == 1
```

- [ ] **Step 2: Run the tests — expect FAIL**

```powershell
cd .; pytest tests/test_demo.py -v
```

Expected failure: `assert 0 == 1` style failures (`assert len(profiles) == 1` fails with `len == 0`) because `create_app` has no startup seeding yet. (`app.demo` does not exist yet, but the test file does not import it directly, so failures are assertion failures, not import errors.)

- [ ] **Step 3: Create the demo fixtures, demo.py, and main.py with lifespan seeding**

Create `backend/app/fixtures/demo/profile.json` as a **verbatim copy** of the `contact` and `master_profile` objects from `backend/app/fixtures/intake.json` (Task 4, Step 8c) — i.e. the file is `{"contact": <intake.json contact verbatim>, "master_profile": <intake.json master_profile verbatim>}`. This is mandatory: the demo pipeline verifies the `tailor.json` resume against THIS master profile via `verify_truthfulness`, so companies/titles/start/end dates and education/certification entries must be identical to `intake.json`'s or the seeded demo application lands in status `"error"`. The copy is exactly this content:

```json
{
  "contact": {
    "name": "Jordan Rivera",
    "email": "jordan.rivera@example.com",
    "phone": "+1 (555) 210-4477",
    "location": "Portland, OR",
    "links": [
      {"label": "GitHub", "url": "https://github.com/jordanrivera"},
      {"label": "LinkedIn", "url": "https://www.linkedin.com/in/jordan-rivera-dev"}
    ]
  },
  "master_profile": {
    "summary_notes": "Backend-focused software engineer with 8 years of experience building Python services, REST APIs, and data-heavy systems on PostgreSQL and AWS. Track record of performance work, service decomposition, CI/CD ownership, and mentoring.",
    "experiences": [
      {
        "company": "Cascade Analytics",
        "title": "Senior Software Engineer",
        "start": "2021-03",
        "end": null,
        "location": "Portland, OR",
        "bullets": [
          {
            "text": "Designed and shipped a FastAPI event-ingestion service handling 40M events/day with p99 latency under 120ms",
            "tags": ["python", "fastapi", "apis", "performance", "scalability"]
          },
          {
            "text": "Led decomposition of a monolithic Django app into 6 domain services on PostgreSQL, cutting deploy time from 45 minutes to 8 minutes",
            "tags": ["architecture", "postgresql", "microservices", "leadership"]
          },
          {
            "text": "Introduced contract tests and CI quality gates with pytest and GitHub Actions, reducing production incidents by 35%",
            "tags": ["testing", "ci-cd", "pytest", "reliability"]
          },
          {
            "text": "Mentored 3 junior engineers through weekly design reviews and pairing rotations",
            "tags": ["mentorship", "leadership", "communication"]
          }
        ]
      },
      {
        "company": "Brightline Software",
        "title": "Software Engineer",
        "start": "2018-06",
        "end": "2021-02",
        "location": "Seattle, WA",
        "bullets": [
          {
            "text": "Built Flask REST APIs powering a customer billing portal used by 12,000 accounts",
            "tags": ["python", "flask", "apis", "billing"]
          },
          {
            "text": "Optimized slow PostgreSQL reporting queries, cutting nightly batch runtime from 4 hours to 50 minutes",
            "tags": ["postgresql", "sql", "performance"]
          },
          {
            "text": "Containerized 9 legacy services with Docker and built the Compose-based local development environment",
            "tags": ["docker", "devops", "developer-experience"]
          },
          {
            "text": "Implemented Stripe webhook processing with idempotent handlers and dead-letter retries",
            "tags": ["payments", "stripe", "reliability", "event-driven"]
          }
        ]
      }
    ],
    "projects": [
      {
        "name": "queuelite",
        "description": "Open-source lightweight Python task queue backed by SQLite",
        "url": "https://github.com/jordanrivera/queuelite",
        "bullets": [
          {
            "text": "Built a polling worker with visibility timeouts and at-least-once delivery guarantees",
            "tags": ["python", "concurrency", "sqlite", "queues"]
          },
          {
            "text": "Published to PyPI with full type hints; 400+ GitHub stars",
            "tags": ["open-source", "python"]
          }
        ]
      }
    ],
    "skills": [
      {
        "label": "Languages & Frameworks",
        "items": ["Python", "TypeScript", "SQL", "FastAPI", "Flask"]
      },
      {
        "label": "Infrastructure & Tools",
        "items": ["PostgreSQL", "Docker", "GitHub Actions", "Redis", "AWS (ECS, S3, RDS)"]
      }
    ],
    "education": [
      {
        "institution": "University of Washington",
        "credential": "B.S. Computer Science",
        "year": "2018",
        "detail": "Focus in distributed systems"
      }
    ],
    "certifications": [
      {
        "name": "AWS Certified Developer - Associate",
        "issuer": "Amazon Web Services",
        "year": "2023"
      }
    ],
    "extras": [
      "Speaker, PyCascades 2024: \"SQLite in Production\"",
      "Maintainer of two pytest plugins"
    ]
  }
}
```

Create `backend/app/fixtures/demo/job_posting.txt`. **ALIGNMENT REQUIREMENT:** company and title must match `backend/app/fixtures/parse_posting.json` (Task 4) — Northwind Labs / Senior Software Engineer; adjust the heading lines if that fixture differs. Content:

```text
Senior Software Engineer (Backend)
Northwind Labs - Seattle, WA (Hybrid) or Remote (US)

About Northwind Labs
Northwind Labs builds analytics infrastructure that helps mid-market retailers
make inventory and pricing decisions in real time. Our platform ingests
point-of-sale, e-commerce, and supply-chain events and turns them into
forecasts our customers act on every day. We are a 120-person, profitable
company growing the engineering team from 30 to 45 this year.

The Role
We are hiring a Senior Software Engineer for the Data Platform team. You will
own services on the ingestion path, work closely with our data scientists, and
raise the bar for reliability and engineering practice across the team.

What you'll do
- Design, build, and operate Python services (FastAPI) that ingest and
  validate high-volume event streams
- Evolve our PostgreSQL schemas and query patterns as data volume grows
- Improve reliability of our Airflow-orchestrated batch pipelines
- Champion testing and CI/CD practices across the team
- Mentor mid-level engineers and lead design reviews

What we're looking for
- 5+ years of professional software engineering experience
- Expert-level Python; production experience with FastAPI, Django, or Flask
- Strong SQL and PostgreSQL experience
- Experience operating services in AWS (ECS, Lambda, RDS, or similar)
- Experience with CI/CD pipelines and infrastructure as code
- Clear written communication; comfort working with distributed teammates

Nice to have
- Airflow or similar workflow orchestration experience
- Experience with Redis, RabbitMQ, or Kafka
- Open-source contributions
- TypeScript/React familiarity for occasional internal tooling

Compensation and benefits
$165,000 - $205,000 base depending on experience, plus equity, 401(k) match,
full medical/dental/vision, and a $1,500 annual learning budget.

Northwind Labs is an equal opportunity employer. We welcome applicants of all
backgrounds and do not discriminate on any protected basis.

How to apply
Apply at careers.northwindlabs.example with a resume. A short cover note about
a system you have operated at scale is appreciated.
```

Create `backend/app/demo.py`:

```python
"""Demo-mode seeding: one profile plus one fully processed application.

Runs only when settings.fake_mode is on and the database has no Profile rows.
Fully offline: the injected fake ClaudeService serves canned fixtures, and PDF
rendering falls back to a placeholder file when Chromium is unavailable, so the
demo never hard-fails without `playwright install chromium`.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import select

from .db import session_scope
from .models import Application, Job, Profile, set_contact, set_master_profile
from .schemas import Contact, MasterProfile
from .services import claude as claude_service
from .services import pipeline, render

DEMO_DIR = Path(__file__).resolve().parent / "fixtures" / "demo"
DEMO_JOB_URL = "https://careers.northwindlabs.example/jobs/senior-software-engineer"
PDF_PLACEHOLDER = b"%PDF-1.4\n% demo placeholder"


def seed_demo(engine, claude, data_dir) -> None:
    """Seed the demo profile + application and run the pipeline to 'ready'."""
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    with session_scope(engine) as session:
        if session.exec(select(Profile)).first() is not None:
            return

        payload = json.loads((DEMO_DIR / "profile.json").read_text(encoding="utf-8"))
        contact = Contact.model_validate(payload["contact"])
        master = MasterProfile.model_validate(payload["master_profile"])
        profile = Profile(name=contact.name)
        set_contact(profile, contact)
        set_master_profile(profile, master)
        session.add(profile)
        session.commit()
        session.refresh(profile)

        posting_text = (DEMO_DIR / "job_posting.txt").read_text(encoding="utf-8")
        job = Job(
            url=DEMO_JOB_URL,
            raw_text=posting_text,
            fetch_status="pasted",
            depth="standard",
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        app_row = Application(
            profile_id=profile.id, job_id=job.id, template="slate", status="queued"
        )
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
        application_id = app_row.id

    _run_pipeline_with_fake_claude(application_id, engine, claude)


def _run_pipeline_with_fake_claude(application_id: int, engine, claude) -> None:
    """Run process_application with the injected ClaudeService and a guarded render_pdf.

    - render.render_pdf is temporarily wrapped: any exception (missing Chromium)
      writes PDF_PLACEHOLDER bytes instead of failing the demo.
    - make_claude is temporarily overridden (on the claude service module and, if
      pipeline bound it by from-import, on the pipeline module) so the pipeline
      uses the injected fake service regardless of env.
    """
    original_render_pdf = render.render_pdf

    def guarded_render_pdf(html: str, out_path, page_size: str = "Letter") -> None:
        try:
            original_render_pdf(html, out_path, page_size=page_size)
        except Exception:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(PDF_PLACEHOLDER)

    patched_factories = []
    for module in (claude_service, pipeline):
        if hasattr(module, "make_claude"):
            patched_factories.append((module, module.make_claude))
            setattr(module, "make_claude", lambda _settings, _c=claude: _c)

    render.render_pdf = guarded_render_pdf
    try:
        pipeline.process_application(application_id, engine=engine)
    finally:
        render.render_pdf = original_render_pdf
        for module, original in patched_factories:
            setattr(module, "make_claude", original)
```

Rewrite `backend/app/main.py` (adds lifespan seeding; the SPA route arrives in cycle 2):

```python
"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import demo
from .api import api_router
from .config import Settings, get_settings
from .db import get_engine, init_db
from .services.claude import make_claude


def create_app(settings: Settings | None = None, engine=None) -> FastAPI:
    settings = settings or get_settings()
    if engine is None:
        engine = get_engine(settings.data_dir / "tailored.db")
    init_db(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.fake_mode:
            demo.seed_demo(engine, app.state.claude, settings.data_dir)
        yield

    app = FastAPI(title="Tailored", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.claude = make_claude(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            f"http://{settings.host}:{settings.port}",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    return app
```

- [ ] **Step 4: Run the tests — expect PASS**

```powershell
cd .; pytest tests/test_demo.py tests/test_api.py -v
```

Expected: both demo tests pass AND all 13 `test_api.py` tests still pass (`test_api.py` uses a plain `TestClient` without a context manager, so the new startup seeding never runs there).

- [ ] **Step 5: Commit cycle 1**

```powershell
cd .
git add backend/app/demo.py backend/app/fixtures/demo backend/app/main.py tests/test_demo.py
git commit -m "feat: offline demo seeding on startup in fake mode" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

#### Cycle 2 — SPA static serving, placeholder frontend build, launcher

- [ ] **Step 6: Append failing test for SPA fallback + API passthrough**

Append exactly this to the end of `tests/test_demo.py`:

```python
def test_spa_fallback_and_api_passthrough(demo_env):
    settings, engine = demo_env
    app = create_app(settings=settings, engine=engine)
    with TestClient(app) as client:
        page = client.get("/applications/1")   # SPA route -> index.html
        assert page.status_code == 200
        assert "Tailored" in page.text

        root = client.get("/")                 # root also serves index.html
        assert root.status_code == 200
        assert "Tailored" in root.text

        assert client.get("/api/nope").status_code == 404  # api never falls back
```

- [ ] **Step 7: Run the test — expect FAIL**

```powershell
cd .; pytest tests/test_demo.py::test_spa_fallback_and_api_passthrough -v
```

Expected failure: `assert 404 == 200` — no catch-all route exists yet, so `/applications/1` returns FastAPI's default 404.

- [ ] **Step 8: Implement SPA serving, the placeholder dist, and the final launcher**

Create `frontend/dist/index.html` with exactly this content (Task 17's real Vite build overwrites this file):

```html
<html><body>Tailored — frontend build pending</body></html>
```

Verify the placeholder is not gitignored (the committed build is a hard requirement):

```powershell
cd .; git check-ignore -v frontend/dist/index.html
```

Expected: no output, exit code 1. If a rule prints, edit `.gitignore` so `frontend/dist/` is NOT excluded (e.g. remove the rule or add a `!frontend/dist/` exception) before continuing.

Rewrite `backend/app/main.py` (final version):

```python
"""FastAPI application factory: API routes, demo seeding, SPA static serving."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from . import demo
from .api import api_router
from .config import Settings, get_settings
from .db import get_engine, init_db
from .services.claude import make_claude

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(settings: Settings | None = None, engine=None) -> FastAPI:
    settings = settings or get_settings()
    if engine is None:
        engine = get_engine(settings.data_dir / "tailored.db")
    init_db(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.fake_mode:
            demo.seed_demo(engine, app.state.claude, settings.data_dir)
        yield

    app = FastAPI(title="Tailored", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.claude = make_claude(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            f"http://{settings.host}:{settings.port}",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    # SPA static serving with fallback. Registered AFTER api_router, so every
    # /api/* route resolves first; unknown /api paths 404 instead of serving HTML.
    @app.get("/{path:path}")
    def serve_spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        dist = FRONTEND_DIST.resolve()
        if dist.is_dir():
            if path:
                candidate = (dist / path).resolve()
                # Serve real build assets; refuse path traversal outside dist.
                if candidate.is_file() and str(candidate).startswith(str(dist)):
                    return FileResponse(candidate)
            index = dist / "index.html"
            if index.is_file():
                return FileResponse(index)
        return PlainTextResponse("frontend not built", status_code=200)

    return app
```

Rewrite `run.py` (final version):

```python
"""Tailored launcher: loads .env, starts the server, opens the browser.

Usage: python run.py
"""
from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# No sys.path manipulation: `python run.py` from the project root already puts
# the root on sys.path, and the backend package is only ever imported as
# `backend.app.*` (matching Task 1's run.py, conftest.py, and every test).
PROJECT_ROOT = Path(__file__).resolve().parent


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    from backend.app.config import get_settings
    from backend.app.main import create_app

    settings = get_settings()
    url = f"http://{settings.host}:{settings.port}"
    print("=" * 62)
    print("  Tailored — AI Resume & Cover Letter Builder")
    print(f"  Open {url} in your browser (opening automatically...)")
    print("  Press Ctrl+C to stop.")
    print("=" * 62)
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 9: Run the demo tests and the full fast suite — expect PASS**

```powershell
cd .; pytest tests/test_demo.py -v
cd .; pytest -m "not pdf"
```

Expected: all 3 tests in `tests/test_demo.py` pass; the entire fast suite is green. As a manual smoke check (optional, requires nothing but Python): `$env:TAILORED_FAKE = "1"; python run.py` should print the banner, open the browser to the placeholder page, and `GET /api/applications` should show one `ready` demo application; stop with Ctrl+C and `Remove-Item Env:TAILORED_FAKE`.

- [ ] **Step 10: Commit cycle 2**

```powershell
cd .
git add backend/app/main.py frontend/dist/index.html run.py tests/test_demo.py
git commit -m "feat: SPA static serving, placeholder frontend build, and launcher" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

# Section 06 — Frontend (Tasks 14–17)

All paths relative to the project root `.` unless absolute. All `npm` commands run from `frontend/`; every command below `cd`s there explicitly because the executor's cwd resets between calls. Node.js is a dev-only dependency; the built `frontend/dist/` is committed in Task 17 (NOT earlier).

App.tsx ships with inline placeholder screen components in Task 14 so the app compiles before the screens exist. Tasks 15–16 create screen files (tests import them directly, so App.tsx does not need them yet). Task 17 replaces the placeholders with real imports of all five screens.

---

### Task 14: Frontend scaffold

**Files**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/test-setup.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`
- Modify: `.gitignore` (ensure `node_modules/` ignored; `frontend/dist/` must NOT be ignored)
- Test: `frontend/src/App.test.tsx`

**Interfaces**
- Consumes: the API route table from the contract (`/api/...` routes, Task 12); enums Depth / Template / AppStatus / page size / export kinds (contract "Enums / literals").
- Produces:
  - `frontend/src/types.ts` exports: `Depth`, `TemplateName`, `AppStatus`, `PageSize`, `ExportKind`, `LinkItem`, `Contact`, `TaggedBullet`, `MPExperience`, `MPProject`, `SkillGroup`, `MPEducation`, `MPCertification`, `MasterProfile`, `ParsedPosting`, `ResearchFindings`, `ExperienceItem`, `ProjectItem`, `EducationItem`, `CertificationItem`, `ExperienceSection`, `ProjectsSection`, `SkillsSection`, `EducationSection`, `CertificationsSection`, `ExtrasSection`, `ResumeSection`, `ResumeDoc`, `UsageInfo`, `DocumentInfo`, `ProfileSummary`, `ProfileDetail`, `ApplicationSummary`, `ApplicationDetail`, `SettingsShape`, `JobRequest`.
  - `frontend/src/api.ts` exports: `listProfiles`, `createProfile`, `getProfile`, `updateProfile`, `uploadDocument`, `buildProfile`, `createApplications`, `listApplications`, `getApplication`, `pasteJobText`, `updateContent`, `regenerate`, `getSettings`, `updateSettings`, `previewUrl(id: number): string`, `exportUrl(id: number, kind: ExportKind): string`.
  - `frontend/src/styles.css` classes used by all screens: `.shell`, `.nav`, `.nav-inner`, `.nav-brand`, `.nav-link`, `.card`, `.card-title`, `.btn`, `.btn-primary`, `.btn-ghost`, `.btn-danger`, `.table`, `.badge`, `.badge-queued`, `.badge-fetching`, `.badge-researching`, `.badge-tailoring`, `.badge-rendering`, `.badge-ready`, `.badge-needs_paste`, `.badge-error`, `.field`, `.field-label`, `.input`, `.select`, `.textarea`, `.row`, `.tabs`, `.tab`, `.tab.active`, `.chip`, `.alert`, `.alert-error`, `.callout`, `.pill`, `.pill-ok`, `.pill-warn`, `.cover-md`, `.spinner`, `.muted`, `.mono`.
  - `frontend/src/App.tsx` default export `App` (nav shell + routes; placeholder screens inline).

- [ ] **Step 1: Create the frontend scaffold config files**

`frontend/package.json`:

```json
{
  "name": "tailored-frontend",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "test": "vitest run",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@testing-library/dom": "^10.4.0",
    "@testing-library/jest-dom": "^6.4.8",
    "@testing-library/react": "^16.0.0",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^24.1.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0",
    "vitest": "^2.0.5"
  }
}
```

`frontend/vite.config.ts`:

```ts
/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8547",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.ts",
  },
});
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "types": ["vitest/globals"]
  },
  "include": ["src"]
}
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Tailored</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/test-setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 2: Install dependencies and ensure node_modules is gitignored**

```powershell
cd frontend; npm install
cd .; if (-not (Select-String -Path .gitignore -Pattern "node_modules" -Quiet)) { Add-Content .gitignore "node_modules/" }
```

`npm install` must exit 0 and produce `frontend/package-lock.json` and `frontend/node_modules/`. Verify `frontend/dist` is NOT matched by `.gitignore` (`git check-ignore frontend/dist` from the project root must print nothing and exit with code 1) — the built dist gets committed in Task 17.

- [ ] **Step 3: Write the failing test** — `frontend/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

describe("App shell", () => {
  it("renders the brand and all nav links", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText("Tailored")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Add Jobs" })).toHaveAttribute("href", "/add");
    expect(screen.getByRole("link", { name: "Profiles" })).toHaveAttribute("href", "/profiles");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });

  it("renders the Dashboard placeholder on /", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });
});
```

(The nav also contains a link named "Dashboard", so the placeholder assertion queries by `heading` role to stay unambiguous. `getByText("Tailored")` matches only the brand link.)

- [ ] **Step 4: Run the test, expect FAIL**

```powershell
cd frontend; npm test
```

Expected failure: `Error: Failed to resolve import "./App" from "src/App.test.tsx". Does the file exist?`

- [ ] **Step 5: Write the implementation — styles, types, api client, entry point, App shell**

`frontend/src/styles.css` (complete design system):

```css
/* ===== Tailored design system ===== */

:root {
  --bg: #FAFAF9;
  --surface: #FFFFFF;
  --ink: #1C1917;
  --muted: #78716C;
  --accent: #0F766E;
  --accent-soft: #CCFBF1;
  --danger: #B91C1C;
  --danger-soft: #FEE2E2;
  --border: #E7E5E4;
  --radius: 8px;
  --shadow: 0 1px 3px rgba(28, 25, 23, 0.08);
  --font-sans: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
  --font-mono: Consolas, "SFMono-Regular", Menlo, monospace;
  /* type scale */
  --fs-xs: 0.75rem;
  --fs-sm: 0.875rem;
  --fs-base: 1rem;
  --fs-lg: 1.25rem;
  --fs-xl: 1.5rem;
  --fs-2xl: 2rem;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-sans);
  font-size: var(--fs-base);
  line-height: 1.55;
}

h1 { font-size: var(--fs-2xl); font-weight: 700; letter-spacing: -0.02em; margin: 1.5rem 0 1rem; }
h2 { font-size: var(--fs-xl); font-weight: 650; letter-spacing: -0.01em; margin: 1.25rem 0 0.75rem; }
h3 { font-size: var(--fs-lg); font-weight: 600; margin: 1rem 0 0.5rem; }
a { color: var(--accent); }
.muted { color: var(--muted); font-size: var(--fs-sm); }
.mono { font-family: var(--font-mono); }

/* ---- shell + nav ---- */
.shell { max-width: 1100px; margin: 0 auto; padding: 0 1.25rem 4rem; }

.nav { background: var(--surface); border-bottom: 1px solid var(--border); }
.nav-inner {
  max-width: 1100px; margin: 0 auto;
  display: flex; align-items: center; gap: 1.5rem;
  padding: 0.75rem 1.25rem;
}
.nav-brand {
  font-size: var(--fs-lg); font-weight: 750; letter-spacing: -0.03em;
  color: var(--accent); text-decoration: none; margin-right: 0.5rem;
}
.nav-link {
  color: var(--muted); text-decoration: none;
  font-size: var(--fs-sm); font-weight: 550; padding: 0.25rem 0;
  border-bottom: 2px solid transparent;
}
.nav-link:hover { color: var(--ink); }
.nav-link.active { color: var(--ink); border-bottom-color: var(--accent); }

/* ---- surfaces ---- */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 1.25rem;
  margin-bottom: 1.25rem;
}
.card-title {
  font-size: var(--fs-sm); font-weight: 650; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted); margin: 0 0 0.75rem;
}

/* ---- buttons ---- */
.btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  font: inherit; font-size: var(--fs-sm); font-weight: 600;
  padding: 0.45rem 0.9rem; border-radius: var(--radius);
  border: 1px solid var(--border); background: var(--surface); color: var(--ink);
  cursor: pointer;
}
.btn:hover { border-color: var(--muted); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: var(--accent); border-color: var(--accent); color: #FFFFFF; }
.btn-primary:hover { background: #0D655E; border-color: #0D655E; }
.btn-ghost { background: transparent; border-color: transparent; color: var(--accent); }
.btn-ghost:hover { background: var(--accent-soft); border-color: transparent; }
.btn-danger { background: transparent; border-color: var(--danger); color: var(--danger); }
.btn-danger:hover { background: var(--danger-soft); }

/* ---- table ---- */
.table { width: 100%; border-collapse: collapse; background: var(--surface); }
.table th {
  text-align: left; font-size: var(--fs-xs); text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted); font-weight: 650;
  padding: 0.6rem 0.75rem; border-bottom: 2px solid var(--border);
}
.table td { padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--border); font-size: var(--fs-sm); }
.table tr:hover td { background: var(--bg); }

/* ---- status badges (one distinct hue per status) ---- */
.badge {
  display: inline-block; font-size: var(--fs-xs); font-weight: 650;
  padding: 0.15rem 0.55rem; border-radius: 999px; white-space: nowrap;
  text-decoration: none;
}
.badge-queued      { background: #F5F5F4; color: #57534E; }  /* stone */
.badge-fetching    { background: #DBEAFE; color: #1D4ED8; }  /* blue */
.badge-researching { background: #EDE9FE; color: #6D28D9; }  /* violet */
.badge-tailoring   { background: #FEF3C7; color: #B45309; }  /* amber */
.badge-rendering   { background: #CFFAFE; color: #0E7490; }  /* cyan */
.badge-ready       { background: #D1FAE5; color: #047857; }  /* green */
.badge-needs_paste { background: #FFEDD5; color: #C2410C; }  /* orange */
.badge-error       { background: #FEE2E2; color: #B91C1C; }  /* red */

/* ---- forms ---- */
.field { display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 0.75rem; }
.field-label { font-size: var(--fs-xs); font-weight: 650; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.input, .select, .textarea {
  font: inherit; font-size: var(--fs-sm); color: var(--ink);
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 0.45rem 0.6rem; width: 100%;
}
.input:focus, .select:focus, .textarea:focus {
  outline: 2px solid var(--accent-soft); border-color: var(--accent);
}
.textarea { min-height: 6rem; resize: vertical; font-family: inherit; }
.row { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.5rem; }
.row > .input, .row > .select { width: auto; flex: 1 1 8rem; }

/* ---- tabs ---- */
.tabs { display: flex; gap: 0.25rem; border-bottom: 2px solid var(--border); margin: 1rem 0 1.25rem; }
.tab {
  font: inherit; font-size: var(--fs-sm); font-weight: 600; color: var(--muted);
  background: none; border: none; cursor: pointer;
  padding: 0.5rem 0.9rem; margin-bottom: -2px; border-bottom: 2px solid transparent;
}
.tab:hover { color: var(--ink); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }

/* ---- misc ---- */
.chip {
  display: inline-block; font-size: var(--fs-xs); font-weight: 550;
  background: var(--accent-soft); color: var(--accent);
  padding: 0.15rem 0.55rem; border-radius: 999px; margin: 0 0.3rem 0.3rem 0;
}
.alert {
  border: 1px solid var(--border); border-left: 4px solid var(--accent);
  background: var(--surface); border-radius: var(--radius);
  padding: 0.75rem 1rem; margin-bottom: 1rem; font-size: var(--fs-sm);
}
.alert-error { border-left-color: var(--danger); background: var(--danger-soft); color: var(--danger); }
.callout {
  background: var(--accent-soft); border-radius: var(--radius);
  padding: 0.75rem 1rem; font-size: var(--fs-sm); margin-bottom: 1rem;
}
.pill {
  display: inline-block; font-size: var(--fs-xs); font-weight: 650;
  padding: 0.2rem 0.7rem; border-radius: 999px;
}
.pill-ok { background: #D1FAE5; color: #047857; }
.pill-warn { background: #FEF3C7; color: #B45309; }
.cover-md {
  white-space: pre-wrap; font-family: var(--font-sans); font-size: var(--fs-sm);
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1.25rem; line-height: 1.7;
}
.preview-frame {
  width: 100%; height: 75vh; border: 1px solid var(--border);
  border-radius: var(--radius); background: #FFFFFF;
}
.spinner {
  display: inline-block; width: 1em; height: 1em;
  border: 2px solid var(--accent-soft); border-top-color: var(--accent);
  border-radius: 50%; animation: spin 0.8s linear infinite; vertical-align: -0.15em;
}
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 640px) {
  .nav-inner { flex-wrap: wrap; gap: 0.75rem; }
  .row { flex-direction: column; align-items: stretch; }
}
```

`frontend/src/types.ts` (complete TS mirrors of the backend schemas — field names identical to backend JSON):

```ts
// ---- enums / literals (verbatim from the backend contract) ----
export type Depth = "quick" | "standard" | "deep";
export type TemplateName = "meridian" | "slate" | "terminal" | "signal";
export type AppStatus =
  | "queued"
  | "fetching"
  | "researching"
  | "tailoring"
  | "rendering"
  | "ready"
  | "needs_paste"
  | "error";
export type PageSize = "Letter" | "A4";
export type ExportKind =
  | "resume.pdf"
  | "resume.html"
  | "resume.txt"
  | "cover_letter.pdf"
  | "cover_letter.txt";

// ---- contact ----
export interface LinkItem {
  label: string;
  url: string;
}

export interface Contact {
  name: string;
  email: string;
  phone?: string | null;
  location?: string | null;
  links: LinkItem[];
}

// ---- master profile ----
export interface TaggedBullet {
  text: string;
  tags: string[];
}

export interface MPExperience {
  company: string;
  title: string;
  start: string;
  end?: string | null;
  location?: string | null;
  bullets: TaggedBullet[];
}

export interface MPProject {
  name: string;
  description: string;
  url?: string | null;
  bullets: TaggedBullet[];
}

export interface SkillGroup {
  label: string;
  items: string[];
}

export interface MPEducation {
  institution: string;
  credential: string;
  year?: string | null;
  detail?: string | null;
}

export interface MPCertification {
  name: string;
  issuer?: string | null;
  year?: string | null;
}

export interface MasterProfile {
  summary_notes: string;
  experiences: MPExperience[];
  projects: MPProject[];
  skills: SkillGroup[];
  education: MPEducation[];
  certifications: MPCertification[];
  extras: string[];
}

// ---- posting analysis + research ----
export interface ParsedPosting {
  title: string;
  company: string;
  company_domain?: string | null;
  must_haves: string[];
  nice_to_haves: string[];
  keywords: string[];
  seniority?: string | null;
  tone?: string | null;
}

export interface ResearchFindings {
  mission: string;
  products: string[];
  news: string[];
  tech_stack_signals: string[];
  culture_language: string[];
  sources: string[];
}

// ---- resume document (renderer contract) ----
export interface ExperienceItem {
  company: string;
  role: string;
  start: string;
  end?: string | null;
  location?: string | null;
  bullets: string[];
}

export interface ProjectItem {
  name: string;
  description: string;
  url?: string | null;
  bullets: string[];
}

export interface EducationItem {
  institution: string;
  credential: string;
  year?: string | null;
  detail?: string | null;
}

export interface CertificationItem {
  name: string;
  issuer?: string | null;
  year?: string | null;
}

export interface ExperienceSection {
  type: "experience";
  title: string;
  items: ExperienceItem[];
}

export interface ProjectsSection {
  type: "projects";
  title: string;
  items: ProjectItem[];
}

export interface SkillsSection {
  type: "skills";
  title: string;
  groups: SkillGroup[];
}

export interface EducationSection {
  type: "education";
  title: string;
  items: EducationItem[];
}

export interface CertificationsSection {
  type: "certifications";
  title: string;
  items: CertificationItem[];
}

export interface ExtrasSection {
  type: "extras";
  title: string;
  items: string[];
}

export type ResumeSection =
  | ExperienceSection
  | ProjectsSection
  | SkillsSection
  | EducationSection
  | CertificationsSection
  | ExtrasSection;

export interface ResumeDoc {
  contact: Contact;
  headline: string;
  summary: string;
  sections: ResumeSection[];
}

// ---- API payload shapes ----
export interface UsageInfo {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface DocumentInfo {
  id: number;
  filename: string;
  kind: string;
}

export interface ProfileSummary {
  id: number;
  name: string;
  contact: Contact;
  has_master_profile: boolean;
}

export interface ProfileDetail {
  id: number;
  name: string;
  contact: Contact;
  master_profile: MasterProfile;
  documents: DocumentInfo[];
  usage?: UsageInfo;
}

export interface ApplicationSummary {
  id: number;
  profile_id: number;
  status: AppStatus;
  version: number;
  template: TemplateName;
  depth: Depth;
  url: string;
  company: string | null; // null until the posting is parsed (queued/fetching/needs_paste)
  title: string | null; // null until the posting is parsed
  cost_usd: number;
  created_at: string;
  error_message?: string | null;
}

export interface ApplicationDetail extends ApplicationSummary {
  resume: ResumeDoc | null;
  cover_letter_md: string | null;
  tailoring_notes: string | null;
  research: ResearchFindings | null;
  parsed: ParsedPosting | null;
  raw_text_present: boolean;
}

export interface SettingsShape {
  api_key_set: boolean;
  fake_mode: boolean;
  default_template: TemplateName;
  default_depth: Depth;
  page_size: PageSize;
}

export interface JobRequest {
  url: string;
  depth?: Depth;
  template?: TemplateName;
}
```

`frontend/src/api.ts` (complete typed client):

```ts
import type {
  ApplicationDetail,
  ApplicationSummary,
  Contact,
  Depth,
  DocumentInfo,
  ExportKind,
  JobRequest,
  MasterProfile,
  PageSize,
  ProfileDetail,
  ProfileSummary,
  ResumeDoc,
  SettingsShape,
  TemplateName,
} from "./types";

const API = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") {
        detail = body.detail;
      } else if (body) {
        detail = JSON.stringify(body);
      }
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

// ---- profiles ----

export function listProfiles(): Promise<ProfileSummary[]> {
  return request<ProfileSummary[]>("/profiles");
}

export function createProfile(name: string, contact?: Contact): Promise<ProfileDetail> {
  return request<ProfileDetail>("/profiles", jsonInit("POST", { name, contact }));
}

export function getProfile(id: number): Promise<ProfileDetail> {
  return request<ProfileDetail>(`/profiles/${id}`);
}

export function updateProfile(
  id: number,
  patch: { name?: string; contact?: Contact; master_profile?: MasterProfile }
): Promise<ProfileDetail> {
  return request<ProfileDetail>(`/profiles/${id}`, jsonInit("PUT", patch));
}

export function uploadDocument(
  profileId: number,
  source: File | { filename: string; text: string }
): Promise<DocumentInfo> {
  if (source instanceof File) {
    const form = new FormData();
    form.append("file", source);
    return request<DocumentInfo>(`/profiles/${profileId}/documents`, {
      method: "POST",
      body: form,
    });
  }
  return request<DocumentInfo>(`/profiles/${profileId}/documents`, jsonInit("POST", source));
}

export function buildProfile(id: number): Promise<ProfileDetail> {
  return request<ProfileDetail>(`/profiles/${id}/build`, { method: "POST" });
}

// ---- applications ----

export function createApplications(
  profileId: number,
  jobs: JobRequest[],
  defaultDepth?: Depth,
  defaultTemplate?: TemplateName
): Promise<ApplicationDetail[]> {
  return request<ApplicationDetail[]>(
    "/applications/batch",
    jsonInit("POST", {
      profile_id: profileId,
      jobs,
      default_depth: defaultDepth,
      default_template: defaultTemplate,
    })
  );
}

export function listApplications(profileId?: number): Promise<ApplicationSummary[]> {
  const qs = profileId !== undefined ? `?profile_id=${profileId}` : "";
  return request<ApplicationSummary[]>(`/applications${qs}`);
}

export function getApplication(id: number): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}`);
}

export function pasteJobText(id: number, text: string): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/paste`, jsonInit("POST", { text }));
}

export function updateContent(
  id: number,
  patch: { resume?: ResumeDoc; cover_letter_md?: string }
): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/content`, jsonInit("PUT", patch));
}

export function regenerate(id: number, feedback: string): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(
    `/applications/${id}/regenerate`,
    jsonInit("POST", { feedback })
  );
}

// ---- settings ----

export function getSettings(): Promise<SettingsShape> {
  return request<SettingsShape>("/settings");
}

export function updateSettings(patch: {
  default_template?: TemplateName;
  default_depth?: Depth;
  page_size?: PageSize;
}): Promise<SettingsShape> {
  return request<SettingsShape>("/settings", jsonInit("PUT", patch));
}

// ---- URL builders (used directly in <a href> / <iframe src>) ----

export function previewUrl(id: number): string {
  return `${API}/applications/${id}/preview`;
}

export function exportUrl(id: number, kind: ExportKind): string {
  return `${API}/applications/${id}/exports/${encodeURIComponent(kind)}`;
}
```

`frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
```

`frontend/src/App.tsx` (nav shell with inline placeholder screens; Task 17 swaps them for real imports):

```tsx
import { NavLink, Route, Routes } from "react-router-dom";

// Placeholder screens — replaced by real imports in Task 17.
export function DashboardPlaceholder() {
  return <h1>Dashboard</h1>;
}
export function AddJobsPlaceholder() {
  return <h1>Add Jobs</h1>;
}
export function ProfilesPlaceholder() {
  return <h1>Profiles</h1>;
}
export function ApplicationPlaceholder() {
  return <h1>Application</h1>;
}
export function SettingsPlaceholder() {
  return <h1>Settings</h1>;
}

export default function App() {
  return (
    <>
      <nav className="nav">
        <div className="nav-inner">
          <NavLink to="/" className="nav-brand">
            Tailored
          </NavLink>
          <NavLink to="/" end className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Dashboard
          </NavLink>
          <NavLink to="/add" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Add Jobs
          </NavLink>
          <NavLink to="/profiles" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Profiles
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Settings
          </NavLink>
        </div>
      </nav>
      <main className="shell">
        <Routes>
          <Route path="/" element={<DashboardPlaceholder />} />
          <Route path="/add" element={<AddJobsPlaceholder />} />
          <Route path="/profiles" element={<ProfilesPlaceholder />} />
          <Route path="/applications/:id" element={<ApplicationPlaceholder />} />
          <Route path="/settings" element={<SettingsPlaceholder />} />
        </Routes>
      </main>
    </>
  );
}
```

- [ ] **Step 6: Run the test, expect PASS**

```powershell
cd frontend; npm test
```

Expected: `Test Files  1 passed (1)` — both tests green.

- [ ] **Step 7: Verify the production build compiles**

```powershell
cd frontend; npm run build
```

Expected: `tsc` exits clean (no type errors — this typechecks `types.ts` and `api.ts` too), then Vite prints `✓ built in ...` and `frontend/dist/index.html` exists. Do NOT commit `dist/` yet (Task 17 commits it).

- [ ] **Step 8: Commit (source only, no dist)**

```powershell
cd .; git add .gitignore frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tsconfig.json frontend/index.html frontend/src; git commit -m "feat: frontend scaffold with design system, types, and typed API client" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 15: Profile screens

**Files**
- Create: `frontend/src/screens/ProfileScreen.tsx`
- Test: `frontend/src/screens/ProfileScreen.test.tsx`

**Interfaces**
- Consumes (from Task 14): `listProfiles`, `createProfile`, `getProfile`, `updateProfile`, `uploadDocument`, `buildProfile` from `../api`; types `MasterProfile`, `MPExperience`, `MPProject`, `MPEducation`, `MPCertification`, `SkillGroup`, `TaggedBullet`, `ProfileDetail`, `ProfileSummary`, `UsageInfo` from `../types`; CSS classes from `styles.css`.
- Produces: default export `ProfileScreen` (React component, no props) — imported by `App.tsx` in Task 17.

- [ ] **Step 1: Write the failing test** — `frontend/src/screens/ProfileScreen.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import ProfileScreen from "./ProfileScreen";

vi.mock("../api", () => {
  const contact = { name: "Eldon", email: "e@example.com", phone: null, location: null, links: [] };
  const detail = {
    id: 1,
    name: "Eldon",
    contact,
    master_profile: {
      summary_notes: "Seasoned engineer notes",
      experiences: [
        {
          company: "Acme",
          title: "Engineer",
          start: "2020-01",
          end: null,
          location: null,
          bullets: [{ text: "Did a thing", tags: ["python"] }],
        },
      ],
      projects: [],
      skills: [],
      education: [],
      certifications: [],
      extras: [],
    },
    documents: [{ id: 5, filename: "resume.pdf", kind: "pdf" }],
  };
  return {
    listProfiles: vi.fn().mockResolvedValue([
      { id: 1, name: "Eldon", contact, has_master_profile: true },
    ]),
    getProfile: vi.fn().mockResolvedValue(detail),
    createProfile: vi.fn(),
    updateProfile: vi.fn(),
    uploadDocument: vi.fn(),
    buildProfile: vi.fn(),
  };
});

describe("ProfileScreen", () => {
  it("renders profiles, documents, and the master profile editor", async () => {
    render(<ProfileScreen />);
    expect(await screen.findByDisplayValue("Seasoned engineer notes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Eldon" })).toBeInTheDocument();
    expect(screen.getByText("resume.pdf")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Acme")).toBeInTheDocument();
  });

  it("adding a bullet grows the bullet input list", async () => {
    render(<ProfileScreen />);
    await screen.findByDisplayValue("Seasoned engineer notes");
    expect(screen.getAllByPlaceholderText("Bullet text")).toHaveLength(1);
    fireEvent.click(screen.getByText("Add bullet"));
    expect(screen.getAllByPlaceholderText("Bullet text")).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run the test, expect FAIL**

```powershell
cd frontend; npm test
```

Expected failure: `Error: Failed to resolve import "./ProfileScreen" from "src/screens/ProfileScreen.test.tsx". Does the file exist?` (the Task 14 App tests still pass).

- [ ] **Step 3: Write the implementation** — `frontend/src/screens/ProfileScreen.tsx` (complete file):

```tsx
import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import {
  buildProfile,
  createProfile,
  getProfile,
  listProfiles,
  updateProfile,
  uploadDocument,
} from "../api";
import type {
  MasterProfile,
  MPCertification,
  MPEducation,
  MPExperience,
  MPProject,
  ProfileDetail,
  ProfileSummary,
  SkillGroup,
  TaggedBullet,
  UsageInfo,
} from "../types";

const emptyMP: MasterProfile = {
  summary_notes: "",
  experiences: [],
  projects: [],
  skills: [],
  education: [],
  certifications: [],
  extras: [],
};

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export default function ProfileScreen() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ProfileDetail | null>(null);
  const [mp, setMp] = useState<MasterProfile>(emptyMP);
  const [newName, setNewName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [pasteName, setPasteName] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [building, setBuilding] = useState(false);
  const [buildUsage, setBuildUsage] = useState<UsageInfo | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function selectProfile(id: number) {
    setSelectedId(id);
    const d = await getProfile(id);
    setDetail(d);
    setMp({ ...emptyMP, ...d.master_profile });
  }

  async function refreshProfiles(selectId?: number) {
    const list = await listProfiles();
    setProfiles(list);
    const target = selectId ?? selectedId ?? (list.length > 0 ? list[0].id : null);
    if (target !== null) {
      await selectProfile(target);
    }
  }

  useEffect(() => {
    refreshProfiles().catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- typed master-profile editor helpers ----

  function updateExperience(idx: number, patch: Partial<MPExperience>) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) => (i === idx ? { ...e, ...patch } : e)),
    }));
  }

  function addExperience() {
    setMp((m) => ({
      ...m,
      experiences: [
        ...m.experiences,
        { company: "", title: "", start: "", end: null, location: null, bullets: [] },
      ],
    }));
  }

  function removeExperience(idx: number) {
    setMp((m) => ({ ...m, experiences: m.experiences.filter((_, i) => i !== idx) }));
  }

  function updateBullet(expIdx: number, bulletIdx: number, patch: Partial<TaggedBullet>) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) =>
        i === expIdx
          ? {
              ...e,
              bullets: e.bullets.map((b, j) => (j === bulletIdx ? { ...b, ...patch } : b)),
            }
          : e
      ),
    }));
  }

  function addBullet(expIdx: number) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) =>
        i === expIdx ? { ...e, bullets: [...e.bullets, { text: "", tags: [] }] } : e
      ),
    }));
  }

  function removeBullet(expIdx: number, bulletIdx: number) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) =>
        i === expIdx ? { ...e, bullets: e.bullets.filter((_, j) => j !== bulletIdx) } : e
      ),
    }));
  }

  function updateSkillGroup(idx: number, patch: Partial<SkillGroup>) {
    setMp((m) => ({
      ...m,
      skills: m.skills.map((g, i) => (i === idx ? { ...g, ...patch } : g)),
    }));
  }

  function addSkillGroup() {
    setMp((m) => ({ ...m, skills: [...m.skills, { label: "", items: [] }] }));
  }

  function removeSkillGroup(idx: number) {
    setMp((m) => ({ ...m, skills: m.skills.filter((_, i) => i !== idx) }));
  }

  function updateEducation(idx: number, patch: Partial<MPEducation>) {
    setMp((m) => ({
      ...m,
      education: m.education.map((ed, i) => (i === idx ? { ...ed, ...patch } : ed)),
    }));
  }

  function addEducation() {
    setMp((m) => ({
      ...m,
      education: [...m.education, { institution: "", credential: "", year: null, detail: null }],
    }));
  }

  function removeEducation(idx: number) {
    setMp((m) => ({ ...m, education: m.education.filter((_, i) => i !== idx) }));
  }

  function updateCertification(idx: number, patch: Partial<MPCertification>) {
    setMp((m) => ({
      ...m,
      certifications: m.certifications.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
    }));
  }

  function addCertification() {
    setMp((m) => ({
      ...m,
      certifications: [...m.certifications, { name: "", issuer: null, year: null }],
    }));
  }

  function removeCertification(idx: number) {
    setMp((m) => ({ ...m, certifications: m.certifications.filter((_, i) => i !== idx) }));
  }

  function updateProject(idx: number, patch: Partial<MPProject>) {
    setMp((m) => ({
      ...m,
      projects: m.projects.map((p, i) => (i === idx ? { ...p, ...patch } : p)),
    }));
  }

  function addProject() {
    setMp((m) => ({
      ...m,
      projects: [...m.projects, { name: "", description: "", url: null, bullets: [] }],
    }));
  }

  function removeProject(idx: number) {
    setMp((m) => ({ ...m, projects: m.projects.filter((_, i) => i !== idx) }));
  }

  function updateExtra(idx: number, value: string) {
    setMp((m) => ({ ...m, extras: m.extras.map((x, i) => (i === idx ? value : x)) }));
  }

  function addExtra() {
    setMp((m) => ({ ...m, extras: [...m.extras, ""] }));
  }

  function removeExtra(idx: number) {
    setMp((m) => ({ ...m, extras: m.extras.filter((_, i) => i !== idx) }));
  }

  // ---- actions ----

  async function handleCreate() {
    if (newName.trim() === "") return;
    try {
      const d = await createProfile(newName.trim(), {
        name: newName.trim(),
        email: newEmail.trim(),
        links: [],
      });
      setNewName("");
      setNewEmail("");
      await refreshProfiles(d.id);
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleFile(e: ChangeEvent<HTMLInputElement>) {
    if (selectedId === null || !e.target.files || e.target.files.length === 0) return;
    try {
      await uploadDocument(selectedId, e.target.files[0]);
      e.target.value = "";
      await selectProfile(selectedId);
    } catch (err) {
      setError(String(err));
    }
  }

  async function handlePasteDoc() {
    if (selectedId === null || pasteText.trim() === "") return;
    try {
      await uploadDocument(selectedId, {
        filename: pasteName.trim() !== "" ? pasteName.trim() : "pasted.txt",
        text: pasteText,
      });
      setPasteName("");
      setPasteText("");
      await selectProfile(selectedId);
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleBuild() {
    if (selectedId === null) return;
    setBuilding(true);
    setError(null);
    try {
      const d = await buildProfile(selectedId);
      setDetail(d);
      setMp({ ...emptyMP, ...d.master_profile });
      setBuildUsage(d.usage ?? null);
    } catch (err) {
      setError(String(err));
    } finally {
      setBuilding(false);
    }
  }

  async function handleSave() {
    if (selectedId === null) return;
    setSaving(true);
    setError(null);
    try {
      const d = await updateProfile(selectedId, { master_profile: mp });
      setDetail(d);
      setMp({ ...emptyMP, ...d.master_profile });
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <h1>Profiles</h1>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        <div className="card-title">Your profiles</div>
        <div className="row">
          {profiles.map((p) => (
            <button
              key={p.id}
              className={p.id === selectedId ? "btn btn-primary" : "btn"}
              onClick={() => selectProfile(p.id).catch((e) => setError(String(e)))}
            >
              {p.name}
            </button>
          ))}
          {profiles.length === 0 && <span className="muted">No profiles yet — create one below.</span>}
        </div>
        <div className="row">
          <input
            className="input"
            placeholder="Name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <input
            className="input"
            placeholder="Email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
          />
          <button className="btn" onClick={handleCreate}>
            Create profile
          </button>
        </div>
      </div>

      {detail && (
        <>
          <h2>{detail.name}</h2>

          <div className="card">
            <div className="card-title">Documents</div>
            <ul>
              {detail.documents.map((d) => (
                <li key={d.id}>
                  {d.filename} <span className="muted">({d.kind})</span>
                </li>
              ))}
            </ul>
            {detail.documents.length === 0 && (
              <p className="muted">Upload your existing resumes and notes to build a master profile.</p>
            )}
            <div className="field">
              <label className="field-label">Upload file (.pdf, .docx, .txt)</label>
              <input type="file" accept=".pdf,.docx,.txt" onChange={handleFile} />
            </div>
            <div className="field">
              <label className="field-label">Or paste text</label>
              <input
                className="input"
                placeholder="Document name"
                value={pasteName}
                onChange={(e) => setPasteName(e.target.value)}
              />
              <textarea
                className="textarea"
                placeholder="Paste resume or notes text"
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
              />
              <button className="btn" onClick={handlePasteDoc}>
                Add pasted text
              </button>
            </div>
          </div>

          <div className="card">
            <div className="card-title">Build</div>
            <p className="muted">
              Structures every document above into the master profile with one Claude call.
              Re-running replaces the current structured profile.
            </p>
            <button className="btn btn-primary" onClick={handleBuild} disabled={building}>
              {building && <span className="spinner" />}
              {building ? " Building..." : "Build master profile"}
            </button>
            {buildUsage && (
              <p className="muted">
                Done — {buildUsage.input_tokens} tokens in, {buildUsage.output_tokens} out, cost $
                {buildUsage.cost_usd.toFixed(4)}
              </p>
            )}
          </div>

          <div className="card">
            <div className="card-title">Master profile</div>

            <div className="field">
              <label className="field-label">Summary notes</label>
              <textarea
                className="textarea"
                value={mp.summary_notes}
                onChange={(e) => setMp({ ...mp, summary_notes: e.target.value })}
              />
            </div>

            <h3>Experiences</h3>
            {mp.experiences.map((exp, i) => (
              <div className="card" key={i}>
                <div className="row">
                  <input
                    className="input"
                    placeholder="Company"
                    value={exp.company}
                    onChange={(e) => updateExperience(i, { company: e.target.value })}
                  />
                  <input
                    className="input"
                    placeholder="Title"
                    value={exp.title}
                    onChange={(e) => updateExperience(i, { title: e.target.value })}
                  />
                </div>
                <div className="row">
                  <input
                    className="input"
                    placeholder="Start (YYYY-MM)"
                    value={exp.start}
                    onChange={(e) => updateExperience(i, { start: e.target.value })}
                  />
                  <input
                    className="input"
                    placeholder="End (blank = present)"
                    value={exp.end ?? ""}
                    onChange={(e) =>
                      updateExperience(i, { end: e.target.value === "" ? null : e.target.value })
                    }
                  />
                  <input
                    className="input"
                    placeholder="Location"
                    value={exp.location ?? ""}
                    onChange={(e) =>
                      updateExperience(i, {
                        location: e.target.value === "" ? null : e.target.value,
                      })
                    }
                  />
                </div>
                {exp.bullets.map((b, j) => (
                  <div className="row" key={j}>
                    <input
                      className="input"
                      placeholder="Bullet text"
                      value={b.text}
                      onChange={(e) => updateBullet(i, j, { text: e.target.value })}
                    />
                    <input
                      className="input"
                      placeholder="tags, comma, separated"
                      value={b.tags.join(", ")}
                      onChange={(e) => updateBullet(i, j, { tags: splitCsv(e.target.value) })}
                    />
                    <button className="btn btn-danger" onClick={() => removeBullet(i, j)}>
                      Remove
                    </button>
                  </div>
                ))}
                <div className="row">
                  <button className="btn btn-ghost" onClick={() => addBullet(i)}>
                    Add bullet
                  </button>
                  <button className="btn btn-danger" onClick={() => removeExperience(i)}>
                    Remove experience
                  </button>
                </div>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addExperience}>
              Add experience
            </button>

            <h3>Skills</h3>
            {mp.skills.map((g, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Group label"
                  value={g.label}
                  onChange={(e) => updateSkillGroup(i, { label: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="items, comma, separated"
                  value={g.items.join(", ")}
                  onChange={(e) => updateSkillGroup(i, { items: splitCsv(e.target.value) })}
                />
                <button className="btn btn-danger" onClick={() => removeSkillGroup(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addSkillGroup}>
              Add skill group
            </button>

            <h3>Education</h3>
            {mp.education.map((ed, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Institution"
                  value={ed.institution}
                  onChange={(e) => updateEducation(i, { institution: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Credential"
                  value={ed.credential}
                  onChange={(e) => updateEducation(i, { credential: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Year"
                  value={ed.year ?? ""}
                  onChange={(e) =>
                    updateEducation(i, { year: e.target.value === "" ? null : e.target.value })
                  }
                />
                <input
                  className="input"
                  placeholder="Detail"
                  value={ed.detail ?? ""}
                  onChange={(e) =>
                    updateEducation(i, { detail: e.target.value === "" ? null : e.target.value })
                  }
                />
                <button className="btn btn-danger" onClick={() => removeEducation(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addEducation}>
              Add education
            </button>

            <h3>Certifications</h3>
            {mp.certifications.map((c, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Certification name"
                  value={c.name}
                  onChange={(e) => updateCertification(i, { name: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Issuer"
                  value={c.issuer ?? ""}
                  onChange={(e) =>
                    updateCertification(i, { issuer: e.target.value === "" ? null : e.target.value })
                  }
                />
                <input
                  className="input"
                  placeholder="Year"
                  value={c.year ?? ""}
                  onChange={(e) =>
                    updateCertification(i, { year: e.target.value === "" ? null : e.target.value })
                  }
                />
                <button className="btn btn-danger" onClick={() => removeCertification(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addCertification}>
              Add certification
            </button>

            <h3>Projects</h3>
            {mp.projects.map((p, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Project name"
                  value={p.name}
                  onChange={(e) => updateProject(i, { name: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Description"
                  value={p.description}
                  onChange={(e) => updateProject(i, { description: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="URL"
                  value={p.url ?? ""}
                  onChange={(e) =>
                    updateProject(i, { url: e.target.value === "" ? null : e.target.value })
                  }
                />
                <button className="btn btn-danger" onClick={() => removeProject(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addProject}>
              Add project
            </button>

            <h3>Additional</h3>
            {mp.extras.map((x, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Extra item"
                  value={x}
                  onChange={(e) => updateExtra(i, e.target.value)}
                />
                <button className="btn btn-danger" onClick={() => removeExtra(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addExtra}>
              Add extra
            </button>

            <div className="row" style={{ marginTop: "1.25rem" }}>
              <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? "Saving..." : "Save master profile"}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the test, expect PASS**

```powershell
cd frontend; npm test
```

Expected: `Test Files  2 passed (2)` (App tests + ProfileScreen tests).

- [ ] **Step 5: Commit**

```powershell
cd .; git add frontend/src/screens; git commit -m "feat: profile screen with documents, build, and master profile editor" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 16: Dashboard + Add Jobs screens

**Files**
- Create: `frontend/src/screens/DashboardScreen.tsx`
- Create: `frontend/src/screens/AddJobsScreen.tsx`
- Test: `frontend/src/screens/DashboardScreen.test.tsx`
- Test: `frontend/src/screens/AddJobsScreen.test.tsx`

**Interfaces**
- Consumes (from Task 14): `listApplications`, `listProfiles`, `getSettings`, `createApplications` from `../api`; types `ApplicationSummary`, `AppStatus`, `Depth`, `JobRequest`, `ProfileSummary`, `TemplateName` from `../types`.
- Produces: default export `DashboardScreen`; named export `usePolling(profileId: number | undefined): ApplicationSummary[]` (in `DashboardScreen.tsx`); default export `AddJobsScreen` — all imported by `App.tsx` in Task 17.

- [ ] **Step 1: Write the failing Dashboard test** — `frontend/src/screens/DashboardScreen.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import DashboardScreen from "./DashboardScreen";

vi.mock("../api", () => {
  const contact = { name: "Eldon", email: "e@example.com", phone: null, location: null, links: [] };
  return {
    listProfiles: vi.fn().mockResolvedValue([
      { id: 1, name: "Eldon", contact, has_master_profile: true },
    ]),
    listApplications: vi.fn().mockResolvedValue([
      {
        id: 10,
        profile_id: 1,
        status: "ready",
        version: 2,
        template: "slate",
        depth: "standard",
        url: "https://example.com/a",
        company: "Acme",
        title: "Backend Engineer",
        cost_usd: 0.4321,
        created_at: "2026-07-22T10:00:00",
        error_message: null,
      },
      {
        id: 11,
        profile_id: 1,
        status: "tailoring",
        version: 1,
        template: "terminal",
        depth: "deep",
        url: "https://example.com/b",
        company: "Globex",
        title: "Platform Engineer",
        cost_usd: 0.1,
        created_at: "2026-07-22T11:00:00",
        error_message: null,
      },
    ]),
  };
});

describe("DashboardScreen", () => {
  it("renders one row per application with per-status badges", async () => {
    render(
      <MemoryRouter>
        <DashboardScreen />
      </MemoryRouter>
    );
    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("Globex")).toBeInTheDocument();
    expect(screen.getByText("ready")).toHaveClass("badge", "badge-ready");
    expect(screen.getByText("tailoring")).toHaveClass("badge", "badge-tailoring");
    expect(screen.getByText("$0.4321")).toBeInTheDocument();
    expect(screen.getAllByText("Open")).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run the test, expect FAIL**

```powershell
cd frontend; npm test
```

Expected failure: `Error: Failed to resolve import "./DashboardScreen" from "src/screens/DashboardScreen.test.tsx". Does the file exist?`

- [ ] **Step 3: Write the implementation** — `frontend/src/screens/DashboardScreen.tsx` (complete file, includes the `usePolling` hook):

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listApplications, listProfiles } from "../api";
import type { ApplicationSummary, AppStatus, ProfileSummary } from "../types";

const TERMINAL: AppStatus[] = ["ready", "error", "needs_paste"];

/**
 * Polls listApplications every 2000ms while any application status is outside
 * ready/error/needs_paste. Cleans up on unmount and on profile change.
 */
export function usePolling(profileId: number | undefined): ApplicationSummary[] {
  const [apps, setApps] = useState<ApplicationSummary[]>([]);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;

    async function tick() {
      let active = false;
      try {
        const list = await listApplications(profileId);
        if (stopped) return;
        setApps(list);
        active = list.some((a) => !TERMINAL.includes(a.status));
      } catch {
        active = false; // stop polling on fetch error; navigating back restarts it
      }
      if (!stopped && active) {
        timer = window.setTimeout(tick, 2000);
      }
    }

    tick();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [profileId]);

  return apps;
}

function StatusBadge({ app }: { app: ApplicationSummary }) {
  if (app.status === "needs_paste") {
    return (
      <Link to={`/applications/${app.id}`} className="badge badge-needs_paste">
        Paste required
      </Link>
    );
  }
  return <span className={`badge badge-${app.status}`}>{app.status}</span>;
}

export default function DashboardScreen() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [profileId, setProfileId] = useState<number | undefined>(undefined);
  const apps = usePolling(profileId);

  useEffect(() => {
    listProfiles()
      .then((list) => {
        setProfiles(list);
        if (list.length > 0) {
          setProfileId((cur) => cur ?? list[0].id);
        }
      })
      .catch(() => setProfiles([]));
  }, []);

  return (
    <div>
      <h1>Dashboard</h1>

      {profiles.length > 1 && (
        <div className="field" style={{ maxWidth: "20rem" }}>
          <label className="field-label">Profile</label>
          <select
            className="select"
            value={profileId ?? ""}
            onChange={(e) => setProfileId(Number(e.target.value))}
          >
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Role</th>
              <th>Depth</th>
              <th>Template</th>
              <th>Status</th>
              <th>Version</th>
              <th>Cost</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {apps.map((a) => (
              <tr key={a.id}>
                <td>{a.company ? a.company : a.url}</td>
                <td>{a.title ?? ""}</td>
                <td>{a.depth}</td>
                <td>{a.template}</td>
                <td>
                  <StatusBadge app={a} />
                </td>
                <td>v{a.version}</td>
                <td className="mono">${a.cost_usd.toFixed(4)}</td>
                <td>{new Date(a.created_at).toLocaleDateString()}</td>
                <td>
                  <Link to={`/applications/${a.id}`}>Open</Link>
                </td>
              </tr>
            ))}
            {apps.length === 0 && (
              <tr>
                <td colSpan={9} className="muted">
                  No applications yet — queue job URLs from the Add Jobs screen.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test, expect PASS**

```powershell
cd frontend; npm test
```

Expected: `Test Files  3 passed (3)`.

- [ ] **Step 5: Write the failing Add Jobs test** — `frontend/src/screens/AddJobsScreen.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AddJobsScreen from "./AddJobsScreen";

vi.mock("../api", () => {
  const contact = { name: "Eldon", email: "e@example.com", phone: null, location: null, links: [] };
  return {
    listProfiles: vi.fn().mockResolvedValue([
      { id: 1, name: "Eldon", contact, has_master_profile: true },
    ]),
    getSettings: vi.fn().mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    }),
    createApplications: vi.fn().mockResolvedValue([]),
  };
});

describe("AddJobsScreen", () => {
  it("parses three URL lines into three preview rows", async () => {
    render(
      <MemoryRouter>
        <AddJobsScreen />
      </MemoryRouter>
    );
    await screen.findByRole("option", { name: "Eldon" });
    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1\nhttps://b.example/j2\n\nhttps://c.example/j3\n" },
    });
    expect(screen.getAllByTestId("job-row")).toHaveLength(3);
    expect(screen.getByText("3 jobs to queue")).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run the test, expect FAIL**

```powershell
cd frontend; npm test
```

Expected failure: `Error: Failed to resolve import "./AddJobsScreen" from "src/screens/AddJobsScreen.test.tsx". Does the file exist?`

- [ ] **Step 7: Write the implementation** — `frontend/src/screens/AddJobsScreen.tsx` (complete file):

```tsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createApplications, getSettings, listProfiles } from "../api";
import type { Depth, JobRequest, ProfileSummary, TemplateName } from "../types";

const DEPTHS: Depth[] = ["quick", "standard", "deep"];
const TEMPLATES: TemplateName[] = ["meridian", "slate", "terminal", "signal"];

interface RowOverride {
  depth?: Depth;
  template?: TemplateName;
}

export default function AddJobsScreen() {
  const navigate = useNavigate();
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [profileId, setProfileId] = useState<number | undefined>(undefined);
  const [defaultDepth, setDefaultDepth] = useState<Depth>("standard");
  const [defaultTemplate, setDefaultTemplate] = useState<TemplateName>("slate");
  const [text, setText] = useState("");
  const [overrides, setOverrides] = useState<Record<number, RowOverride>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listProfiles()
      .then((list) => {
        setProfiles(list);
        if (list.length > 0) {
          setProfileId((cur) => cur ?? list[0].id);
        }
      })
      .catch((e) => setError(String(e)));
    getSettings()
      .then((s) => {
        setDefaultDepth(s.default_depth);
        setDefaultTemplate(s.default_template);
      })
      .catch(() => undefined);
  }, []);

  const urls = useMemo(
    () =>
      text
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0),
    [text]
  );

  function setOverride(idx: number, patch: RowOverride) {
    setOverrides((o) => ({ ...o, [idx]: { ...o[idx], ...patch } }));
  }

  async function handleSubmit() {
    if (profileId === undefined || urls.length === 0) return;
    setSubmitting(true);
    setError(null);
    const jobs: JobRequest[] = urls.map((url, i) => ({
      url,
      depth: overrides[i]?.depth ?? defaultDepth,
      template: overrides[i]?.template ?? defaultTemplate,
    }));
    try {
      await createApplications(profileId, jobs, defaultDepth, defaultTemplate);
      navigate("/");
    } catch (err) {
      setError(String(err));
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h1>Add Jobs</h1>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        <div className="row">
          <div className="field">
            <label className="field-label">Profile</label>
            <select
              className="select"
              value={profileId ?? ""}
              onChange={(e) => setProfileId(Number(e.target.value))}
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label">Default depth</label>
            <select
              className="select"
              value={defaultDepth}
              onChange={(e) => setDefaultDepth(e.target.value as Depth)}
            >
              {DEPTHS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label">Default template</label>
            <select
              className="select"
              value={defaultTemplate}
              onChange={(e) => setDefaultTemplate(e.target.value as TemplateName)}
            >
              {TEMPLATES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="field">
          <label className="field-label">Job posting URLs — one per line</label>
          <textarea
            className="textarea"
            placeholder="https://..."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
      </div>

      {urls.length > 0 && (
        <div className="card">
          <div className="card-title">
            {urls.length} job{urls.length === 1 ? "" : "s"} to queue
          </div>
          {urls.map((url, i) => (
            <div className="row" data-testid="job-row" key={i}>
              <span className="mono" style={{ flex: "2 1 16rem", overflowWrap: "anywhere" }}>
                {url}
              </span>
              <select
                className="select"
                aria-label={`Depth for row ${i + 1}`}
                value={overrides[i]?.depth ?? defaultDepth}
                onChange={(e) => setOverride(i, { depth: e.target.value as Depth })}
              >
                {DEPTHS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
              <select
                className="select"
                aria-label={`Template for row ${i + 1}`}
                value={overrides[i]?.template ?? defaultTemplate}
                onChange={(e) => setOverride(i, { template: e.target.value as TemplateName })}
              >
                {TEMPLATES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
          ))}
          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={submitting || profileId === undefined}
          >
            {submitting ? "Queueing..." : "Queue applications"}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 8: Run the test, expect PASS**

```powershell
cd frontend; npm test
```

Expected: `Test Files  4 passed (4)`.

- [ ] **Step 9: Commit**

```powershell
cd .; git add frontend/src/screens; git commit -m "feat: dashboard with status polling and add-jobs batch screen" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 17: Application view + Settings + committed build

**Files**
- Create: `frontend/src/screens/ApplicationScreen.tsx`
- Create: `frontend/src/screens/SettingsScreen.tsx`
- Modify: `frontend/src/App.tsx` (replace inline placeholders with real screen imports)
- Modify: `frontend/src/App.test.tsx` (placeholder heading assertion no longer applies)
- Create: `frontend/dist/` (production build, committed)
- Test: `frontend/src/screens/ApplicationScreen.test.tsx`

**Interfaces**
- Consumes (from Task 14): `getApplication`, `pasteJobText`, `updateContent`, `regenerate`, `getSettings`, `updateSettings`, `previewUrl`, `exportUrl` from `../api`; types `ApplicationDetail`, `AppStatus`, `Depth`, `ExportKind`, `PageSize`, `ResumeDoc`, `SettingsShape`, `SkillGroup`, `TemplateName` from `../types`. (From Tasks 15–16): default exports `ProfileScreen`, `DashboardScreen`, `AddJobsScreen`.
- Produces: default exports `ApplicationScreen` and `SettingsScreen`; final `App.tsx` wiring all five screens; committed `frontend/dist/` served by `main.py`'s static mount.

- [ ] **Step 1: Write the failing test** — `frontend/src/screens/ApplicationScreen.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ApplicationScreen from "./ApplicationScreen";
import * as api from "../api";
import type { ApplicationDetail } from "../types";

vi.mock("../api", () => ({
  getApplication: vi.fn(),
  pasteJobText: vi.fn(),
  updateContent: vi.fn(),
  regenerate: vi.fn(),
  previewUrl: (id: number) => `/api/applications/${id}/preview`,
  exportUrl: (id: number, kind: string) => `/api/applications/${id}/exports/${kind}`,
}));

const base: Omit<ApplicationDetail, "status"> = {
  id: 1,
  profile_id: 1,
  version: 1,
  template: "slate",
  depth: "standard",
  url: "https://example.com/job",
  company: "Acme",
  title: "Backend Engineer",
  cost_usd: 0.25,
  created_at: "2026-07-22T10:00:00",
  error_message: null,
  resume: null,
  cover_letter_md: null,
  tailoring_notes: null,
  research: null,
  parsed: null,
  raw_text_present: false,
};

function renderAt() {
  return render(
    <MemoryRouter initialEntries={["/applications/1"]}>
      <Routes>
        <Route path="/applications/:id" element={<ApplicationScreen />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("ApplicationScreen", () => {
  it("shows the paste panel when status is needs_paste", async () => {
    vi.mocked(api.getApplication).mockResolvedValue({ ...base, status: "needs_paste" });
    renderAt();
    expect(await screen.findByText("Paste the job posting")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Paste the full job posting text here")
    ).toBeInTheDocument();
  });

  it("shows all four tabs when status is ready", async () => {
    vi.mocked(api.getApplication).mockResolvedValue({
      ...base,
      status: "ready",
      resume: {
        contact: { name: "Eldon", email: "e@example.com", phone: null, location: null, links: [] },
        headline: "Backend Engineer",
        summary: "A summary.",
        sections: [],
      },
      cover_letter_md: "Dear team,",
      tailoring_notes: "Emphasized Python work.",
    });
    renderAt();
    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cover Letter" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Research" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exports" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test, expect FAIL**

```powershell
cd frontend; npm test
```

Expected failure: `Error: Failed to resolve import "./ApplicationScreen" from "src/screens/ApplicationScreen.test.tsx". Does the file exist?`

- [ ] **Step 3: Write the implementation** — `frontend/src/screens/ApplicationScreen.tsx` (complete file):

```tsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  exportUrl,
  getApplication,
  pasteJobText,
  previewUrl,
  regenerate,
  updateContent,
} from "../api";
import type {
  ApplicationDetail,
  AppStatus,
  ExportKind,
  ResumeDoc,
  SkillGroup,
} from "../types";

const TERMINAL: AppStatus[] = ["ready", "error", "needs_paste"];
const EXPORT_KINDS: ExportKind[] = [
  "resume.pdf",
  "resume.html",
  "resume.txt",
  "cover_letter.pdf",
  "cover_letter.txt",
];

type Tab = "resume" | "cover" | "research" | "exports";

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export default function ApplicationScreen() {
  const params = useParams<{ id: string }>();
  const appId = Number(params.id);

  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [tab, setTab] = useState<Tab>("resume");
  const [editingResume, setEditingResume] = useState(false);
  const [draft, setDraft] = useState<ResumeDoc | null>(null);
  const [editingCover, setEditingCover] = useState(false);
  const [coverDraft, setCoverDraft] = useState("");
  const [iframeKey, setIframeKey] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollNonce, setPollNonce] = useState(0);

  // Load + poll getApplication every 2000ms while status is non-terminal.
  // pollNonce restarts polling after regenerate / paste.
  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;

    async function tick() {
      try {
        const d = await getApplication(appId);
        if (stopped) return;
        setDetail(d);
        if (!TERMINAL.includes(d.status)) {
          timer = window.setTimeout(tick, 2000);
        } else {
          setIframeKey((k) => k + 1); // reload preview once the pipeline settles
        }
      } catch (err) {
        if (!stopped) setError(String(err));
      }
    }

    tick();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [appId, pollNonce]);

  // ---- resume draft editing helpers ----

  function startEditResume() {
    if (detail && detail.resume) {
      setDraft(JSON.parse(JSON.stringify(detail.resume)) as ResumeDoc);
      setEditingResume(true);
    }
  }

  function cancelEditResume() {
    setEditingResume(false);
    setDraft(null);
  }

  function setSectionTitle(idx: number, title: string) {
    setDraft((d) =>
      d ? { ...d, sections: d.sections.map((s, i) => (i === idx ? { ...s, title } : s)) } : d
    );
  }

  function removeSection(idx: number) {
    setDraft((d) => (d ? { ...d, sections: d.sections.filter((_, i) => i !== idx) } : d));
  }

  function setExperienceBullet(secIdx: number, itemIdx: number, bulletIdx: number, text: string) {
    setDraft((d) => {
      if (!d) return d;
      return {
        ...d,
        sections: d.sections.map((s, i) => {
          if (i !== secIdx || s.type !== "experience") return s;
          return {
            ...s,
            items: s.items.map((item, j) =>
              j === itemIdx
                ? { ...item, bullets: item.bullets.map((b, k) => (k === bulletIdx ? text : b)) }
                : item
            ),
          };
        }),
      };
    });
  }

  function removeExperienceBullet(secIdx: number, itemIdx: number, bulletIdx: number) {
    setDraft((d) => {
      if (!d) return d;
      return {
        ...d,
        sections: d.sections.map((s, i) => {
          if (i !== secIdx || s.type !== "experience") return s;
          return {
            ...s,
            items: s.items.map((item, j) =>
              j === itemIdx
                ? { ...item, bullets: item.bullets.filter((_, k) => k !== bulletIdx) }
                : item
            ),
          };
        }),
      };
    });
  }

  function removeExperienceItem(secIdx: number, itemIdx: number) {
    setDraft((d) => {
      if (!d) return d;
      return {
        ...d,
        sections: d.sections.map((s, i) => {
          if (i !== secIdx || s.type !== "experience") return s;
          return { ...s, items: s.items.filter((_, j) => j !== itemIdx) };
        }),
      };
    });
  }

  function setSkillGroupField(secIdx: number, groupIdx: number, patch: Partial<SkillGroup>) {
    setDraft((d) => {
      if (!d) return d;
      return {
        ...d,
        sections: d.sections.map((s, i) => {
          if (i !== secIdx || s.type !== "skills") return s;
          return {
            ...s,
            groups: s.groups.map((g, j) => (j === groupIdx ? { ...g, ...patch } : g)),
          };
        }),
      };
    });
  }

  // ---- actions ----

  async function saveResume() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      const d = await updateContent(appId, { resume: draft });
      setDetail(d);
      setEditingResume(false);
      setDraft(null);
      setIframeKey((k) => k + 1);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function startEditCover() {
    if (detail) {
      setCoverDraft(detail.cover_letter_md ?? "");
      setEditingCover(true);
    }
  }

  async function saveCover() {
    setBusy(true);
    setError(null);
    try {
      const d = await updateContent(appId, { cover_letter_md: coverDraft });
      setDetail(d);
      setEditingCover(false);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRegenerate() {
    if (feedback.trim() === "") return;
    setBusy(true);
    setError(null);
    try {
      await regenerate(appId, feedback);
      setFeedback("");
      setPollNonce((n) => n + 1);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handlePaste() {
    if (pasteText.trim() === "") return;
    setBusy(true);
    setError(null);
    try {
      await pasteJobText(appId, pasteText);
      setPasteText("");
      setPollNonce((n) => n + 1);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!detail) {
    return (
      <div>
        {error && <div className="alert alert-error">{error}</div>}
        <p className="muted">Loading application...</p>
      </div>
    );
  }

  const working = !TERMINAL.includes(detail.status);

  return (
    <div>
      <h1>
        {detail.company ? detail.company : detail.url} — {detail.title ?? ""}
      </h1>
      <p>
        <span className={`badge badge-${detail.status}`}>{detail.status}</span>{" "}
        <span className="muted">
          v{detail.version} · ${detail.cost_usd.toFixed(4)} · {detail.depth} · {detail.template}
        </span>
        {working && <span className="spinner" style={{ marginLeft: "0.5rem" }} />}
      </p>

      {error && <div className="alert alert-error">{error}</div>}

      {detail.status === "error" && (
        <div className="alert alert-error">
          <strong>Generation failed:</strong> {detail.error_message ?? "Unknown error"}
          <div className="muted" style={{ marginTop: "0.25rem" }}>
            Fix the issue (API key, network) and use "Regenerate with feedback" below to retry.
          </div>
        </div>
      )}

      {detail.status === "needs_paste" ? (
        <div className="card">
          <h2>Paste the job posting</h2>
          <p className="muted">
            The posting URL could not be fetched automatically (login wall, bot protection, or a
            JavaScript-only page). Paste the full posting text below and the pipeline will resume.
          </p>
          <textarea
            className="textarea"
            style={{ minHeight: "12rem" }}
            placeholder="Paste the full job posting text here"
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
          />
          <button className="btn btn-primary" onClick={handlePaste} disabled={busy}>
            {busy ? "Submitting..." : "Submit pasted text"}
          </button>
        </div>
      ) : (
        <>
          <div className="tabs">
            <button
              className={tab === "resume" ? "tab active" : "tab"}
              onClick={() => setTab("resume")}
            >
              Resume
            </button>
            <button
              className={tab === "cover" ? "tab active" : "tab"}
              onClick={() => setTab("cover")}
            >
              Cover Letter
            </button>
            <button
              className={tab === "research" ? "tab active" : "tab"}
              onClick={() => setTab("research")}
            >
              Research
            </button>
            <button
              className={tab === "exports" ? "tab active" : "tab"}
              onClick={() => setTab("exports")}
            >
              Exports
            </button>
          </div>

          {tab === "resume" && (
            <div>
              {!editingResume && (
                <>
                  <div className="row">
                    <button
                      className="btn"
                      onClick={startEditResume}
                      disabled={!detail.resume || working}
                    >
                      Edit
                    </button>
                  </div>
                  <iframe
                    key={iframeKey}
                    src={previewUrl(appId)}
                    title="Resume preview"
                    className="preview-frame"
                  />
                </>
              )}

              {editingResume && draft && (
                <div className="card">
                  <div className="card-title">Edit resume</div>
                  <div className="field">
                    <label className="field-label">Headline</label>
                    <input
                      className="input"
                      value={draft.headline}
                      onChange={(e) => setDraft({ ...draft, headline: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label className="field-label">Summary</label>
                    <textarea
                      className="textarea"
                      value={draft.summary}
                      onChange={(e) => setDraft({ ...draft, summary: e.target.value })}
                    />
                  </div>

                  {draft.sections.map((section, si) => (
                    <div className="card" key={si}>
                      <div className="row">
                        <input
                          className="input"
                          aria-label={`Section ${si + 1} title`}
                          value={section.title}
                          onChange={(e) => setSectionTitle(si, e.target.value)}
                        />
                        <button className="btn btn-danger" onClick={() => removeSection(si)}>
                          Remove section
                        </button>
                      </div>

                      {section.type === "experience" &&
                        section.items.map((item, ii) => (
                          <div className="card" key={ii}>
                            <div className="row">
                              <strong>
                                {item.company} — {item.role}
                              </strong>
                              <span className="muted">
                                {item.start} – {item.end ?? "present"}
                              </span>
                              <button
                                className="btn btn-danger"
                                onClick={() => removeExperienceItem(si, ii)}
                              >
                                Remove item
                              </button>
                            </div>
                            {item.bullets.map((b, bi) => (
                              <div className="row" key={bi}>
                                <textarea
                                  className="textarea"
                                  style={{ minHeight: "3rem" }}
                                  value={b}
                                  onChange={(e) =>
                                    setExperienceBullet(si, ii, bi, e.target.value)
                                  }
                                />
                                <button
                                  className="btn btn-danger"
                                  onClick={() => removeExperienceBullet(si, ii, bi)}
                                >
                                  Remove bullet
                                </button>
                              </div>
                            ))}
                          </div>
                        ))}

                      {section.type === "skills" &&
                        section.groups.map((g, gi) => (
                          <div className="row" key={gi}>
                            <input
                              className="input"
                              placeholder="Group label"
                              value={g.label}
                              onChange={(e) =>
                                setSkillGroupField(si, gi, { label: e.target.value })
                              }
                            />
                            <input
                              className="input"
                              placeholder="items, comma, separated"
                              value={g.items.join(", ")}
                              onChange={(e) =>
                                setSkillGroupField(si, gi, { items: splitCsv(e.target.value) })
                              }
                            />
                          </div>
                        ))}
                    </div>
                  ))}

                  <div className="row">
                    <button className="btn btn-primary" onClick={saveResume} disabled={busy}>
                      {busy ? "Saving..." : "Save"}
                    </button>
                    <button className="btn btn-ghost" onClick={cancelEditResume}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              <div className="card" style={{ marginTop: "1.25rem" }}>
                <div className="card-title">Regenerate with feedback</div>
                <textarea
                  className="textarea"
                  placeholder="e.g. Emphasize the data pipeline work more; shorter summary."
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                />
                <button
                  className="btn btn-primary"
                  onClick={handleRegenerate}
                  disabled={busy || working}
                >
                  {busy ? "Submitting..." : "Regenerate"}
                </button>
              </div>
            </div>
          )}

          {tab === "cover" && (
            <div>
              {!editingCover && (
                <>
                  <div className="row">
                    <button
                      className="btn"
                      onClick={startEditCover}
                      disabled={detail.cover_letter_md === null || working}
                    >
                      Edit
                    </button>
                  </div>
                  <pre className="cover-md">{detail.cover_letter_md ?? "No cover letter yet."}</pre>
                </>
              )}
              {editingCover && (
                <div className="card">
                  <textarea
                    className="textarea"
                    style={{ minHeight: "20rem" }}
                    value={coverDraft}
                    onChange={(e) => setCoverDraft(e.target.value)}
                  />
                  <div className="row">
                    <button className="btn btn-primary" onClick={saveCover} disabled={busy}>
                      {busy ? "Saving..." : "Save"}
                    </button>
                    <button className="btn btn-ghost" onClick={() => setEditingCover(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === "research" && (
            <div>
              {detail.tailoring_notes && (
                <div className="callout">
                  <strong>Tailoring notes:</strong> {detail.tailoring_notes}
                </div>
              )}

              {detail.parsed && (
                <div className="card">
                  <div className="card-title">Parsed posting</div>
                  <h3>Must-haves</h3>
                  <div>
                    {detail.parsed.must_haves.map((m, i) => (
                      <span className="chip" key={i}>
                        {m}
                      </span>
                    ))}
                  </div>
                  <h3>Nice-to-haves</h3>
                  <div>
                    {detail.parsed.nice_to_haves.map((m, i) => (
                      <span className="chip" key={i}>
                        {m}
                      </span>
                    ))}
                  </div>
                  <h3>Keywords</h3>
                  <div>
                    {detail.parsed.keywords.map((m, i) => (
                      <span className="chip" key={i}>
                        {m}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {detail.research ? (
                <div className="card">
                  <div className="card-title">Research findings</div>
                  <dl>
                    <dt>
                      <strong>Mission</strong>
                    </dt>
                    <dd>{detail.research.mission}</dd>
                    <dt>
                      <strong>Products</strong>
                    </dt>
                    <dd>{detail.research.products.join("; ")}</dd>
                    <dt>
                      <strong>News</strong>
                    </dt>
                    <dd>{detail.research.news.join("; ")}</dd>
                    <dt>
                      <strong>Tech stack signals</strong>
                    </dt>
                    <dd>{detail.research.tech_stack_signals.join("; ")}</dd>
                    <dt>
                      <strong>Culture language</strong>
                    </dt>
                    <dd>{detail.research.culture_language.join("; ")}</dd>
                    <dt>
                      <strong>Sources</strong>
                    </dt>
                    <dd>
                      {detail.research.sources.map((s, i) => (
                        <div key={i} className="mono">
                          {s}
                        </div>
                      ))}
                    </dd>
                  </dl>
                </div>
              ) : (
                <p className="muted">
                  No research brief — this application ran at "quick" depth (parse only).
                </p>
              )}
            </div>
          )}

          {tab === "exports" && (
            <div className="card">
              <div className="card-title">Downloads</div>
              <ul>
                {EXPORT_KINDS.map((kind) => (
                  <li key={kind}>
                    <a href={exportUrl(appId, kind)} download>
                      {kind}
                    </a>
                  </li>
                ))}
              </ul>
              {detail.status !== "ready" && (
                <p className="muted">Exports are written when the application reaches "ready".</p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the test, expect PASS**

```powershell
cd frontend; npm test
```

Expected: `Test Files  5 passed (5)`.

- [ ] **Step 5: Write SettingsScreen and wire all real screens into App.tsx**

`frontend/src/screens/SettingsScreen.tsx` (complete file):

```tsx
import { useEffect, useState } from "react";
import { getSettings, updateSettings } from "../api";
import type { Depth, PageSize, SettingsShape, TemplateName } from "../types";

const DEPTHS: Depth[] = ["quick", "standard", "deep"];
const TEMPLATES: TemplateName[] = ["meridian", "slate", "terminal", "signal"];
const PAGE_SIZES: PageSize[] = ["Letter", "A4"];

export default function SettingsScreen() {
  const [settings, setSettings] = useState<SettingsShape | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSettings()
      .then(setSettings)
      .catch((e) => setError(String(e)));
  }, []);

  async function patch(p: {
    default_template?: TemplateName;
    default_depth?: Depth;
    page_size?: PageSize;
  }) {
    setError(null);
    try {
      const s = await updateSettings(p);
      setSettings(s);
    } catch (err) {
      setError(String(err));
    }
  }

  if (!settings) {
    return (
      <div>
        <h1>Settings</h1>
        {error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading...</p>}
      </div>
    );
  }

  return (
    <div>
      <h1>Settings</h1>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        <div className="card-title">Anthropic API key</div>
        <p>
          {settings.api_key_set ? (
            <span className="pill pill-ok">API key set</span>
          ) : (
            <span className="pill pill-warn">API key not set</span>
          )}
        </p>
        <p className="muted">
          The key is read from the ANTHROPIC_API_KEY variable in the .env file next to run.py.
          Add or change it there and restart the app — it is never stored in the database.
        </p>
        {settings.fake_mode ? (
          <div className="callout">
            Demo mode is active (TAILORED_FAKE=1): all generation uses offline canned fixtures and
            no API calls are made.
          </div>
        ) : (
          <p className="muted">
            Demo mode is off. Set TAILORED_FAKE=1 in the .env file next to run.py and restart to
            explore the app fully offline with no API key.
          </p>
        )}
      </div>

      <div className="card">
        <div className="card-title">Defaults</div>
        <div className="field" style={{ maxWidth: "20rem" }}>
          <label className="field-label">Default template</label>
          <select
            className="select"
            value={settings.default_template}
            onChange={(e) => patch({ default_template: e.target.value as TemplateName })}
          >
            {TEMPLATES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ maxWidth: "20rem" }}>
          <label className="field-label">Default research depth</label>
          <select
            className="select"
            value={settings.default_depth}
            onChange={(e) => patch({ default_depth: e.target.value as Depth })}
          >
            {DEPTHS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ maxWidth: "20rem" }}>
          <label className="field-label">Page size</label>
          <select
            className="select"
            value={settings.page_size}
            onChange={(e) => patch({ page_size: e.target.value as PageSize })}
          >
            {PAGE_SIZES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
```

`frontend/src/App.tsx` — full replacement (placeholders removed, real imports):

```tsx
import { NavLink, Route, Routes } from "react-router-dom";
import DashboardScreen from "./screens/DashboardScreen";
import AddJobsScreen from "./screens/AddJobsScreen";
import ProfileScreen from "./screens/ProfileScreen";
import ApplicationScreen from "./screens/ApplicationScreen";
import SettingsScreen from "./screens/SettingsScreen";

export default function App() {
  return (
    <>
      <nav className="nav">
        <div className="nav-inner">
          <NavLink to="/" className="nav-brand">
            Tailored
          </NavLink>
          <NavLink to="/" end className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Dashboard
          </NavLink>
          <NavLink to="/add" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Add Jobs
          </NavLink>
          <NavLink to="/profiles" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Profiles
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Settings
          </NavLink>
        </div>
      </nav>
      <main className="shell">
        <Routes>
          <Route path="/" element={<DashboardScreen />} />
          <Route path="/add" element={<AddJobsScreen />} />
          <Route path="/profiles" element={<ProfileScreen />} />
          <Route path="/applications/:id" element={<ApplicationScreen />} />
          <Route path="/settings" element={<SettingsScreen />} />
        </Routes>
      </main>
    </>
  );
}
```

`frontend/src/App.test.tsx` — full replacement. The old second test asserted the placeholder `<h1>Dashboard</h1>`; the real DashboardScreen calls the API on mount, so App.test.tsx now mocks the api module and asserts the real Dashboard heading renders:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

vi.mock("./api", () => ({
  listProfiles: vi.fn().mockResolvedValue([]),
  listApplications: vi.fn().mockResolvedValue([]),
  getSettings: vi.fn().mockResolvedValue({
    api_key_set: false,
    fake_mode: true,
    default_template: "slate",
    default_depth: "standard",
    page_size: "Letter",
  }),
  createProfile: vi.fn(),
  getProfile: vi.fn(),
  updateProfile: vi.fn(),
  uploadDocument: vi.fn(),
  buildProfile: vi.fn(),
  createApplications: vi.fn(),
  getApplication: vi.fn(),
  pasteJobText: vi.fn(),
  updateContent: vi.fn(),
  regenerate: vi.fn(),
  updateSettings: vi.fn(),
  previewUrl: (id: number) => `/api/applications/${id}/preview`,
  exportUrl: (id: number, kind: string) => `/api/applications/${id}/exports/${kind}`,
}));

describe("App shell", () => {
  it("renders the brand and all nav links", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText("Tailored")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Add Jobs" })).toHaveAttribute("href", "/add");
    expect(screen.getByRole("link", { name: "Profiles" })).toHaveAttribute("href", "/profiles");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });

  it("renders the real Dashboard screen on /", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run the full frontend suite, expect PASS**

```powershell
cd frontend; npm test
```

Expected: `Test Files  5 passed (5)` — App, ProfileScreen, DashboardScreen, AddJobsScreen, ApplicationScreen all green.

- [ ] **Step 7: Build production bundle and verify dist**

```powershell
cd frontend; npm run build
cd .; Test-Path frontend/dist/index.html; Get-ChildItem frontend/dist/assets
```

Expected: build succeeds (`✓ built in ...`); `Test-Path` prints `True`; the assets listing shows at least one `index-*.js` and one `index-*.css`.

- [ ] **Step 8: Confirm dist is not gitignored, then commit source + build**

```powershell
cd .; git check-ignore frontend/dist
```

Expected: prints nothing and exits with a non-zero code (PowerShell shows `$LASTEXITCODE` = 1) — meaning `frontend/dist` is NOT ignored. If it prints a path, remove the offending pattern from `.gitignore` before continuing (the committed build is how end users run without Node).

```powershell
cd .; git add frontend/src frontend/dist; git commit -m "feat: application view, settings screen, and committed frontend build" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

# Phase 7: End-to-End Smoke, README, and Ship

This phase proves the whole stack works as one system — real app factory, real routes, real
pipeline, fake Claude via `TAILORED_FAKE=1` — then writes the final README and cuts v0.1.0.

Cross-section note (implementer, read first): this section calls
`pipeline.process_application(app_id, engine=..., claude=...)` and
`pipeline.regenerate_application(app_id, feedback, engine=..., claude=...)` with an optional
`claude` keyword. Task 9 produces the pipeline with that optional kwarg
(`claude: ClaudeService | None = None`, falling back to `make_claude(get_settings())` when
`None`). If the Task 9 implementation on your branch is missing the kwarg, add it there
(pure plumbing: accept the kwarg, use it instead of constructing a new service) before
running this section's tests — do not weaken the tests.

---

### Task 18: End-to-end smoke test, final README, release v0.1.0

**Files**

- Create: `tests\test_e2e.py`
- Create (overwrite the Task 1 stub if one exists): `README.md`
- Modify (ONLY if Task 9 omitted the optional `claude` kwarg — see phase note above): `backend\app\services\pipeline.py`
- Test: `tests\test_e2e.py`

**Interfaces**

- Consumes:
  - `create_app() -> FastAPI` from `backend/app/main.py` (Task 12) — engine at `app.state.engine`, serves all `/api` routes from the contract route table.
  - `get_settings()` from `backend/app/config.py` (Task 1) — reads `TAILORED_DATA_DIR`, `TAILORED_FAKE`, `ANTHROPIC_API_KEY`; cached accessor (the test clears the cache via `getattr(get_settings, "cache_clear", None)`).
  - `ClaudeService(fake_mode=True, fixtures_dir=...)` from `backend/app/services/claude.py` (Task 4).
  - `pipeline.process_application(app_id: int, engine=None, claude=None)` and `pipeline.regenerate_application(app_id: int, feedback: str, engine=None, claude=None)` from `backend/app/services/pipeline.py` (Task 9).
  - `render.render_pdf(html: str, out_path: Path, page_size: str = "Letter")` from `backend/app/services/render.py` (Task 10) — monkeypatch target in the fast variant; `export_application` must resolve `render_pdf` as a module-level global of `render.py` (it does per Task 10) so the patch takes effect.
  - Fixtures `backend/app/fixtures/intake.json` (IntakeResult shape: `{"contact": ..., "master_profile": ...}`) and `backend/app/fixtures/tailor.json` (TailorResult shape: `{"resume": ..., "cover_letter_md": ..., "tailoring_notes": ...}`) — the test reads them at runtime so it never hardcodes fixture names/companies.
  - Export kinds enum: `resume.pdf | resume.html | resume.txt | cover_letter.pdf | cover_letter.txt`.
  - `pdf` pytest marker registered in `pyproject.toml` (Task 1).
- Produces:
  - `tests/test_e2e.py` with `test_e2e_fake_mode_full_flow` (fast), `test_e2e_real_pdf` (`@pytest.mark.pdf`), `test_readme_quickstart`.
  - Final `README.md` (complete content below).
  - Release commit `chore: release v0.1.0` and git tag `v0.1.0`.

- [ ] **Step 1: Write the end-to-end smoke tests (COMPLETE test file)**

  Notes on the design of this test, so nobody "fixes" it wrong later:

  - No service is monkeypatched. Fake Claude comes from the sanctioned mechanism
    (`TAILORED_FAKE=1` env → `make_claude` returns a fake-mode service inside the app;
    plus an explicit `ClaudeService(fake_mode=True, ...)` passed to the direct pipeline
    calls). The ONLY patches are:
    1. `starlette.background.BackgroundTasks.add_task` → dropped, in BOTH variants, so
       API calls never run the pipeline implicitly and the test drives it synchronously
       and deterministically (the task requirement "do not rely on BackgroundTasks").
    2. `render.render_pdf` → tiny stub, in the fast (non-pdf) variant ONLY. It is
       patched BEFORE `create_app()` so that Task 13's demo seeding (which runs the fake
       pipeline at startup when `TAILORED_FAKE=1` and the DB is empty) also uses the stub.
  - Demo seeding may create a demo profile + application at startup; every assertion
    therefore filters by the profile/application ids this test creates itself.
  - Fixture-dependent assertions (contact name, companies) are read from the fixture
    JSON files at runtime, so this test stays correct whatever realistic names the
    fixture tasks chose.
  - Only the posting URL is HTTP-mocked (respx); respx also guarantees no other real
    network call escapes during the pipeline run. TestClient calls happen outside the
    respx context (respx patches httpx transports; TestClient's ASGI transport is
    unaffected either way, but keeping them separate removes all doubt).

  Create `tests\test_e2e.py`:

  ```python
  """End-to-end smoke test: the full stack in fake mode, driven through the real app.

  No services are monkeypatched. The only patches:
  - BackgroundTasks.add_task is dropped (both variants) so the test drives the
    pipeline synchronously via direct pipeline calls instead of relying on
    BackgroundTasks execution semantics inside TestClient.
  - render_pdf is stubbed in the fast (non-pdf) variant only; the @pytest.mark.pdf
    variant uses the real Playwright/Chromium renderer.
  """
  from __future__ import annotations

  import json
  from pathlib import Path

  import httpx
  import pytest
  import respx
  from fastapi.testclient import TestClient
  from starlette.background import BackgroundTasks

  from backend.app.services import pipeline, render
  from backend.app.services.claude import ClaudeService

  PROJECT_ROOT = Path(__file__).resolve().parents[1]
  FIXTURES_DIR = PROJECT_ROOT / "backend" / "app" / "fixtures"

  POSTING_URL = "https://jobs.example.com/postings/senior-backend-4471"

  POSTING_HTML = """<!DOCTYPE html>
  <html>
  <head><title>Senior Backend Engineer - Job Posting</title></head>
  <body>
  <article>
    <h1>Senior Backend Engineer</h1>
    <p>We are looking for a Senior Backend Engineer to join our platform team and take
    ownership of the services that power our analytics products. You will design and
    operate Python services in production, collaborate with product engineers on API
    design, and help us keep our data pipeline fast, observable, and reliable as our
    customer base grows across three continents.</p>
    <p>In this role you will build and maintain FastAPI services backed by PostgreSQL,
    design schemas and migrations, own the reliability of asynchronous job processing,
    and instrument everything with meaningful metrics and traces. You will review code,
    mentor mid-level engineers, and participate in a humane on-call rotation with real
    influence over what pages you and what does not.</p>
    <p>Requirements: five or more years of professional software engineering experience,
    deep working knowledge of Python and at least one modern web framework such as
    FastAPI or Django, strong SQL skills, and experience deploying and operating
    services in a cloud environment with CI/CD. You write clearly and communicate
    trade-offs honestly.</p>
    <p>Nice to have: experience with React and TypeScript, Kubernetes, streaming
    systems such as Kafka, and infrastructure as code. Familiarity with data-intensive
    applications and cost-aware architecture decisions is a strong plus.</p>
    <p>We offer remote-friendly work with quarterly team onsites, a professional
    development budget, and transparent salary bands. Our interview process is four
    stages and we always tell you where you stand within two business days.</p>
  </article>
  </body>
  </html>"""

  PASTED_RESUME_TEXT = """Professional summary: backend-leaning software engineer with
  production Python experience, API design, and data pipeline work.

  Experience includes building web services, maintaining CI/CD pipelines, operating
  SQL databases, mentoring junior engineers, and shipping developer tooling.

  Skills: Python, FastAPI, SQL, Docker, TypeScript, React, testing, observability.

  Education: bachelor's degree in a technical field.
  """

  EXPORT_KINDS = (
      "resume.pdf",
      "resume.html",
      "resume.txt",
      "cover_letter.pdf",
      "cover_letter.txt",
  )


  def _reset_settings_cache() -> None:
      from backend.app import config

      cache_clear = getattr(config.get_settings, "cache_clear", None)
      if cache_clear is not None:
          cache_clear()


  @pytest.fixture(autouse=True)
  def _settings_cache_guard():
      """Ensure cached Settings never leak between this module's tests and others."""
      _reset_settings_cache()
      yield
      _reset_settings_cache()


  def _make_app(tmp_path, monkeypatch):
      """Real create_app() in fake mode with an isolated data dir.

      BackgroundTasks.add_task is dropped so no API call runs the pipeline
      implicitly -- this test drives the pipeline synchronously and explicitly.
      """
      monkeypatch.setenv("TAILORED_DATA_DIR", str(tmp_path / "data"))
      monkeypatch.setenv("TAILORED_FAKE", "1")
      monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
      monkeypatch.setattr(
          BackgroundTasks, "add_task", lambda self, func, *args, **kwargs: None
      )
      _reset_settings_cache()
      from backend.app.main import create_app

      return create_app()


  def _intake_fixture() -> dict:
      return json.loads((FIXTURES_DIR / "intake.json").read_text(encoding="utf-8"))


  def _tailor_fixture() -> dict:
      return json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))


  def _first_experience_company(tailor: dict) -> str:
      for section in tailor["resume"]["sections"]:
          if section["type"] == "experience" and section["items"]:
              return section["items"][0]["company"]
      raise AssertionError("tailor.json fixture has no experience items")


  def _run_full_flow(client: TestClient, engine, claude: ClaudeService) -> int:
      """Shared flow for both variants. Returns the created application id."""
      intake = _intake_fixture()
      tailor = _tailor_fixture()

      # 1. Create a profile.
      r = client.post("/api/profiles", json={"name": "E2E Test User"})
      assert r.status_code in (200, 201), r.text
      profile_id = r.json()["id"]

      # 2. Upload a pasted source document.
      r = client.post(
          f"/api/profiles/{profile_id}/documents",
          json={"filename": "resume_notes.txt", "text": PASTED_RESUME_TEXT},
      )
      assert r.status_code in (200, 201), r.text
      doc = r.json()
      assert doc["filename"] == "resume_notes.txt"
      assert doc["kind"] in ("paste", "txt")

      # 3. Build the master profile: the real intake path through fake Claude.
      r = client.post(f"/api/profiles/{profile_id}/build")
      assert r.status_code == 200, r.text
      built = r.json()
      assert "usage" in built
      assert built["usage"]["cost_usd"] == 0.0  # fake mode reports zero usage
      assert built["master_profile"]["experiences"], "intake produced no experiences"
      assert (
          built["master_profile"]["experiences"][0]["company"]
          == intake["master_profile"]["experiences"][0]["company"]
      )

      # 4. Batch-create ONE application. add_task is dropped, so it stays queued.
      r = client.post(
          "/api/applications/batch",
          json={
              "profile_id": profile_id,
              "jobs": [
                  {"url": POSTING_URL, "depth": "standard", "template": "slate"}
              ],
          },
      )
      assert r.status_code in (200, 201), r.text
      apps = r.json()
      assert len(apps) == 1
      app_id = apps[0]["id"]
      assert apps[0]["status"] == "queued"

      # 5. Drive the pipeline synchronously. Only the posting URL is HTTP-mocked;
      # respx also fails the test if anything tries to reach the real network.
      with respx.mock:
          respx.get(POSTING_URL).mock(
              return_value=httpx.Response(200, html=POSTING_HTML)
          )
          pipeline.process_application(app_id, engine=engine, claude=claude)

      # 6. Final status: ready, version 1, content present.
      r = client.get(f"/api/applications/{app_id}")
      assert r.status_code == 200, r.text
      detail = r.json()
      assert detail["status"] == "ready", detail.get("error_message")
      assert detail["version"] == 1
      assert detail["resume"] is not None
      assert detail["cover_letter_md"]
      assert detail["raw_text_present"] is True
      assert detail["parsed"]["company"], "parsed posting missing company"

      # 7. Preview HTML renders the tailored resume (fixture company + contact name).
      r = client.get(f"/api/applications/{app_id}/preview")
      assert r.status_code == 200
      assert "text/html" in r.headers["content-type"]
      assert _first_experience_company(tailor) in r.text
      assert tailor["resume"]["contact"]["name"] in r.text

      # 8. All five export endpoints serve files.
      for kind in EXPORT_KINDS:
          r = client.get(f"/api/applications/{app_id}/exports/{kind}")
          assert r.status_code == 200, f"export {kind} -> {r.status_code}"

      # 9. ATS text starts with the fixture contact name uppercased.
      r = client.get(f"/api/applications/{app_id}/exports/resume.txt")
      assert r.status_code == 200
      assert r.text.startswith(tailor["resume"]["contact"]["name"].upper())

      # 10. Application listing shows cost fields.
      r = client.get(f"/api/applications?profile_id={profile_id}")
      assert r.status_code == 200
      rows = [row for row in r.json() if row["id"] == app_id]
      assert len(rows) == 1
      row = rows[0]
      assert "cost_usd" in row
      assert isinstance(row["cost_usd"], (int, float))
      assert row["cost_usd"] == 0.0  # fake mode
      assert row["depth"] == "standard"
      assert row["template"] == "slate"

      # 11. Regenerate with feedback bumps version to 2.
      feedback = "Emphasize the data-platform work more."
      r = client.post(
          f"/api/applications/{app_id}/regenerate", json={"feedback": feedback}
      )
      assert r.status_code in (200, 201), r.text
      # add_task is dropped, so perform the regeneration explicitly:
      pipeline.regenerate_application(app_id, feedback, engine=engine, claude=claude)
      r = client.get(f"/api/applications/{app_id}")
      assert r.status_code == 200
      detail = r.json()
      assert detail["version"] == 2
      assert detail["status"] == "ready"

      return app_id


  def test_e2e_fake_mode_full_flow(tmp_path, monkeypatch):
      """Fast variant: real everything except render_pdf (stubbed) and Claude (fake)."""

      def fake_render_pdf(html: str, out_path: Path, page_size: str = "Letter") -> None:
          out_path = Path(out_path)
          out_path.parent.mkdir(parents=True, exist_ok=True)
          out_path.write_bytes(b"%PDF-1.4 stub e2e\n")

      # Patch BEFORE create_app so demo seeding at startup also uses the stub.
      monkeypatch.setattr(render, "render_pdf", fake_render_pdf)
      fastapi_app = _make_app(tmp_path, monkeypatch)
      claude = ClaudeService(fake_mode=True, fixtures_dir=FIXTURES_DIR)
      with TestClient(fastapi_app) as client:
          _run_full_flow(client, fastapi_app.state.engine, claude)


  @pytest.mark.pdf
  def test_e2e_real_pdf(tmp_path, monkeypatch):
      """PDF variant: same flow with the REAL Playwright renderer; asserts %PDF bytes."""
      fastapi_app = _make_app(tmp_path, monkeypatch)
      claude = ClaudeService(fake_mode=True, fixtures_dir=FIXTURES_DIR)
      with TestClient(fastapi_app) as client:
          app_id = _run_full_flow(client, fastapi_app.state.engine, claude)
          r = client.get(f"/api/applications/{app_id}/exports/resume.pdf")
          assert r.status_code == 200
          assert r.content.startswith(b"%PDF"), r.content[:16]


  def test_readme_quickstart():
      readme_path = PROJECT_ROOT / "README.md"
      assert readme_path.exists(), "README.md is missing"
      readme = readme_path.read_text(encoding="utf-8")
      for needle in (
          "pip install -r requirements.txt",
          "playwright install chromium",
          "python run.py",
          "TAILORED_FAKE=1",
          "ANTHROPIC_API_KEY",
          'pytest -m "not pdf"',
          "TAILORED_PORT",
      ):
          assert needle in readme, f"README.md missing: {needle}"
  ```

- [ ] **Step 2: Run the fast e2e tests, expect exactly the README test to FAIL**

  ```powershell
  cd .; pytest tests/test_e2e.py -m "not pdf" -v
  ```

  Expected output:

  ```
  tests/test_e2e.py::test_e2e_fake_mode_full_flow PASSED
  tests/test_e2e.py::test_readme_quickstart FAILED
  ...
  AssertionError: README.md missing: TAILORED_PORT
  ```

  (If the Task 1 README stub was never written, the failure is
  `AssertionError: README.md is missing` instead — either failure is the expected RED.)

  One test deselected (`test_e2e_real_pdf`, marker `pdf`).

  IMPORTANT: `test_e2e_fake_mode_full_flow` must PASS on this first run — it exercises
  only behavior Tasks 1–17 already shipped. If it FAILS, that is an integration bug in an
  earlier task. Use superpowers:systematic-debugging, fix the bug at its source (the
  service/route/fixture, never by weakening this test), commit that fix with a
  `fix:`-style message under the earlier task's area, and re-run this step until only
  `test_readme_quickstart` fails. Two failure modes worth knowing in advance:
  - `TypeError: process_application() got an unexpected keyword argument 'claude'` →
    Task 9's pipeline is missing the optional `claude` kwarg; add
    `claude: "ClaudeService | None" = None` to `process_application`,
    `resume_after_paste`, and `regenerate_application` in
    `backend/app/services/pipeline.py`, and inside each replace the
    `make_claude(get_settings())` construction with
    `claude = claude if claude is not None else make_claude(get_settings())`.
  - Application ends `needs_paste` instead of `ready` → trafilatura returned empty for
    `POSTING_HTML`; that HTML is intentionally long/realistic, so this indicates a
    fetcher bug (content-type check or extraction wiring), not a test problem.

- [ ] **Step 3: Write the final README.md (COMPLETE content, overwrite any stub)**

  Create `README.md` with exactly this
  content:

  ````markdown
  # Tailored — AI Resume & Cover Letter Builder

  Tailored is a local web app that turns job-posting URLs into customized,
  well-structured resumes and cover letters. You maintain one **Master Profile** —
  everything you have ever done, structured as JSON — and Tailored *selects, reorders,
  and emphasizes* from it per job. It never invents anything
  (see [Truthfulness](#truthfulness)).

  For each job URL it runs a four-stage pipeline:

  1. **Fetch** — downloads the posting and extracts the text (paste fallback for
     login-walled sites).
  2. **Research** — parses the posting; optionally researches the company
     (per-job depth dial, see below).
  3. **Tailor** — Claude (`claude-opus-4-8`) selects and emphasizes the most relevant
     parts of your Master Profile and writes a matching cover letter.
  4. **Render** — four print-tuned templates (Meridian, Slate, Terminal, Signal) →
     PDF, standalone HTML, and ATS-safe plain text.

  Everything runs on your machine. The only network traffic is fetching postings and
  calling the Anthropic API. All state lives in the `data/` folder — a backup is
  copying one folder.

  ## Quickstart (end users)

  You need **Python 3.11+** and an [Anthropic API key](https://console.anthropic.com/).
  Node.js is **not** required — the built frontend is committed.

  ```
  git clone <this-repo-url> tailored
  cd tailored
  python -m venv .venv
  .venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
  pip install -r requirements.txt
  playwright install chromium
  copy .env.example .env          # macOS/Linux: cp .env.example .env
  ```

  Edit `.env` and set your key:

  ```
  ANTHROPIC_API_KEY=sk-ant-...
  ```

  Then start it:

  ```
  python run.py
  ```

  The server starts on http://127.0.0.1:8547 and your browser opens automatically.

  ## Demo mode (no API key, fully offline)

  Want to try it without a key or network? Set `TAILORED_FAKE=1`:

  ```
  # Windows PowerShell
  $env:TAILORED_FAKE = "1"; python run.py

  # macOS / Linux
  TAILORED_FAKE=1 python run.py
  ```

  Demo mode seeds a sample profile plus one finished application and answers every AI
  call from offline fixtures. Every screen is clickable end to end.

  ## Research depth = cost dial

  Research depth is chosen per job when you add it. Approximate cost per application
  (Claude Opus 4.8; real token usage and cost are recorded per application and shown on
  the dashboard):

  | Depth      | What it does                                                        | Approx. cost |
  |------------|---------------------------------------------------------------------|--------------|
  | `quick`    | Parse the posting only                                              | $0.15-0.30   |
  | `standard` | + fetch the company's own site (mission, products, values)          | $0.30-0.60   |
  | `deep`     | + web search: recent news, products, tech-stack & culture signals   | $1-3         |

  ## Truthfulness

  Tailoring is a *selection and emphasis* problem, never invention. The generator may
  reorder, reweight, and rephrase your bullets to mirror a posting's vocabulary — but
  only where factually supported by your Master Profile. It may never invent employers,
  titles, dates, degrees, certifications, tools, or metrics. This is enforced twice:
  in the prompt rubric, and structurally after every generation — each employer, title,
  date range, degree, and certification on the generated resume must match your Master
  Profile exactly, or the application lands in an error state instead of shipping a
  fabrication. Regenerations are versioned, so earlier outputs are never lost.

  ## Development

  ### Frontend (Node required for development only)

  ```
  cd frontend
  npm install
  npm run dev        # Vite dev server; proxies /api to http://127.0.0.1:8547
  ```

  Run the backend (`python run.py`) alongside `npm run dev`. **Before committing UI
  changes, rebuild the bundle** — `frontend/dist/` is committed so end users don't
  need Node:

  ```
  npm run build
  ```

  ### Tests

  ```
  pytest -m "not pdf"      # fast suite (no Chromium)
  pytest                   # full suite, incl. Playwright PDF tests
  cd frontend; npm test    # frontend tests
  ```

  Tests never call the real Anthropic API — the Claude wrapper has a fixture-backed
  fake mode (the same one demo mode uses).

  ## Project layout

  ```
  tailored/
  ├── run.py                  # one-command launcher (server + browser)
  ├── requirements.txt
  ├── .env.example
  ├── backend/
  │   ├── app/
  │   │   ├── main.py         # FastAPI app; serves API + built frontend
  │   │   ├── config.py       # env / settings
  │   │   ├── db.py           # SQLite engine + sessions
  │   │   ├── models.py       # SQLModel entities
  │   │   ├── schemas.py      # Pydantic schemas (the resume JSON contract)
  │   │   ├── services/       # claude, intake, fetcher, research, tailor, render, pipeline
  │   │   ├── api/            # REST routes
  │   │   └── fixtures/       # offline fixtures (tests + demo mode)
  │   └── templates/          # meridian/ slate/ terminal/ signal/ + cover letter
  ├── frontend/               # React + Vite + TypeScript (dist/ committed)
  ├── tests/
  └── data/                   # gitignored: SQLite db, exports/, settings.json
  ```

  ## Troubleshooting

  - **LinkedIn or other login-walled postings** — sites that block bots land the
    application in **"needs paste"** (not an error). Open the application, paste the
    posting text into the prompt, and the pipeline resumes identically.
  - **Playwright browser missing** (`Executable doesn't exist` or similar) — install
    the browser once: `playwright install chromium`.
  - **Port already in use** — Tailored defaults to port 8547. Set `TAILORED_PORT` in
    `.env` (e.g. `TAILORED_PORT=8600`) and restart.
  - **Missing API key** — the app still runs; generation actions will prompt you.
    Set `ANTHROPIC_API_KEY` in `.env`, or use demo mode (`TAILORED_FAKE=1`).
  ````

- [ ] **Step 4: Run the fast e2e tests again, expect PASS**

  ```powershell
  cd .; pytest tests/test_e2e.py -m "not pdf" -v
  ```

  Expected output:

  ```
  tests/test_e2e.py::test_e2e_fake_mode_full_flow PASSED
  tests/test_e2e.py::test_readme_quickstart PASSED
  ...
  2 passed, 1 deselected
  ```

- [ ] **Step 5: Run the real-PDF e2e variant, expect PASS**

  No new implementation is needed — `render_pdf` shipped in Task 10; this verifies real
  Chromium PDF output end to end (`%PDF` magic bytes on the downloaded `resume.pdf`).
  This test launches Chromium several times (demo seed + exports + regeneration
  re-export) and may take a minute or two.

  ```powershell
  cd .; pytest tests/test_e2e.py -m pdf -v
  ```

  Expected output:

  ```
  tests/test_e2e.py::test_e2e_real_pdf PASSED
  ...
  1 passed, 2 deselected
  ```

  If it fails with a missing-browser error, run `playwright install chromium` and re-run.

- [ ] **Step 6: Commit the e2e tests and README**

  ```powershell
  cd .; git add tests/test_e2e.py README.md; git commit -m "feat: end-to-end smoke test and final README" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

  (If Step 2 forced a pipeline `claude`-kwarg fix, `backend/app/services/pipeline.py`
  was already committed in that step; if not, `git add` it here too before committing.)

- [ ] **Step 7: Ship check — full fast suite green**

  ```powershell
  cd .; pytest -m "not pdf"
  ```

  Expected: every collected test passes, PDF-marked tests deselected — final line of the
  form `N passed, M deselected` with **0 failed, 0 errors**. Any failure blocks the
  release: debug with superpowers:systematic-debugging, fix at the source, commit the
  fix, re-run.

- [ ] **Step 8: Ship check — frontend tests green**

  ```powershell
  cd frontend; npm test; cd .
  ```

  Expected: the frontend test run (configured in Task 14 as a non-watch, CI-style run)
  exits 0 with all tests passing. Any failure blocks the release — fix, commit, re-run.

- [ ] **Step 9: Ship check — working tree clean**

  ```powershell
  cd .; git status --short
  ```

  Expected: **empty output** (nothing staged, nothing modified, nothing untracked —
  `data/` is gitignored per Task 1). If anything shows up, inspect it: legitimate
  leftovers (e.g. a rebuilt `frontend/dist/`) get committed now with
  `git add -A; git commit -m "chore: pre-release tidy" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`;
  stray junk gets deleted. Re-run until the output is empty.

- [ ] **Step 10: Release commit and tag v0.1.0**

  ```powershell
  cd .; git commit --allow-empty -m "chore: release v0.1.0" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"; git tag v0.1.0
  ```

  Verify:

  ```powershell
  cd .; git tag --list; git log --oneline -3
  ```

  Expected: `v0.1.0` appears in the tag list, and the newest commit is
  `chore: release v0.1.0`. Done — Tailored v0.1.0 is shipped.