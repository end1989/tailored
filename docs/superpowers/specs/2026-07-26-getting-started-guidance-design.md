# Getting Started guidance — design spec

**Date:** 2026-07-26
**Status:** Approved (design); implementation plan pending
**Approach:** B — a dedicated "Getting Started" hub plus contextual polish (no first-run wizard)

## Goal

Make Tailored friendlier for a mixed audience by delivering how-to guidance **inside the
running app**, so a user no longer has to read the README or `docs/` to get started. In
particular, make the two ways to power Tailored — the built-in **Anthropic API** pipeline
and **MCP mode** (drive it with Claude Code / Codex / any MCP client) — clear, self-selectable,
and set-up-able entirely in-app.

## Audience & framing

Assume a **mixed audience**. The app does not force a "primary" mode; it presents a clear
three-way choice (API key / MCP / demo) and helps each person self-select and complete setup.

## Scope

### In scope
1. A new **Getting Started** page (nav item + empty-Dashboard call-to-action).
2. A new read-only backend endpoint `GET /api/setup` that returns an **auto-filled, copyable**
   `claude mcp add` command (OS-aware, no hand-substitution of paths).
3. Contextual touchpoints on existing screens (Dashboard empty state, Add Jobs note, Settings).
4. Shared, reusable copy-to-clipboard UI.
5. Tests (backend + frontend) and a rebuilt, committed frontend bundle.

### Out of scope (YAGNI / non-goals)
- **First-run wizard / onboarding state** (that was Approach C). Revisit only if users still get stuck.
- **Storing or editing the API key in-app.** The key is deliberately read from `.env` only and
  never persisted (the current Settings screen states this). The hub *instructs* editing `.env`
  and restarting; it adds no key-writing endpoint.
- **Auto-installing Claude Code or running `claude mcp add`** for the user. We display the command;
  installing an external CLI is the user's responsibility.
- No changes to the generation pipeline, the truthfulness guard, or the MCP tool contract.
- No i18n/localization. No removal of the existing README/docs (the app simply stops *depending*
  on them for setup).

## What the user sees

### New "Getting Started" page
Nav item added in `App.tsx` (between the brand and Dashboard), route `/getting-started`. It is
also the primary call-to-action from the empty Dashboard. Four blocks:

1. **Your setup at a glance** — a live readiness panel:
   - **Master Profile:** created (N entries) / empty → `Create your profile →`
   - **Power mode:** `Anthropic API key: set / not set`; `Demo mode: on` when active
   - A single "You're ready to tailor your first job" confirmation when a profile exists *and*
     web-app generation is possible (API key set **or** demo mode). **MCP setup is not
     app-detectable** — registration lives in the user's own agent config, not anything the
     backend can see — so the MCP card guides setup without ever claiming a detected "ready"
     state, and the readiness panel makes no MCP-readiness claim.

2. **Choose how to power Tailored** — three cards:
   - **Use your Anthropic API key** — "Paste job URLs and walk away. ~$0.15–$3/job by depth."
     Steps: get a key → copyable `ANTHROPIC_API_KEY=…` line for `.env` → restart. Live
     "set / not set" chip.
   - **Use your own Claude agent (MCP)** — "No API key; uses your Claude Code/Codex subscription;
     can read login-walled postings." Shows the **auto-filled, copyable** `claude mcp add tailored
     -- "<python>" "<mcp_server>"` command plus a copyable prompt
     (*"Read Tailored's workflow guide, then tailor my profile for <job url>"*). One honest note:
     this path assumes an MCP client (e.g. Claude Code) is installed.
   - **Just explore (Demo mode)** — "Offline sample data, no key, no network." How to enable; live
     "on" chip.

3. **How Tailored works** — a four-step walkthrough, each deep-linking to the relevant screen:
   Build Master Profile → Add job URLs (depth/template) → Watch generation + truthfulness check on
   the Dashboard → Compare templates & export PDF / HTML / ATS.

4. **Touchpoints on other screens:**
   - **Dashboard** empty state → "New here? Start with **Getting Started** →" + "Create your Master
     Profile →".
   - **Add Jobs** → the existing MCP note deep-links into the MCP card.
   - **Settings** → keeps the API-key card; its MCP card renders the same copyable command via the
     shared component and links to the hub.

## Architecture

### Backend — `GET /api/setup` (new, read-only)
New router `backend/app/api/setup.py`, registered in `main.py` alongside the existing routers.
Returns:

```jsonc
{
  "platform": "windows",                              // os.name == "nt" ? "windows" : "posix"
  "python_path": "<sys.executable>",                  // exact running interpreter
  "mcp_server_path": "<PROJECT_ROOT>/backend/mcp_server.py",
  "mcp_server_exists": true,                           // sanity flag for the UI
  "mcp_command": "claude mcp add tailored -- \"<python_path>\" \"<mcp_server_path>\"",
  "env_line": "ANTHROPIC_API_KEY=sk-ant-...",         // static placeholder template, NOT a real key
  "workflow_guide_tool": "get_workflow_guide"
}
```

Derivation:
- `python_path = sys.executable` — the exact interpreter running the server, so it is correct for
  venv, conda, or system Python without guessing a `.venv` layout.
- `mcp_server_path = str(PROJECT_ROOT / "backend" / "mcp_server.py")`, using `PROJECT_ROOT` from
  `config.py`.
- `platform = "windows" if os.name == "nt" else "posix"`.
- `mcp_command` = f-string with both paths double-quoted (handles spaces/backslashes).
- `mcp_server_exists = Path(mcp_server_path).exists()`.

**Security:** the endpoint takes no input, changes no state, and **never returns the API key
value** — only the already-exposed boolean "is a key set" (from `/settings`). `env_line` is a
literal placeholder.

**Readiness needs no new backend fields.** The panel composes from existing endpoints: `/settings`
(`api_key_set`, `fake_mode`) and `/profiles` (profile count). So the only backend change is this
one endpoint.

### Frontend
- `screens/GettingStartedScreen.tsx` — the hub. On mount, fetches `getSetup()`, `getSettings()`,
  and `listProfiles()` in parallel; renders the four blocks. Read-only (no writes).
- `components/McpSetup.tsx` — the copyable MCP command block, **shared** by the hub and Settings
  (single source of truth).
- `components/CopyButton.tsx` — copy-to-clipboard with "Copied!" feedback; reused for the `.env`
  line, the MCP command, and the agent prompt.
- `api.ts` + `types.ts` — add `getSetup()` and a `SetupShape` type.
- Wiring: `App.tsx` (nav link + route), `DashboardScreen.tsx` (richer empty state),
  `AddJobsScreen.tsx` (deep-link the MCP note), `SettingsScreen.tsx` (embed `<McpSetup/>`, link to
  the hub).

### Data flow
Getting Started mounts → three parallel reads → render. Copy actions use
`navigator.clipboard.writeText`. Writing the API key remains a `.env` + restart action (unchanged);
the hub never writes settings or keys.

## Error handling & edge cases
- **Clipboard:** the app runs on `127.0.0.1` (secure context), so `navigator.clipboard` is
  available; `CopyButton` still degrades gracefully — if `writeText` is absent or rejects, it
  selects the text and shows "Copy failed — select and copy manually." It never throws.
- **`/api/setup` fails:** the hub still renders all static guidance; the MCP card degrades to a
  generic manual template with a note rather than blanking the page.
- **`mcp_server_exists: false`:** inline warning in the MCP card naming the expected path.
- **No profile / demo on / key unset:** readiness reflects each state honestly with the matching
  CTA; the walkthrough stays visible regardless.
- **Windows paths (spaces/backslashes):** command is quoted and shown in a preformatted block with
  overflow handling; copy copies the raw string verbatim.
- **No new coupling** to the generation pipeline or the existing MCP in-progress locking behavior —
  the hub is purely informational.

## Testing
Match existing patterns: pytest (backend) and Vitest + Testing Library (frontend); all fixture-based,
never hitting the real Anthropic API.

**Backend — `tests/test_setup.py`:**
- 200 OK.
- `python_path == sys.executable`.
- `mcp_server_path` ends with `backend/mcp_server.py`.
- `mcp_command` starts with `claude mcp add tailored --` and contains both quoted paths.
- `platform` matches the running OS.
- With a fake `ANTHROPIC_API_KEY` set in the environment, the key value never appears anywhere in
  the response.
- `env_line` equals the placeholder template.

**Frontend:**
- `GettingStartedScreen.test.tsx` — readiness permutations (profile empty vs present; key set vs
  not; demo on/off), MCP command rendered from `getSetup()`, deep-links present.
- `McpSetup.test.tsx` and `CopyButton.test.tsx` — copy success path and clipboard-failure fallback.
- Updates to `App.test.tsx` (new nav item + route), `DashboardScreen.test.tsx` (empty-state links),
  `SettingsScreen.test.tsx` (embedded `McpSetup`).

## Build / finishing steps
- `frontend/dist/` is committed so end users need no Node. After implementation, run
  `npm run build` in `frontend/` and commit the rebuilt bundle.
- Run the fast backend suite (`pytest -m "not pdf"`) and frontend tests (`npm test`) before finishing.

## Files touched (summary)
- **New:** `backend/app/api/setup.py`, `tests/test_setup.py`,
  `frontend/src/screens/GettingStartedScreen.tsx`, `frontend/src/components/McpSetup.tsx`,
  `frontend/src/components/CopyButton.tsx`, plus their `*.test.tsx` files.
- **Edited:** `backend/app/main.py` (register router), `frontend/src/App.tsx`, `api.ts`, `types.ts`,
  `screens/DashboardScreen.tsx`, `screens/AddJobsScreen.tsx`, `screens/SettingsScreen.tsx`, and
  `styles.css` as needed; rebuilt `frontend/dist/`.
