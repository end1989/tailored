# Tailored — Template System Overhaul — Design Spec

Date: 2026-07-26
Status: approved
Depends on: nothing (independent of specs 2, 3, 4)

## 1. What this is

Tailored ships four resume templates. Only one of them — Meridian — reads as a
deliberately designed document. This spec rebuilds the template system so all
eight templates in the final lineup meet Meridian's bar, and fixes the plumbing
that currently makes adding a template invasive.

Two things are true at once and both must survive:

- The output has to look professionally designed.
- The output has to be machine-parseable by ATS software and by LLMs.

These pull against each other. The things that usually make a resume *look*
designed — two-column layouts, sidebars, icons, skill bars, text baked into
images — are exactly the things that destroy parsing. Meridian is good partly
*because* it is single-column and restrained. Every template here therefore
earns its quality from typography, rhythm, hierarchy and restraint, never from
layout tricks. That constraint is not a compromise; it is the design brief.

## 2. What is wrong today

**Identity is CSS-only and the structure is identical.** All four
`backend/templates/*/template.html` files are byte-identical except for their
opening comment. Templates differ only in `style.css`. Meridian works because
its choices form a coherent system (centered header, small caps, hairline
rules); Signal's orange square section bullet and Slate's default system-font
stack are simply weaker choices layered on the same skeleton.

**`base.css` under-owns the system.** It carries a reset, a four-step spacing
scale, and print rules. It does not own a type scale, so every template picks
`pt` values ad hoc. It does not own a measure, so only some templates cap line
length. Every template re-declares `break-inside: avoid` on `.item`. Templates
end up differing by accident as much as by intent.

**System font stacks cap quality.** Georgia, Segoe UI, Arial. Output varies by
machine — a resume rendered on Windows does not match one rendered on macOS.

**A template's existence is asserted in four places that must agree:**

| Location | What it asserts |
|---|---|
| `backend/app/services/render.py:17` | `TEMPLATES` tuple of valid names |
| `backend/app/api/templates.py:19` | `_METADATA` label / description / best_for |
| `frontend/src/screens/AddJobsScreen.tsx:7` | hardcoded array for the dropdowns |
| `frontend/src/screens/SettingsScreen.tsx:10` | hardcoded array for the dropdown |
| `backend/app/services/tailor.py:41` | literal `"terminal"` for the structural hint |

`frontend/src/types.ts:3` additionally pins a four-way union type. Going from
four templates to eight makes this a liability.

**You cannot change the template of an application that already exists.**
`POST /applications/{id}/regenerate` accepts only feedback and re-runs the LLM.
To see your real resume in a different template you must create a new
application and pay for another tailoring run. Eight templates are worth little
if you cannot try them on your own resume.

**The dropdowns show raw ids** (`meridian`, `slate`) rather than labels.

## 3. Decisions

| Decision | Choice |
|---|---|
| Existing templates | Slate, Terminal, Signal rebuilt to Meridian's bar; Meridian's identity kept |
| Lineup size | 8 templates |
| Typefaces | Embed SIL OFL fonts, base64-inlined; Plainwork deliberately uses a system stack |
| Machine readability | Clean extraction (test-enforced) **plus** schema.org JSON-LD in HTML exports |
| Meridian | Visual identity unchanged; **does** inherit `base.css` structural fixes |

### 3.1 The Meridian decision, stated explicitly

Improving `base.css` means Meridian inherits the pagination, measure and rhythm
fixes. Its identity is untouched — same Georgia, same small caps, same hairline
rules, same centered header — but its rendered output will **not** be
byte-identical to today's.

This was raised with the user and accepted. The alternative, freezing Meridian,
would exclude the one template they like from every structural improvement.

## 4. Architecture

### 4.1 Template registry becomes data

Each template directory gains a `template.json` manifest:

```json
{
  "name": "ledger",
  "label": "Ledger",
  "description": "Executive serif with wide leading and generous whitespace.",
  "best_for": "Director-level and above",
  "structure": "experience-first",
  "order": 5,
  "fonts": [
    {"family": "Source Serif 4", "file": "SourceSerif4-Regular.woff2", "weight": 400, "style": "normal"},
    {"family": "Source Serif 4", "file": "SourceSerif4-Semibold.woff2", "weight": 600, "style": "normal"},
    {"family": "Source Serif 4", "file": "SourceSerif4-It.woff2", "weight": 400, "style": "italic"}
  ]
}
```

`render.py` discovers templates by scanning `backend/templates/*/template.json`
at import time and builds an ordered registry keyed by name, sorted by `order`.

- `TEMPLATES` stays as a derived tuple of names, so existing validation in
  `api/settings.py`, `api/applications.py`, `mcp_ops.py` and the test suite
  keeps working unchanged.
- `api/templates.py::_METADATA` is deleted. `TEMPLATE_META` is built from
  manifests.
- `tailor.py::_structural_hint` reads `structure` from the manifest instead of
  comparing against the literal `"terminal"`.
- A malformed or missing manifest fails loudly at import with the offending
  path. A silent skip would make a template vanish from the UI with no
  diagnosis.

Adding a ninth template becomes: create a directory with three files.

### 4.2 Frontend reads the registry

Both `AddJobsScreen` and `SettingsScreen` fetch `/api/templates` and render
`label` (falling back to `name`). The hardcoded arrays are deleted.

`types.ts`: `TemplateName` drops from a four-way union to `string`. This trades
a compile-time check the frontend can no longer honestly make — it does not
know what is on disk — for server-side validation that already exists in
`api/settings.py:43` and `api/applications.py`. `TemplateInfo` gains no new
required fields beyond what `/api/templates` already returns.

The committed `frontend/dist` bundle must be rebuilt as part of this work.

### 4.3 `base.css` becomes a typographic system

`base.css` takes ownership of everything structural, exposed as custom
properties that templates override with *values*:

```
--fs-name, --fs-headline, --fs-section, --fs-body, --fs-meta   type scale
--leading                                                       vertical rhythm
--measure                                                       max line length
--rule-weight, --rule-color                                     rules
--space-1 .. --space-4                                          existing scale
```

It additionally gains:

- The `break-inside: avoid` / `page-break-inside: avoid` pair on `.item`,
  hoisted out of all four template stylesheets where it is currently duplicated.
- Hanging indents on bullets so wrapped lines align to the text, not the marker.
- `orphans` / `widows` on `li`, not just `p`.
- `--measure` applied to `.summary`, `.bullets` and `.detail` by default;
  currently only some templates cap line length, and only on `.summary`.
- Print link handling.
- The `@font-face` block injected per template (§4.4).

The rule: **`base.css` owns structure, `style.css` owns identity.** A template
stylesheet that redefines pagination behaviour is a bug.

### 4.4 Font pipeline

`backend/templates/fonts/` holds Latin-subset `.woff2` files, committed as
binaries, with provenance and licence text in
`backend/templates/fonts/LICENSES.md`.

`render.py` gains:

```python
@functools.lru_cache(maxsize=None)
def _font_css(template: str) -> str:
    """@font-face declarations with base64-inlined woff2 for one template."""
```

Called from `_load_css`, its output is concatenated ahead of `style_css`.
Because it is cached per process, base64 encoding happens once per template per
run. This keeps binaries as binaries in git, keeps every exported HTML file
standalone, and requires no network access at render time — which matters
because `render_pdf` calls `page.set_content(html)` with no base URL and would
silently drop any externally referenced font.

Subsetting to Latin plus common punctuation is done **once, during
implementation**, and the results are committed. There is no build step: the
repo must clone and run with only Python, per the project's existing
constraint.

All fonts are SIL Open Font License, which permits embedding and
redistribution.

### 4.5 The eight templates

| Name | Typeface | Character | Best for |
|---|---|---|---|
| Meridian | Georgia (system) | Unchanged: centered header, small caps, hairline rules | Corporate, finance, healthcare, government |
| Slate | Inter | Neutral default; weight contrast and whitespace instead of rules | General purpose |
| Terminal | IBM Plex Sans + IBM Plex Mono | Mono confined to metadata and skills, as information design | Engineering, data, infrastructure |
| Signal | Public Sans | One accent, used once. The orange square section bullet is removed | Design, marketing, product |
| Ledger | Source Serif 4 | Executive: large name, wide leading, fewer and longer bullets | Director-level and above |
| Quarto | EB Garamond | Academic CV: tolerates long publication lists, multi-page | Academia, research, grants |
| Dossier | Source Sans 3 | Dense: more content per page, 9pt floor on body text | 15+ years of history |
| Plainwork | System stack | Deliberately unstyled: no rules, no colour, no letterspacing | Workday, government portals, maximum ATS |

Terminal keeps `"structure": "projects-forward"`; all others are
`"experience-first"`.

Plainwork's system stack is a design decision, not an omission — its entire
purpose is maximum parser compatibility, and an embedded font is one more
variable between the document and a hostile parser.

### 4.6 Changing template without re-running the LLM

New endpoint:

```
PATCH /applications/{id}/template   body: {"template": "ledger"}
```

Validates the name against the registry, updates `Application.template`, and
re-runs `export_application` against the **stored** `resume_json` and
`cover_letter_md`. No Claude call, no cost, no version bump — the content is
unchanged, only its presentation.

Guards:
- 404 if the application does not exist.
- 409 if `status` is in `PROCESSING_STATUSES`.
- 422 if there is no stored resume yet (nothing to re-render).
- 422 if the template name is unknown.

Returns the updated `application_detail`.

`mcp_ops.py` gains a matching `set_application_template(application_id,
template)` operation exposed as an MCP tool, so agent-driven users get the same
capability.

Frontend: `ApplicationScreen` gains a template selector beside the export
buttons. Changing it calls the endpoint and refreshes the preview and export
links.

### 4.7 Machine readability

A `structured_data.html` partial emits a schema.org `Person` JSON-LD block,
included by all eight templates:

```
Person
  name, email, telephone, address, url / sameAs (from contact.links)
  description                        (summary)
  hasOccupation    -> Occupation     (each experience item)
  worksFor         -> Organization
  alumniOf         -> EducationalOrganization
  hasCredential    -> EducationalOccupationalCredential
  knowsAbout                         (skill group items)
```

Serialized by `render.py::resume_json_ld(resume: ResumeDoc) -> dict`, dumped
with `json.dumps` and emitted through `| safe`, with `</` escaped as `<\/` so a
string in the resume cannot terminate the `<script>` element early. This is the
one place autoescaping is bypassed and it needs a test proving injection is
handled.

`resume.txt` — the ATS artifact produced by `render_ats_text` — is unchanged.
It remains the canonical machine-readable output; JSON-LD is additive and lives
only in the HTML export.

## 5. Testing

Existing tests that must keep passing: `tests/test_templates.py`,
`tests/test_render.py`, `tests/test_api.py`.

New and changed coverage:

- **Registry**: every directory under `backend/templates/` with a
  `template.json` appears in `TEMPLATES` and in `GET /api/templates`, in
  `order`. A malformed manifest raises at import.
- **All eight render**: the existing parametrised tests extend to eight
  automatically via `TEMPLATES`; the all-six-section-types test covers each.
- **PDF text extraction** — the important one. For each template: render the
  fixture resume to PDF, extract text with `pypdf` (already a dependency), and
  assert every employer, title, and date appears **in document order**. This
  converts "AI searchable" from an intention into something that fails the
  build, and it is the specific test that will catch a bad font subset breaking
  text extraction.
- **JSON-LD**: valid JSON, correct `@type` values, and a resume containing
  `</script>` in a bullet does not break the document.
- **Template switch**: changing template re-renders exports, does not bump
  `version`, does not call Claude (assert the client is never invoked), and
  returns 409 mid-pipeline / 422 with no stored resume.
- **Frontend**: `TemplatesScreen`, `AddJobsScreen` and `SettingsScreen` render
  options from the API rather than a hardcoded list, and display labels rather
  than raw ids.
- **`base.css` contract**: no template `style.css` declares
  `break-inside`/`page-break-inside` — enforced by a test that greps the
  stylesheets, so the structure/identity split does not erode.

## 6. Out of scope

- Two-column and sidebar layouts, icons, skill bars, photos. All break the
  parsing guarantees this spec exists to protect.
- PDF/UA tagging and reading-order metadata. Headless Chromium's support is not
  sufficient to deliver it honestly.
- Running headers or footers on page 2+. CSS `position: running()` is not
  supported in Chromium.
- Any change to the tailoring pipeline, truthfulness enforcement, or the
  `resume.txt` format.
- User-authored or uploaded custom templates.

## 7. Risks

**A font subset breaks PDF text extraction.** The specific failure is a subset
missing its `ToUnicode` mapping, which renders correctly but extracts as
garbage — invisible to the eye and fatal to an ATS. Mitigated by the extraction
test in §5, which must be written before the fonts are vendored so it can
actually fail.

**Meridian's rendering shifts.** Accepted and documented in §3.1.

**Repo size.** Roughly 300–600KB of woff2 across seven families at two to three
weights. Acceptable; verified during implementation, and weights are dropped
rather than adding a build step if it runs over.
