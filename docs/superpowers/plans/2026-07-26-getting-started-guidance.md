# Getting Started guidance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Tailored's setup and how-to guidance inside the running app — a "Getting Started" hub plus contextual touchpoints — so users can pick and set up API-key mode, MCP mode, or demo mode without reading the README.

**Architecture:** One new read-only backend endpoint (`GET /api/setup`) emits an auto-filled, OS-aware `claude mcp add` command from `sys.executable` + `PROJECT_ROOT`. A new `GettingStartedScreen` renders a readiness panel (composed from existing `/settings` + `/profiles`), a three-way mode chooser, and a workflow walkthrough. Two small shared components (`CopyButton`, `McpSetup`) are reused by the hub and Settings.

**Tech Stack:** FastAPI (Python 3.11+), React + Vite + TypeScript, pytest, Vitest + Testing Library.

## Global Constraints

- **No new dependencies** (backend or frontend). Use the browser's `navigator.clipboard`; no clipboard library.
- **Never store or return the Anthropic API key.** The key is read from `.env` only. The endpoint returns only "is a key set" (already on `/settings`) — never the value. The UI instructs editing `.env` + restart; it adds no key-writing path.
- **`frontend/dist/` is committed** so end users need no Node — rebuild and commit the bundle as the final task.
- **Tests never hit the real Anthropic API** — fixture/mock only.
- **Follow existing patterns:** backend routes via `APIRouter` aggregated in `backend/app/api/__init__.py`; frontend calls via the `request<T>` helper and named exports in `api.ts`; UI uses existing CSS classes (`card`, `card-title`, `field`, `field-label`, `muted`, `pill`, `pill-ok`, `pill-warn`, `mono`, `btn`, `btn-ghost`); tests use Vitest globals (`vi`, `describe`, `it`, `expect`) and `MemoryRouter` for screens that use `<Link>`.
- **Copy strings verbatim** where this plan quotes them (mode names, the agent prompt, the `.env` line).
- **Repo policy: work on a feature branch, never commit directly to `main`.** Create/checkout a branch (e.g. `feature/getting-started-guidance`) before Task 1.
- Conventional-commit messages (`feat:`, `test:`, `chore:`, `docs:`), matching repo history.

## File Structure

**New files**
- `backend/app/api/setup.py` — the `GET /api/setup` route (read-only environment/setup info).
- `tests/test_setup.py` — backend tests for the endpoint.
- `frontend/src/components/CopyButton.tsx` — copy-to-clipboard button with feedback + fallback.
- `frontend/src/components/CopyButton.test.tsx`
- `frontend/src/components/McpSetup.tsx` — copyable MCP registration command + agent prompt; fetches `/api/setup`; shared by hub and Settings.
- `frontend/src/components/McpSetup.test.tsx`
- `frontend/src/screens/GettingStartedScreen.tsx` — the hub (readiness panel, mode chooser, walkthrough).
- `frontend/src/screens/GettingStartedScreen.test.tsx`

**Modified files**
- `backend/app/api/__init__.py` — register the setup router.
- `frontend/src/types.ts` — add `SetupShape`.
- `frontend/src/api.ts` — add `getSetup()`.
- `frontend/src/App.tsx` — add "Getting Started" nav link + `/getting-started` route.
- `frontend/src/App.test.tsx` — assert the new nav link.
- `frontend/src/screens/SettingsScreen.tsx` — replace the README pointer with `<McpSetup/>` + a hub link.
- `frontend/src/screens/SettingsScreen.test.tsx` — mock `McpSetup`.
- `frontend/src/screens/DashboardScreen.tsx` — richer empty state (links to hub + profile).
- `frontend/src/screens/DashboardScreen.test.tsx` — empty-state test.
- `frontend/src/screens/AddJobsScreen.tsx` — deep-link the MCP note to the hub.
- `frontend/src/screens/AddJobsScreen.test.tsx` — assert the hub link.
- `frontend/src/styles.css` — add `.code-block`.
- `frontend/dist/**` — rebuilt bundle (final task).

---

### Task 1: Backend `GET /api/setup` endpoint

**Files:**
- Create: `backend/app/api/setup.py`
- Modify: `backend/app/api/__init__.py`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: `PROJECT_ROOT` from `backend/app/config.py`; the `client` and (for the leak test) `Settings`/`create_app` fixtures from `tests/conftest.py`.
- Produces: `GET /api/setup` returning JSON with keys `platform` (`"windows"|"posix"`), `python_path` (str), `mcp_server_path` (str), `mcp_server_exists` (bool), `mcp_command` (str), `env_line` (str), `workflow_guide_tool` (str).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_setup.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db import get_engine, init_db
from backend.app.main import create_app


def test_setup_returns_running_interpreter_and_command(client):
    resp = client.get("/api/setup")
    assert resp.status_code == 200
    body = resp.json()
    assert body["python_path"] == sys.executable
    assert Path(body["mcp_server_path"]).name == "mcp_server.py"
    assert body["mcp_server_path"].replace("\\", "/").endswith("backend/mcp_server.py")
    assert body["mcp_command"].startswith("claude mcp add tailored -- ")
    assert f'"{sys.executable}"' in body["mcp_command"]
    assert body["platform"] in ("windows", "posix")
    assert body["env_line"] == "ANTHROPIC_API_KEY=sk-ant-..."
    assert body["workflow_guide_tool"] == "get_workflow_guide"
    assert isinstance(body["mcp_server_exists"], bool)


def test_setup_never_leaks_api_key(tmp_path):
    secret = "sk-ant-SECRET-should-not-appear-0000"
    settings = Settings(
        anthropic_api_key=secret,
        data_dir=tmp_path,
        fake_mode=False,
        host="127.0.0.1",
        port=8547,
    )
    engine = get_engine(tmp_path / "leak.db")
    init_db(engine)
    app = create_app(settings=settings, engine=engine)
    resp = TestClient(app).get("/api/setup")
    assert resp.status_code == 200
    assert secret not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_setup.py -v`
Expected: FAIL — 404 on `/api/setup` (route not registered yet).

- [ ] **Step 3: Create the route**

Create `backend/app/api/setup.py`:

```python
"""Setup route: read-only environment info for the in-app Getting Started guide.

Emits the exact, OS-aware `claude mcp add` command (paths taken from the running
interpreter and the project root) so users never hand-substitute paths. Never
returns the Anthropic API key value.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from ..config import PROJECT_ROOT

router = APIRouter()

ENV_LINE_TEMPLATE = "ANTHROPIC_API_KEY=sk-ant-..."


@router.get("/setup")
def read_setup() -> dict[str, Any]:
    python_path = sys.executable
    mcp_server_path = str(PROJECT_ROOT / "backend" / "mcp_server.py")
    platform = "windows" if os.name == "nt" else "posix"
    mcp_command = f'claude mcp add tailored -- "{python_path}" "{mcp_server_path}"'
    return {
        "platform": platform,
        "python_path": python_path,
        "mcp_server_path": mcp_server_path,
        "mcp_server_exists": Path(mcp_server_path).exists(),
        "mcp_command": mcp_command,
        "env_line": ENV_LINE_TEMPLATE,
        "workflow_guide_tool": "get_workflow_guide",
    }
```

- [ ] **Step 4: Register the router**

Modify `backend/app/api/__init__.py` — add `setup` to the import and include it:

```python
from . import applications, profiles, settings, setup, templates
```

```python
api_router.include_router(settings.router)
api_router.include_router(setup.router)
api_router.include_router(templates.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_setup.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/setup.py backend/app/api/__init__.py tests/test_setup.py
git commit -m "feat: add read-only /api/setup endpoint for in-app setup guidance"
```

---

### Task 2: `CopyButton` component

**Files:**
- Create: `frontend/src/components/CopyButton.tsx`
- Test: `frontend/src/components/CopyButton.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `export default function CopyButton(props: { text: string; label?: string })` — renders a `<button>` that copies `text` and shows "Copied!" on success or "Copy failed — select manually" on failure.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/CopyButton.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import CopyButton from "./CopyButton";

function stubClipboard(writeText: () => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
}

describe("CopyButton", () => {
  it("copies the text and shows 'Copied!'", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    render(<CopyButton text="hello world" label="Copy" />);
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText("Copied!")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith("hello world");
  });

  it("shows a fallback message when the clipboard write rejects", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    stubClipboard(writeText);
    render(<CopyButton text="hello world" />);
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(/Copy failed/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/CopyButton.test.tsx`
Expected: FAIL — cannot resolve `./CopyButton`.

- [ ] **Step 3: Create the component**

Create `frontend/src/components/CopyButton.tsx`:

```tsx
import { useState } from "react";

interface CopyButtonProps {
  text: string;
  label?: string;
}

export default function CopyButton({ text, label = "Copy" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  async function handleCopy() {
    setFailed(false);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setFailed(true);
    }
  }

  return (
    <button type="button" className="btn btn-ghost" onClick={handleCopy}>
      {copied ? "Copied!" : failed ? "Copy failed — select manually" : label}
    </button>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/CopyButton.test.tsx`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CopyButton.tsx frontend/src/components/CopyButton.test.tsx
git commit -m "feat: add CopyButton component with clipboard fallback"
```

---

### Task 3: `SetupShape` type, `getSetup()` API, and `McpSetup` component

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/styles.css`
- Create: `frontend/src/components/McpSetup.tsx`
- Test: `frontend/src/components/McpSetup.test.tsx`

**Interfaces:**
- Consumes: `CopyButton` from Task 2; `GET /api/setup` from Task 1.
- Produces: `SetupShape` type; `getSetup(): Promise<SetupShape>`; `export default function McpSetup()` (no props) that fetches `/api/setup` and renders the command + agent prompt with copy buttons, a manual fallback on fetch error, and a warning when `mcp_server_exists` is false.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/McpSetup.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import McpSetup from "./McpSetup";
import * as api from "../api";

vi.mock("../api", () => ({ getSetup: vi.fn() }));

const SETUP = {
  platform: "windows" as const,
  python_path: "C:\\proj\\.venv\\Scripts\\python.exe",
  mcp_server_path: "C:\\proj\\backend\\mcp_server.py",
  mcp_server_exists: true,
  mcp_command:
    'claude mcp add tailored -- "C:\\proj\\.venv\\Scripts\\python.exe" "C:\\proj\\backend\\mcp_server.py"',
  env_line: "ANTHROPIC_API_KEY=sk-ant-...",
  workflow_guide_tool: "get_workflow_guide",
};

describe("McpSetup", () => {
  it("renders the auto-filled mcp command from the backend", async () => {
    vi.mocked(api.getSetup).mockResolvedValue(SETUP);
    render(<McpSetup />);
    expect(await screen.findByText(SETUP.mcp_command)).toBeInTheDocument();
  });

  it("falls back to a manual template when setup detection fails", async () => {
    vi.mocked(api.getSetup).mockRejectedValue(new Error("boom"));
    render(<McpSetup />);
    expect(
      await screen.findByText(/Couldn't detect your paths automatically/)
    ).toBeInTheDocument();
    expect(screen.getByText(/backend\/mcp_server\.py/)).toBeInTheDocument();
  });

  it("warns when the MCP server file is missing", async () => {
    vi.mocked(api.getSetup).mockResolvedValue({ ...SETUP, mcp_server_exists: false });
    render(<McpSetup />);
    expect(await screen.findByText(/couldn't find it/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/McpSetup.test.tsx`
Expected: FAIL — cannot resolve `./McpSetup` (and `getSetup` not yet exported).

- [ ] **Step 3: Add the `SetupShape` type**

Modify `frontend/src/types.ts` — append:

```ts
export interface SetupShape {
  platform: "windows" | "posix";
  python_path: string;
  mcp_server_path: string;
  mcp_server_exists: boolean;
  mcp_command: string;
  env_line: string;
  workflow_guide_tool: string;
}
```

- [ ] **Step 4: Add the `getSetup()` API call**

Modify `frontend/src/api.ts` — add `SetupShape` to the type import block, then add after the `// ---- settings ----` section:

```ts
// ---- setup ----

export function getSetup(): Promise<SetupShape> {
  return request<SetupShape>("/setup");
}
```

- [ ] **Step 5: Add the `.code-block` style**

Modify `frontend/src/styles.css` — append (align colors with existing tokens if the file defines them; this neutral rgba reads acceptably in light and dark):

```css
.code-block {
  display: block;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  overflow-x: auto;
  padding: 0.6rem 0.8rem;
  margin: 0.3rem 0;
  border-radius: 6px;
  background: rgba(127, 127, 127, 0.14);
}
```

- [ ] **Step 6: Create the component**

Create `frontend/src/components/McpSetup.tsx`:

```tsx
import { useEffect, useState } from "react";
import { getSetup } from "../api";
import type { SetupShape } from "../types";
import CopyButton from "./CopyButton";

const AGENT_PROMPT =
  "Read Tailored's workflow guide (the get_workflow_guide tool), then tailor my profile for <job url>.";

const MANUAL_COMMAND =
  'claude mcp add tailored -- "<path to your Python>" "<path to>/backend/mcp_server.py"';

export default function McpSetup() {
  const [setup, setSetup] = useState<SetupShape | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getSetup()
      .then(setSetup)
      .catch(() => setFailed(true));
  }, []);

  const command = setup?.mcp_command ?? MANUAL_COMMAND;

  return (
    <div className="mcp-setup">
      <p className="muted">
        Register Tailored with Claude Code (or any MCP-capable agent). This path assumes you
        already have such an agent installed.
      </p>
      {failed && (
        <p className="muted">
          Couldn't detect your paths automatically — fill in the two paths in the command below.
        </p>
      )}
      {setup && !setup.mcp_server_exists && (
        <div className="alert alert-error">
          Expected the MCP server at <span className="mono">{setup.mcp_server_path}</span> but
          couldn't find it — is your clone complete?
        </div>
      )}
      <div className="field">
        <label className="field-label">1. Register the MCP server</label>
        <pre className="code-block mono">{command}</pre>
        <CopyButton text={command} label="Copy command" />
      </div>
      <div className="field">
        <label className="field-label">2. Ask your agent</label>
        <pre className="code-block mono">{AGENT_PROMPT}</pre>
        <CopyButton text={AGENT_PROMPT} label="Copy prompt" />
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/McpSetup.test.tsx`
Expected: PASS (all three tests).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/styles.css frontend/src/components/McpSetup.tsx frontend/src/components/McpSetup.test.tsx
git commit -m "feat: add McpSetup component and getSetup API for in-app MCP registration"
```

---

### Task 4: `GettingStartedScreen` + nav/route wiring

**Files:**
- Create: `frontend/src/screens/GettingStartedScreen.tsx`
- Test: `frontend/src/screens/GettingStartedScreen.test.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `getSettings`, `listProfiles` from `api.ts`; `McpSetup` (Task 3); `CopyButton` (Task 2); `ProfileSummary.has_master_profile` and `SettingsShape` from `types.ts`.
- Produces: `export default function GettingStartedScreen()`; a `/getting-started` route and a "Getting Started" nav link in `App.tsx`.

- [ ] **Step 1: Write the failing screen test**

Create `frontend/src/screens/GettingStartedScreen.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import GettingStartedScreen from "./GettingStartedScreen";
import * as api from "../api";

vi.mock("../api", () => ({
  getSettings: vi.fn(),
  listProfiles: vi.fn(),
}));
vi.mock("../components/McpSetup", () => ({ default: () => <div>MCP setup block</div> }));

const contact = { name: "", email: "", phone: null, location: null, links: [] };

function renderScreen() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <GettingStartedScreen />
    </MemoryRouter>
  );
}

describe("GettingStartedScreen", () => {
  it("shows the ready confirmation when a profile exists and the API key is set", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listProfiles).mockResolvedValue([
      { id: 1, name: "Me", contact, has_master_profile: true },
    ]);
    renderScreen();
    expect(
      await screen.findByText("You're ready to tailor your first job")
    ).toBeInTheDocument();
  });

  it("prompts to create a profile and shows 'not set' when nothing is configured", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: false,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listProfiles).mockResolvedValue([]);
    renderScreen();
    expect(await screen.findByText("Create your profile →")).toBeInTheDocument();
    expect(screen.getByText("not set")).toBeInTheDocument();
    expect(
      screen.queryByText("You're ready to tailor your first job")
    ).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/screens/GettingStartedScreen.test.tsx`
Expected: FAIL — cannot resolve `./GettingStartedScreen`.

- [ ] **Step 3: Create the screen**

Create `frontend/src/screens/GettingStartedScreen.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getSettings, listProfiles } from "../api";
import type { ProfileSummary, SettingsShape } from "../types";
import CopyButton from "../components/CopyButton";
import McpSetup from "../components/McpSetup";

const ENV_LINE = "ANTHROPIC_API_KEY=sk-ant-...";

export default function GettingStartedScreen() {
  const [settings, setSettings] = useState<SettingsShape | null>(null);
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);

  useEffect(() => {
    getSettings().then(setSettings).catch(() => setSettings(null));
    listProfiles().then(setProfiles).catch(() => setProfiles([]));
  }, []);

  const hasProfile = profiles.some((p) => p.has_master_profile);
  const canGenerateWebApp = Boolean(settings?.api_key_set || settings?.fake_mode);
  const ready = hasProfile && canGenerateWebApp;

  return (
    <div>
      <h1>Getting Started</h1>
      <p className="muted">
        Tailored turns job-posting URLs into truthful, tailored resumes and cover letters from one
        Master Profile you maintain.
      </p>

      <div className="card">
        <div className="card-title">Your setup at a glance</div>
        <p>
          Master Profile:{" "}
          {hasProfile ? (
            <span className="pill pill-ok">created</span>
          ) : (
            <span className="pill pill-warn">empty</span>
          )}{" "}
          {!hasProfile && <Link to="/profiles">Create your profile →</Link>}
        </p>
        <p>
          Anthropic API key:{" "}
          {settings?.api_key_set ? (
            <span className="pill pill-ok">set</span>
          ) : (
            <span className="pill pill-warn">not set</span>
          )}
          {settings?.fake_mode && (
            <span className="pill" style={{ marginLeft: "0.4rem" }}>
              Demo mode on
            </span>
          )}
        </p>
        {ready && <p className="pill pill-ok">You're ready to tailor your first job</p>}
      </div>

      <div className="card">
        <div className="card-title">Choose how to power Tailored</div>

        <div className="field">
          <label className="field-label">Use your Anthropic API key</label>
          <p className="muted">
            Paste job URLs and walk away. ~$0.15–$3 per job by research depth.
          </p>
          <pre className="code-block mono">{ENV_LINE}</pre>
          <CopyButton text={ENV_LINE} label="Copy .env line" />
          <p className="muted">
            Put that line in the <span className="mono">.env</span> file next to{" "}
            <span className="mono">run.py</span> (with your real key) and restart.
          </p>
        </div>

        <div className="field">
          <label className="field-label">Use your own Claude agent (MCP)</label>
          <p className="muted">
            No API key — uses your Claude Code/Codex subscription, and can read login-walled
            postings.
          </p>
          <McpSetup />
        </div>

        <div className="field">
          <label className="field-label">Just explore (Demo mode)</label>
          <p className="muted">
            Offline sample data, no key, no network. Set{" "}
            <span className="mono">TAILORED_FAKE=1</span> and restart, or let the launcher offer it.
          </p>
        </div>
      </div>

      <div className="card">
        <div className="card-title">How Tailored works</div>
        <ol>
          <li>
            Build your <Link to="/profiles">Master Profile</Link> — everything you've done.
          </li>
          <li>
            <Link to="/add">Add job URLs</Link>, pick research depth and template.
          </li>
          <li>
            Watch generation and the truthfulness check on the <Link to="/">Dashboard</Link>.
          </li>
          <li>
            Compare <Link to="/templates">templates</Link> and export PDF / HTML / ATS text.
          </li>
        </ol>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire the nav link and route**

Modify `frontend/src/App.tsx`. Add the import near the other screen imports:

```tsx
import GettingStartedScreen from "./screens/GettingStartedScreen";
```

Add the nav link immediately after the `Dashboard` `NavLink` (before `Add Jobs`):

```tsx
<NavLink to="/getting-started" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
  Getting Started
</NavLink>
```

Add the route inside `<Routes>` (before the settings route):

```tsx
<Route path="/getting-started" element={<GettingStartedScreen />} />
```

- [ ] **Step 5: Update the App shell test for the new link**

Modify `frontend/src/App.test.tsx` — inside the "renders the brand and all nav links" test, add:

```tsx
expect(screen.getByRole("link", { name: "Getting Started" })).toHaveAttribute(
  "href",
  "/getting-started"
);
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/screens/GettingStartedScreen.test.tsx src/App.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/screens/GettingStartedScreen.tsx frontend/src/screens/GettingStartedScreen.test.tsx frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: add Getting Started hub screen with nav link and route"
```

---

### Task 5: Settings integration

**Files:**
- Modify: `frontend/src/screens/SettingsScreen.tsx`
- Test: `frontend/src/screens/SettingsScreen.test.tsx`

**Interfaces:**
- Consumes: `McpSetup` (Task 3).
- Produces: the Settings "Your own AI agent (MCP)" field renders `<McpSetup/>` plus a link to `/getting-started`, replacing the README pointer.

- [ ] **Step 1: Update the Settings test to mock `McpSetup`**

Modify `frontend/src/screens/SettingsScreen.test.tsx`. Add the mock (after the existing `vi.mock("../api", ...)`):

```tsx
vi.mock("../components/McpSetup", () => ({ default: () => <div>MCP setup block</div> }));
```

Add a new test inside the `describe("SettingsScreen", ...)` block:

```tsx
it("embeds the MCP setup block in the generation section", async () => {
  vi.mocked(api.getSettings).mockResolvedValue({
    api_key_set: true,
    fake_mode: false,
    default_template: "slate",
    default_depth: "standard",
    page_size: "Letter",
  });
  render(<SettingsScreen />);
  expect(await screen.findByText("MCP setup block")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/screens/SettingsScreen.test.tsx`
Expected: FAIL — "MCP setup block" not found (component not embedded yet).

- [ ] **Step 3: Embed `McpSetup` in Settings**

Modify `frontend/src/screens/SettingsScreen.tsx`. Add the import at the top:

```tsx
import McpSetup from "../components/McpSetup";
import { Link } from "react-router-dom";
```

Replace the "Your own AI agent (MCP)" field body (the block currently rendering the two `<p className="muted">…</p>` that reference the README / docs/EXTENDING.md) with:

```tsx
<div className="field">
  <label className="field-label">Your own AI agent (MCP)</label>
  <p className="muted">
    Connect Tailored to Claude Code (or any MCP-capable agent) and it does the work on your own
    subscription — no API key used. These applications show a depth of "external" on the
    dashboard, and the same truthfulness guard applies.
  </p>
  <McpSetup />
  <p className="muted">
    New here? The <Link to="/getting-started">Getting Started</Link> page walks through all three
    ways to power Tailored.
  </p>
</div>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/screens/SettingsScreen.test.tsx`
Expected: PASS (existing tests still find "Web app (this browser)" and "Your own AI agent (MCP)"; new test finds "MCP setup block").

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/SettingsScreen.tsx frontend/src/screens/SettingsScreen.test.tsx
git commit -m "feat: embed in-app MCP setup and hub link in Settings"
```

---

### Task 6: Dashboard and Add Jobs touchpoints

**Files:**
- Modify: `frontend/src/screens/DashboardScreen.tsx`, `frontend/src/screens/DashboardScreen.test.tsx`
- Modify: `frontend/src/screens/AddJobsScreen.tsx`, `frontend/src/screens/AddJobsScreen.test.tsx`

**Interfaces:**
- Consumes: the `/getting-started` route (Task 4).
- Produces: an enriched Dashboard empty state and an Add Jobs note, both deep-linking to `/getting-started`.

- [ ] **Step 1: Write the failing tests**

Modify `frontend/src/screens/DashboardScreen.test.tsx`. Add `import * as api from "../api";` at the top (below existing imports), and add a new test that overrides the applications list to empty:

```tsx
it("shows Getting Started and profile links in the empty state", async () => {
  vi.mocked(api.listApplications).mockResolvedValueOnce([]);
  render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <DashboardScreen />
    </MemoryRouter>
  );
  expect(
    await screen.findByRole("link", { name: /Getting Started/ })
  ).toHaveAttribute("href", "/getting-started");
});
```

Modify `frontend/src/screens/AddJobsScreen.test.tsx`. Add to the "shows the plain mode note" test (the `api_key_set: true` case), after the existing assertions:

```tsx
expect(screen.getByRole("link", { name: /See MCP mode/ })).toHaveAttribute(
  "href",
  "/getting-started"
);
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/screens/DashboardScreen.test.tsx src/screens/AddJobsScreen.test.tsx`
Expected: FAIL — no "Getting Started" link in the empty state; no "See MCP mode" link.

- [ ] **Step 3: Enrich the Dashboard empty state**

Modify `frontend/src/screens/DashboardScreen.tsx`. Add `Link` is already imported. Replace the empty-state `<td>` (currently: `No applications yet — queue job URLs from the Add Jobs screen.`) with:

```tsx
<td colSpan={9} className="muted">
  No applications yet. New here? Start with{" "}
  <Link to="/getting-started">Getting Started</Link>, or{" "}
  <Link to="/profiles">create your Master Profile</Link> and then{" "}
  <Link to="/add">add job URLs</Link>.
</td>
```

- [ ] **Step 4: Deep-link the Add Jobs note**

Modify `frontend/src/screens/AddJobsScreen.tsx`. `Link` is already imported. In the block that renders when `!apiKeySet && !fakeMode`, change the message to:

```tsx
<div className="alert alert-error">
  No API key set — add ANTHROPIC_API_KEY to .env and restart, or{" "}
  <Link to="/getting-started">use MCP mode</Link>. Submitting now will fail at generation.
</div>
```

And in the `else` branch (the muted note), change it to:

```tsx
<p className="muted">
  Generated with your Anthropic API key (~$0.15–$3 each, by research depth). Prefer your own
  Claude agent? <Link to="/getting-started">See MCP mode →</Link>
</p>
```

(The strings "No API key set" and "Generated with your Anthropic API key" are preserved so the existing tests still pass.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/screens/DashboardScreen.test.tsx src/screens/AddJobsScreen.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/screens/DashboardScreen.tsx frontend/src/screens/DashboardScreen.test.tsx frontend/src/screens/AddJobsScreen.tsx frontend/src/screens/AddJobsScreen.test.tsx
git commit -m "feat: deep-link Dashboard empty state and Add Jobs note to Getting Started"
```

---

### Task 7: Full test run + rebuild committed bundle

**Files:**
- Modify: `frontend/dist/**` (regenerated)

**Interfaces:**
- Consumes: all prior tasks.
- Produces: passing backend + frontend suites and a rebuilt, committed frontend bundle.

- [ ] **Step 1: Run the full frontend test suite**

Run: `cd frontend && npm test`
Expected: PASS — all suites, including the new CopyButton, McpSetup, GettingStarted, and updated App/Settings/Dashboard/AddJobs tests.

- [ ] **Step 2: Run the fast backend suite**

Run: `pytest -m "not pdf"`
Expected: PASS — including `tests/test_setup.py`.

- [ ] **Step 3: Rebuild the committed frontend bundle**

Run: `cd frontend && npm run build`
Expected: build succeeds; `frontend/dist/` is regenerated.

- [ ] **Step 4: Commit the rebuilt bundle**

```bash
git add frontend/dist
git commit -m "chore: rebuild frontend bundle with Getting Started guidance"
```

---

## Self-Review

**Spec coverage:**
- Getting Started page (nav + empty-Dashboard CTA) → Tasks 4, 6. ✅
- `GET /api/setup` with auto-filled OS-aware command, no secret leak → Task 1. ✅
- Four blocks (readiness / mode chooser / walkthrough / touchpoints) → Task 4 (blocks 1–3) + Tasks 5–6 (touchpoints). ✅
- Shared `McpSetup` + `CopyButton` reused in hub and Settings → Tasks 2, 3, 5. ✅
- Readiness composed from `/settings` + `/profiles`, MCP not claimed as detectable → Task 4 (`canGenerateWebApp` = key or demo only; no MCP-ready claim). ✅
- No key storage; `.env`-only instruction preserved → Tasks 1, 4 (env line is a template; no write path). ✅
- Error handling: clipboard fallback (Task 2), `/api/setup` failure fallback + `mcp_server_exists` warning (Task 3). ✅
- Testing (backend + frontend, fixture-based) → every task + Task 7. ✅
- Committed `dist/` rebuilt → Task 7. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete content. The `sk-ant-...`, `<job url>`, and `<path …>` tokens are intentional user-facing templates, not plan gaps. ✅

**Type consistency:** `SetupShape` fields (Task 3) match the endpoint keys (Task 1) and `McpSetup` usage. `getSetup` name consistent across api.ts, McpSetup, and mocks. `has_master_profile` matches the existing `ProfileSummary` type. Preserved test-critical strings ("No API key set", "Generated with your Anthropic API key", "Web app (this browser)", "Your own AI agent (MCP)"). ✅
