# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Tailored is a local FastAPI + React app that turns job-posting URLs into tailored resumes and cover letters from one Master Profile per person (several people can share an install; see "The active person" under Frontend). `README.md` is the user-facing reference (setup, templates, cost, troubleshooting); `docs/EXTENDING.md` documents the three extension seams (MCP tool contract, model-provider seam, template registry). Read those before changing the areas they cover.

This file describes the software. Operator-specific instructions for *using* the app to run a job search (profile, voice, playbook) live outside the repo and, on a machine that has them, load through the gitignored `CLAUDE.local.md`; keep them out of this file.

## Commands

Windows venv interpreter is `.venv\Scripts\python.exe` (macOS/Linux: `.venv/bin/python`). Node is needed only for frontend development — `frontend/dist` is committed.

```
# setup (what Tailored.bat / start_tailored.sh automate)
python -m venv .venv && .venv\Scripts\activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # PDF rendering + the `pdf` test marker
copy .env.example .env               # macOS/Linux: cp; then set ANTHROPIC_API_KEY, or run demo mode

# run
python run.py                        # http://127.0.0.1:8547, opens browser
TAILORED_FAKE=1 python run.py        # offline demo mode: fixture-backed AI, seeded profile

# backend tests (never call the real API; ClaudeService fake mode)
pytest -m "not pdf"                  # fast suite, no Chromium
pytest                               # full suite incl. real headless-Chromium PDF tests
pytest tests/test_pipeline.py -k regenerate      # one file / one test

# frontend
cd frontend
npm install
npm run dev                          # Vite on :5173, proxies /api -> 127.0.0.1:8547 (run python run.py alongside)
npm test                             # vitest run
npx vitest run src/screens/DashboardScreen.test.tsx   # one test file
npm run build                        # tsc + vite build + scripts/stamp-build.mjs

# MCP server (stdio); register with Claude Code:
claude mcp add tailored -- "<abs>\.venv\Scripts\python.exe" "<abs>\backend\mcp_server.py"

# re-vendor template fonts after editing SPECS in the script
python scripts/vendor_fonts.py
```

No linter/formatter is configured (no ruff/black/eslint config); match the surrounding style.

**Frontend changes require a rebuild before commit.** `npm run build` writes `frontend/dist/build-inputs.sha256` (hash of every non-test source file, LF-normalized); `tests/test_frontend_bundle.py` recomputes it and fails the Python suite when `frontend/src` has moved on. Commit `frontend/dist` with the source change (`git status` dirty after a rebuild means you forgot to `git add` it).

## Architecture

### Two intelligences, one gated write path

Everything converges on `verify_truthfulness()` in `backend/app/services/tailor.py`, then `check_style()` in `backend/app/services/style.py` (the voice contract: em dashes, emoji, curly quotes, ellipsis, invisible characters, a short banned-phrase list; ban list is a module constant, hard-fail only what has near-zero legitimate resume use), followed by `render.export_application()`. The pipeline retries tailoring once on a style failure with the violations as feedback; the MCP path returns the list for the agent to correct. Two callers feed it:

1. **Built-in pipeline** (`backend/app/services/pipeline.py`) — synchronous stage machine run via FastAPI `BackgroundTasks` from `api/applications.py`: `queued → fetching → researching → tailoring → rendering → ready`, with `needs_paste` (fetch failed; user pastes text) and `error` as off-ramps. Every transition is committed immediately (`_set_status`) so the polling UI sees progress. Entry points: `process_application`, `resume_after_paste`, `regenerate_application` (bumps `version`, snapshots to `ApplicationVersion`).
2. **MCP mode** (`backend/mcp_server.py` → `backend/mcp_ops.py`) — an external agent (Claude Code, Codex, …) does fetch/parse/research/tailor itself and writes back through 14 tools; no API key involved. `mcp_server.py` is a thin `MCPServer` wrapper (mcp 2.x; `FastMCP` was removed in mcp 2.0): every tool body is offloaded with `anyio.to_thread.run_sync` because export rendering uses Playwright's *sync* API, which refuses to run on a live asyncio loop. All logic lives in `mcp_ops.py` as plain sync functions taking an explicit `engine` (and `data_dir`), raising `McpOpsError` whose message is the agent-facing error. `get_workflow_guide()` is the agent's contract — its JSON schemas are generated from the Pydantic models via `strict_schema`, but the prose and `_WORKED_EXAMPLE` are hand-written, so update them when schemas or tool order change. MCP never follows the web app's person picker: every tool that works on a person takes an explicit `profile_id`, and `get_master_profile()` without one still errors when several people exist. `get_master_profile` also returns `inbox_url` (`services/inbox.py`), and the guide's CANDIDATE'S INBOX section, after WRITING VOICE, tells the agent to open that URL in the user's browser, confirm the mailbox address on the page is the candidate's contact email before reading anything, stop at a sign-in page, and never pick an account by position or sign in on the user's behalf.

The truthfulness guard is exact-match: every resume experience `(company, role, start, end)`, education `(institution, credential)`, and certification `name` must exist in the Master Profile. Violations are returned verbatim to the agent / land the pipeline app in `error`. This is a product guarantee, not a heuristic — do not loosen it.

**Ownership between the two paths:** MCP-created applications park in status `tailoring` until `save_tailored_resume`; the web UI blocks paste/regenerate/edit on that row meanwhile. Conversely MCP writes are rejected while status is in `_PIPELINE_ACTIVE_STATUSES` (`queued|fetching|researching|rendering`).

**MCP queue:** `queue_jobs` creates `not_started`/stage `saved` rows (free, no fetch); `next_pending_job` drains them oldest-first from the DB, so an agent that loses context resumes where it left off; `report_fetch_blocked` moves a job to `needs_paste` with the reason on its timeline. Blocked postings are read by the agent in the *user's own browser session*; by policy (see EXTENDING.md) no evasion tooling (CAPTCHA solving, proxies, UA rotation) is added to that ladder. The built-in `fetcher.py` sends a desktop-Chrome UA header and nothing more.

### Status vs. stage (two orthogonal columns on `Application`)

- `status` = document pipeline state only (`not_started|queued|fetching|researching|tailoring|rendering|ready|needs_paste|error`). Frontend labels/terminal set live in `frontend/src/statuses.ts` — the single source of truth both screens import for "stop polling"; do not redeclare per screen.
- `stage` = job-hunt funnel (`saved|drafted|applied|screening|interview|offer|rejected|withdrawn`, in `models.STAGES`), user-owned, plus `ApplicationEvent` timeline rows (`EVENT_KINDS`; a note is `kind="note"`). The only status→stage coupling is in `_tailor_and_render`: finishing generation moves `saved → drafted`.

### Backend layout (`backend/app/`)

- `main.py` — `create_app(settings, engine)` factory: mounts `/api` routers, then a catch-all that serves `frontend/dist` (SPA fallback; unknown `/api/*` 404s). In fake mode the lifespan seeds demo data via `demo.seed_demo` in a threadpool (same Playwright-sync reason).
- `config.py` — `Settings` reads env once (`ANTHROPIC_API_KEY`, `TAILORED_FAKE`, `TAILORED_DATA_DIR`, `TAILORED_HOST`, `TAILORED_PORT`); `get_settings()` is `lru_cache`d; the install-wide defaults for the three prefs (`default_template`, `default_depth`, `page_size`) live in `data/settings.json` via `load_user_settings/save_user_settings`, and each person's own values override them from `Profile.settings_json`. Every render path and batch create resolves them with `services/person_settings.settings_for(data_dir, profile)`, passing the application's owner (or `body.profile_id` for batch create), never whoever is selected in a browser. `GET/PUT /api/settings?profile_id=N` reads and writes one person's values; without `profile_id` they act on the install-wide file exactly as before. Per-person template and depth defaults reach web-app jobs only: rows from MCP `create_application`/`queue_jobs` keep `slate` and the `Job` default depth.
- `db.py` — SQLite at `<data_dir>/tailored.db`. `init_db` = `create_all` + `_add_missing_columns` (additive `ALTER TABLE ADD COLUMN` for new model fields; requires a scalar default for NOT NULL) + `_backfill_stage`. There is no Alembic: **adding a column = add a defaulted field to the SQLModel class**; never drop/rename/retype.
- `models.py` — SQLModel tables (`Profile`, `SourceDocument`, `Job`, `ResearchBrief`, `Application`, `ApplicationVersion`, `ApplicationEvent`). Structured data is stored as JSON TEXT columns; always go through the typed helpers (`get_resume/set_resume`, `get_master_profile/set_master_profile`, `get_parsed/set_parsed`, `get_contact`, `get_findings`, `get_profile_settings/set_profile_settings`). `Profile.settings_json` holds one person's overrides of the three prefs; its helpers keep only `PROFILE_SETTING_KEYS` with string values, and `{}` means inherit the install-wide values. The `profile` table has no `AUTOINCREMENT`, so SQLite reissues the highest id after a delete; the frontend pairs a remembered id with `created_at`, and tombstoning removed profiles was deliberately left out.
- `schemas.py` — the Pydantic contract shared by API, pipeline, MCP, and prompts: `MasterProfile` (+ `MPExperience/MPProject/SkillGroup/…`), `ParsedPosting`, `ResearchFindings`, `ResumeDoc` (typed sections), `TailorResult`, `UsageInfo`, `FetchResult`.
- `services/claude.py` — the single AI seam. `ClaudeService.structured(task, system, user_content, schema_model, tools, max_tokens) -> (model, UsageInfo)`. Fake mode loads `backend/app/fixtures/<task>.json` (tasks: `intake`, `parse_posting`, `research_standard`, `research_deep`, `tailor`) and records every call on `.calls` for assertions. Real mode uses strict structured output with a prompt-embedded-schema fallback for oversized grammars; `MODEL_ID`/pricing constants live here. `make_claude(settings)` picks the mode.
- `services/` — `intake.py` (uploaded PDF/DOCX/TXT → MasterProfile), `fetcher.py` (httpx + trafilatura; never raises, collapses to `needs_paste`), `research.py` (parse posting; standard/deep research with web_fetch/web_search tools; `quick` returns None), `tailor.py`, `style.py` (`check_style`, the voice contract; `style_report` and `clean_mechanical` for the inline editor), `render.py` (template registry, Jinja HTML, ATS text, JSON-LD, Playwright PDF, `export_application` → five files under `data/exports/<id>/`; `render_resume_html(..., edit_mode=True)` for the inline editor), `inbox.py` (`inbox_url(email)`: a Gmail `?authuser=` URL, the iCloud or Outlook.com mail URL, or None for any other domain), `person_settings.py` (`settings_for`), `removal.py` (`delete_application_rows`, shared by single-application delete and person removal; `remove_person`, which refuses with `RemovalBlocked` (409) while `blocking_applications` finds work in `ACTIVE_STATUSES` newer than `STALE_AFTER`, stages the person's export dirs by rename into `exports/.removing-<profile_id>/` and moves them back if any rename fails, deletes the rows in one transaction, then removes the staging dir).
- `api/` — `applications.py` (batch create, paste/regenerate/retry/generate, template switch, content edit, `preview?edit=1`, exports, events, archive/delete; delete also removes the job and research briefs via `removal.delete_application_rows`), `profiles.py` (CRUD through `profile_summary`, ordered by id and carrying `created_at`/`inbox_url`; detail adds `application_count`, archived included; a blank name is 422; document upload and `DELETE /profiles/{id}/documents/{doc_id}`; `build`, which keeps filled contact fields via `_merge_contact`; `DELETE /profiles/{id}?confirm_name=` removes a person), `settings.py` (optional `?profile_id=N` for one person's values), `setup.py` (emits the exact `claude mcp add` command for the Getting Started screen), `templates.py` (`TEMPLATE_META` + live previews rendered from `fixtures/tailor.json`).

Package import root is the project root: modules are `backend.app.*` (`run.py` and pytest run from root; `mcp_server.py` and `conftest.py` insert the root on `sys.path` themselves).

### Inline editing (the live preview is the editor)

`GET /applications/{id}/preview?edit=1` renders the same document through
`render_resume_html(..., edit_mode=True)`, which adds three attributes from
`templates/_edit.html` and appends `templates/edit_mode.css`:
`data-edit-path` (this element's text *is* the value at that path),
`data-node-path` (this container *is* that object) and `data-delete-path`.
`ApplicationScreen` writes that HTML into an iframe sandboxed
`allow-same-origin` **without** `allow-scripts` — nothing runs inside it; the
parent reads and listens to its document because it is same-origin —
and `frontend/src/inlineEdit.ts` harvests a `ResumeDoc` back out of it.
Harvest rebuilds every array from the containers still in the DOM rather than
from the paths, which is what makes deletion work; the paths only locate the
base object each container came from. Fields the truthfulness guard checks are
rendered `data-locked` and not editable, so a hand edit cannot trip it.

Edit mode is **on-screen only**. `edit_mode=False` output is asserted
byte-identical to golden copies of both body partials
(`tests/test_inline_edit.py`, `tests/golden/`), so nothing here can ever reach
an exported file. `PUT /content` accepts `clean: true` (apply
`style.clean_mechanical`) and always returns `style_violations` from
`style.style_report` — the structured form of `check_style`, carrying the
`data-edit-path` of each hit and whether it has a single correct fix. Hand
edits are reported on, never blocked; the generated path still hard-fails.

### Templates (`backend/templates/`)

Discovered at import by `render.load_registry` from `<name>/template.json` (name must equal dir; `order`, `structure` ∈ `experience-first|projects-forward`, `fonts`). Adding one is three files, no code — see EXTENDING.md §3. Contract enforced by tests: `base.css` owns structure / `style.css` owns identity (no `break-inside`, grid tracks, floats, absolute positioning, or any network reference — `test_base_css_contract.py`); the rendered PDF must extract role → employer → dates in source order, so never reorder flex/grid children (`test_pdf_extraction.py`); manifest fonts and stylesheet `font-family` must agree both ways (`test_template_registry.py`); fonts are SIL-OFL `.woff2` vendored under `templates/fonts/` and base64-inlined so exported HTML is standalone (`test_vendored_fonts.py`, `scripts/vendor_fonts.py`).

### Frontend (`frontend/src/`)

React 18 + react-router-dom v7 + Vite + TypeScript, tested with vitest/jsdom. One API client (`api.ts`), one screen per route in `App.tsx` (`/`, `/getting-started`, `/add`, `/templates`, `/profiles`, `/applications/:id`, `/settings`), shared `types.ts`/`statuses.ts`/`theme.ts`. Screens poll the API until a status in `TERMINAL_STATUSES`.

**The active person** (`person.tsx`). `PersonProvider` wraps `<App/>` in `main.tsx` and is the only frontend code that lists profiles: screens read `usePerson()` (`person`, `people`, `loading`, `labelFor`) and never call `listProfiles` or keep a profile id of their own. The choice is browser-only, stored as `localStorage["tailored-person"]` (`PERSON_STORAGE_KEY`) = `{id, created_at}` and used on load only when a person with that id and that `created_at` exists, because SQLite reissues a deleted profile's id; every storage access is in try/catch, and the fallback is the first person. It is never sent to the server, and no backend or MCP behaviour may depend on it. Every per-person fetch is keyed on `person.id` and drops a response that lands after a switch. `components/PersonPicker.tsx` is the nav control. A screen with work a switch would lose calls `setSwitchGuard(message)`, and clears it when the condition ends and in the cleanup of the effect that set it. Picker switches go through `requestSwitch`, which honors the guard; `setPersonId` (the Application screen's switch to an application's owner, with `remember: false`) and `refreshPeople()` bypass it. Call `refreshPeople()` after every profile write; it resolves true only when it applied a freshly fetched list. Screen tests render through `renderWithPerson` in `test-utils.tsx`, a static context of `vi.fn()`s inside a `MemoryRouter`; that file name has no `.test.`, so it is a hashed bundle input and editing it needs `npm run build`.

### Tests (`tests/`)

Fixtures in `conftest.py`: `engine` (tmp SQLite with `init_db`), `session`, `fake_settings` (tmp `data_dir`, `fake_mode=True`), `app`, `client` (TestClient), `claude_fake`. Marker `pdf` = needs Chromium (`test_pdf_extraction.py`, parts of `test_e2e.py`, `test_render.py`, `test_mcp_server.py`); `test_e2e.py` stubs `render_pdf` in the fast variant. `test_claude_real_mode.py` stubs the anthropic client in-process — nothing in the suite touches the network. `data/` is gitignored runtime state; tests must never point at it.

### Design history

`docs/superpowers/specs/*.md` and `docs/superpowers/plans/*.md` are the approved design specs and implementation plans per feature (spec → plan → TDD is the working method here). Check the relevant spec before changing behaviour it defines; the git log is descriptive and worth reading for rationale.
