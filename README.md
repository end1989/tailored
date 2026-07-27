# Tailored — AI Resume & Cover Letter Builder

Tailored is a local web app that turns job-posting URLs into customized,
well-structured resumes and cover letters. You maintain one **Master Profile** —
everything you have ever done, structured as JSON — and Tailored *selects, reorders,
and emphasizes* from it per job. It never invents anything
(see [Truthfulness](#truthfulness)).

## Highlights

- **Truthfulness enforced in the data layer, not the prompt.** Most AI resume tools ask the model nicely not to exaggerate. Tailored rejects any generated resume that contains an employer, title, date, degree, or certification not present in your Master Profile — a structural check on the write path, so the guarantee holds no matter which AI produced the text.
- **Two ways to supply the intelligence, one contract.** Use the built-in Anthropic API pipeline (paste a batch of job URLs and walk away), or connect your own agent over MCP — a from-scratch MCP server (11 tools) that lets Claude Code, Codex, or any MCP-capable client do the work on its own subscription, no API key, and read login-walled postings its browser can reach. The same truthfulness guard applies to both.
- **Your codebase becomes resume evidence.** A portfolio-scan prompt plus an MCP write tool let an agent read the repos in your workspace and write evidence-backed, skill-tagged project entries straight into your profile (additive-only, validated, never destructive).
- **Built to be handed to a non-engineer.** Double-click launcher (Windows `.bat` + Unix `.sh`) that self-installs on first run, a fully offline demo mode needing no API key, eight print-tuned templates exporting PDF / HTML / ATS plain text, dark mode, and a committed frontend build so cloning needs only Python.
- **It tracks the job hunt, not just the generation.** Stages from Saved through Offer, a dated timeline for callbacks, interviews and notes, archive and permanent delete, and saved jobs you can park for free and generate later.
- **Engineered, not vibe-coded.** Spec → implementation plan → test-driven development, every task independently reviewed. 548 automated tests (479 backend including real headless-Chromium PDF rendering and text extraction, 69 frontend), and validated end to end against the live Anthropic API — two API-only bugs were found and fixed that way.

Job URLs can be queued for immediate generation or parked as a saved job to
generate later at no cost. For each job URL you choose to generate, it runs a
four-stage pipeline:

1. **Fetch** — downloads the posting and extracts the text (paste fallback for
   login-walled sites).
2. **Research** — parses the posting; optionally researches the company
   (per-job depth dial, see below).
3. **Tailor** — Claude (`claude-opus-4-8`) selects and emphasizes the most relevant
   parts of your Master Profile and writes a matching cover letter.
4. **Render** — eight print-tuned templates (see [Templates](#templates)) → PDF,
   standalone HTML, and ATS-safe plain text.

Compare all eight templates side by side, with live previews, on the in-app
**Templates** page. The UI also follows your system's light/dark preference
automatically, with a one-click override in the nav bar or Settings.

Got a workspace full of your own repos? Use the
[portfolio scan prompt](docs/portfolio-scan-prompt.md) with Claude Code (or any
capable coding agent) to turn your actual codebases into evidence-backed project
material for your master profile.

Everything runs on your machine. The only network traffic is fetching postings and
calling the Anthropic API. All state lives in the `data/` folder — a backup is
copying one folder.

## Quickstart (Windows)

1. Install **Python 3.11+** from [python.org](https://www.python.org/downloads/) — on
   the first install screen, **check "Add python.exe to PATH"**.
2. Clone or download this repo, then double-click **`Tailored.bat`** in the project
   folder.

The first launch does the setup for you — creates a virtual environment, installs
dependencies, downloads the Chromium browser used for PDF export — which takes a
few minutes. Every launch after that starts in a couple of seconds.

If you don't have an [Anthropic API key](https://console.anthropic.com/) yet, the
launcher offers a **demo mode** with sample data — no key or network access needed.

## Quickstart (macOS / Linux)

You need **Python 3.11+** (check with `python3 --version`, or install via your
package manager / [python.org](https://www.python.org/downloads/)).

```
git clone <this-repo-url> tailored
cd tailored
bash start_tailored.sh
```

Same idea as Windows: the first run sets everything up (a few minutes), later runs
are instant, and the script offers a no-key **demo mode** if you don't have an API
key yet.

## Manual setup (developers)

This is what `Tailored.bat` / `start_tailored.sh` automate above. Use it if you're
developing, on an unsupported OS, or just want full manual control.

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

### Use your own AI agent instead of the API (MCP mode)

Tailored ships an MCP server (`backend/mcp_server.py`) that lets any
MCP-capable agent — Claude Code, Codex CLI, and friends — act as the
intelligence instead of the built-in Anthropic API pipeline. Your coding
agent's subscription does the thinking, so **no API key is needed**, and
because the agent fetches postings with its own browser/tools, it can read
login-walled postings the app's fetcher cannot.

Register it with Claude Code in one line (replace both paths with your
clone's absolute paths — any MCP-capable agent can register the same
command):

```
claude mcp add tailored -- "<abs path>\.venv\Scripts\python.exe" "<abs path>\backend\mcp_server.py"
```

Then ask your agent to read Tailored's workflow guide (the
`get_workflow_guide` tool), and from there it's just:

> tailor my profile for &lt;job url&gt;

The agent reads your master profile, fetches and analyzes the posting,
optionally researches the company, and writes the tailored resume and cover
letter back into Tailored, which renders the same PDF/HTML/ATS exports as the
built-in pipeline. The [truthfulness guard](#truthfulness) applies to agents
too — it is enforced server-side on the write path, so a connected agent
cannot save invented employers, titles, dates, degrees, or certifications;
it gets the violation list back and must correct the resume. See
[docs/EXTENDING.md](docs/EXTENDING.md) for the full tool contract. An
MCP-driven application parks in status `tailoring` until the agent saves,
which blocks that row's web-UI paste/regenerate/edit actions until you save
or delete it, and conversely MCP saves are rejected while the built-in
pipeline is actively processing that same application.

The same connected agent can also import your workspace projects straight into
your master profile: run the
[portfolio scan prompt](docs/portfolio-scan-prompt.md) and the agent writes its
verified findings back through the `add_profile_evidence` tool (additive — it
never overwrites what you already have), no copy-paste needed.

## Demo mode (no API key, fully offline)

`Tailored.bat` / `start_tailored.sh` offer this automatically when no key is found.
To set it manually (e.g. for the manual setup above): set `TAILORED_FAKE=1`:

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
each application's page):

| Depth      | What it does                                                        | Approx. cost |
|------------|---------------------------------------------------------------------|--------------|
| `quick`    | Parse the posting only                                              | $0.15-0.30   |
| `standard` | + fetch the company's own site (mission, products, values)          | $0.30-0.60   |
| `deep`     | + web search: recent news, products, tech-stack & culture signals   | $1-3         |

## Templates

Eight print-tuned templates. Every one is single-column with no sidebars, icons,
skill bars, or text baked into images, because all of those break ATS and LLM
parsing. They differ in typography, rhythm and hierarchy, not in structure.

| Template | Id | What it is | Best for |
|---|---|---|---|
| Meridian | `meridian` | Classic serif with small caps and hairline rules. Understated and traditional. | Corporate, finance, healthcare, government |
| Slate | `slate` | Neutral contemporary sans-serif that builds hierarchy from weight and whitespace rather than rules. | General purpose, safe everywhere |
| Terminal | `terminal` | Technical layout with monospace metadata and projects placed forward. | Engineering, data, infrastructure |
| Signal | `signal` | Confident headline treatment with a single accent used once. | Design, marketing, product |
| Ledger | `ledger` | Executive serif with a large name, wide leading and generous whitespace. | Director level and above |
| Quarto | `quarto` | Academic CV that carries long publication lists gracefully across pages. | Academia, research, grants |
| Dossier | `dossier` | Dense sans-serif that fits a long career onto fewer pages without crowding. | Fifteen or more years of history |
| Plainwork | `plainwork` | Deliberately unstyled: no rules, no colour, no letterspacing, system fonts only. | Workday and government portals, maximum ATS compatibility |

Templates are discovered from `backend/templates/*/template.json`, so the API,
both dropdowns and the gallery all stay in step automatically. You can switch an
existing application to a different template from its page at any time: it
re-renders the resume you already have, with no model call and no cost.

Every typeface except Meridian's and Plainwork's system stacks is a latin-subset
[SIL Open Font License](https://openfontlicense.org/) `.woff2` vendored into the
repo and base64-inlined at render time, so an exported `resume.html` is a single
standalone file that needs no network access to render correctly. Adding a ninth
template is three files and no code: see [docs/EXTENDING.md](docs/EXTENDING.md).

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
├── Tailored.bat             # double-click launcher (Windows)
├── start_tailored.sh        # launch script (macOS/Linux: bash start_tailored.sh)
├── run.py                   # one-command launcher (server + browser)
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
│   └── templates/          # one dir per resume template (template.json +
│                           #   template.html + style.css), shared base.css,
│                           #   vendored fonts/, + cover letter
├── frontend/               # React + Vite + TypeScript (dist/ committed)
├── tests/
└── data/                   # gitignored: SQLite db, exports/, settings.json
```

## Known limitations

- Dashboard polling stops until refresh if one status fetch fails.
- Regenerating while the resume editor is open can let a stale Save overwrite the new version.
- Project bullets aren't editable in the profile editor (preserved on save).
- Browser-printing an exported resume.html always uses Letter (PDF exports honor the page-size setting).
- Standard-depth research is domain-restricted only when a company domain was detected in the posting.
- Token spend from a failed generation isn't counted into the displayed cost.

## Troubleshooting

- **LinkedIn or other login-walled postings** — sites that block bots land the
  application in **"needs paste"** (not an error). Open the application, paste the
  posting text into the prompt, and the pipeline resumes identically.
- **Playwright browser missing** (`Executable doesn't exist` or similar) —
  `Tailored.bat` / `start_tailored.sh` install this automatically on first run (and
  print a warning if it fails, without blocking the rest of the app). If you're on
  the manual setup, or the automatic install failed, install it yourself once:
  `playwright install chromium`.
- **Port already in use** — Tailored defaults to port 8547. If it's Tailored itself
  already running, `run.py` detects that and just opens your browser to it instead
  of erroring. Otherwise set `TAILORED_PORT` in `.env` (e.g. `TAILORED_PORT=8600`)
  and restart.
- **Missing API key** — the app still runs; generation actions will prompt you.
  Set `ANTHROPIC_API_KEY` in `.env`, or use demo mode (`TAILORED_FAKE=1`).
