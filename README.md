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
- **Playwright browser missing** (`Executable doesn't exist` or similar) — install
  the browser once: `playwright install chromium`.
- **Port already in use** — Tailored defaults to port 8547. Set `TAILORED_PORT` in
  `.env` (e.g. `TAILORED_PORT=8600`) and restart.
- **Missing API key** — the app still runs; generation actions will prompt you.
  Set `ANTHROPIC_API_KEY` in `.env`, or use demo mode (`TAILORED_FAKE=1`).
