# Extending Tailored

Tailored has three deliberate extension seams: the MCP tool contract (plug in
any agent as the intelligence), the internal pipeline's provider seam (run the
built-in pipeline on any model/provider), and the template registry (add a
resume design with three files and no code).

## 1. The MCP tool contract (any agent)

`backend/mcp_server.py` exposes Tailored over stdio MCP; the business logic
lives in `backend/mcp_ops.py` as plain functions. Any MCP-capable agent that
registers the server (see the README's MCP mode section) can drive the full
workflow. The truthfulness guard runs server-side inside
`save_tailored_resume`, so no connected agent can save fabricated history.

| Tool | What it does |
|------|--------------|
| `get_workflow_guide()` | Call first: returns the workflow order, the truthfulness contract, and the exact JSON schemas with a worked example. |
| `list_profiles()` | List stored profiles (id, name, has_master_profile). |
| `get_master_profile(profile_id?)` | Contact + master profile — the only facts an agent may use. Omitting `profile_id` resolves the sole profile; ambiguity returns an error listing the profiles. |
| `add_profile_evidence(profile_id, projects?, skill_groups?, summary_note?)` | Import portfolio-scan findings into the master profile (`MPProject` + `SkillGroup` shapes). Additive and verified-evidence-only: never overwrites — new projects are appended (duplicate names skipped), same-label skill groups are merged, `summary_note` is appended; safe to call repeatedly. |
| `list_templates()` | Every template in the registry (currently eight) with label/description/best_for metadata, read straight from the manifests. |
| `create_application(profile_id, url, posting_text, template?)` | Register a job with agent-gathered posting text; creates the Job + Application (status `tailoring`, depth `external`) and returns `application_id`. |
| `queue_jobs` | Register many job URLs at once. Free; creates saved jobs. |
| `next_pending_job` | The next queued job, or null when the queue is empty. |
| `report_fetch_blocked` | Record that a posting could not be read, and why. |
| `save_parsed_posting(application_id, parsed)` | Store the agent's `ParsedPosting` analysis (dashboard shows company/title from it). |
| `save_research(application_id, findings)` | Optionally store agent-performed research as a `ResearchFindings` brief (tokens/cost 0). |
| `save_tailored_resume(application_id, resume, cover_letter_md, tailoring_notes?)` | The gated write: validates `ResumeDoc`, verifies truthfulness against the master profile (violations are returned verbatim for correction), snapshots a version, renders and exports; returns `ready` with the export files. |
| `set_application_template(application_id, template)` | Re-render an application that already has a tailored resume in a different template. No model call, no cost, no new version; only presentation changes, and section order is not revisited. |
| `get_application(application_id)` | Status / version / error_message / export files. |

**Concurrency with the built-in pipeline.** An application is owned by
whichever side is actively working it, in one direction only at a time.
MCP-driven applications park in status `tailoring` between
`create_application` and `save_tailored_resume`; while parked, the web UI's
paste/regenerate/edit actions on that row are blocked, so an abandoned agent
run leaves the row stuck there until someone either deletes it from the
dashboard/DB or an agent saves to it to release it. Conversely,
`save_parsed_posting`, `save_research`, `save_tailored_resume`, and
`set_application_template` reject
with an error naming the status whenever the built-in pipeline is actively
processing that application (`queued`, `fetching`, `researching`, or
`rendering`) - retry once it finishes or create a separate application for
the agent run.

`add_profile_evidence` and other profile writes have no such guard: they
use last-writer-wins on the whole profile record, so don't hand-edit a
profile in the web UI while an agent is writing to it (and vice-versa) -
this is a single-user local app and simultaneous edits to the same profile
are unsupported.

### Why Tailored does not fetch blocked postings itself

Playwright is in this project to render PDFs and will not be repurposed to
fetch job postings. A headless browser with no user session is exactly what a
job board's defences are built to refuse, so it would fail at the one job it
was added for while adding a whole category of maintenance.

Blocked postings are read by the client agent, in the user's own browser, with
the user's own session, on a posting the user is entitled to read. That is a
person's browser loading a page, which is what those defences are designed to
permit. Tailored's part is the instruction and the record: the escalation ladder
in `get_workflow_guide`, and `report_fetch_blocked` so giving up is visible
rather than silent.

Bot-detection evasion, CAPTCHA solving, proxying and user-agent spoofing are out
of scope and will not be added.

## 2. The pipeline's provider seam (any model)

Every AI call in the built-in pipeline goes through one method:

```
ClaudeService.structured(
    task, system, user_content, schema_model, tools, max_tokens
) -> (BaseModel, UsageInfo)
```

(`backend/app/services/claude.py`). To run the pipeline on a different model
or provider, implement an object with that method — it must return an
instance of `schema_model` plus a `UsageInfo` — and swap it in `make_claude`
(same file). The fixture-backed fake mode (`ClaudeService` with
`fake_mode=True`) is the reference implementation of the contract: it shows
exactly what the pipeline passes in and expects back, and the whole test
suite runs against it.

## 3. Adding a template

Create `backend/templates/<name>/` containing three files:

- `template.json` — the manifest. Copy an existing one; `name` must equal the
  directory name, `order` decides where it appears in every list, and
  `structure` is either `experience-first` or `projects-forward`
  (`tailor.py` turns that into the structural hint the model is given).
- `template.html` — the shell. Copy any existing one; it includes
  `_resume_body.html` and `_structured_data.html` and differs only in its
  comment. Plainwork is the one exception: it includes
  `_resume_body_plain.html` instead.
- `style.css` — the identity. Override the custom properties `base.css`
  declares (`--fs-name`, `--fs-headline`, `--fs-section`, `--fs-body`,
  `--fs-meta`, `--leading`, `--measure`, `--rule-weight`, `--rule-color`,
  `--item-break`, `--space-1` through `--space-4`), then add your own rules.

Nothing else needs editing. `render.py` picks the directory up at import, and
`TEMPLATES`, `/api/templates`, the MCP `list_templates` tool, both dropdowns
and the gallery follow. A directory without a `template.json`, or with a
malformed one, fails loudly at import rather than vanishing from the UI.

Three rules the test suite enforces:

- **`base.css` owns structure, `style.css` owns identity.** A template
  stylesheet must not declare `break-inside` or `page-break-inside` (set
  `--item-break: auto` instead, as Quarto does for long publication lists),
  must not declare multi-column, CSS grid tracks or placement, a `float` other
  than `none`, or `position: absolute/fixed` (`display: grid` with a gap is
  fine: a single-column grid preserves source order), and must not reference
  the network at all: no
  `https?://`, no `@import`, and no `url()` that is not a `data:` URI.
  `render_pdf` calls `page.set_content` with no base URL, so an external
  reference resolves to nothing and fails silently.
  See `tests/test_base_css_contract.py`.
- **The rendered PDF must extract every employer, title and date in document
  order**, and within one entry must extract as role, then employer, then
  dates. `tests/test_pdf_extraction.py` checks both, through real headless
  Chromium. In practice this means never reordering flex or grid children: no
  `row-reverse`, no `column-reverse`, no `order:`. To flush the dates right,
  use `margin-left: auto`.
- **The manifest and the stylesheet must agree on the typeface.** Every family
  a manifest embeds has to be named in that template's `font-family`
  declarations, and every vendored family a stylesheet asks for has to be
  embedded by its manifest. Either half alone renders a plausible page in the
  wrong face with no error, so both directions are asserted in
  `tests/test_template_registry.py`.

If your template needs a typeface that is not already vendored, add it to
`SPECS` in `scripts/vendor_fonts.py`, re-run the script, and paste the printed
font entries into your manifest. The font must be SIL Open Font License, which
is what permits embedding and redistribution; `tests/test_vendored_fonts.py`
holds the roster, the per-file woff2 integrity check, and the licence
cross-check in both directions.
