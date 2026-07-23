# Tailored — AI Resume & Cover Letter Builder — Design Spec

**Date:** 2026-07-22
**Status:** Approved by Eldon (design conversation, this session)
**Project location:** `F:\workspace\WORKSPACE_CLAUDES\web-apps\tailored\` (per workspace conventions)

## 1. What this is

A local web app that turns job posting URLs into customized, well-structured resumes and
cover letters. Generic by design: any user clones it, adds their Anthropic API key, uploads
their existing resume material, and gets tailored application documents per job URL.

**Guiding ideas:**

1. **The Master Profile is the single source of truth.** Everything a person has ever done,
   structured as JSON. Tailoring is a *selection and emphasis* problem, never invention.
2. **Research depth is a per-job dial.** Quick / Standard / Deep — turn it up for
   high-priority applications, down for volume.
3. **Templates are a small curated set**, each strongly designed, all consuming identical
   resume JSON.
4. **Truthfulness is enforced by architecture and prompt.** The generator may rephrase,
   reorder, and emphasize; it may never invent employers, titles, dates, degrees,
   certifications, or metrics.

## 2. Stack

- **Backend:** Python 3.11+, FastAPI, SQLModel over SQLite, Anthropic Python SDK.
- **Frontend:** React + Vite + TypeScript. The built `dist/` is committed so end users need
  only Python; Node is required only for frontend development.
- **PDF rendering:** Playwright (Chromium, headless) printing the rendered HTML.
- **Model:** `claude-opus-4-8`, adaptive thinking (`{"type": "adaptive"}`), structured
  outputs via `output_config.format` where the response feeds rendering.
- **Server tools:** `web_search_20260209` and `web_fetch_20260209` for the research stage.

**End-user setup:** clone → `pip install -r requirements.txt` → `playwright install
chromium` → put `ANTHROPIC_API_KEY` in `.env` → `python run.py` (starts server, opens
browser).

## 3. Project structure

```
tailored/
├── run.py                    # one-command launcher
├── requirements.txt
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app; serves API + built frontend
│   │   ├── config.py         # env/settings
│   │   ├── db.py             # SQLite engine + session
│   │   ├── models/           # SQLModel entities (below)
│   │   ├── services/
│   │   │   ├── intake.py     # uploaded docs -> master profile
│   │   │   ├── fetcher.py    # job posting fetch + readability extraction
│   │   │   ├── research.py   # parse posting + Quick/Standard/Deep research
│   │   │   ├── tailor.py     # resume + cover letter generation
│   │   │   ├── render.py     # Jinja -> HTML -> PDF; ATS text
│   │   │   └── claude.py     # client wrapper, prompts, fake mode, usage tracking
│   │   └── api/              # REST routes (profiles, jobs, applications, exports)
│   └── templates/            # resume templates: base/ + meridian/ slate/ terminal/ signal/
├── frontend/                 # React app (dist/ committed)
├── tests/
└── data/                     # SQLite db + generated files (gitignored)
```

## 4. Data model

All entities in SQLite via SQLModel. JSON payloads stored as JSON columns.

- **Profile** — one per person; multiple profiles per install supported.
  - `name`, `contact` (email, phone, location, links)
  - `master_profile` (JSON): `summary_notes`, `experiences[]` (company, title, start/end,
    location, `bullets[]` each with text + `tags[]` of skills/themes demonstrated),
    `skills[]` (grouped), `education[]`, `projects[]`, `certifications[]`, `extras`
  - Every bullet carries tags so the tailor stage can select by relevance.
- **SourceDocument** — uploaded file (or pasted text) that fed the profile; kept for
  re-structuring and provenance.
- **Job** — `url`, `raw_text` (fetched or pasted), `parsed` (JSON: title, company,
  must_haves[], nice_to_haves[], keywords[], seniority, tone), `fetch_status`
  (`fetched | needs_paste | pasted`), `depth` (`quick | standard | deep`).
- **ResearchBrief** — per job: `depth`, `findings` (JSON: mission, products, news[],
  tech_stack_signals[], culture_language[], sources[]), token usage.
- **Application** — job + profile + `template` + `resume_json` + `cover_letter_md` +
  `status` (`queued | fetching | researching | tailoring | rendering | ready |
  needs_paste | error`), `error_message`, `version` (regenerations create new versions;
  prior versions retained), token usage + computed cost, paths to rendered files.

## 5. Pipeline

Jobs process asynchronously (FastAPI background tasks); the dashboard polls status.

### 5.1 Fetch
`httpx` GET with browser-like headers → readability extraction (`readability-lxml` or
`trafilatura`) → store clean text on Job. On block/failure (403, login wall, JS-only page):
status `needs_paste`; UI prompts the user to paste the posting text, then the pipeline
resumes identically.

### 5.2 Parse & Research
One Claude call parses the posting into `Job.parsed` (structured output). Then by depth:
- **Quick:** stop after parsing.
- **Standard:** one call with `web_fetch` limited to the company's own domain
  (`allowed_domains`) — homepage/about/values.
- **Deep:** research call with `web_search` + `web_fetch` (with `max_uses` caps) —
  recent news, products, eng-blog/tech-stack signals, culture language. Produces a
  readable ResearchBrief saved and shown in the UI.

### 5.3 Tailor
Single call (streamed) with: master profile, parsed posting, research brief (if any),
template's structural constraints (max bullets per role, section order options), and the
truthfulness rubric. System prompt rules:
- Select the most relevant experiences/bullets; reorder and reweight.
- Rewrite bullets to mirror the posting's vocabulary **only where factually supported**.
- Never invent employers, titles, dates, degrees, certifications, tools, or metrics.
- Cover letter must reference specific research findings (Standard/Deep) or specific
  posting language (Quick); no boilerplate openings.
Output: structured JSON — `resume` (typed schema shared with the renderer) +
`cover_letter` (markdown) + `tailoring_notes` (what it emphasized and why, shown in UI).

### 5.4 Render
`resume_json` → chosen Jinja template → standalone HTML → Playwright print-to-PDF
(Letter default, A4 option). ATS plain text generated directly from `resume_json`.
Cover letter rendered to matching PDF + text. Files stored under
`data/exports/<application_id>/`.

**Cost (Opus 4.8, approximate):** Quick $0.15–0.30 · Standard $0.30–0.60 · Deep $1–3.
Token usage recorded per call; UI shows real cost per application.

## 6. Templates

Four templates, one shared structural base (spacing scale, section grammar, typographic
rhythm). All consume identical `resume_json`. Print CSS tuned for one page first, graceful
two-page overflow (no orphaned headings, no split bullets).

| Template | Character | Intended fields |
|---|---|---|
| **Meridian** | Classic serif, understated | Corporate, finance, healthcare, government |
| **Slate** | Clean contemporary sans (default) | General purpose |
| **Terminal** | Technical; mono accents, projects-forward | Engineering, data |
| **Signal** | Bold headline treatment, accent color | Design, marketing, creative |

Section *order* can vary per template/field (e.g. projects before experience in Terminal),
but the section grammar is fixed: header → summary → core sections → skills → education →
extras.

## 7. UI

React SPA, four areas:

1. **Onboarding / Profile** — upload resumes/notes (PDF, DOCX, TXT, paste) → intake
   service structures them into a master profile → structured editor for review/edit.
   Profile switcher for multiple people per install.
2. **Dashboard** — applications table: company, role, depth, template, status, cost, date.
   Live status updates (polling).
3. **Add Jobs** — paste one or many URLs; per-job depth + template (with defaults); submit
   queues all.
4. **Application view** — tabs: Resume (live HTML preview), Cover Letter, Research Brief,
   Exports. Inline edits to generated content re-render without an API call. "Regenerate
   with feedback" free-text box triggers a new tailor call (new version).
5. **Settings** — API key status, defaults (template, depth, page size), demo mode toggle.

## 8. Error handling

- Every failure lands the Application in a visible state with a human-readable reason and
  a retry action.
- Fetch blocked → `needs_paste` flow (not an error).
- API errors: SDK's built-in retry/backoff for 429/5xx; typed exception chain
  (`RateLimitError` → `APIStatusError` → `APIConnectionError`) mapped to friendly messages.
- Malformed/refused generations: status `error`, raw response persisted for debugging.
- Missing API key: app runs; generation actions prompt for key setup.
- All state in `data/` — backup is copying one folder.

## 9. Testing

- **pytest** with a mocked Claude client (`services/claude.py` supports a fake mode with
  canned fixtures — also powers the UI demo mode).
- Unit: intake structuring, posting parsing, tailoring-output schema validation,
  truthfulness guard checks (generated content references only master-profile facts —
  verified structurally where possible, e.g. employers/dates/titles must match).
- Golden tests: known `resume_json` → each template → HTML snapshot comparison.
- ATS text generation tests.
- API routes via FastAPI `TestClient`.
- One Playwright end-to-end smoke test: JSON → HTML → PDF exists and is non-empty.

## 10. Out of scope (v1)

- Auto-submission to job boards.
- Multi-machine sync / cloud hosting (local single-machine only).
- DOCX export (PDF, HTML, ATS text only).
- Tracking application outcomes / follow-ups (status is about generation, not job-hunt CRM).
