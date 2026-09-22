# Tailored — AI Resume & Cover Letter Builder

Tailored is a local web app that turns job-posting URLs into customized,
well-structured resumes and cover letters. You maintain one **Master Profile** —
everything you have ever done, structured as JSON — and Tailored *selects, reorders,
and emphasizes* from it per job. It never invents anything
(see [Truthfulness](#truthfulness)). Several people can share one install,
each with their own profile, applications and settings; see
[Several people, one install](#several-people-one-install).

## Highlights

- **Truthfulness enforced in the data layer, not the prompt.** Most AI resume tools ask the model nicely not to exaggerate. Tailored rejects any generated resume that contains an employer, title, date, degree, or certification not present in your Master Profile — a structural check on the write path, so the guarantee holds no matter which AI produced the text.
- **Voice enforced the same way.** Generated text is rejected if it carries the
mechanical tells of machine writing: em dashes, emoji, curly quotes, the
ellipsis character, invisible spaces, and a short curated list of recruitment
cliches. The check runs on the write path, so it holds for both the built-in
pipeline and any MCP agent, whichever model produced the text. The API pipeline
retries once with the violations attached; an agent gets the list back and
corrects it.
- **Two ways to supply the intelligence, one contract.** Use the built-in Anthropic API pipeline (paste a batch of job URLs and walk away), or connect your own agent over MCP — a from-scratch MCP server (14 tools) that lets Claude Code, Codex, or any MCP-capable client do the work on its own subscription, no API key, and read login-walled postings its browser can reach. The same truthfulness guard applies to both.
- **Your codebase becomes resume evidence.** A portfolio-scan prompt plus an MCP write tool let an agent read the repos in your workspace and write evidence-backed, skill-tagged project entries straight into your profile (additive-only, validated, never destructive).
- **Built to be handed to a non-engineer.** Double-click launcher (Windows `.bat` + Unix `.sh`) that self-installs on first run, a fully offline demo mode needing no API key, eight print-tuned templates exporting PDF / HTML / ATS plain text, dark mode, and a committed frontend build so cloning needs only Python.
- **It tracks the job hunt, not just the generation.** Stages from Saved through Offer, a dated timeline for callbacks, interviews and notes, archive and permanent delete, and saved jobs you can park for free and generate later.
- **Engineered, not vibe-coded.** Spec → implementation plan → test-driven development, every task independently reviewed. 1119 automated tests (851 backend including real headless-Chromium PDF rendering and text extraction, 268 frontend), and validated end to end against the live Anthropic API — two API-only bugs were found and fixed that way.

Job URLs can be queued for immediate generation or parked as a saved job to
generate later at no cost. For each job URL you choose to generate, it runs a
four-stage pipeline:

1. **Fetch** — downloads the posting and extracts the text (paste fallback for
   login-walled sites, and for JavaScript-only pages that carry no schema.org
   job data).
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

**Having issues?** See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common solutions.
Or try: `Tailored.bat --clean` to rebuild the environment from scratch.

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

**Having issues?** See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common solutions.
Or try: `bash start_tailored.sh --clean` to rebuild the environment from scratch.

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

When several people share the install, say whose profile to use. The
copyable prompts on the Getting Started page name the person selected in the
nav for you, and an agent never follows the picker by itself (see
[Several people, one install](#several-people-one-install)).

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

### Working through a list of jobs

Paste a list of URLs at your agent and let it work:

> Queue these twenty jobs for my profile and work through them one at a time.

The agent calls `queue_jobs` once, and all twenty appear on your dashboard as
saved jobs immediately, before anything has been fetched or generated. Nothing
has cost anything yet. It then loops on `next_pending_job`, taking one job all
the way to a finished resume before starting the next, and you watch the list
drain in real time.

The queue lives in the database, not in the agent's context. If the agent
restarts or runs out of context at job eleven, it picks up at job eleven. If you
delete a saved job partway through, the agent simply never receives it.

When a job board refuses to be read, the agent opens the posting in your own
Chrome using your own session, which is what works for postings behind a login
you already hold. Tailored never asks your agent to disguise automated traffic
or defeat a bot check, and no evasion tooling will be added. If that still does
not work, the job is marked blocked with the reason on its timeline and moves
out of the queue into the needs-paste state, so you get a paste box for exactly
that posting instead of finding a row that never moved.

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
call from offline fixtures. Every screen is clickable end to end. To try the
person picker, add a second person with **Add a person** in the nav's person
list. The sample is seeded whenever the database has no people at all, so
removing the last person in demo mode brings the sample person and
application back on the next start.

## Research depth = cost dial

Research depth is chosen per job when you add it, and the Add Jobs form starts
on the selected person's default depth from Settings. Approximate cost per application
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

## Editing by hand

Open an application and the resume preview is the editor: click any line and
type. It is the real template at real size, so what you change is what prints.
The facts the truthfulness check guards - company, role, dates, institution,
credential, certification name - are locked and carry a note saying they live
in your Master Profile, which means a hand edit cannot break that contract. A
small x beside each bullet, entry and section removes it. The cover letter is
edited the same way, in place, on its own tab.

Save rewrites all five export files immediately. There is no AI call and no
cost. The voice check then runs over what you wrote and reports what it found
instead of refusing the save, since it is your own writing: curly quotes, the
ellipsis character and invisible spaces can be fixed for you in one click, and
judgment calls like an em dash are highlighted where they sit and left to you.

## Voice

Generated text that carries the mechanical tells of machine writing (em dashes,
emoji, curly quotes, the ellipsis character, invisible spaces, and a short
curated list of recruitment cliches) is rejected on the write path, for both
the built-in pipeline and MCP agents; the pipeline retries once with the
violations attached, and an agent gets the list back to correct.
The list is deliberately short. Words with real, common, pre-LLM use in resumes - leverage, robust, scale, spearheaded - are not banned, because a false
positive blocks a truthful resume and that is worse than an occasional
stylistic miss.

Set **Voice notes** on your profile to direct the writing explicitly, for
example "Plain and direct. No salesmanship. Short sentences." Tailored also
reads the register of the documents you uploaded during intake, as style only:
every fact still has to come from your Master Profile, and the truthfulness
check is what guarantees it. The register comes from the newest document on
the person's profile, so removing a document on the Profiles screen changes it
from the next generation on: to the newest one left, or to none.

## Several people, one install

One install can serve several people, such as a household sharing a computer.
Each person has their own Master Profile, applications and settings. The person
picker in the nav bar, beside the theme toggle, chooses whose you are looking
at, and every screen follows it: the dashboard lists that person's
applications, Add Jobs adds jobs for them, Getting Started checks their
profile, and Profiles, Settings and Templates show theirs. Switching is one
click at any time, with no sign-in. To add someone, pick **Add a person** at
the bottom of the list.

**The choice is kept per browser.** Tailored remembers the last person picked
in the browser's own storage, and each Chrome profile has its own storage. If
everyone in the household uses their own Chrome profile, Tailored opens on the
right person for each of them, and anyone can still switch. A web page cannot
see which Chrome profile or Google account is signed in, so Tailored does not
guess. The choice is never sent to the server and is not part of `data/`, and
switching in one tab leaves other open tabs as they were.

**Opening another person's application.** A link to someone else's
application switches to its owner for that visit and says so. It does not
change which person this browser opens on next time.

**Unsaved work.** Switching while the Profiles screen has unsaved changes or a
save, upload or Build still running, or while an application's editor has
unsaved edits, asks first, with **Switch anyway** and **Stay**.

**Settings are per person.** Default template, default research depth and page
size belong to the person selected when you change them, and the Settings
screen names that person in its heading. A new person starts from the
install-wide defaults in `data/settings.json`. The API key and the theme are
the same for everyone. An application always renders with the page size of
the person it belongs to, whoever is selected in any browser, and that holds
for renders an MCP agent triggers too. Jobs an agent registers over MCP do not
pick up a person's default template or depth: they start on the Slate template
unless the agent picks another, and a saved job an agent queued uses standard
depth if you later generate it from the dashboard.

**Name, email and documents.** The Profiles screen edits the selected person's
name and email. Build fills in only the contact details that are still empty,
so building over an old resume does not change a name, email or phone number
already there. Each uploaded document has a **Remove** button, which is how to
undo a resume uploaded to the wrong person. Removing a document leaves the
built Master Profile as it is; the next Build reads only what is left.

**The Inbox link.** When a person's email is at Gmail (`gmail.com`,
`googlemail.com`), iCloud (`icloud.com`, `me.com`, `mac.com`) or Outlook.com
(`outlook.com`, `hotmail.com`, `live.com`, `msn.com`), an **Inbox** link beside
the picker opens their mailbox in a new tab. The Gmail link asks for that exact
account; the other two open whichever account is signed in on that site. A
custom domain, including Google Workspace, gets no link, because the domain
does not say who hosts the mail. A connected agent gets the same link as
`inbox_url` from `get_master_profile`, and the workflow guide tells it to
confirm the mailbox on screen is the person's before reading anything and
never to sign in for you.

**Removing a person.** **Remove this person**, at the bottom of the Profiles
screen, states what will be deleted: the person's profile, documents and
applications (archived ones included), plus their exported files. The button
stays disabled until you type the person's name exactly. Removal is permanent
and leaves everyone else's rows and files alone. It is refused while any of the
person's applications is being generated, or is parked for an agent, and has
changed in the last 15 minutes; the refusal links to those applications. Rows
stuck in those states for longer count as abandoned and go with the rest. It
is also refused, with nothing deleted, while another program has one of the
person's exported files open, since Windows will not move an open file; close
it and try again. Saved jobs are removed too, including any an agent is
working through, so stop an agent working for that person first. There is no
MCP tool for removing a person.

**Agents and profile ids.** An agent never follows the picker. Every MCP tool
that works on a person takes an explicit `profile_id`, so name the person when
you ask an agent for work; the copyable prompts on the Getting Started and
Settings pages name the person selected in the nav. After a removal, the next
person created can be given the removed person's `profile_id`. The picker
guards against that by checking each person's creation time as well as the
id, but an agent that kept an old id would act on the new person, so start
each agent session from the person's name rather than a remembered id.

## Development

### Frontend (Node required for development only)

```
cd frontend
npm install
npm run dev        # Vite dev server; proxies /api to http://127.0.0.1:8547
```

Run the backend (`python run.py`) alongside `npm run dev`. **Before committing UI
changes, rebuild the bundle** — `frontend/dist/` is committed so end users don't
need Node, which makes it the UI people actually run:

```
npm run build
```

This is enforced, not left to memory. The build records a hash of every file it
was built from into `frontend/dist/build-inputs.sha256`, and
`tests/test_frontend_bundle.py` recomputes it: editing `frontend/src` without
rebuilding fails the Python suite, naming the files that moved on. Commit
`frontend/dist` along with your source change.

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
- Project bullets aren't editable in the profile editor (preserved on save).
- Browser-printing an exported resume.html always uses Letter (PDF exports honor the page-size setting of the person the application belongs to).
- Standard-depth research is domain-restricted only when a company domain was detected in the posting.
- Token spend from a failed generation isn't counted into the displayed cost.

## Troubleshooting

- **LinkedIn or other login-walled postings** — sites that block bots land the
  application in **"needs paste"** (not an error). Open the application, paste the
  posting text into the prompt, and the pipeline resumes identically. A page that
  comes back with almost no text (under about 400 characters, usually a
  "please enable JavaScript" shell) and no schema.org job data is treated the
  same way.
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
