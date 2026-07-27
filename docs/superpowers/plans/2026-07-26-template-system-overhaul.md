# Template System Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four hardcoded, CSS-only-differentiated resume templates with a data-driven registry of eight templates that each meet Meridian's design bar, embed their own fonts, emit schema.org JSON-LD, and can be switched on an existing application without re-running the LLM.

**Architecture:** Each template directory gains a `template.json` manifest. `render.py` scans `backend/templates/*/template.json` at import time and builds an ordered registry; `TEMPLATES` becomes a derived tuple so every existing validation site keeps working untouched. `base.css` grows into a typographic system exposing custom properties that templates override with *values only* — structure lives in `base.css`, identity lives in `style.css`, and a grep test enforces the split. Fonts are latin-subset woff2 files vendored into the repo and base64-inlined per template at render time, so every export is standalone with no network access.

**Tech Stack:** Python 3.14 / FastAPI / Jinja2 / Playwright (headless Chromium) / pypdf; React 18 + TypeScript / Vitest.

## Global Constraints

- **Python is `./.venv/Scripts/python.exe`.** The ambient `python` is a conda install missing this project's dependencies. Every command in this plan uses `./.venv/Scripts/python.exe -m pytest ...`. Run from the repo root.
- **No build step for the backend.** The repo must clone and run with only Python. Font subsetting happens once, during implementation, and the results are committed as binaries.
- **Single-column only.** No two-column layouts, no sidebars, no icons, no skill bars, no photos, no text baked into images. Every one of these destroys ATS and LLM parsing, which is the guarantee this work exists to protect. Design quality comes from typography, rhythm, hierarchy and restraint.
- **`base.css` owns structure. `style.css` owns identity.** A template stylesheet that declares `break-inside` or `page-break-inside` is a bug, and Task 5 adds a test that fails the build for it.
- **All vendored fonts are SIL Open Font License**, which permits embedding and redistribution. No other licence is acceptable.
- **Meridian's visual identity does not change.** Same Georgia stack, same small caps, same hairline rules, same centered header. It *does* inherit `base.css` structural fixes, so its rendered output will not be byte-identical to today's. This was raised with the user and accepted (spec §3.1).
- **`resume.txt` (`render_ats_text`) is not modified by any task in this plan.** It remains the canonical machine-readable artifact.
- **No em dashes, no emoji** in any user-visible copy this plan adds (template labels, descriptions, docstrings shown to MCP agents). Use a plain hyphen or restructure the sentence.
- **Frontend package has no `@testing-library/user-event`.** Use `fireEvent` from `@testing-library/react`.
- **Vitest is configured without `clearMocks`/`resetMocks`.** Mock call counts accumulate across tests within a file. Assert observable output, or relative deltas, never absolute call counts.

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| `scripts/vendor_fonts.py` | One-shot, re-runnable fetcher: pulls latin-subset woff2 from Google Fonts, dedupes by content hash, writes `backend/templates/fonts/`, emits manifest font entries and `LICENSES.md`. Not imported by the app. |
| `backend/templates/fonts/*.woff2` | Committed binaries. ~466 KB total. |
| `backend/templates/fonts/LICENSES.md` | Provenance and OFL text. |
| `backend/templates/_resume_body.html` | The canonical resume markup, included by seven templates. Removes the byte-identical duplication called out in spec §2. |
| `backend/templates/_resume_body_plain.html` | Plainwork's deliberately minimal markup. |
| `backend/templates/_structured_data.html` | The JSON-LD `<script>` element. |
| `backend/templates/{ledger,quarto,dossier,plainwork}/` | Four new templates: `template.json` + `template.html` + `style.css`. |
| `backend/templates/{meridian,slate,terminal,signal}/template.json` | Manifests for the existing four. |
| `tests/test_template_registry.py` | Manifest loading, ordering, malformed-manifest failure, font inlining. |
| `tests/test_pdf_extraction.py` | The marquee guard: every template's PDF extracts employers, titles and dates in document order. |
| `tests/test_json_ld.py` | JSON-LD validity, `@type` correctness, script-injection safety. |
| `tests/test_template_switch.py` | The `PATCH /applications/{id}/template` endpoint and its MCP twin. |

**Modified**

| Path | Change |
|---|---|
| `backend/app/services/render.py` | Registry, `_font_css`, `resume_json_ld`, `TEMPLATES` derived. |
| `backend/app/api/templates.py` | `_METADATA` deleted; `TEMPLATE_META` built from manifests. |
| `backend/app/services/tailor.py` | `_structural_hint` reads the manifest; prompt generalised off the `"terminal"` literal. |
| `backend/app/api/applications.py` | New `PATCH /applications/{id}/template` route. |
| `backend/mcp_ops.py`, `backend/mcp_server.py` | `set_application_template` operation and tool; docstrings de-hardcoded from "four". |
| `backend/templates/base.css` | Becomes the typographic system. |
| `backend/templates/{meridian,slate,terminal,signal}/{template.html,style.css}` | Rebuilt. |
| `frontend/src/types.ts` | `TemplateName` becomes `string`. |
| `frontend/src/api.ts` | `setApplicationTemplate`. |
| `frontend/src/screens/{AddJobsScreen,SettingsScreen,ApplicationScreen}.tsx` | Read the registry; add the switcher. |
| `frontend/dist/` | Rebuilt bundle. |
| `README.md`, `docs/EXTENDING.md` | Eight templates, how to add a ninth. |

**Dependency order.** Tasks 1-7 are strictly sequential; each builds on the previous one's changes to `render.py`.

Task 8 must land before Tasks 9 and 10, because its first step creates `backend/templates/_resume_body.html` and the shells written in 9 and 10 include it. Tasks 9 and 10 touch disjoint directories and are independent of each other.

Task 11 (backend) and Task 12 (frontend) are independent of each other and of 8-10. Task 13 depends on both 11 and 12. Task 14 is last and depends on everything.

If two tasks are worked concurrently, only one may run `git add`/`git commit` at a time: a shared index does not tolerate two writers.

---

### Task 1: PDF text-extraction guard

Spec §7 requires this test to exist *before* fonts are vendored, so that a bad font subset makes it fail rather than sliding through. At this point it runs against the four current system-font templates and passes; it will automatically cover all eight as they are added, because it parametrises over `TEMPLATES`.

**Files:**
- Create: `tests/test_pdf_extraction.py`

**Interfaces:**
- Consumes: `backend.app.services.render.TEMPLATES`, `render_resume_html`, `render_pdf`.
- Produces: nothing other tasks import. It is a guard.

- [ ] **Step 1: Write the test**

Rendering eight PDFs one browser-launch at a time is slow, so the fixture launches Chromium once and prints every template inside that one session. Note that it deliberately does **not** call `render_pdf`, which opens its own browser per call.

Create `tests/test_pdf_extraction.py`:

```python
"""Every template must round-trip through PDF with its text intact and in order.

This is the test that converts "AI searchable" from an intention into something
that fails the build. The specific failure it exists to catch is an embedded
font subset shipped without a usable ToUnicode mapping: it renders correctly to
the eye and extracts as garbage to an ATS.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from backend.app.schemas import TailorResult
from backend.app.services.render import TEMPLATES, render_resume_html

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"

pytestmark = pytest.mark.pdf


def _fixture_resume():
    data = json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))
    return TailorResult.model_validate(data).resume


@pytest.fixture(scope="module")
def rendered_text(tmp_path_factory) -> dict[str, str]:
    """template name -> text extracted from its rendered PDF.

    One Chromium launch for all templates; render_pdf launches per call.
    """
    from playwright.sync_api import sync_playwright

    resume = _fixture_resume()
    out_dir = tmp_path_factory.mktemp("extraction")
    texts: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for name in TEMPLATES:
                page = browser.new_page()
                page.set_content(render_resume_html(resume, name), wait_until="load")
                pdf_path = out_dir / f"{name}.pdf"
                page.pdf(
                    path=str(pdf_path),
                    format="Letter",
                    print_background=True,
                    margin={
                        "top": "0.5in",
                        "right": "0.5in",
                        "bottom": "0.5in",
                        "left": "0.5in",
                    },
                )
                page.close()
                texts[name] = "\n".join(
                    pg.extract_text() for pg in PdfReader(str(pdf_path)).pages
                )
        finally:
            browser.close()
    return texts


@pytest.mark.parametrize("template", TEMPLATES)
def test_pdf_extraction_preserves_every_employer_title_and_date(
    rendered_text, template
):
    resume = _fixture_resume()
    text = rendered_text[template]
    for section in resume.sections:
        if section.type != "experience":
            continue
        for item in section.items:
            for field in (item.company, item.role, item.start):
                assert field in text, (
                    f"{template}: {field!r} missing from extracted PDF text. "
                    "The font subset or the markup has broken text extraction."
                )


@pytest.mark.parametrize("template", TEMPLATES)
def test_pdf_extraction_preserves_document_order(rendered_text, template):
    """Employers must appear in the PDF in the same order as in the document.

    An ATS reads top to bottom. A layout that visually reorders content relative
    to the extraction stream produces a resume that reads as nonsense to a parser
    even though it looks correct on screen.
    """
    resume = _fixture_resume()
    text = rendered_text[template]
    companies = [
        item.company
        for section in resume.sections
        if section.type == "experience"
        for item in section.items
    ]
    positions = [text.index(c) for c in companies]
    assert positions == sorted(positions), (
        f"{template}: employers extract out of document order. "
        f"expected {companies}, got positions {positions}"
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_pdf_extraction_preserves_contact_details(rendered_text, template):
    resume = _fixture_resume()
    text = rendered_text[template]
    assert resume.contact.name in text
    assert resume.contact.email in text
```

- [ ] **Step 2: Run it and confirm it passes against today's four templates**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_pdf_extraction.py -v`
Expected: 12 passed (4 templates x 3 tests). If any fails now, stop and report — today's templates already have an extraction problem and that changes the plan.

- [ ] **Step 3: Prove the guard actually bites**

Temporarily edit `backend/templates/meridian/style.css` and add at the end:

```css
.item-head { display: flex; flex-direction: row-reverse; }
```

Run: `./.venv/Scripts/python.exe -m pytest tests/test_pdf_extraction.py -k meridian -v`
Expected: FAIL. `flex-direction: row-reverse` visually reorders the role and company while leaving the extraction stream alone, which is exactly the class of bug this test exists to catch.

If it does NOT fail, the test is not measuring what it claims. Report that rather than proceeding.

- [ ] **Step 4: Revert the deliberate break**

Run: `git checkout backend/templates/meridian/style.css`
Run: `./.venv/Scripts/python.exe -m pytest tests/test_pdf_extraction.py -q`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_pdf_extraction.py
git commit -m "test: guard PDF text extraction and document order for every template"
```

---

### Task 2: Template manifests and the registry

**Files:**
- Modify: `backend/app/services/render.py:17-32`
- Create: `backend/templates/{meridian,slate,terminal,signal}/template.json`
- Create: `tests/test_template_registry.py`

**Interfaces:**
- Produces, all importable from `backend.app.services.render`:
  - `class TemplateManifest` — a frozen dataclass with fields `name: str`, `label: str`, `description: str`, `best_for: str`, `structure: str`, `order: int`, `fonts: tuple[FontFace, ...]`.
  - `class FontFace` — a frozen dataclass with fields `family: str`, `file: str`, `weight: str`, `style: str`. `weight` is a string because a variable font declares a range (`"400 700"`); see Task 3.
  - `TEMPLATE_REGISTRY: dict[str, TemplateManifest]` — insertion-ordered by `order`.
  - `TEMPLATES: tuple[str, ...]` — derived, `tuple(TEMPLATE_REGISTRY)`. Every existing import site keeps working unchanged.
  - `load_registry(templates_dir: Path) -> dict[str, TemplateManifest]` — the scanner, exposed so tests can point it at a tmp dir.
  - `TemplateManifestError(Exception)` — raised on a malformed manifest.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_template_registry.py`:

```python
"""The template registry: manifests on disk are the single source of truth."""
from __future__ import annotations

import json

import pytest

from backend.app.services.render import (
    TEMPLATE_REGISTRY,
    TEMPLATES,
    TEMPLATES_DIR,
    TemplateManifestError,
    load_registry,
)


def test_every_template_directory_has_a_manifest():
    dirs = {
        p.name
        for p in TEMPLATES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
        and p.name != "fonts"
    }
    assert dirs == set(TEMPLATE_REGISTRY)


def test_templates_tuple_is_derived_from_the_registry():
    assert TEMPLATES == tuple(TEMPLATE_REGISTRY)


def test_registry_is_ordered_by_the_manifest_order_field():
    orders = [m.order for m in TEMPLATE_REGISTRY.values()]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders), "two templates share an order value"


def test_meridian_is_first():
    assert TEMPLATES[0] == "meridian"


def test_manifest_name_matches_its_directory():
    for name, manifest in TEMPLATE_REGISTRY.items():
        assert manifest.name == name


def test_every_manifest_declares_a_known_structure():
    for manifest in TEMPLATE_REGISTRY.values():
        assert manifest.structure in ("experience-first", "projects-forward")


def test_every_declared_font_file_exists_on_disk():
    for manifest in TEMPLATE_REGISTRY.values():
        for face in manifest.fonts:
            path = TEMPLATES_DIR / "fonts" / face.file
            assert path.is_file(), f"{manifest.name} declares missing font {face.file}"


def test_malformed_manifest_raises_with_the_offending_path(tmp_path):
    """A silent skip would make a template vanish from the UI with no diagnosis."""
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "template.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(TemplateManifestError) as exc:
        load_registry(tmp_path)
    assert "broken" in str(exc.value)


def test_manifest_missing_a_required_field_raises(tmp_path):
    bad = tmp_path / "incomplete"
    bad.mkdir()
    (bad / "template.json").write_text(
        json.dumps({"name": "incomplete", "label": "Incomplete"}), encoding="utf-8"
    )
    with pytest.raises(TemplateManifestError) as exc:
        load_registry(tmp_path)
    assert "incomplete" in str(exc.value)


def test_manifest_name_disagreeing_with_its_directory_raises(tmp_path):
    bad = tmp_path / "alpha"
    bad.mkdir()
    (bad / "template.json").write_text(
        json.dumps(
            {
                "name": "beta",
                "label": "Beta",
                "description": "d",
                "best_for": "b",
                "structure": "experience-first",
                "order": 1,
                "fonts": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TemplateManifestError):
        load_registry(tmp_path)


def test_unknown_structure_value_raises(tmp_path):
    bad = tmp_path / "weird"
    bad.mkdir()
    (bad / "template.json").write_text(
        json.dumps(
            {
                "name": "weird",
                "label": "Weird",
                "description": "d",
                "best_for": "b",
                "structure": "sideways",
                "order": 1,
                "fonts": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TemplateManifestError):
        load_registry(tmp_path)
```

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_template_registry.py -q`
Expected: collection error, `ImportError: cannot import name 'TEMPLATE_REGISTRY'`.

- [ ] **Step 3: Write the four manifests**

`backend/templates/meridian/template.json`:

```json
{
  "name": "meridian",
  "label": "Meridian",
  "description": "Classic serif with small caps and hairline rules. Understated and traditional.",
  "best_for": "Corporate, finance, healthcare, government",
  "structure": "experience-first",
  "order": 1,
  "fonts": []
}
```

`backend/templates/slate/template.json`:

```json
{
  "name": "slate",
  "label": "Slate",
  "description": "Neutral contemporary sans-serif that builds hierarchy from weight and whitespace rather than rules.",
  "best_for": "General purpose, safe everywhere",
  "structure": "experience-first",
  "order": 2,
  "fonts": []
}
```

`backend/templates/terminal/template.json`:

```json
{
  "name": "terminal",
  "label": "Terminal",
  "description": "Technical layout with monospace metadata and projects placed forward.",
  "best_for": "Engineering, data, infrastructure",
  "structure": "projects-forward",
  "order": 3,
  "fonts": []
}
```

`backend/templates/signal/template.json`:

```json
{
  "name": "signal",
  "label": "Signal",
  "description": "Confident headline treatment with a single accent used once.",
  "best_for": "Design, marketing, product",
  "structure": "experience-first",
  "order": 4,
  "fonts": []
}
```

`fonts` is empty for now. Task 4 fills in Slate, Terminal and Signal; Meridian keeps `[]` permanently because Georgia is a system font.

- [ ] **Step 4: Implement the registry**

In `backend/app/services/render.py`, replace lines 17-32 (the `TEMPLATES` tuple through the end of `_load_css`) with:

```python
TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
FONTS_DIR = TEMPLATES_DIR / "fonts"

STRUCTURES = ("experience-first", "projects-forward")
_REQUIRED_KEYS = frozenset(
    {"name", "label", "description", "best_for", "structure", "order", "fonts"}
)


class TemplateManifestError(Exception):
    """A template.json is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class FontFace:
    """One @font-face declaration.

    `weight` is a string, not an int, because a variable font covers a range and
    declares it as "400 700". A single-weight static font declares "400".
    """

    family: str
    file: str
    weight: str
    style: str


@dataclass(frozen=True)
class TemplateManifest:
    name: str
    label: str
    description: str
    best_for: str
    structure: str
    order: int
    fonts: tuple[FontFace, ...]


def _parse_manifest(path: Path, directory_name: str) -> TemplateManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TemplateManifestError(f"{path}: cannot read manifest: {exc}") from exc
    if not isinstance(raw, dict):
        raise TemplateManifestError(f"{path}: manifest must be a JSON object")
    missing = _REQUIRED_KEYS - set(raw)
    if missing:
        raise TemplateManifestError(
            f"{path}: manifest missing required key(s): {', '.join(sorted(missing))}"
        )
    if raw["name"] != directory_name:
        raise TemplateManifestError(
            f"{path}: manifest name {raw['name']!r} does not match its "
            f"directory {directory_name!r}"
        )
    if raw["structure"] not in STRUCTURES:
        raise TemplateManifestError(
            f"{path}: unknown structure {raw['structure']!r}; "
            f"expected one of {STRUCTURES}"
        )
    if not isinstance(raw["order"], int):
        raise TemplateManifestError(f"{path}: order must be an integer")
    faces: list[FontFace] = []
    for entry in raw["fonts"]:
        try:
            faces.append(
                FontFace(
                    family=entry["family"],
                    file=entry["file"],
                    weight=str(entry["weight"]),
                    style=entry["style"],
                )
            )
        except (TypeError, KeyError) as exc:
            raise TemplateManifestError(
                f"{path}: font entry {entry!r} missing key {exc}"
            ) from exc
    return TemplateManifest(
        name=raw["name"],
        label=raw["label"],
        description=raw["description"],
        best_for=raw["best_for"],
        structure=raw["structure"],
        order=raw["order"],
        fonts=tuple(faces),
    )


def load_registry(templates_dir: Path) -> dict[str, TemplateManifest]:
    """Scan a templates directory and return manifests keyed by name, order-sorted.

    Directories whose name starts with "_" or "." are partials, not templates,
    and "fonts" holds the vendored binaries. Everything else must carry a
    manifest: a directory without one is a template that would silently vanish
    from the UI, which is worse than a loud failure at import.
    """
    manifests: list[TemplateManifest] = []
    for entry in sorted(Path(templates_dir).iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(("_", ".")) or entry.name == "fonts":
            continue
        manifest_path = entry / "template.json"
        if not manifest_path.is_file():
            raise TemplateManifestError(
                f"{entry}: template directory has no template.json"
            )
        manifests.append(_parse_manifest(manifest_path, entry.name))
    manifests.sort(key=lambda m: m.order)
    return {m.name: m for m in manifests}


TEMPLATE_REGISTRY: dict[str, TemplateManifest] = load_registry(TEMPLATES_DIR)
TEMPLATES: tuple[str, ...] = tuple(TEMPLATE_REGISTRY)

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(),
)


def _load_css(template: str) -> tuple[str, str]:
    """Return (base_css, style_css) for a template; raise on unknown template."""
    if template not in TEMPLATE_REGISTRY:
        raise ValueError(f"Unknown template {template!r}; expected one of {TEMPLATES}")
    base_css = (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")
    style_css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    return base_css, style_css
```

Add to the imports at the top of the file:

```python
import json
from dataclasses import dataclass
```

Leave `_env` where the code above places it — after the registry, so a manifest failure surfaces before Jinja is configured.

- [ ] **Step 5: Run the registry tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_template_registry.py -q`
Expected: 10 passed.

- [ ] **Step 6: Run the whole suite — nothing may regress**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 204 passed (192 baseline + 12 from Task 1). Zero failures. `TEMPLATES` is still a tuple of the same four names in the same order, so every existing validation site and test is unaffected.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/render.py backend/templates/*/template.json tests/test_template_registry.py
git commit -m "feat: discover templates from template.json manifests"
```

---

### Task 3: Vendor the fonts

**Files:**
- Create: `scripts/vendor_fonts.py`
- Create: `backend/templates/fonts/*.woff2` (generated)
- Create: `backend/templates/fonts/LICENSES.md` (generated)

**Interfaces:**
- Produces: font files on disk, named `<Stem>-<style>.woff2` for a variable face (`Inter-normal.woff2`) or `<Stem>-<weight>-<style>.woff2` for a static one (`IBMPlexMono-400-normal.woff2`). The script prints the exact JSON `fonts` array to paste into each manifest in Task 4.

**Context the implementer needs.** Google Fonts' `css2` endpoint, given a modern browser User-Agent, returns `@font-face` blocks already split per unicode subset, each pointing at a pre-built woff2. Taking only the block commented `/* latin */` gives a correctly subsetted file with no local fonttools or brotli dependency, neither of which is installed. Several families (Inter, IBM Plex Sans, Public Sans, Source Serif 4, EB Garamond, Source Sans 3) are variable: Google serves the *same* file for every requested weight. Inlining that file once per weight would triple the size of every exported HTML document, so the script dedupes by content hash and collapses the covered weights into a single range.

- [ ] **Step 1: Write the script**

Create `scripts/vendor_fonts.py`:

```python
"""Vendor latin-subset woff2 fonts from Google Fonts into backend/templates/fonts/.

Run once during implementation; the output is committed. There is no build step
at runtime, and the app never touches the network to render.

    ./.venv/Scripts/python.exe scripts/vendor_fonts.py

Google's css2 endpoint returns @font-face blocks already split per unicode
subset. We keep only the block commented /* latin */. Variable families serve
one identical file for every requested weight, so we dedupe by content hash and
collapse the covered weights into a single CSS weight range.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
FONTS_DIR = Path(__file__).resolve().parents[1] / "backend" / "templates" / "fonts"

# (css2 family query, filename stem, human family name, upstream project URL)
SPECS = [
    (
        "Inter:ital,wght@0,400..700;1,400..700",
        "Inter",
        "Inter",
        "https://github.com/rsms/inter",
    ),
    (
        "IBM+Plex+Sans:ital,wght@0,400;0,600;1,400",
        "IBMPlexSans",
        "IBM Plex Sans",
        "https://github.com/IBM/plex",
    ),
    (
        "IBM+Plex+Mono:wght@400;500",
        "IBMPlexMono",
        "IBM Plex Mono",
        "https://github.com/IBM/plex",
    ),
    (
        "Public+Sans:ital,wght@0,400..700;1,400",
        "PublicSans",
        "Public Sans",
        "https://github.com/uswds/public-sans",
    ),
    (
        "Source+Serif+4:ital,opsz,wght@0,8..60,400..600;1,8..60,400",
        "SourceSerif4",
        "Source Serif 4",
        "https://github.com/adobe-fonts/source-serif",
    ),
    (
        "EB+Garamond:ital,wght@0,400..600;1,400",
        "EBGaramond",
        "EB Garamond",
        "https://github.com/octaviopardo/EBGaramond12",
    ),
    (
        "Source+Sans+3:ital,wght@0,400..600;1,400",
        "SourceSans3",
        "Source Sans 3",
        "https://github.com/adobe-fonts/source-sans",
    ),
]

BLOCK = re.compile(
    r"/\*\s*(?P<subset>[a-z0-9\-]+)\s*\*/\s*@font-face\s*\{(?P<body>[^}]*)\}",
    re.IGNORECASE,
)


def _latin_faces(query: str) -> list[dict]:
    """Fetch one family's css2 and return the latin-subset faces with their bytes."""
    url = f"https://fonts.googleapis.com/css2?family={query}&display=swap"
    resp = httpx.get(url, headers={"User-Agent": UA}, timeout=30.0)
    resp.raise_for_status()
    faces = []
    for match in BLOCK.finditer(resp.text):
        if match.group("subset").lower() != "latin":
            continue
        body = match.group("body")
        src = re.search(r"url\((https://[^)]+\.woff2)\)", body)
        family = re.search(r"font-family:\s*'([^']+)'", body)
        style = re.search(r"font-style:\s*([a-z]+)", body)
        weight = re.search(r"font-weight:\s*([0-9]+(?:\s+[0-9]+)?)", body)
        if src is None or family is None:
            raise SystemExit(f"unparsable @font-face for {query}:\n{body}")
        data = httpx.get(src.group(1), headers={"User-Agent": UA}, timeout=30.0)
        data.raise_for_status()
        faces.append(
            {
                "family": family.group(1),
                "style": style.group(1) if style else "normal",
                "weight": (weight.group(1) if weight else "400").strip(),
                "bytes": data.content,
            }
        )
    if not faces:
        raise SystemExit(f"no latin subset returned for {query}")
    return faces


def main() -> int:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    per_family: dict[str, list[dict]] = {}
    provenance: list[tuple[str, str]] = []
    total = 0

    for query, stem, family_name, project_url in SPECS:
        provenance.append((family_name, project_url))
        groups: dict[str, dict] = {}
        css_family = ""
        for face in _latin_faces(query):
            css_family = face["family"]
            digest = hashlib.sha256(face["bytes"]).hexdigest()
            slot = groups.setdefault(
                f"{face['style']}:{digest}",
                {"style": face["style"], "bytes": face["bytes"], "weights": []},
            )
            slot["weights"].extend(int(p) for p in face["weight"].split())

        # Count files per style so a static family (several distinct files for
        # one style) gets weight-qualified names and a variable one does not.
        per_style: dict[str, int] = defaultdict(int)
        for slot in groups.values():
            per_style[slot["style"]] += 1

        entries = []
        for slot in groups.values():
            lo, hi = min(slot["weights"]), max(slot["weights"])
            if per_style[slot["style"]] > 1:
                filename = f"{stem}-{lo}-{slot['style']}.woff2"
            else:
                filename = f"{stem}-{slot['style']}.woff2"
            (FONTS_DIR / filename).write_bytes(slot["bytes"])
            total += len(slot["bytes"])
            entries.append(
                {
                    "family": css_family,
                    "file": filename,
                    "weight": f"{lo} {hi}" if lo != hi else str(lo),
                    "style": slot["style"],
                }
            )
        entries.sort(key=lambda e: (e["style"], e["weight"]))
        per_family[family_name] = entries

    lines = [
        "# Vendored font licences",
        "",
        "Every font in this directory is licensed under the "
        "[SIL Open Font License 1.1](https://openfontlicense.org/), which permits "
        "embedding and redistribution.",
        "",
        "These are latin-subset `.woff2` files fetched from the Google Fonts "
        "`css2` endpoint by `scripts/vendor_fonts.py` and committed as binaries. "
        "There is no build step: the app base64-inlines them at render time so "
        "every exported HTML document is standalone.",
        "",
        "| Family | Upstream project |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | {url} |" for name, url in provenance)
    lines.append("")
    (FONTS_DIR / "LICENSES.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(per_family, indent=2))
    print(f"\nTOTAL: {total / 1024:.1f} KB in {FONTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it**

Run: `./.venv/Scripts/python.exe scripts/vendor_fonts.py`
Expected: a JSON block mapping each family to its font entries, then a total. The total must land between 300 KB and 600 KB. **Save the printed JSON** — Task 4 pastes it into the manifests.

If the total exceeds 600 KB, drop the italic face of the largest family and re-run rather than adding a build step (spec §7).

- [ ] **Step 3: Sanity-check what landed**

Run: `ls -la backend/templates/fonts/ && ./.venv/Scripts/python.exe -c "from pathlib import Path; print(sum(p.stat().st_size for p in Path('backend/templates/fonts').glob('*.woff2'))/1024, 'KB')"`
Expected: roughly 12 to 14 `.woff2` files plus `LICENSES.md`, total 300-600 KB. Every file must start with the bytes `wOF2` — verify:

Run: `./.venv/Scripts/python.exe -c "from pathlib import Path; [print(p.name, p.read_bytes()[:4]) for p in sorted(Path('backend/templates/fonts').glob('*.woff2'))]"`
Expected: every line ends with `b'wOF2'`. Anything else means an HTML error page was saved instead of a font.

- [ ] **Step 4: Commit**

```bash
git add scripts/vendor_fonts.py backend/templates/fonts/
git commit -m "feat: vendor latin-subset OFL woff2 fonts"
```

---

### Task 4: Base64-inline fonts at render time

**Files:**
- Modify: `backend/app/services/render.py` (`_font_css`, `_load_css`)
- Modify: `backend/templates/{slate,terminal,signal}/template.json` (fill in `fonts`)
- Modify: `tests/test_template_registry.py` (append)

**Interfaces:**
- Produces: `render._font_css(template: str) -> str`, `functools.lru_cache`d, returning the `@font-face` block for one template. Concatenated ahead of `style_css` inside `_load_css`, so `template.html`'s `{{ base_css }}{{ style_css }}` contract is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_template_registry.py`:

```python
import base64
import re

from backend.app.services.render import _font_css, _load_css, render_resume_html


def test_font_css_is_empty_for_a_template_with_no_fonts():
    assert _font_css("meridian") == ""


def test_font_css_emits_one_face_per_declared_font():
    css = _font_css("slate")
    assert css.count("@font-face") == len(TEMPLATE_REGISTRY["slate"].fonts)


def test_font_css_inlines_the_bytes_as_a_data_uri():
    css = _font_css("slate")
    face = TEMPLATE_REGISTRY["slate"].fonts[0]
    raw = (TEMPLATES_DIR / "fonts" / face.file).read_bytes()
    assert base64.b64encode(raw).decode("ascii") in css
    assert "data:font/woff2;base64," in css
    assert "https://" not in css, "a render-time network reference would drop silently"


def test_font_css_never_inlines_the_same_file_twice():
    """A variable font covers several weights with one file. Emitting it once per
    weight would multiply the size of every exported HTML document."""
    for name in TEMPLATES:
        css = _font_css(name)
        payloads = re.findall(r"base64,([A-Za-z0-9+/=]+)\)", css)
        assert len(payloads) == len(set(payloads)), f"{name} inlines a font twice"


def test_font_css_is_cached_per_template():
    _font_css.cache_clear()
    _font_css("slate")
    _font_css("slate")
    assert _font_css.cache_info().hits >= 1


def test_load_css_puts_font_faces_ahead_of_the_template_style():
    _base, style = _load_css("slate")
    assert style.index("@font-face") < style.index("body")


def test_rendered_html_carries_the_font_faces():
    resume = _registry_fixture_resume()
    html = render_resume_html(resume, "slate")
    assert "data:font/woff2;base64," in html


def _registry_fixture_resume():
    import json as _json
    from pathlib import Path as _Path

    from backend.app.schemas import TailorResult

    fixtures = _Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"
    data = _json.loads((fixtures / "tailor.json").read_text(encoding="utf-8"))
    return TailorResult.model_validate(data).resume
```

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_template_registry.py -q`
Expected: `ImportError: cannot import name '_font_css'`.

- [ ] **Step 3: Fill in the three manifests**

Paste the entries printed by Task 3 into the `fonts` array of each manifest, dropping any private keys. Mapping (spec §4.5):

- `slate` gets the **Inter** entries.
- `terminal` gets the **IBM Plex Sans** entries followed by the **IBM Plex Mono** entries.
- `signal` gets the **Public Sans** entries.
- `meridian` keeps `"fonts": []`.

A filled-in `slate` manifest looks like this (use the real filenames and weights the script printed, which may differ):

```json
{
  "name": "slate",
  "label": "Slate",
  "description": "Neutral contemporary sans-serif that builds hierarchy from weight and whitespace rather than rules.",
  "best_for": "General purpose, safe everywhere",
  "structure": "experience-first",
  "order": 2,
  "fonts": [
    {"family": "Inter", "file": "Inter-italic.woff2", "weight": "400 700", "style": "italic"},
    {"family": "Inter", "file": "Inter-normal.woff2", "weight": "400 700", "style": "normal"}
  ]
}
```

- [ ] **Step 4: Implement `_font_css`**

Add to `backend/app/services/render.py` immediately above `_load_css`:

```python
@functools.lru_cache(maxsize=None)
def _font_css(template: str) -> str:
    """@font-face declarations with base64-inlined woff2 for one template.

    Cached per process, so a font is base64-encoded once per template per run.
    Inlining matters: render_pdf calls page.set_content(html) with no base URL,
    so an externally referenced font would be silently dropped and the PDF would
    render in a fallback face without any error.
    """
    manifest = TEMPLATE_REGISTRY.get(template)
    if manifest is None:
        raise ValueError(f"Unknown template {template!r}; expected one of {TEMPLATES}")
    blocks: list[str] = []
    for face in manifest.fonts:
        path = FONTS_DIR / face.file
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        blocks.append(
            "@font-face {\n"
            f"  font-family: '{face.family}';\n"
            f"  font-style: {face.style};\n"
            f"  font-weight: {face.weight};\n"
            "  font-display: block;\n"
            f"  src: url(data:font/woff2;base64,{payload}) format('woff2');\n"
            "}"
        )
    return "\n".join(blocks)
```

Change `_load_css` to prepend it:

```python
def _load_css(template: str) -> tuple[str, str]:
    """Return (base_css, style_css) for a template; raise on unknown template.

    style_css carries the template's @font-face declarations ahead of its own
    rules, so the single {{ style_css }} slot in template.html stays sufficient.
    """
    if template not in TEMPLATE_REGISTRY:
        raise ValueError(f"Unknown template {template!r}; expected one of {TEMPLATES}")
    base_css = (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")
    style_css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    font_css = _font_css(template)
    if font_css:
        style_css = f"{font_css}\n\n{style_css}"
    return base_css, style_css
```

Add to the imports at the top of the file:

```python
import base64
import functools
```

`font-display: block` rather than `swap`: Chromium prints the PDF as soon as load fires, and `swap` can flash a fallback face into the printed output.

- [ ] **Step 5: Point the three rebuilt templates at their families**

`style.css` for slate, terminal and signal still names system fonts. Task 8 rebuilds them properly; for now, so this task is independently verifiable, change only the `font-family` declaration in each:

- `backend/templates/slate/style.css`: `font-family: Inter, "Segoe UI", system-ui, sans-serif;`
- `backend/templates/terminal/style.css`: `font-family: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;`
- `backend/templates/signal/style.css`: `font-family: "Public Sans", "Segoe UI", system-ui, sans-serif;`

- [ ] **Step 6: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_template_registry.py -q`
Expected: 17 passed.

- [ ] **Step 7: Prove the fonts survive PDF extraction**

This is the moment the guard from Task 1 earns its keep. Three templates now use embedded fonts.

Run: `./.venv/Scripts/python.exe -m pytest tests/test_pdf_extraction.py -q`
Expected: 12 passed. A failure here means a font subset has no usable ToUnicode mapping and the family must be replaced — do not proceed past it.

- [ ] **Step 8: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 211 passed, 0 failed.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/render.py backend/templates/ tests/test_template_registry.py
git commit -m "feat: base64-inline vendored fonts per template at render time"
```

---

### Task 5: base.css becomes the typographic system

**Files:**
- Modify: `backend/templates/base.css` (whole file)
- Modify: `backend/templates/meridian/style.css:57-60` (delete the duplicated pagination block)
- Create: `tests/test_base_css_contract.py`

**Interfaces:**
- Produces: the custom-property vocabulary every `style.css` written in Tasks 8-10 overrides. Names are fixed here and must not drift.

**The `--item-break` escape hatch.** Quarto (Task 9) is an academic CV that must tolerate a publication list longer than a page, so its items have to be breakable. Rather than let one template redeclare pagination and erode the structure/identity split, `base.css` exposes `--item-break` and Quarto sets it to `auto`. The contract test greps for the *properties*, which Quarto never declares.

- [ ] **Step 1: Write the failing contract test**

Create `tests/test_base_css_contract.py`:

```python
"""base.css owns structure; style.css owns identity. This test keeps them apart."""
from __future__ import annotations

import re

import pytest

from backend.app.services.render import TEMPLATES, TEMPLATES_DIR

BASE_CSS = (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")

REQUIRED_PROPERTIES = (
    "--fs-name",
    "--fs-headline",
    "--fs-section",
    "--fs-body",
    "--fs-meta",
    "--leading",
    "--measure",
    "--rule-weight",
    "--rule-color",
    "--item-break",
    "--space-1",
    "--space-2",
    "--space-3",
    "--space-4",
)


@pytest.mark.parametrize("prop", REQUIRED_PROPERTIES)
def test_base_css_defines_the_shared_property(prop):
    assert re.search(rf"^\s*{re.escape(prop)}\s*:", BASE_CSS, re.MULTILINE), (
        f"base.css must define {prop}; templates override its value, not its meaning"
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_style_does_not_declare_pagination(template):
    """Pagination is structural. A template that redefines it is a bug."""
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    for prop in ("break-inside", "page-break-inside"):
        assert not re.search(rf"(?<!-)\b{prop}\s*:", stripped), (
            f"{template}/style.css declares {prop}. Structure belongs in base.css; "
            "set --item-break instead if this template needs breakable items."
        )


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_style_does_not_reference_the_network(template):
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    assert "http://" not in css and "https://" not in css, (
        f"{template}/style.css references a URL. render_pdf sets content with no "
        "base URL, so the reference would be silently dropped."
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_style_does_not_use_multi_column_layout(template):
    """Two-column layouts, sidebars and grid placement destroy ATS parsing."""
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    for banned in ("column-count", "grid-template-columns", "position: absolute"):
        assert banned not in stripped, f"{template}/style.css uses {banned}"


def test_base_css_owns_item_pagination():
    assert "break-inside: var(--item-break)" in BASE_CSS
    assert "page-break-inside: var(--item-break)" in BASE_CSS
```

- [ ] **Step 2: Run and confirm it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_base_css_contract.py -q`
Expected: failures on the missing custom properties, and one failure on `meridian/style.css` declaring `break-inside`.

- [ ] **Step 3: Rewrite base.css**

Replace `backend/templates/base.css` in full:

```css
/* ============================================================
   base.css — the shared structural and typographic system for
   ALL resume templates.

   The contract: base.css owns structure — reset, page setup,
   the type scale, vertical rhythm, measure, section grammar and
   pagination. A template's style.css owns identity — which
   typeface, which weights, which rules, which colour — and
   changes structure only by overriding the custom properties
   declared here with different VALUES.

   A style.css that declares break-inside, column-count or an
   absolute position is a bug, and tests/test_base_css_contract.py
   fails the build for it.
   ============================================================ */

/* --- Reset --- */
*,
*::before,
*::after {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

/* --- The system --- */
:root {
  /* Type scale. Templates override the values, never the names. */
  --fs-name: 20pt;
  --fs-headline: 10.5pt;
  --fs-section: 10pt;
  --fs-body: 10pt;
  --fs-meta: 9pt;

  /* Vertical rhythm */
  --leading: 1.4;

  /* Maximum line length for prose. Around 65 to 75 characters reads best;
     a template that wants full-bleed text sets this to 100%. */
  --measure: 34em;

  /* Rules */
  --rule-weight: 0.5pt;
  --rule-color: #8a8a8a;

  /* Ink */
  --ink: #161616;
  --ink-soft: #3a3a3a;
  --ink-faint: #555555;

  /* Pagination. "avoid" keeps an entry whole; a template with lists longer
     than a page (an academic CV) sets "auto". */
  --item-break: avoid;

  /* Spacing scale */
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.85rem;
  --space-4: 1.4rem;
}

/* --- Page setup --- */
@page {
  size: Letter;
  margin: 0.5in;
}

html {
  font-size: 10.5pt;
}

body {
  font-size: var(--fs-body);
  line-height: var(--leading);
  color: var(--ink);
  background: #ffffff;
  /* Tabular figures keep date columns aligned in every family that has them. */
  font-variant-numeric: tabular-nums;
}

a {
  color: inherit;
  text-decoration: none;
}

img {
  max-width: 100%;
}

/* --- Section grammar --- */
.resume-header {
  margin-bottom: var(--space-4);
}

.section {
  margin-bottom: var(--space-4);
}

.section:last-child {
  margin-bottom: 0;
}

.section-title {
  font-size: var(--fs-section);
  margin-bottom: var(--space-2);
  break-after: avoid;
  page-break-after: avoid;
}

.item {
  margin-bottom: var(--space-3);
  break-inside: var(--item-break);
  page-break-inside: var(--item-break);
}

.item:last-child {
  margin-bottom: 0;
}

.item-head {
  margin-bottom: var(--space-1);
}

.name {
  font-size: var(--fs-name);
}

.headline {
  font-size: var(--fs-headline);
}

.contact-line,
.meta {
  font-size: var(--fs-meta);
}

/* --- Measure: prose is capped, tables of facts are not --- */
.summary,
.detail {
  max-width: var(--measure);
}

.bullets {
  max-width: var(--measure);
  margin-left: 1.1em;
  list-style: disc outside;
}

.bullets li {
  margin-bottom: var(--space-1);
  /* Hanging indent: a wrapped line aligns to the text, not under the marker. */
  padding-left: 0.15em;
}

.bullets li::marker {
  font-size: 0.9em;
}

/* --- Widow and orphan control --- */
h1,
h2,
h3 {
  break-after: avoid;
  page-break-after: avoid;
}

p,
li {
  orphans: 2;
  widows: 2;
}

/* --- Print --- */
@media print {
  body {
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }

  /* Links are already plain text in the contact line and project metadata;
     never append href in parentheses, which corrupts ATS extraction. */
  a::after {
    content: none;
  }
}
```

- [ ] **Step 4: Delete Meridian's duplicated pagination block**

In `backend/templates/meridian/style.css`, delete these four lines (currently 57-60):

```css
.item {
  break-inside: avoid;
  page-break-inside: avoid;
}
```

Meridian now inherits them from `base.css`. Nothing else in that file changes: its identity is unchanged by decision (spec §3.1).

- [ ] **Step 5: Run the contract test**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_base_css_contract.py -q`
Expected: 30 passed (14 properties + 4 templates x 3 + 1 + ... count will vary with template count; all must pass).

- [ ] **Step 6: Confirm nothing regressed, especially extraction**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures. The `.item` hoist and the new measure caps change layout, so if `test_pdf_extraction.py` fails, the new `--measure` is wrapping text in a way that breaks the extraction stream — investigate rather than loosening the test.

- [ ] **Step 7: Commit**

```bash
git add backend/templates/base.css backend/templates/meridian/style.css tests/test_base_css_contract.py
git commit -m "feat: base.css owns the type scale, measure and pagination"
```

---

### Task 6: schema.org JSON-LD

**Files:**
- Modify: `backend/app/services/render.py` (add `resume_json_ld`, `_json_ld_payload`; pass into the template context)
- Create: `backend/templates/_structured_data.html`
- Modify: `backend/templates/{meridian,slate,terminal,signal}/template.html` (include the partial)
- Create: `tests/test_json_ld.py`

**Interfaces:**
- Produces: `render.resume_json_ld(resume: ResumeDoc) -> dict` and `render._json_ld_payload(resume: ResumeDoc) -> str`. `render_resume_html` passes `json_ld=_json_ld_payload(resume)` into the Jinja context; every `template.html` includes `_structured_data.html`, which emits it through `| safe`.

**Why `<` is escaped rather than just `</`.** Emitting JSON inside a `<script>` element is the one place autoescaping is bypassed. Escaping only `</` still leaves `<!--`, which legally opens a comment inside a script element and can swallow the rest of the document. Replacing every `<` with the JSON escape `<` is exhaustive, costs nothing, and stays valid JSON.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_json_ld.py`:

```python
"""schema.org JSON-LD in the HTML export. Additive; resume.txt is unchanged."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.app.schemas import ResumeDoc, TailorResult
from backend.app.services.render import (
    TEMPLATES,
    render_resume_html,
    resume_json_ld,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"
SCRIPT = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)


def _resume() -> ResumeDoc:
    data = json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))
    return TailorResult.model_validate(data).resume


def _embedded(html: str) -> dict:
    match = SCRIPT.search(html)
    assert match, "no JSON-LD block in the rendered HTML"
    return json.loads(match.group(1))


def test_json_ld_describes_a_person():
    data = resume_json_ld(_resume())
    assert data["@context"] == "https://schema.org"
    assert data["@type"] == "Person"
    assert data["name"] == _resume().contact.name


def test_json_ld_carries_contact_details():
    resume = _resume()
    data = resume_json_ld(resume)
    assert data["email"] == resume.contact.email
    assert data["description"] == resume.summary
    assert data["jobTitle"] == resume.headline


def test_json_ld_maps_experience_to_occupation_and_organization():
    resume = _resume()
    data = resume_json_ld(resume)
    roles = [item.role for s in resume.sections if s.type == "experience" for item in s.items]
    companies = [
        item.company for s in resume.sections if s.type == "experience" for item in s.items
    ]
    assert [o["@type"] for o in data["hasOccupation"]] == ["Occupation"] * len(roles)
    assert [o["name"] for o in data["hasOccupation"]] == roles
    assert [o["@type"] for o in data["worksFor"]] == ["Organization"] * len(companies)
    assert [o["name"] for o in data["worksFor"]] == companies


def test_json_ld_maps_education_and_certifications():
    resume = _resume()
    data = resume_json_ld(resume)
    for entry in data.get("alumniOf", []):
        assert entry["@type"] == "EducationalOrganization"
    for entry in data.get("hasCredential", []):
        assert entry["@type"] == "EducationalOccupationalCredential"


def test_json_ld_lists_skills_under_knows_about():
    resume = _resume()
    data = resume_json_ld(resume)
    expected = [
        item for s in resume.sections if s.type == "skills" for g in s.groups for item in g.items
    ]
    if expected:
        assert data["knowsAbout"] == expected


def test_json_ld_omits_keys_with_no_value():
    resume = _resume().model_copy(deep=True)
    resume.contact.phone = None
    resume.contact.location = None
    data = resume_json_ld(resume)
    assert "telephone" not in data
    assert "address" not in data


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_template_embeds_valid_json_ld(template):
    data = _embedded(render_resume_html(_resume(), template))
    assert data["@type"] == "Person"


def test_a_bullet_containing_a_script_tag_cannot_break_out():
    """The one place autoescaping is bypassed. It must not be an injection point."""
    resume = _resume().model_copy(deep=True)
    payload = '</script><script>alert("xss")</script>'
    for section in resume.sections:
        if section.type == "experience":
            section.items[0].bullets[0] = payload
            break
    html = render_resume_html(resume, "meridian")
    block = SCRIPT.search(html)
    assert block, "the injected payload terminated the script element early"
    assert "alert(" not in block.group(1) or "\\u003c" in block.group(1)
    assert "</script><script>" not in block.group(1)
    # and it is still parseable JSON
    json.loads(block.group(1))


def test_a_comment_opener_in_the_resume_cannot_open_a_comment():
    resume = _resume().model_copy(deep=True)
    resume.summary = "I reduced costs <!-- by a lot"
    html = render_resume_html(resume, "meridian")
    block = SCRIPT.search(html)
    assert block
    assert "<!--" not in block.group(1)
    assert json.loads(block.group(1))["description"] == resume.summary


def test_json_ld_is_absent_from_the_ats_text():
    """resume.txt is the canonical machine-readable artifact and is unchanged."""
    from backend.app.services.render import render_ats_text

    assert "schema.org" not in render_ats_text(_resume())
```

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_json_ld.py -q`
Expected: `ImportError: cannot import name 'resume_json_ld'`.

- [ ] **Step 3: Implement the serializer**

Add to `backend/app/services/render.py`, after `render_ats_text`:

```python
def resume_json_ld(resume: ResumeDoc) -> dict:
    """A schema.org Person describing this resume.

    Additive machine readability for the HTML export. Keys with no value are
    omitted rather than emitted empty, because an empty schema.org property is
    worse than an absent one: it asserts the absence of a fact.
    """
    contact = resume.contact
    data: dict = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": contact.name,
    }
    if contact.email:
        data["email"] = contact.email
    if contact.phone:
        data["telephone"] = contact.phone
    if contact.location:
        data["address"] = {
            "@type": "PostalAddress",
            "addressLocality": contact.location,
        }
    urls = [link.url for link in contact.links if link.url]
    if urls:
        data["url"] = urls[0]
        data["sameAs"] = urls
    if resume.headline:
        data["jobTitle"] = resume.headline
    if resume.summary:
        data["description"] = resume.summary

    occupations: list[dict] = []
    organizations: list[dict] = []
    alumni: list[dict] = []
    credentials: list[dict] = []
    skills: list[str] = []

    for section in resume.sections:
        if section.type == "experience":
            for item in section.items:
                occupation: dict = {"@type": "Occupation", "name": item.role}
                if item.location:
                    occupation["occupationLocation"] = {
                        "@type": "Place",
                        "name": item.location,
                    }
                occupations.append(occupation)
                organizations.append({"@type": "Organization", "name": item.company})
        elif section.type == "education":
            for item in section.items:
                alumni.append(
                    {"@type": "EducationalOrganization", "name": item.institution}
                )
                credentials.append(
                    {
                        "@type": "EducationalOccupationalCredential",
                        "name": item.credential,
                        "recognizedBy": {
                            "@type": "EducationalOrganization",
                            "name": item.institution,
                        },
                    }
                )
        elif section.type == "certifications":
            for item in section.items:
                credential: dict = {
                    "@type": "EducationalOccupationalCredential",
                    "name": item.name,
                }
                if item.issuer:
                    credential["recognizedBy"] = {
                        "@type": "Organization",
                        "name": item.issuer,
                    }
                credentials.append(credential)
        elif section.type == "skills":
            for group in section.groups:
                skills.extend(group.items)

    if occupations:
        data["hasOccupation"] = occupations
    if organizations:
        data["worksFor"] = organizations
    if alumni:
        data["alumniOf"] = alumni
    if credentials:
        data["hasCredential"] = credentials
    if skills:
        data["knowsAbout"] = skills
    return data


def _json_ld_payload(resume: ResumeDoc) -> str:
    """resume_json_ld serialized for safe embedding inside a <script> element.

    Every "<" becomes the JSON escape \\u003c. That is exhaustive: it neutralises
    "</script>" and "<!--" alike, and the result is still valid JSON. This is the
    one place Jinja autoescaping is bypassed, so it does the escaping itself.
    """
    return json.dumps(resume_json_ld(resume), ensure_ascii=False).replace(
        "<", "\\u003c"
    )
```

Change `render_resume_html` to pass it in:

```python
def render_resume_html(resume: ResumeDoc, template: str) -> str:
    """Render a ResumeDoc into a fully standalone HTML document."""
    base_css, style_css = _load_css(template)
    tpl = _env.get_template(f"{template}/template.html")
    return tpl.render(
        resume=resume,
        base_css=base_css,
        style_css=style_css,
        json_ld=_json_ld_payload(resume),
    )
```

- [ ] **Step 4: Create the partial**

Create `backend/templates/_structured_data.html`:

```html
{# schema.org Person for the HTML export. Escaping is done in render.py's
   _json_ld_payload, which is why this passes through | safe. #}
<script type="application/ld+json">{{ json_ld | safe }}</script>
```

- [ ] **Step 5: Include it in all four templates**

In each of `backend/templates/{meridian,slate,terminal,signal}/template.html`, insert this line immediately before the closing `</head>`:

```html
{% include "_structured_data.html" %}
```

- [ ] **Step 6: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_json_ld.py -q`
Expected: 13 passed.

- [ ] **Step 7: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures. In particular `tests/test_render.py::test_render_resume_html_escapes_html` must still pass — autoescaping in the body is untouched.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/render.py backend/templates/ tests/test_json_ld.py
git commit -m "feat: emit schema.org JSON-LD in every HTML resume export"
```

---

### Task 7: Delete the last hardcoded template lists

**Files:**
- Modify: `backend/app/api/templates.py:1-49`
- Modify: `backend/app/services/tailor.py:27,40-41`
- Modify: `backend/mcp_server.py:133-138`
- Modify: `tests/test_templates_api.py:7-13`
- Modify: `tests/test_templates.py:1,107-117`

**Interfaces:**
- Consumes: `TEMPLATE_REGISTRY` from Task 2.
- Produces: `templates.TEMPLATE_META` keeps its exact current shape — a list of dicts with exactly the keys `name`, `label`, `description`, `best_for`, ordered by `order`. `structure` and `order` stay internal; the frontend has no use for them and adding them would break the API contract test for no gain.

- [ ] **Step 1: Update the API-shape tests first**

In `tests/test_templates_api.py`, replace `test_list_templates_returns_four_in_order` (lines 7-13) with:

```python
def test_list_templates_returns_every_registered_template_in_order(client):
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert [t["name"] for t in data] == list(TEMPLATES)
    for item in data:
        assert set(item.keys()) == {"name", "label", "description", "best_for"}
        assert item["label"] and item["description"] and item["best_for"]


def test_list_templates_labels_are_not_raw_ids(client):
    """The dropdowns render label, so a label equal to the id is a regression."""
    data = client.get("/api/templates").json()
    for item in data:
        assert item["label"] != item["name"]
```

In `tests/test_templates.py`, change the module docstring on line 1 from "Tests for the four resume templates" to "Tests for the resume templates.", and replace `test_template_visual_identity` (lines 107-117) with a version driven by the registry rather than a hardcoded subset:

```python
@pytest.mark.parametrize("template", TEMPLATES)
def test_template_declares_its_own_body_typeface(template):
    """Every template must choose a typeface. Inheriting the default is not a design."""
    css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    assert re.search(r"^\s*font-family\s*:", css, re.MULTILINE), (
        f"{template}/style.css never declares font-family"
    )
```

Add `import re` to that file's imports if it is not already present.

- [ ] **Step 2: Run and confirm the shape test still passes but the identity test now covers all templates**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_templates.py tests/test_templates_api.py -q`
Expected: all pass. If `test_list_templates_labels_are_not_raw_ids` fails, a manifest label is wrong.

- [ ] **Step 3: Make `api/templates.py` data-driven**

Replace lines 1-49 of `backend/app/api/templates.py` with:

```python
"""Template gallery routes: metadata for every registered template plus a live
HTML preview of each, rendered from the shared sample resume fixture."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..schemas import TailorResult
from ..services.render import TEMPLATE_REGISTRY, TEMPLATES, render_resume_html

router = APIRouter()

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# Built from the on-disk manifests, already ordered by their `order` field.
# `structure` and `order` stay internal: the UI has no use for either.
TEMPLATE_META: list[dict[str, str]] = [
    {
        "name": manifest.name,
        "label": manifest.label,
        "description": manifest.description,
        "best_for": manifest.best_for,
    }
    for manifest in TEMPLATE_REGISTRY.values()
]
```

Delete the now-unused `from typing import Any` import if present.

- [ ] **Step 4: Make the structural hint read the manifest**

In `backend/app/services/tailor.py`, replace lines 40-41:

```python
def _structural_hint(template: str) -> str:
    """The section order this template is designed around, from its manifest."""
    manifest = TEMPLATE_REGISTRY.get(template)
    return manifest.structure if manifest is not None else "experience-first"
```

Add the import at the top of `tailor.py`:

```python
from .render import TEMPLATE_REGISTRY
```

And generalise the prompt. Replace line 27 of `TAILOR_SYSTEM`:

```
- Respect the template structural hint given in the input: when the hint is "projects-forward", a Projects section leads, before Experience; when it is "experience-first", Experience leads. Include Skills and Education sections whenever the master profile has content for them.
```

- [ ] **Step 5: De-hardcode the MCP tool description**

In `backend/mcp_server.py`, replace the `list_templates` docstring (lines 135-137):

```python
@mcp.tool()
async def list_templates() -> list[dict]:
    """List every available resume template (name, label, description, best_for).
    Call before create_application to choose deliberately: match best_for to the
    role. 'slate' is the safe general-purpose default."""
    return await _run(mcp_ops.list_templates)
```

In `backend/mcp_ops.py`, the workflow-guide text at line 124-125 says `the "terminal" template is projects-forward`. Replace that sentence with:

```
Templates differ in section order: call list_templates and match best_for to the role. Most templates lead with Experience; Terminal leads with Projects.
```

- [ ] **Step 6: Verify no import cycle**

`tailor.py` now imports from `render.py`. Confirm `render.py` does not import `tailor`:

Run: `./.venv/Scripts/python.exe -c "import backend.app.services.tailor as t; print(t._structural_hint('terminal'), t._structural_hint('meridian'), t._structural_hint('nope'))"`
Expected: `projects-forward experience-first experience-first`

- [ ] **Step 7: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures.

- [ ] **Step 8: Commit**

```bash
git add backend/ tests/
git commit -m "refactor: build template metadata and structural hints from manifests"
```

---

### Tasks 8, 9 and 10 share this design brief

Read it before starting any of them. **Tasks 8, 9 and 10 are independent and may run in parallel** — each touches only its own template directories.

**The constraint is the brief.** Single column. No sidebars, no icons, no skill bars, no colour blocks behind text, no letter-spacing on body text, nothing absolutely positioned. Quality comes from four levers only: typeface, scale, rhythm, and restraint in the use of rules and colour.

**How to express identity.** Override the custom properties from `base.css` with values, then add identity rules. A `style.css` should read as a short, coherent set of decisions, not a pile of one-off overrides. Do not restate a value that `base.css` already provides.

**Every template's `style.css` must:**
- Declare `font-family` on `body`.
- Set `--fs-name`, `--fs-section`, `--fs-body`, `--fs-meta`, `--leading` and `--measure` explicitly, even where the value matches the default. These are the template's typographic decisions and should be visible in one block at the top.
- Not declare `break-inside`, `page-break-inside`, `column-count`, `grid-template-columns`, `position: absolute`, or any `http`/`https` URL. The contract test from Task 5 fails the build for each.

**Every template's `template.html` is a thin shell:**

```html
{# <Name> — <one-line character description>. #}
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ resume.contact.name }} — Resume</title>
<style>
{{ base_css | safe }}
{{ style_css | safe }}
</style>
{% include "_structured_data.html" %}
</head>
<body>
{% include "_resume_body.html" %}
</body>
</html>
```

**Every template's `template.json`** follows the schema from Task 2. Font entries come from the JSON printed by `scripts/vendor_fonts.py` in Task 3.

**Verification loop for any template work** — run all three, in this order:

```bash
./.venv/Scripts/python.exe -m pytest tests/test_base_css_contract.py -q
./.venv/Scripts/python.exe -m pytest tests/test_pdf_extraction.py -q
./.venv/Scripts/python.exe -m pytest tests/ -q
```

To look at a template, start the app and open `http://127.0.0.1:8000/api/templates/preview/<name>`.

---

### Task 8: Extract the shared body and rebuild Slate, Terminal and Signal

**Files:**
- Create: `backend/templates/_resume_body.html`
- Modify: `backend/templates/{meridian,slate,terminal,signal}/template.html`
- Modify: `backend/templates/{slate,terminal,signal}/style.css`

- [ ] **Step 1: Extract the shared body partial**

Create `backend/templates/_resume_body.html` containing exactly the current contents of `backend/templates/meridian/template.html` from the `<header class="resume-header">` line through the final `{% endfor %}` — that is, everything between `<body>` and `</body>`, inclusive of neither tag. Do not change the markup. Add this comment as the first line:

```html
{# The canonical resume markup, shared by every template except Plainwork.
   Structure is identical on purpose: identity comes from typography, not from
   layout, because layout tricks are what break ATS and LLM parsing. #}
```

- [ ] **Step 2: Reduce all four template.html files to the shell**

Rewrite each of `backend/templates/{meridian,slate,terminal,signal}/template.html` to the shell shown in the shared brief above, keeping each file's existing first-line comment.

- [ ] **Step 3: Verify the refactor changed nothing**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures. This step is a pure refactor; if anything fails, the extraction dropped or reordered markup.

- [ ] **Step 4: Commit the refactor separately from the redesign**

```bash
git add backend/templates/
git commit -m "refactor: extract the shared resume body into a partial"
```

- [ ] **Step 5: Rebuild Slate**

Replace `backend/templates/slate/style.css` in full:

```css
/* ============================================================
   Slate — the neutral default.
   Inter. Hierarchy from weight and whitespace, not from rules.
   The only rule in the document sits under the header.
   ============================================================ */

:root {
  --fs-name: 22pt;
  --fs-headline: 10.5pt;
  --fs-section: 8.5pt;
  --fs-body: 10pt;
  --fs-meta: 9pt;
  --leading: 1.45;
  --measure: 34em;
  --rule-color: #d4d4d4;
  --space-4: 1.6rem;
}

body {
  font-family: Inter, "Segoe UI", system-ui, sans-serif;
  letter-spacing: -0.005em;
}

.resume-header {
  padding-bottom: var(--space-3);
  border-bottom: var(--rule-weight) solid var(--rule-color);
}

.name {
  font-weight: 700;
  letter-spacing: -0.02em;
}

.headline {
  font-weight: 400;
  color: var(--ink-soft);
  margin-top: var(--space-1);
}

.contact-line {
  color: var(--ink-faint);
  margin-top: var(--space-2);
}

.summary {
  margin-top: var(--space-3);
}

.section-title {
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-faint);
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
}

.item-head .primary {
  font-weight: 600;
}

.item-head .secondary {
  color: var(--ink-soft);
}

.item-head .meta {
  margin-left: auto;
  color: var(--ink-faint);
}

.bullets,
.detail {
  color: var(--ink);
}

.skill-label {
  font-weight: 600;
}
```

- [ ] **Step 6: Rebuild Terminal**

Replace `backend/templates/terminal/style.css` in full. Mono is confined to metadata and skills, where it is information design; body text stays in a sans because mono body copy is slower to read and wider on the page.

```css
/* ============================================================
   Terminal — engineering.
   IBM Plex Sans for reading, IBM Plex Mono for metadata and
   skills only. Mono as information design, not as decoration.
   ============================================================ */

:root {
  --fs-name: 18pt;
  --fs-headline: 10pt;
  --fs-section: 9pt;
  --fs-body: 10pt;
  --fs-meta: 8.5pt;
  --leading: 1.45;
  --measure: 35em;
  --rule-color: #c8c8c8;
}

body {
  font-family: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
}

.resume-header {
  padding-bottom: var(--space-3);
  border-bottom: var(--rule-weight) solid var(--rule-color);
}

.name {
  font-weight: 600;
  letter-spacing: 0.01em;
}

.headline {
  color: var(--ink-soft);
  margin-top: var(--space-1);
}

.contact-line {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  color: var(--ink-faint);
  margin-top: var(--space-2);
}

.summary {
  margin-top: var(--space-3);
}

.section-title {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink);
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
}

.item-head .primary {
  font-weight: 600;
}

.item-head .secondary {
  color: var(--ink-soft);
}

.item-head .meta {
  margin-left: auto;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  color: var(--ink-faint);
}

.skill-label,
.skill-items {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: var(--fs-meta);
}

.skill-label {
  font-weight: 500;
}
```

- [ ] **Step 7: Rebuild Signal**

Replace `backend/templates/signal/style.css` in full. The orange square section bullet is removed, per spec §4.5. The accent survives as exactly one mark in the document: a short rule under the header.

```css
/* ============================================================
   Signal — design, marketing, product.
   Public Sans. One accent, used once: the short rule beneath
   the header. Section titles carry no colour.
   ============================================================ */

:root {
  --fs-name: 21pt;
  --fs-headline: 11pt;
  --fs-section: 9pt;
  --fs-body: 10pt;
  --fs-meta: 9pt;
  --leading: 1.45;
  --measure: 33em;
  --accent: #C2410C;
  --rule-color: #dcdcdc;
  --space-4: 1.5rem;
}

body {
  font-family: "Public Sans", "Segoe UI", system-ui, sans-serif;
}

.resume-header {
  padding-bottom: var(--space-3);
}

.name {
  font-weight: 700;
  letter-spacing: -0.015em;
}

/* The one accent in the document. */
.resume-header::after {
  content: "";
  display: block;
  width: 2.4rem;
  height: 2pt;
  margin-top: var(--space-2);
  background: var(--accent);
}

.headline {
  font-weight: 400;
  color: var(--ink-soft);
  margin-top: var(--space-1);
}

.contact-line {
  color: var(--ink-faint);
  margin-top: var(--space-2);
}

.summary {
  margin-top: var(--space-3);
}

.section-title {
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--ink);
  padding-bottom: var(--space-1);
  border-bottom: var(--rule-weight) solid var(--rule-color);
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
}

.item-head .primary {
  font-weight: 700;
}

.item-head .secondary {
  color: var(--ink-soft);
}

.item-head .meta {
  margin-left: auto;
  color: var(--ink-faint);
}

.skill-label {
  font-weight: 700;
}
```

- [ ] **Step 8: Run the verification loop**

Run the three commands from the shared brief.
Expected: 0 failures throughout.

- [ ] **Step 9: Look at all four**

Run: `./.venv/Scripts/python.exe -m backend.app.run &` (or the project's documented start command), then fetch each preview and confirm it returns HTML containing the expected family name:

```bash
for t in meridian slate terminal signal; do
  curl -s "http://127.0.0.1:8000/api/templates/preview/$t" | grep -o "font-family:[^;]*" | head -2
done
```

Expected: Georgia for meridian, Inter for slate, IBM Plex Sans for terminal, Public Sans for signal.

- [ ] **Step 10: Commit**

```bash
git add backend/templates/
git commit -m "feat: rebuild Slate, Terminal and Signal to the design bar"
```

---

### Task 9: Ledger and Quarto

**Files:**
- Create: `backend/templates/ledger/{template.json,template.html,style.css}`
- Create: `backend/templates/quarto/{template.json,template.html,style.css}`

Read the shared design brief above Task 8 first.

- [ ] **Step 1: Create Ledger's manifest**

`backend/templates/ledger/template.json` — use the Source Serif 4 entries printed by `scripts/vendor_fonts.py`:

```json
{
  "name": "ledger",
  "label": "Ledger",
  "description": "Executive serif with a large name, wide leading and generous whitespace.",
  "best_for": "Director level and above",
  "structure": "experience-first",
  "order": 5,
  "fonts": [
    {"family": "Source Serif 4", "file": "SourceSerif4-italic.woff2", "weight": "400", "style": "italic"},
    {"family": "Source Serif 4", "file": "SourceSerif4-normal.woff2", "weight": "400 600", "style": "normal"}
  ]
}
```

- [ ] **Step 2: Create Ledger's shell**

`backend/templates/ledger/template.html` — the shell from the shared brief, with this first line:

```html
{# Ledger — executive serif. Director level and above. #}
```

- [ ] **Step 3: Create Ledger's style**

`backend/templates/ledger/style.css`:

```css
/* ============================================================
   Ledger — executive.
   Source Serif 4. A large, quiet name; wide leading; a narrow
   measure so paragraphs read as considered rather than dense.
   Section rules sit ABOVE their title, which reads as a ledger
   line and separates Ledger from Meridian's rule-below.
   ============================================================ */

:root {
  --fs-name: 24pt;
  --fs-headline: 11pt;
  --fs-section: 8.5pt;
  --fs-body: 10.5pt;
  --fs-meta: 9pt;
  --leading: 1.55;
  --measure: 32em;
  --rule-color: #b0b0b0;
  --space-3: 1rem;
  --space-4: 2rem;
}

body {
  font-family: "Source Serif 4", Georgia, "Times New Roman", serif;
}

.name {
  font-weight: 400;
  letter-spacing: 0.005em;
}

.headline {
  font-style: italic;
  color: var(--ink-soft);
  margin-top: var(--space-2);
}

.contact-line {
  color: var(--ink-faint);
  margin-top: var(--space-2);
}

.summary {
  margin-top: var(--space-3);
}

.section-title {
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: var(--ink-faint);
  padding-top: var(--space-2);
  border-top: var(--rule-weight) solid var(--rule-color);
  margin-bottom: var(--space-3);
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
}

.item-head .primary {
  font-size: 11pt;
  font-weight: 600;
}

.item-head .secondary {
  font-style: italic;
  color: var(--ink-soft);
}

.item-head .meta {
  margin-left: auto;
  color: var(--ink-faint);
}

.skill-label {
  font-weight: 600;
}
```

- [ ] **Step 4: Create Quarto's manifest**

`backend/templates/quarto/template.json` — use the EB Garamond entries:

```json
{
  "name": "quarto",
  "label": "Quarto",
  "description": "Academic CV that carries long publication lists gracefully across pages.",
  "best_for": "Academia, research, grants",
  "structure": "experience-first",
  "order": 6,
  "fonts": [
    {"family": "EB Garamond", "file": "EBGaramond-italic.woff2", "weight": "400", "style": "italic"},
    {"family": "EB Garamond", "file": "EBGaramond-normal.woff2", "weight": "400 600", "style": "normal"}
  ]
}
```

- [ ] **Step 5: Create Quarto's shell**

`backend/templates/quarto/template.html` — the shell from the shared brief, with this first line:

```html
{# Quarto — academic CV. Academia, research, grants. #}
```

- [ ] **Step 6: Create Quarto's style**

`backend/templates/quarto/style.css`. Note `--item-break: auto`: an academic CV routinely carries an entry longer than a page, and forcing those to stay whole would leave half-empty pages. This is the sanctioned way to vary pagination — see Task 5.

```css
/* ============================================================
   Quarto — academic CV.
   EB Garamond, set a little larger because Garamond runs small.
   Built to run to several pages: entries may break across a
   page boundary rather than leaving one half empty.
   ============================================================ */

:root {
  --fs-name: 21pt;
  --fs-headline: 11pt;
  --fs-section: 11pt;
  --fs-body: 11pt;
  --fs-meta: 9.5pt;
  --leading: 1.45;
  --measure: 36em;
  --rule-color: #9c9c9c;
  --item-break: auto;
  --space-3: 0.7rem;
  --space-4: 1.5rem;
}

body {
  font-family: "EB Garamond", Garamond, Georgia, serif;
}

.resume-header {
  text-align: center;
}

.name {
  font-weight: 400;
  letter-spacing: 0.02em;
}

.headline {
  font-style: italic;
  color: var(--ink-soft);
  margin-top: var(--space-1);
}

.contact-line {
  color: var(--ink-faint);
  margin-top: var(--space-2);
}

.summary {
  margin: var(--space-3) auto 0;
  text-align: left;
}

.section-title {
  font-style: italic;
  font-weight: 400;
  color: var(--ink);
  padding-bottom: 2px;
  border-bottom: var(--rule-weight) solid var(--rule-color);
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
}

.item-head .primary {
  font-weight: 600;
}

.item-head .secondary {
  font-style: italic;
  color: var(--ink-soft);
}

.item-head .meta {
  margin-left: auto;
  color: var(--ink-faint);
}

.bullets li {
  margin-bottom: 2px;
}

.skill-label {
  font-weight: 600;
}
```

- [ ] **Step 7: Run the verification loop**

Run the three commands from the shared brief. `TEMPLATES` now has six entries, so `test_pdf_extraction.py` reports 18 tests and `test_base_css_contract.py` grows accordingly.
Expected: 0 failures.

- [ ] **Step 8: Confirm Quarto's pagination override is the sanctioned one**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_base_css_contract.py -q -k quarto`
Expected: passes. Quarto sets `--item-break`, never `break-inside`, so the contract holds.

- [ ] **Step 9: Commit**

```bash
git add backend/templates/ledger backend/templates/quarto
git commit -m "feat: add the Ledger and Quarto templates"
```

---

### Task 10: Dossier and Plainwork

**Files:**
- Create: `backend/templates/dossier/{template.json,template.html,style.css}`
- Create: `backend/templates/plainwork/{template.json,template.html,style.css}`
- Create: `backend/templates/_resume_body_plain.html`

Read the shared design brief above Task 8 first.

- [ ] **Step 1: Create Dossier's manifest**

`backend/templates/dossier/template.json` — use the Source Sans 3 entries:

```json
{
  "name": "dossier",
  "label": "Dossier",
  "description": "Dense sans-serif that fits a long career onto fewer pages without crowding.",
  "best_for": "Fifteen or more years of history",
  "structure": "experience-first",
  "order": 7,
  "fonts": [
    {"family": "Source Sans 3", "file": "SourceSans3-italic.woff2", "weight": "400", "style": "italic"},
    {"family": "Source Sans 3", "file": "SourceSans3-normal.woff2", "weight": "400 600", "style": "normal"}
  ]
}
```

- [ ] **Step 2: Create Dossier's shell**

`backend/templates/dossier/template.html` — the shell from the shared brief, with this first line:

```html
{# Dossier — dense. Fifteen or more years of history. #}
```

- [ ] **Step 3: Create Dossier's style**

`backend/templates/dossier/style.css`. 9pt is the floor for body text: below that, print legibility and some ATS OCR paths both start to fail.

```css
/* ============================================================
   Dossier — density without crowding.
   Source Sans 3 at a 9pt floor, tightened rhythm, full-width
   measure. Every reduction here is deliberate; 9pt is the
   smallest body size that still prints and scans reliably.
   ============================================================ */

:root {
  --fs-name: 17pt;
  --fs-headline: 9.5pt;
  --fs-section: 8.5pt;
  --fs-body: 9pt;
  --fs-meta: 8pt;
  --leading: 1.3;
  --measure: 100%;
  --rule-color: #bcbcbc;
  --space-1: 0.15rem;
  --space-2: 0.35rem;
  --space-3: 0.55rem;
  --space-4: 0.95rem;
}

body {
  font-family: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
}

.resume-header {
  padding-bottom: var(--space-2);
  border-bottom: var(--rule-weight) solid var(--rule-color);
}

.name {
  font-weight: 600;
  letter-spacing: -0.01em;
}

.headline {
  color: var(--ink-soft);
}

.contact-line {
  color: var(--ink-faint);
  margin-top: var(--space-1);
}

.summary {
  margin-top: var(--space-2);
}

.section-title {
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--ink);
  padding-bottom: 1px;
  border-bottom: var(--rule-weight) solid var(--rule-color);
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
}

.item-head .primary {
  font-weight: 600;
}

.item-head .secondary {
  color: var(--ink-soft);
}

.item-head .meta {
  margin-left: auto;
  color: var(--ink-faint);
}

.bullets {
  margin-left: 0.95em;
}

.bullets li {
  margin-bottom: 1px;
}

.skill-label {
  font-weight: 600;
}
```

- [ ] **Step 4: Create Plainwork's minimal body partial**

Plainwork is the one template whose markup differs, and it differs for a reason: its entire purpose is maximum parser compatibility, and flexbox in `.item-head` reorders nothing but does introduce a layout path that some parsers handle worse than plain block flow. This partial uses stacked block elements and nothing else.

Create `backend/templates/_resume_body_plain.html`:

```html
{# Plainwork's markup: block flow only. No flex, no inline layout, no
   decoration. Every fact sits on its own line in reading order, which is the
   most conservative thing a resume can hand to an unknown parser. #}
<header class="resume-header">
  <h1 class="name">{{ resume.contact.name }}</h1>
  <p class="headline">{{ resume.headline }}</p>
  <p class="contact-line">
    {{ [resume.contact.email, resume.contact.phone, resume.contact.location] | select | join(" | ") }}
  </p>
  {%- for link in resume.contact.links %}
  <p class="contact-line">{{ link.label }}: {{ link.url }}</p>
  {%- endfor %}
  {% if resume.summary %}<p class="summary">{{ resume.summary }}</p>{% endif %}
</header>

{% for section in resume.sections %}
<section class="section section-{{ section.type }}">
  <h2 class="section-title">{{ section.title }}</h2>

  {% if section.type == "experience" %}
    {% for item in section.items %}
    <div class="item">
      <p class="primary">{{ item.role }}</p>
      <p class="secondary">{{ item.company }}</p>
      <p class="meta">{{ item.start }}–{{ item.end or "Present" }}{% if item.location %} | {{ item.location }}{% endif %}</p>
      {% if item.bullets %}
      <ul class="bullets">
        {% for bullet in item.bullets %}<li>{{ bullet }}</li>{% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "projects" %}
    {% for item in section.items %}
    <div class="item">
      <p class="primary">{{ item.name }}</p>
      {% if item.description %}<p class="secondary">{{ item.description }}</p>{% endif %}
      {% if item.url %}<p class="meta">{{ item.url }}</p>{% endif %}
      {% if item.bullets %}
      <ul class="bullets">
        {% for bullet in item.bullets %}<li>{{ bullet }}</li>{% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "skills" %}
    {% for group in section.groups %}
    <div class="item skill-group">
      <p><span class="skill-label">{{ group.label }}:</span> <span class="skill-items">{{ group.items | join(", ") }}</span></p>
    </div>
    {% endfor %}

  {% elif section.type == "education" %}
    {% for item in section.items %}
    <div class="item">
      <p class="primary">{{ item.credential }}</p>
      <p class="secondary">{{ item.institution }}</p>
      {% if item.year %}<p class="meta">{{ item.year }}</p>{% endif %}
      {% if item.detail %}<p class="detail">{{ item.detail }}</p>{% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "certifications" %}
    {% for item in section.items %}
    <div class="item">
      <p class="primary">{{ item.name }}</p>
      {% if item.issuer %}<p class="secondary">{{ item.issuer }}</p>{% endif %}
      {% if item.year %}<p class="meta">{{ item.year }}</p>{% endif %}
    </div>
    {% endfor %}

  {% elif section.type == "extras" %}
    <ul class="bullets extras">
      {% for item in section.items %}<li>{{ item }}</li>{% endfor %}
    </ul>
  {% endif %}
</section>
{% endfor %}
```

- [ ] **Step 5: Create Plainwork's manifest and shell**

`backend/templates/plainwork/template.json`. `fonts` is empty on purpose: the whole point of this template is maximum parser compatibility, and an embedded font is one more variable between the document and a hostile parser (spec §4.5).

```json
{
  "name": "plainwork",
  "label": "Plainwork",
  "description": "Deliberately unstyled: no rules, no colour, no letterspacing, system fonts only.",
  "best_for": "Workday and government portals, maximum ATS compatibility",
  "structure": "experience-first",
  "order": 8,
  "fonts": []
}
```

`backend/templates/plainwork/template.html` — the shell from the shared brief with two changes: the first-line comment, and it includes the plain body partial instead of the canonical one.

```html
{# Plainwork — deliberately unstyled. Maximum ATS compatibility. #}
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ resume.contact.name }} — Resume</title>
<style>
{{ base_css | safe }}
{{ style_css | safe }}
</style>
{% include "_structured_data.html" %}
</head>
<body>
{% include "_resume_body_plain.html" %}
</body>
</html>
```

- [ ] **Step 6: Create Plainwork's style**

`backend/templates/plainwork/style.css`:

```css
/* ============================================================
   Plainwork — the template that gets out of the way.
   Arial, black on white, no rules, no colour, no letterspacing,
   no flex. This is not an unfinished template; every absence is
   a decision. It exists for portals that parse badly.
   ============================================================ */

:root {
  --fs-name: 16pt;
  --fs-headline: 11pt;
  --fs-section: 11pt;
  --fs-body: 11pt;
  --fs-meta: 11pt;
  --leading: 1.35;
  --measure: 100%;
  --ink: #000000;
  --ink-soft: #000000;
  --ink-faint: #000000;
  --space-1: 0.2rem;
  --space-2: 0.4rem;
  --space-3: 0.7rem;
  --space-4: 1.1rem;
}

body {
  font-family: Arial, Helvetica, sans-serif;
}

.name {
  font-weight: 700;
}

.headline,
.contact-line,
.summary,
.primary,
.secondary,
.meta,
.detail {
  font-weight: 400;
}

.section-title {
  font-weight: 700;
  text-transform: uppercase;
}

.primary {
  font-weight: 700;
}

.skill-label {
  font-weight: 700;
}
```

- [ ] **Step 7: Run the verification loop**

Run the three commands from the shared brief. `TEMPLATES` now has eight entries: `test_pdf_extraction.py` reports 24 tests.
Expected: 0 failures. Plainwork's different markup makes it the single most likely template to trip the document-order assertion, so read that output carefully.

- [ ] **Step 8: Confirm Plainwork really is plain**

Run: `./.venv/Scripts/python.exe -c "
from pathlib import Path
css = Path('backend/templates/plainwork/style.css').read_text(encoding='utf-8')
for banned in ('border', 'letter-spacing', 'display: flex', '#1', '#3', '#5', '#8', '#b', '#c', '#d'):
    assert banned not in css, f'plainwork/style.css contains {banned!r}'
print('plainwork is plain')
"`
Expected: `plainwork is plain`

- [ ] **Step 9: Commit**

```bash
git add backend/templates/
git commit -m "feat: add the Dossier and Plainwork templates"
```

---

### Task 11: Switch an application's template without re-running the LLM

**Files:**
- Modify: `backend/app/api/applications.py` (new route after `regenerate`, which currently ends at line 427)
- Modify: `backend/mcp_ops.py` (new `set_application_template`)
- Modify: `backend/mcp_server.py` (register the tool)
- Create: `tests/test_template_switch.py`

**Interfaces:**
- Produces:
  - `PATCH /api/applications/{application_id}/template`, body `{"template": "ledger"}`, returns the updated `application_detail`.
  - `mcp_ops.set_application_template(engine, application_id: int, template: str) -> dict` returning the same shape as `mcp_ops.get_application`.

**A limitation to state plainly, not paper over.** Section *order* is decided at tailoring time from the template's `structure` hint, so switching from Terminal (projects-forward) to a template that is experience-first leaves the sections in their original order. That is the honest consequence of not re-running the LLM, and it is what the user asked for: no Claude call, no cost, no version bump. The endpoint's docstring says so, and a test asserts it, so nobody later mistakes it for a bug.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_template_switch.py`:

```python
"""PATCH /applications/{id}/template re-renders stored content in a new template.

No Claude call, no cost, no version bump: the content is unchanged, only its
presentation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session

from backend.app.models import Application, Job, Profile
from backend.app.schemas import TailorResult
from backend.app.services import render

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


def _resume_json() -> str:
    data = json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))
    return TailorResult.model_validate(data).resume.model_dump_json()


@pytest.fixture()
def seeded(engine, tmp_path, monkeypatch):
    """A ready application with stored resume content, and no real PDF rendering."""
    calls: list[tuple] = []

    def fake_export(application_id, resume, cover_md, contact, template, data_dir, page_size="Letter"):
        calls.append((application_id, template))
        out = Path(data_dir) / "exports" / str(application_id)
        out.mkdir(parents=True, exist_ok=True)
        return out

    monkeypatch.setattr(render, "export_application", fake_export)

    with Session(engine) as session:
        profile = Profile(name="Ada", contact_json=json.dumps({
            "name": "Ada Lovelace", "email": "ada@example.com", "links": []
        }))
        session.add(profile)
        session.commit()
        session.refresh(profile)
        job = Job(url="https://example.com/job", raw_text="text")
        session.add(job)
        session.commit()
        session.refresh(job)
        app_row = Application(
            profile_id=profile.id,
            job_id=job.id,
            template="slate",
            status="ready",
            version=1,
            resume_json=_resume_json(),
            cover_letter_md="Dear team,",
        )
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
        app_id = app_row.id
    return {"application_id": app_id, "calls": calls, "data_dir": tmp_path}


def test_switching_template_updates_the_row(client, seeded):
    resp = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    )
    assert resp.status_code == 200
    assert resp.json()["template"] == "ledger"


def test_switching_template_re_exports_in_the_new_template(client, seeded):
    client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    )
    assert seeded["calls"], "export_application was never called"
    assert seeded["calls"][-1][1] == "ledger"


def test_switching_template_does_not_bump_the_version(client, seeded):
    before = client.get(f"/api/applications/{seeded['application_id']}").json()["version"]
    after = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    ).json()["version"]
    assert after == before


def test_switching_template_does_not_change_the_cost(client, seeded):
    before = client.get(f"/api/applications/{seeded['application_id']}").json()["cost_usd"]
    after = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    ).json()["cost_usd"]
    assert after == before


def test_switching_template_leaves_the_resume_content_identical(client, seeded):
    before = client.get(f"/api/applications/{seeded['application_id']}").json()["resume"]
    after = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    ).json()["resume"]
    assert after == before


def test_switching_to_an_unknown_template_is_422(client, seeded):
    resp = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "nonexistent"},
    )
    assert resp.status_code == 422


def test_switching_template_on_a_missing_application_is_404(client):
    resp = client.patch("/api/applications/9999/template", json={"template": "ledger"})
    assert resp.status_code == 404


def test_switching_template_mid_pipeline_is_409(client, seeded, engine):
    with Session(engine) as session:
        row = session.get(Application, seeded["application_id"])
        row.status = "tailoring"
        session.add(row)
        session.commit()
    resp = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    )
    assert resp.status_code == 409


def test_switching_template_with_no_stored_resume_is_422(client, seeded, engine):
    with Session(engine) as session:
        row = session.get(Application, seeded["application_id"])
        row.resume_json = None
        session.add(row)
        session.commit()
    resp = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    )
    assert resp.status_code == 422


def test_switching_template_never_calls_claude(client, seeded, monkeypatch):
    """The whole point: a different template costs nothing."""
    from backend.app.services import claude as claude_module

    def explode(*args, **kwargs):
        raise AssertionError("switching a template must not call Claude")

    monkeypatch.setattr(claude_module.ClaudeService, "structured", explode)
    resp = client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "ledger"},
    )
    assert resp.status_code == 200


def test_switching_template_does_not_reorder_sections(client, seeded):
    """Documented limitation: section order was decided at tailoring time and a
    template switch deliberately does not re-run the LLM to revisit it."""
    before = [s["type"] for s in client.get(
        f"/api/applications/{seeded['application_id']}"
    ).json()["resume"]["sections"]]
    after = [s["type"] for s in client.patch(
        f"/api/applications/{seeded['application_id']}/template",
        json={"template": "terminal"},
    ).json()["resume"]["sections"]]
    assert after == before


def test_mcp_set_application_template(engine, seeded):
    from backend import mcp_ops

    result = mcp_ops.set_application_template(
        engine, seeded["data_dir"], seeded["application_id"], "ledger"
    )
    assert result["template"] == "ledger"
    assert result["application_id"] == seeded["application_id"]


def test_mcp_set_application_template_rejects_unknown(engine, seeded):
    from backend import mcp_ops

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.set_application_template(
            engine, seeded["data_dir"], seeded["application_id"], "nope"
        )
    assert "nope" in str(exc.value)


def test_mcp_set_application_template_rejects_mid_pipeline(engine, seeded):
    from backend import mcp_ops

    with Session(engine) as session:
        row = session.get(Application, seeded["application_id"])
        row.status = "tailoring"
        session.add(row)
        session.commit()
    with pytest.raises(mcp_ops.McpOpsError):
        mcp_ops.set_application_template(
            engine, seeded["data_dir"], seeded["application_id"], "ledger"
        )
```

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_template_switch.py -q`
Expected: 405 or 404 on every route test, `AttributeError` on the two MCP tests.

- [ ] **Step 3: Add the route**

In `backend/app/api/applications.py`, add this request body next to `ApplicationPatch` (around line 220):

```python
class TemplateChange(BaseModel):
    template: str
```

And add this route immediately after `regenerate` ends (line 427), before `retry`:

```python
@router.patch("/applications/{application_id}/template")
def set_template(
    application_id: int,
    body: TemplateChange,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Re-render an existing application in a different template.

    No Claude call, no cost, no version bump: the stored resume and cover letter
    are unchanged and only their presentation differs.

    Known limitation, by design: section ORDER was chosen at tailoring time from
    the original template's structural hint, so switching between a
    projects-forward and an experience-first template does not reorder sections.
    Reordering would require re-running the LLM, which is exactly what this
    endpoint exists to avoid. Use regenerate for that.
    """
    app_row, job = _get_app_and_job(session, application_id)
    if app_row.status in PROCESSING_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"application is currently {app_row.status}; wait for it to finish",
        )
    if body.template not in TEMPLATES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown template {body.template!r}; expected one of {list(TEMPLATES)}",
        )
    resume_now = get_resume(app_row)
    if resume_now is None:
        raise HTTPException(
            status_code=422,
            detail="this application has no tailored resume yet; nothing to re-render",
        )

    app_row.template = body.template
    app_row.updated_at = datetime.utcnow()
    session.add(app_row)
    session.commit()
    session.refresh(app_row)

    profile = session.get(Profile, app_row.profile_id)
    settings = request.app.state.settings
    user_settings = load_user_settings(settings.data_dir)
    export_dir = render.export_application(
        app_row.id,
        resume_now,
        app_row.cover_letter_md or "",
        get_contact(profile),
        app_row.template,
        settings.data_dir,
        page_size=user_settings.get("page_size", "Letter"),
    )
    app_row.export_dir = str(export_dir)
    session.add(app_row)
    session.commit()
    session.refresh(app_row)
    return application_detail(session, app_row, job)
```

Confirm `Request`, `datetime`, `Profile`, `get_contact`, `get_resume`, `load_user_settings` and `render` are already imported in this module — `update_content` at line 481 uses every one of them, so they are.

- [ ] **Step 4: Add the MCP operation**

In `backend/mcp_ops.py`, add after `create_application`:

Note the signature: `mcp_ops` functions never call `get_settings()` themselves. They take `data_dir` explicitly as the second positional argument, exactly like `save_tailored_resume(engine, data_dir, application_id, ...)` at line 437, and `mcp_server.py` passes `_settings.data_dir` at the call site. Follow that convention.

```python
def set_application_template(
    engine, data_dir: Path, application_id: int, template: str
) -> dict:
    """Re-render an existing application in a different template.

    No Claude call and no cost: the stored resume and cover letter are unchanged.
    Section order is not revisited, because that was decided at tailoring time
    from the original template's structural hint.
    """
    if template not in render.TEMPLATES:
        raise McpOpsError(
            f"Unknown template {template!r}; expected one of "
            f"{list(render.TEMPLATES)}. Call list_templates for descriptions."
        )
    with Session(engine) as session:
        app, job = _get_app_and_job(session, application_id)
        _reject_if_pipeline_active(app)
        resume_doc = get_resume(app)
        if resume_doc is None:
            raise McpOpsError(
                f"Application {application_id} has no tailored resume yet; "
                "nothing to re-render. Call save_tailored_resume first."
            )
        profile = session.get(Profile, app.profile_id)
        contact = get_contact(profile)

        app.template = template
        session.add(app)
        session.commit()
        session.refresh(app)

        user_settings = load_user_settings(Path(data_dir))
        export_dir = render.export_application(
            app.id,
            resume_doc,
            app.cover_letter_md or "",
            contact,
            template,
            Path(data_dir),
            page_size=user_settings.get("page_size", "Letter"),
        )
        app.export_dir = str(export_dir)
        session.add(app)
        session.commit()
        session.refresh(app)

        return {
            "application_id": app.id,
            "status": app.status,
            "version": app.version,
            "template": app.template,
            "export_dir": app.export_dir,
            "files": sorted(
                p.name for p in Path(export_dir).iterdir() if p.is_file()
            ),
        }
```

`get_resume` is imported in `mcp_ops.py` alongside `get_contact` and `get_parsed` from `.app.models`; add it to that import list if it is not already there. `_reject_if_pipeline_active` is the module's existing guard at line 379 — use it rather than re-implementing the status check.

- [ ] **Step 5: Register the MCP tool**

In `backend/mcp_server.py`, add next to the other tools:

```python
@mcp.tool()
async def set_application_template(application_id: int, template: str) -> dict:
    """Re-render an existing application in a different template.
    Free and instant: no model call, no cost, no new version. Only presentation
    changes; section order is not revisited. Call list_templates for options."""
    return await _run(
        mcp_ops.set_application_template,
        _engine,
        _settings.data_dir,
        application_id,
        template,
    )
```

- [ ] **Step 6: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_template_switch.py -q`
Expected: 13 passed.

- [ ] **Step 7: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures.

- [ ] **Step 8: Commit**

```bash
git add backend/ tests/test_template_switch.py
git commit -m "feat: switch an application's template without re-running the LLM"
```

---

### Task 12: Frontend reads the registry

**Files:**
- Modify: `frontend/src/types.ts:3`
- Modify: `frontend/src/screens/AddJobsScreen.tsx:7,113-129,178-189`
- Modify: `frontend/src/screens/SettingsScreen.tsx:10,132-145`
- Modify: `frontend/src/screens/AddJobsScreen.test.tsx`, `SettingsScreen.test.tsx`

**Interfaces:**
- Consumes: `listTemplates(): Promise<TemplateInfo[]>` from `frontend/src/api.ts:210`, already present.
- Produces: `TemplateName = string`.

**The type trade.** `TemplateName` drops from a four-way union to `string`. That gives up a compile-time check the frontend can no longer honestly make — it does not know what is on disk — in exchange for server-side validation that already exists in `api/settings.py:43`, `api/applications.py:262` and the new route from Task 11. Keeping a union that silently excludes four real templates would be worse than no check at all.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/screens/SettingsScreen.test.tsx`, add:

```tsx
it("renders template options from the API, not a hardcoded list", async () => {
  vi.mocked(api.listTemplates).mockResolvedValue([
    { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
    { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
    { name: "plainwork", label: "Plainwork", description: "d", best_for: "b" },
  ]);
  render(<SettingsScreen />);
  const select = await screen.findByLabelText(/default template/i);
  expect(within(select).getByRole("option", { name: "Ledger" })).toBeInTheDocument();
  expect(within(select).getByRole("option", { name: "Plainwork" })).toBeInTheDocument();
});

it("shows template labels rather than raw ids", async () => {
  vi.mocked(api.listTemplates).mockResolvedValue([
    { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
  ]);
  render(<SettingsScreen />);
  const select = await screen.findByLabelText(/default template/i);
  expect(within(select).getByRole("option", { name: "Meridian" })).toBeInTheDocument();
  expect(within(select).queryByRole("option", { name: "meridian" })).toBeNull();
});
```

Add the equivalent pair to `frontend/src/screens/AddJobsScreen.test.tsx`, targeting the "Default template" select and one per-row select (`aria-label="Template for row 1"`).

Import `within` from `@testing-library/react` in both files if it is not already imported, and make sure `api.listTemplates` is part of the existing `vi.mock("../api", ...)` factory in each file.

- [ ] **Step 2: Run and confirm they fail**

Run: `cd frontend && npx vitest run src/screens/SettingsScreen.test.tsx src/screens/AddJobsScreen.test.tsx`
Expected: failures — the selects still render the four hardcoded ids.

- [ ] **Step 3: Widen the type**

In `frontend/src/types.ts`, replace line 3:

```ts
// Template ids come from the backend registry (backend/templates/*/template.json),
// so the frontend cannot honestly enumerate them. Validation is server-side, in
// api/settings.py, api/applications.py and PATCH /applications/{id}/template.
export type TemplateName = string;
```

- [ ] **Step 4: Make SettingsScreen fetch the registry**

In `frontend/src/screens/SettingsScreen.tsx`, delete the hardcoded array on line 10 and add `listTemplates` to the existing api import. Add state and a fetch alongside the existing settings load:

```tsx
const [templates, setTemplates] = useState<TemplateInfo[]>([]);

useEffect(() => {
  listTemplates().then(setTemplates).catch(() => setTemplates([]));
}, []);
```

Replace the options in the "Default template" select:

```tsx
{templates.map((t) => (
  <option key={t.name} value={t.name}>
    {t.label || t.name}
  </option>
))}
```

Import `TemplateInfo` from `../types`.

- [ ] **Step 5: Make AddJobsScreen fetch the registry**

Same change in `frontend/src/screens/AddJobsScreen.tsx`: delete the array on line 7, add the fetch, and use `templates.map` with `{t.label || t.name}` in **both** the "Default template" select (lines 113-129) and the per-row select (lines 178-189).

- [ ] **Step 6: Run the frontend tests and the type checker**

Run: `cd frontend && npx vitest run`
Expected: 0 failures.

Run: `cd frontend && npx tsc --noEmit`
Expected: no output. If `TemplateName = string` produced errors anywhere, fix them at the call site rather than reintroducing a union.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat: dropdowns read the template registry and show labels"
```

---

### Task 13: Template switcher on the application screen

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/screens/ApplicationScreen.tsx`
- Modify: `frontend/src/screens/ApplicationScreen.test.tsx`

**Interfaces:**
- Consumes: `PATCH /api/applications/{id}/template` from Task 11; `listTemplates` from Task 12.
- Produces: `setApplicationTemplate(id: number, template: string): Promise<ApplicationDetail>`.

- [ ] **Step 1: Write the failing tests**

Two facts about this file to get right. Its `vi.mock("../api", ...)` factory (lines 7-20) lists every function the screen imports, and a function missing from it is `undefined` at runtime, so **add `listTemplates: vi.fn()` and `setApplicationTemplate: vi.fn()` to that factory first**. And its shared fixture is named `base`, typed `Omit<ApplicationDetail, "status">` — tests spread it and supply `status` themselves, as `{ ...base, status: "ready" }`.

Add to `frontend/src/screens/ApplicationScreen.test.tsx`:

```tsx
it("offers every registered template in the switcher", async () => {
  vi.mocked(api.listTemplates).mockResolvedValue([
    { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
    { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
  ]);
  renderScreen();
  const select = await screen.findByLabelText(/template/i);
  expect(within(select).getByRole("option", { name: "Ledger" })).toBeInTheDocument();
});

it("switches template and shows the new one", async () => {
  vi.mocked(api.listTemplates).mockResolvedValue([
    { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
    { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
  ]);
  vi.mocked(api.setApplicationTemplate).mockResolvedValue({
    ...base,
    status: "ready",
    template: "ledger",
  });
  renderScreen();
  const select = await screen.findByLabelText(/template/i);
  fireEvent.change(select, { target: { value: "ledger" } });
  await waitFor(() =>
    expect(api.setApplicationTemplate).toHaveBeenCalledWith(base.id, "ledger"),
  );
  await waitFor(() => expect((select as HTMLSelectElement).value).toBe("ledger"));
});

it("surfaces a failed template switch instead of silently reverting", async () => {
  vi.mocked(api.listTemplates).mockResolvedValue([
    { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
    { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
  ]);
  vi.mocked(api.setApplicationTemplate).mockRejectedValue(new Error("boom"));
  renderScreen();
  const select = await screen.findByLabelText(/template/i);
  fireEvent.change(select, { target: { value: "ledger" } });
  expect(await screen.findByText(/boom/i)).toBeInTheDocument();
});
```

Use the file's existing `renderScreen()` helper, which already seeds `getApplication`. The `switches template` test asserts the call arguments rather than a mock call count, because Vitest is configured without `resetMocks` and counts accumulate across tests in a file.

- [ ] **Step 2: Run and confirm they fail**

Run: `cd frontend && npx vitest run src/screens/ApplicationScreen.test.tsx`
Expected: failures — no template control exists.

- [ ] **Step 3: Add the API client function**

In `frontend/src/api.ts`, next to the other application mutations:

Place it immediately after `patchApplication` (line 125) and use the module's existing `jsonInit` helper, which sets the `Content-Type` header. Hand-rolling a `RequestInit` here would omit that header and the request would fail.

```ts
export function setApplicationTemplate(
  id: number,
  template: string,
): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(
    `/applications/${id}/template`,
    jsonInit("PATCH", { template }),
  );
}
```

- [ ] **Step 4: Add the switcher**

In `frontend/src/screens/ApplicationScreen.tsx`, beside the export buttons, add a labelled select. Reuse the screen's existing error state and its existing `reload()`; do not add a second error channel.

```tsx
<label className="field-inline">
  <span>Template</span>
  <select
    className="select-inline"
    value={detail.template}
    disabled={switching}
    onChange={async (e) => {
      const next = e.target.value;
      setSwitching(true);
      setError(null);
      try {
        await setApplicationTemplate(detail.id, next);
        await reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSwitching(false);
      }
    }}
  >
    {templates.map((t) => (
      <option key={t.name} value={t.name}>
        {t.label || t.name}
      </option>
    ))}
  </select>
</label>
```

Add `templates` and `switching` state and a `listTemplates()` fetch in the existing mount effect. `.select-inline` already exists in `frontend/src/styles.css`; if `.field-inline` does not, add it there rather than inventing an inline style:

```css
.field-inline {
  display: inline-flex;
  align-items: baseline;
  gap: var(--space-2, 0.5rem);
}
```

Check `styles.css` for an existing rule of that name before adding it — redefining an existing class would restyle it everywhere.

- [ ] **Step 5: Run the frontend tests and the type checker**

Run: `cd frontend && npx vitest run`
Expected: 0 failures.

Run: `cd frontend && npx tsc --noEmit`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat: switch an application's template from the application screen"
```

---

### Task 14: Bundle, docs, and end-to-end verification

**Files:**
- Modify: `frontend/dist/` (rebuilt)
- Modify: `README.md:14,28,31,233`
- Modify: `docs/EXTENDING.md:21`

- [ ] **Step 1: Rebuild the committed bundle**

The dist bundle is committed and currently contains the four hardcoded template names.

Run: `cd frontend && npm run build`
Expected: a successful build. The asset filenames change, which is expected.

Run: `grep -c "meridian" frontend/dist/assets/*.js || echo "no hardcoded names in the bundle"`
Expected: `no hardcoded names in the bundle`, or a count that reflects only `"slate"` appearing as a default value.

- [ ] **Step 2: Update the README**

Replace every reference to four templates with eight, and replace the template list with all eight names, labels and `best_for` values from the manifests. Lines 14, 28, 31 and 233 are the known sites; search for "four" and "Meridian" to catch any others.

Add a short paragraph under the templates section:

```markdown
Templates are discovered from `backend/templates/*/template.json`, so the API,
both dropdowns and the gallery all stay in step automatically. You can switch an
existing application to a different template from its page at any time: it
re-renders the resume you already have, with no model call and no cost.
```

- [ ] **Step 3: Update docs/EXTENDING.md**

Replace the "adding a template" instructions at line 21 with the three-file recipe:

```markdown
### Adding a template

Create `backend/templates/<name>/` containing three files:

- `template.json` — the manifest. Copy an existing one; `name` must equal the
  directory name, `order` decides where it appears in every list, and
  `structure` is either `experience-first` or `projects-forward`.
- `template.html` — the shell. Copy any existing one; it includes
  `_resume_body.html` and `_structured_data.html` and differs only in its
  comment.
- `style.css` — the identity. Override the custom properties `base.css`
  declares, then add your own rules.

Nothing else needs editing. `render.py` picks the directory up at import, and
`TEMPLATES`, `/api/templates`, both dropdowns and the gallery follow.

Two rules the test suite enforces:

- `style.css` must not declare `break-inside`, `page-break-inside`,
  `column-count`, `grid-template-columns`, `position: absolute`, or any URL.
  Pagination is structural and lives in `base.css`; set `--item-break` if your
  template genuinely needs breakable entries.
- The rendered PDF must extract every employer, title and date in document
  order. `tests/test_pdf_extraction.py` checks it.

If your template needs a typeface that is not already vendored, add it to
`SPECS` in `scripts/vendor_fonts.py`, re-run the script, and paste the printed
font entries into your manifest. The font must be SIL Open Font License.
```

- [ ] **Step 4: Run everything**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures.

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 0 failures, no type errors.

- [ ] **Step 5: Verify the repo size did not blow up**

Run: `./.venv/Scripts/python.exe -c "from pathlib import Path; print(round(sum(p.stat().st_size for p in Path('backend/templates/fonts').glob('*.woff2'))/1024), 'KB of fonts')"`
Expected: between 300 and 600.

- [ ] **Step 6: Manual end-to-end check**

Start the app. Then, by hand:

1. Open the Templates gallery. Confirm eight cards render, each with a distinct label, and that each preview thumbnail actually looks different from its neighbours.
2. Set the default template to Ledger in Settings. Reload. Confirm it stuck.
3. Open Add Jobs. Confirm the dropdown lists eight labels, not eight ids, and that the default is Ledger.
4. Open an existing ready application. Switch its template to Plainwork. Confirm the preview changes, the version does not increase, and the cost does not increase.
5. Download `resume.pdf` for that application and open it. Select all the text and paste it somewhere. Confirm it pastes as readable text in the right order.

Report anything that does not match, with a screenshot if it is visual.

- [ ] **Step 7: Commit**

```bash
git add frontend/dist README.md docs/EXTENDING.md
git commit -m "docs: eight templates, and rebuild the bundle"
```

---

## Self-Review

**Spec coverage.**

| Spec section | Task |
|---|---|
| §4.1 registry becomes data | 2, 7 |
| §4.1 `TEMPLATES` stays a derived tuple | 2 |
| §4.1 `_METADATA` deleted | 7 |
| §4.1 `tailor.py` reads `structure` | 7 |
| §4.1 malformed manifest fails loudly | 2 |
| §4.2 frontend reads the registry | 12 |
| §4.2 `TemplateName` becomes `string` | 12 |
| §4.2 dist rebuilt | 14 |
| §4.3 `base.css` type scale, measure, pagination hoist, hanging indents, `orphans`/`widows` on `li`, print links | 5 |
| §4.4 fonts vendored, base64-inlined, `lru_cache`, LICENSES.md | 3, 4 |
| §4.5 all eight templates | 8, 9, 10 |
| §4.5 Signal's orange square removed | 8 |
| §4.5 Plainwork uses a system stack | 10 |
| §4.6 `PATCH /applications/{id}/template` with all four guards | 11 |
| §4.6 MCP `set_application_template` | 11 |
| §4.6 `ApplicationScreen` selector | 13 |
| §4.7 JSON-LD, `</` escaping, injection test | 6 |
| §4.7 `resume.txt` unchanged | 6 (asserted) |
| §5 registry tests | 2 |
| §5 all eight render | 8, 9, 10 (parametrised) |
| §5 PDF text extraction | 1 |
| §5 JSON-LD tests | 6 |
| §5 template switch tests | 11 |
| §5 frontend tests | 12, 13 |
| §5 `base.css` contract grep test | 5 |
| §7 extraction test written before fonts land | 1 precedes 3 |

No gaps.

**Placeholder scan.** Clean. Every code step carries real code. Four things were wrong on the first pass and are fixed:

- Task 3's script carried a broken first draft of `main()` referencing three helpers that were never written. Deleted; only the working version remains.
- Task 11's MCP operation called a non-existent `get_settings()` inside `mcp_ops` and returned a non-existent `_application_payload`. `mcp_ops` functions take `data_dir` explicitly as their second positional argument (`save_tailored_resume(engine, data_dir, ...)`, line 437) and `mcp_server.py` passes `_settings.data_dir`. Signature and return payload corrected to match, and the tests now thread a `data_dir` through the fixture.
- Task 13's `setApplicationTemplate` hand-rolled a `RequestInit` without a `Content-Type` header. `api.ts` has a `jsonInit(method, body)` helper at line 44 that every other mutation uses; the request would have failed without it.
- Task 13's tests referenced a fixture named `baseDetail`. The file's fixture is `base`, and it is typed `Omit<ApplicationDetail, "status">`, so `status` has to be supplied at the spread.

**Verified against the codebase rather than assumed.** The font pipeline was proven end to end before this plan was written: latin-subset woff2 fetched from Google Fonts, base64-inlined, printed through headless Chromium, and extracted with `pypdf`. All seven families round-tripped verbatim. That run is also what produced the variable-font finding behind `FontFace.weight` being a string: Inter, IBM Plex Sans, Public Sans, Source Serif 4, EB Garamond and Source Sans 3 each serve one identical file for every weight, so a naive one-face-per-weight manifest would have inlined the same 48 KB payload three times into every exported document. Deduplicated, the whole set is roughly 466 KB. `font-weight: 400 700` on the shared file was confirmed to interpolate genuinely rather than fall back to faux bold, by measuring four distinct advance widths at weights 400, 500, 600 and 700.

`.select-inline` exists in `styles.css:277`; `.field-inline` does not, which is why Task 13 adds it. `pyproject.toml` registers the `pdf` marker but sets no `addopts`, so `pytest tests/ -q` runs the PDF tests by default and the extraction guard cannot be skipped accidentally.

**Type consistency.** `FontFace.weight` is `str` everywhere (Task 2 defines it, Task 3 emits `"400 700"`, Task 4 renders it into `font-weight:`). `TemplateManifest.structure` is checked against `STRUCTURES` in Task 2 and read in Task 7. `TEMPLATE_REGISTRY` is a `dict[str, TemplateManifest]` in Tasks 2, 4, 7. `setApplicationTemplate(id, template)` has the same signature in Task 13 Step 3 and its tests. `TEMPLATE_META` keeps exactly four keys in Task 7 and its test in the same task asserts exactly that set.

**One thing to watch during execution.** Task 7 adds `from .render import TEMPLATE_REGISTRY` to `tailor.py`. `render.py` imports only from `..schemas`, so there is no cycle today — Step 6 verifies it explicitly rather than assuming.
