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
