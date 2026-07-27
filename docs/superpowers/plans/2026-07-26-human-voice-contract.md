# Human Voice Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make generated resumes and cover letters read as the candidate's own writing, and enforce the mechanical part of that on the write path rather than asking the model nicely.

**Architecture:** A new pure function `check_style(resume, cover_md) -> list[str]` sits beside `verify_truthfulness` and is called from both generation paths — `pipeline._tailor_and_render` for the API and `mcp_ops.save_tailored_resume` for agents. It runs on the `ResumeDoc` object and the cover-letter markdown, never on rendered HTML, so a template's own en dash can never trigger it. The API path retries tailoring exactly once with the violations appended; the MCP path raises a correctable violation list, which is the pattern agents already follow for truthfulness. Voice comes from the user's own uploaded documents, with an explicit `Profile.voice_notes` override that takes precedence.

**Tech Stack:** Python 3.14 / FastAPI / SQLModel / Pydantic v2; React 18 + TypeScript / Vitest.

## Global Constraints

- **Python is `./.venv/Scripts/python.exe`.** The ambient `python` is a conda install missing this project's dependencies. Run every test as `./.venv/Scripts/python.exe -m pytest tests/ -q` from the repo root.
- **Truthfulness is checked first, always.** A resume that invents an employer must be reported as inventing an employer, not as having an em dash in the invented employer's bullet (spec §5.3).
- **Hard-fail only what has near-zero legitimate use in a resume.** Everything else is prompt guidance. A false positive blocks a truthful resume and burns a retry, which is worse than an occasional stylistic miss. `leverage`, `robust`, `scale`, `architect`, `drive`, `spearheaded`, `cutting-edge`, `meticulous` and `not only ... but also` are **deliberately not banned** (spec §4.4), and Task 1 includes a test whose whole job is to stop that list creeping.
- **Every violation string must say where it is and what to do instead.** A violation the model cannot act on is a violation that will not be fixed on retry.
- **One retry, never a loop.** A second failure surfaces as an error rather than burning tokens in a cycle.
- **No em dashes and no emoji in any copy this plan adds** — that includes docstrings, prompt text, UI labels and comments. The feature would be absurd otherwise.
- **Frontend has no `@testing-library/user-event`.** Use `fireEvent`.
- **Vitest runs without `clearMocks`/`resetMocks`.** Mock call counts accumulate within a file; assert observable outcomes or call arguments.
- **`tailor_application` is called with six positional arguments** from `pipeline.py:100-103` and from six sites in `tests/test_tailor.py`. Any new parameter must be keyword-with-default and must come after `feedback`, or every one of those call sites breaks.

## Verified starting conditions

Checked against the repo before this plan was written, so the tasks below can rely on them:

- **The shipped fixture is already clean.** All 14 prose fields of `backend/app/fixtures/tailor.json`, cover letter included, contain zero em dashes, zero non-numeric en dashes, zero curly quotes, zero emoji, zero invisible characters and none of the banned phrases. Wiring the check in therefore breaks no existing test. If a later fixture edit introduces one, Task 3's pipeline tests will catch it.
- **`Profile.voice_notes` needs no migration code.** `db.py`'s `_add_missing_columns` runs on every `init_db`, and `_column_ddl` emits `NOT NULL DEFAULT ''` for a column declared with a scalar string default. Declaring `voice_notes: str = ""` is the entire migration. Do **not** use `default_factory` or a non-scalar default: `_column_ddl` checks `default.is_scalar` and would silently drop the clause.
- **`pipeline.py` has no retry mechanism today.** `verify_truthfulness` raises `ClaudeError`, which escapes to the caller's `except Exception` and `_mark_error`. Task 3 introduces the first retry and must not disturb that path.
- **Tests monkeypatch `pipeline.verify_truthfulness` as a module attribute.** `check_style` must be imported the same way (`from .style import check_style` at module level in `pipeline.py`) so it stays patchable by the same technique.
- **`profile_detail()` at `backend/app/api/profiles.py:43-55` is the single serializer** used by the create, get, update and build routes. A new profile field must be added there once, and nowhere else, to reach the frontend.
- **The profile write route is `PUT /profiles/{id}`** (`profiles.py:100-115`) with body model `ProfileUpdate` (`:32-35`). It is semantically a PATCH: every field is `Optional` and `None` means leave alone.

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| `backend/app/services/style.py` | `check_style` and the rule tables. The one place the ban lists live. |
| `tests/test_style.py` | Every rule, every checked field, and the anti-creep test for §4.4. |

**Modified**

| Path | Change |
|---|---|
| `backend/mcp_ops.py` | Style gate beside the truthfulness raise in `save_tailored_resume`; voice in the guide. |
| `backend/app/services/pipeline.py` | Style gate plus the single retry in `_tailor_and_render`. |
| `backend/app/models.py` | `Profile.voice_notes`. |
| `backend/app/api/profiles.py` | `voice_notes` in `ProfileUpdate` and in `profile_detail`. |
| `backend/app/services/tailor.py` | `voice_sample` and `voice_notes` parameters; baseline style rules in `TAILOR_SYSTEM`. |
| `frontend/src/types.ts`, `api.ts`, `screens/ProfileScreen.tsx` | The `voice_notes` textarea. |
| `tests/test_pipeline.py`, `tests/test_tailor.py`, `tests/test_mcp_ops.py` | Enforcement and wiring tests. |
| `README.md` | The voice contract alongside the truthfulness contract. |

**Dependency order.** Task 1 (the module) first; everything else depends on it. Tasks 2 and 3 are independent of each other. Task 4 must precede Task 5. Task 6 depends on 5. Task 7 is last. Only one task at a time may run `git add`/`git commit`.

---

### Task 1: The style check

**Files:**
- Create: `backend/app/services/style.py`
- Create: `tests/test_style.py`

**Interfaces:**
- Produces `backend.app.services.style.check_style(resume: ResumeDoc, cover_md: str) -> list[str]`. Returns human-readable violation strings; an empty list means clean. Same contract shape as `verify_truthfulness` in `tailor.py:78`, deliberately, so both gates read identically at their call sites.
- Also produces the module constants `BANNED_CHARACTERS`, `BANNED_PHRASES` and `ALLOWED_WORDS` for the tests to reference.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_style.py`:

```python
"""The voice contract: mechanical style rules enforced on the write path.

The governing rule (spec section 4.4) is that we hard-fail only what has
near-zero legitimate use in a resume. A false positive blocks a truthful resume
and burns a retry, which is worse than an occasional stylistic miss.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.schemas import (
    ExperienceItem,
    ExperienceSection,
    ResumeDoc,
    TailorResult,
)
from backend.app.services.style import check_style

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


def _resume(**overrides) -> ResumeDoc:
    """A minimal clean resume, with fields overridable per test."""
    data = {
        "contact": {"name": "Ada Lovelace", "email": "ada@example.com", "links": []},
        "headline": "Backend engineer building payment systems",
        "summary": "Eight years building payment infrastructure in Python.",
        "sections": [],
    }
    data.update(overrides)
    return ResumeDoc.model_validate(data)


def _with_bullet(text: str) -> ResumeDoc:
    return _resume(
        sections=[
            {
                "type": "experience",
                "title": "Experience",
                "items": [
                    {
                        "company": "Initech",
                        "role": "Engineer",
                        "start": "2020",
                        "end": "2024",
                        "bullets": [text],
                    }
                ],
            }
        ]
    )


# --- clean input stays clean -------------------------------------------------


def test_a_clean_resume_and_cover_letter_produce_no_violations():
    assert check_style(_resume(), "Dear team,\n\nI built the thing.\n") == []


def test_the_shipped_fixture_passes():
    """If this ever fails, a fixture edit introduced a tell into the sample data."""
    data = json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))
    result = TailorResult.model_validate(data)
    assert check_style(result.resume, result.cover_letter_md) == []


# --- characters --------------------------------------------------------------


def test_em_dash_in_a_bullet_is_a_violation():
    violations = check_style(_with_bullet("Cut latency — by half"), "")
    assert len(violations) == 1
    assert "em dash" in violations[0].lower()


def test_a_violation_names_its_location_and_says_what_to_do():
    """A violation the model cannot act on will not be fixed on retry."""
    violations = check_style(_with_bullet("Cut latency — by half"), "")
    assert "Initech" in violations[0]
    assert "bullet 1" in violations[0]
    # some actionable instruction, not just a diagnosis
    assert any(word in violations[0].lower() for word in ("rewrite", "use", "replace"))


def test_curly_quotes_are_violations():
    assert check_style(_with_bullet("Built the “fleet” service"), "")
    assert check_style(_with_bullet("Ran Ada’s migration"), "")


def test_ellipsis_character_is_a_violation():
    assert check_style(_with_bullet("Shipped it… eventually"), "")


def test_emoji_is_a_violation():
    assert check_style(_with_bullet("Shipped the release \U0001F680"), "")


def test_invisible_characters_are_violations():
    """Independently harmful: they corrupt ATS text extraction."""
    assert check_style(_with_bullet("Cut latency by half"), "")
    assert check_style(_with_bullet("Cut​latency by half"), "")


# --- the en dash rule, which is the one most likely to be broken later -------


def test_a_numeric_range_en_dash_is_allowed():
    """`Led the 2020-2023 migration` with a real en dash must pass.

    The naive rule ("no en dashes") would reject a truthful bullet. This test
    exists because that simplification is the single most likely regression.
    """
    assert check_style(_with_bullet("Led the 2020–2023 platform migration"), "") == []


def test_an_en_dash_between_words_is_a_violation():
    violations = check_style(_with_bullet("Improved work – life balance"), "")
    assert len(violations) == 1
    assert "en dash" in violations[0].lower()


def test_a_spaced_en_dash_between_numbers_is_still_a_violation():
    """`2020 - 2023` spaced is being used as punctuation, not as a range."""
    assert check_style(_with_bullet("Ran it 2020 – 2023 without downtime"), "")


# --- phrases -----------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "passionate about",
        "proven track record",
        "results-driven",
        "results-oriented",
        "results-focused",
        "wealth of experience",
        "seamlessly",
        "testament to",
        "delve",
        "tapestry",
    ],
)
def test_each_banned_phrase_is_detected(phrase):
    assert check_style(_with_bullet(f"I am {phrase} things"), ""), phrase


def test_banned_phrases_are_case_insensitive():
    assert check_style(_with_bullet("Delve into the data"), "")
    assert check_style(_with_bullet("DELVE into the data"), "")


def test_delve_catches_its_inflections():
    assert check_style(_with_bullet("Delved into the data"), "")
    assert check_style(_with_bullet("Delving into the data"), "")


def test_passionately_is_not_caught_by_the_passionate_about_rule():
    """Word-boundary matching, not substring matching."""
    assert check_style(_with_bullet("Worked passionately on the migration"), "") == []


def test_excited_openers_are_detected_in_the_cover_letter():
    assert check_style(_resume(), "I am excited to apply for this role.")
    assert check_style(_resume(), "I was excited to see this posting.")


def test_in_todays_world_construction_is_detected():
    assert check_style(_resume(), "In today's fast-moving world, data matters.")
    assert check_style(_resume(), "In today's competitive landscape, speed wins.")


# --- the anti-creep test -----------------------------------------------------


def test_legitimate_resume_vocabulary_is_not_banned():
    """Spec section 4.4. Every word here has real, common, pre-LLM resume use.

    Banning them would block truthful sentences and push the model toward
    stranger phrasing. This test exists to stop the ban list creeping.
    """
    bullet = (
        "Spearheaded a robust, cutting-edge platform, using meticulous testing "
        "to leverage existing infrastructure and scale it; as architect I did "
        "not only design but also drive delivery."
    )
    assert check_style(_with_bullet(bullet), "") == []


# --- field scoping -----------------------------------------------------------


def test_date_fields_are_not_checked():
    """Facts carried verbatim from the master profile can never be rejected."""
    resume = _resume(
        sections=[
            {
                "type": "experience",
                "title": "Experience",
                "items": [
                    {
                        "company": "Initech",
                        "role": "Engineer",
                        "start": "2020–2021",
                        "end": "2022–2024",
                        "bullets": ["Shipped the thing"],
                    }
                ],
            }
        ]
    )
    assert check_style(resume, "") == []


def test_company_and_role_names_are_not_checked():
    resume = _resume(
        sections=[
            {
                "type": "experience",
                "title": "Experience",
                "items": [
                    {
                        "company": "Smith — Jones LLP",
                        "role": "Engineer — Platform",
                        "start": "2020",
                        "end": "2024",
                        "bullets": ["Shipped the thing"],
                    }
                ],
            }
        ]
    )
    assert check_style(resume, "") == []


def test_skill_labels_and_items_are_not_checked():
    resume = _resume(
        sections=[
            {
                "type": "skills",
                "title": "Skills",
                "groups": [{"label": "Back — end", "items": ["Python — 3.12"]}],
            }
        ]
    )
    assert check_style(resume, "") == []


def test_contact_and_urls_are_not_checked():
    resume = _resume(
        contact={
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "location": "Portland — OR",
            "links": [{"label": "Site — personal", "url": "https://a.example/x—y"}],
        }
    )
    assert check_style(resume, "") == []


def test_headline_and_summary_are_checked():
    assert check_style(_resume(headline="Engineer — platform"), "")
    assert check_style(_resume(summary="I am passionate about systems."), "")


def test_project_description_and_bullets_are_checked():
    resume = _resume(
        sections=[
            {
                "type": "projects",
                "title": "Projects",
                "items": [
                    {
                        "name": "Fleet",
                        "description": "A tool — for fleets",
                        "bullets": ["Shipped it"],
                    }
                ],
            }
        ]
    )
    violations = check_style(resume, "")
    assert violations and "Fleet" in violations[0]


def test_education_detail_is_checked():
    resume = _resume(
        sections=[
            {
                "type": "education",
                "title": "Education",
                "items": [
                    {
                        "institution": "State University",
                        "credential": "BSc Computer Science",
                        "detail": "Graduated with honours — top decile",
                    }
                ],
            }
        ]
    )
    assert check_style(resume, "")


def test_extras_items_are_checked():
    resume = _resume(
        sections=[{"type": "extras", "title": "Extras", "items": ["Speaker — PyCon"]}]
    )
    assert check_style(resume, "")


def test_the_cover_letter_is_checked_whole():
    assert check_style(_resume(), "Dear team — I built the thing.")


# --- reporting ---------------------------------------------------------------


def test_multiple_violations_are_all_reported():
    resume = _resume(headline="Engineer — platform", summary="I am passionate about it.")
    assert len(check_style(resume, "Dear team — hello.")) >= 3


def test_one_field_with_two_different_problems_reports_both():
    violations = check_style(_with_bullet("Cut latency — seamlessly"), "")
    assert len(violations) == 2
```

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_style.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'backend.app.services.style'`.

- [ ] **Step 3: Write the module**

Create `backend/app/services/style.py`:

```python
"""The voice contract: mechanical style rules, enforced rather than requested.

The project already enforces truthfulness in the data layer rather than in the
prompt, on the reasoning that asking a model nicely holds most of the time,
which means it does not hold. Asking a model nicely not to use em dashes fails
the same way. So the style rules live beside the truthfulness rules, on the
write path, covering both the API pipeline and MCP agents with one
implementation.

Scope is deliberate. The check runs on the ResumeDoc object and the
cover-letter markdown, never on rendered HTML, so a template's own en dash in
"{{ item.start }}-{{ item.end }}" can never trigger it. And it reads only prose
the model wrote: company names, role titles, institutions, credentials, dates,
URLs and skill items are excluded, so a fact carried verbatim from the master
profile can never be rejected.

The governing rule for what belongs here: hard-fail only what has near-zero
legitimate use in a resume. Everything else is prompt guidance. A false
positive blocks a truthful resume and burns a retry, which is worse than an
occasional stylistic miss.
"""
from __future__ import annotations

import re

from ..schemas import ResumeDoc

# --- Characters --------------------------------------------------------------
#
# Each entry: (compiled pattern, human name, what to do instead).

BANNED_CHARACTERS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile("—"),
        "em dash",
        "rewrite the sentence, or use a comma, colon or full stop",
    ),
    (
        # An en dash that does NOT sit directly between two digits. "2020-2023"
        # written with an en dash is correct typography and passes; "work - life"
        # does not. Stated precisely because the naive rule would reject a
        # truthful bullet like "Led the 2020-2023 platform migration".
        re.compile(r"(?<!\d)–|–(?!\d)"),
        "en dash outside a numeric range",
        "use a comma or rewrite; en dashes belong only between two years",
    ),
    (
        re.compile(
            "["
            "\U0001f000-\U0001faff"  # emoji and pictographs
            "☀-⛿"  # miscellaneous symbols
            "✀-➿"  # dingbats
            "️"  # variation selector, the emoji presentation marker
            "]"
        ),
        "emoji or pictograph",
        "remove it; there is no legitimate use in a resume or cover letter",
    ),
    (
        re.compile("[“”‘’]"),
        "curly quote",
        "use a straight quote, which is always acceptable and never a tell",
    ),
    (
        re.compile("…"),
        "ellipsis character",
        "use three periods, or better, finish the sentence",
    ),
    (
        re.compile("[ ​‌‍﻿]"),
        "invisible character (non-breaking or zero-width space)",
        "replace it with an ordinary space; these also corrupt ATS text extraction",
    ),
)

# --- Phrases -----------------------------------------------------------------
#
# Deliberately short and curated. Matched case-insensitively on word boundaries.
# See ALLOWED_WORDS below for what is deliberately absent, and why.

BANNED_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), advice)
    for pattern, advice in (
        (r"\bpassionate about\b", "say what you did instead of how you feel about it"),
        (r"\bproven track record\b", "give the specific result instead"),
        (r"\bresults[-\s]driven\b", "name the result"),
        (r"\bresults[-\s]oriented\b", "name the result"),
        (r"\bresults[-\s]focused\b", "name the result"),
        (r"\bwealth of experience\b", "say how many years, doing what"),
        (r"\bseamlessly\b", "cut the adverb, or say what made it work"),
        (r"\btestament to\b", "state the fact plainly"),
        (r"\bdelv\w*\b", "use a plain verb such as studied, examined or read"),
        (r"\btapestry\b", "use a plain noun"),
        (r"\bI am excited to\b", "open on a specific fact about the company or role"),
        (r"\bI was excited to\b", "open on a specific fact about the company or role"),
        (
            r"\bin today['’]s\b[^.!?]{0,40}\bworld\b",
            "cut the throat-clearing and open on the specific point",
        ),
        (
            r"\bin today['’]s\b[^.!?]{0,40}\blandscape\b",
            "cut the throat-clearing and open on the specific point",
        ),
    )
)

# Documented as a constant so the intent survives, and so tests can assert it.
# Every one of these has real, common, pre-LLM use in resumes: "leverage" in
# finance, "robust" and "scale" in engineering, "spearheaded" in decades of
# management resumes. Banning them would block truthful sentences and push the
# model toward stranger phrasing.
ALLOWED_WORDS: tuple[str, ...] = (
    "leverage",
    "robust",
    "scale",
    "architect",
    "drive",
    "spearheaded",
    "cutting-edge",
    "meticulous",
    "not only ... but also",
)


def _check_text(label: str, text: str) -> list[str]:
    """Every rule violated by one piece of prose, each named and actionable."""
    if not text:
        return []
    found: list[str] = []
    for pattern, name, advice in BANNED_CHARACTERS:
        if pattern.search(text):
            found.append(f"{label}: {name}. {advice[0].upper()}{advice[1:]}.")
    for pattern, advice in BANNED_PHRASES:
        match = pattern.search(text)
        if match:
            found.append(
                f"{label}: the phrase {match.group(0)!r} reads as machine-written. "
                f"{advice[0].upper()}{advice[1:]}."
            )
    return found


def _prose_fields(resume: ResumeDoc, cover_md: str) -> list[tuple[str, str]]:
    """(label, text) for every field the model wrote as prose.

    Excluded on purpose: company, role, institution and credential names; start,
    end and year strings; URLs, email, phone and location; skill group labels
    and items. Those are facts carried from the master profile, and rejecting
    the user's own data would be a bug, not a feature.
    """
    fields: list[tuple[str, str]] = [
        ("Headline", resume.headline),
        ("Summary", resume.summary),
    ]
    for section in resume.sections:
        if section.type == "experience":
            for item in section.items:
                for i, bullet in enumerate(item.bullets, start=1):
                    fields.append((f"Experience '{item.company}' bullet {i}", bullet))
        elif section.type == "projects":
            for item in section.items:
                fields.append((f"Project '{item.name}' description", item.description))
                for i, bullet in enumerate(item.bullets, start=1):
                    fields.append((f"Project '{item.name}' bullet {i}", bullet))
        elif section.type == "education":
            for item in section.items:
                if item.detail:
                    fields.append(
                        (f"Education '{item.credential}' detail", item.detail)
                    )
        elif section.type == "extras":
            for i, entry in enumerate(section.items, start=1):
                fields.append((f"Extras item {i}", entry))
    fields.append(("Cover letter", cover_md))
    return fields


def check_style(resume: ResumeDoc, cover_md: str) -> list[str]:
    """Human-readable violations of the voice contract. Empty list = clean.

    Mirrors verify_truthfulness's contract exactly, so both gates read the same
    way at their call sites.
    """
    violations: list[str] = []
    for label, text in _prose_fields(resume, cover_md):
        violations.extend(_check_text(label, text))
    return violations
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_style.py -q`
Expected: all pass.

Two of them are load-bearing and worth reading the output for:
- `test_a_numeric_range_en_dash_is_allowed` — the precision of the en-dash rule.
- `test_legitimate_resume_vocabulary_is_not_banned` — the anti-creep guard.

- [ ] **Step 5: Confirm nothing else changed**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: the previous total plus the new style tests, zero failures. `style.py` is not yet imported by anything, so nothing else can move.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/style.py tests/test_style.py
git commit -m "feat: add the voice contract style check"
```

---

### Task 2: Enforce on the MCP path

**Files:**
- Modify: `backend/mcp_ops.py` (import, and the block after the truthfulness raise at lines 468-475)
- Modify: `tests/test_mcp_ops.py` (append)

**Interfaces:**
- Consumes `check_style` from Task 1.
- Behaviour: `save_tailored_resume` raises `McpOpsError` listing the violations, and persists nothing, exactly as it already does for truthfulness. No server-side retry counter — the agent owns its own loop.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_ops.py`:

```python
def test_save_tailored_resume_rejects_an_em_dash(engine, profile_id, tmp_path, pdf_faked):
    app_id = _create_app(engine, profile_id)
    tailor = _fixture("tailor")
    resume = tailor["resume"]
    resume["summary"] = "Eight years building payment systems — mostly in Python."

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.save_tailored_resume(
            engine, tmp_path, app_id, resume, tailor["cover_letter_md"], ""
        )
    message = str(exc.value)
    assert "Style check failed" in message
    assert "em dash" in message.lower()
    assert "Summary" in message


def test_a_style_rejection_persists_nothing(engine, profile_id, tmp_path, pdf_faked):
    app_id = _create_app(engine, profile_id)
    tailor = _fixture("tailor")
    resume = tailor["resume"]
    resume["summary"] = "I am passionate about payment systems."

    with pytest.raises(mcp_ops.McpOpsError):
        mcp_ops.save_tailored_resume(
            engine, tmp_path, app_id, resume, tailor["cover_letter_md"], ""
        )
    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.resume_json is None
        assert app.cover_letter_md is None
        assert app.status == "tailoring", "the agent must be able to correct and retry"


def test_truthfulness_is_reported_before_style(engine, profile_id, tmp_path, pdf_faked):
    """A resume that invents an employer should be reported as inventing an
    employer, not as having an em dash in the invented employer's bullet."""
    app_id = _create_app(engine, profile_id)
    tailor = _fixture("tailor")
    resume = tailor["resume"]
    resume["summary"] = "Built things — quickly."
    for section in resume["sections"]:
        if section["type"] == "experience":
            section["items"][0]["company"] = "Totally Invented Corp"
            break

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.save_tailored_resume(
            engine, tmp_path, app_id, resume, tailor["cover_letter_md"], ""
        )
    message = str(exc.value)
    assert "Truthfulness check failed" in message
    assert "Style check failed" not in message


def test_a_style_rejection_tells_the_agent_what_to_do(engine, profile_id, tmp_path, pdf_faked):
    app_id = _create_app(engine, profile_id)
    tailor = _fixture("tailor")
    resume = tailor["resume"]
    resume["summary"] = "Built things — quickly."

    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.save_tailored_resume(
            engine, tmp_path, app_id, resume, tailor["cover_letter_md"], ""
        )
    assert "call this tool again" in str(exc.value)


def test_the_clean_fixture_still_saves(engine, profile_id, tmp_path, pdf_faked):
    """The style gate must not block the sample data the whole suite relies on."""
    app_id = _create_app(engine, profile_id)
    result = _save_tailor(engine, tmp_path, app_id, _fixture("tailor"))
    assert result["status"] == "ready"
```

Confirm `Application` and `Session` are already imported at the top of `tests/test_mcp_ops.py`; the existing stage tests at lines 315 and 335 use both, so they are.

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp_ops.py -q -k "style or truthfulness_is_reported"`
Expected: the rejection tests fail because the save succeeds; `test_the_clean_fixture_still_saves` passes already.

- [ ] **Step 3: Wire the gate in**

In `backend/mcp_ops.py`, add to the imports near `from .app.services.tailor import verify_truthfulness`:

```python
from .app.services.style import check_style
```

Then, immediately after the existing truthfulness raise (which ends at line 475 with the closing parenthesis of the `McpOpsError`), add:

```python
        style_violations = check_style(resume_doc, cover_letter_md)
        if style_violations:
            raise McpOpsError(
                "Style check failed:\n- "
                + "\n- ".join(style_violations)
                + "\nRewrite the flagged text in the candidate's own plain "
                "voice and call this tool again."
            )
```

Placement matters: after truthfulness, before any `session.add`. Nothing is persisted on either failure, which is what lets the agent correct and retry.

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp_ops.py -q`
Expected: all pass, including the five new ones.

- [ ] **Step 5: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures.

- [ ] **Step 6: Commit**

```bash
git add backend/mcp_ops.py tests/test_mcp_ops.py
git commit -m "feat: enforce the voice contract on the MCP write path"
```

---

### Task 3: Enforce on the API pipeline, with one retry

**Files:**
- Modify: `backend/app/services/pipeline.py:94-147` (`_tailor_and_render`)
- Modify: `tests/test_pipeline.py` (append)

**Interfaces:**
- Consumes `check_style` from Task 1.
- Behaviour: a style failure re-runs tailoring exactly once with the violations appended as feedback. A second failure raises `ClaudeError`, which the existing caller-level `except Exception` turns into `_mark_error`. Truthfulness still raises immediately and is never retried.

**Two things the spec does not say that follow from it and must be implemented anyway:**

1. **The retry's output goes through both gates again.** A retry that fixes an em dash but invents an employer must still be rejected for inventing an employer.
2. **Usage from both calls is accumulated.** Two API calls cost two API calls, and a cost figure that hides the retry is a lie to the user. `_add_usage` is called once per attempt.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`:

```python
def _style_failure_once():
    """A check_style stand-in that fails the first call and passes after."""
    calls = {"n": 0}

    def _check(resume, cover_md):
        calls["n"] += 1
        return ["Summary: em dash. Rewrite the sentence."] if calls["n"] == 1 else []

    return _check, calls


def test_a_style_failure_retries_tailoring_once_and_succeeds(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    check, calls = _style_failure_once()
    monkeypatch.setattr(pipeline, "check_style", check)
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "ready"
    assert calls["n"] == 2, "expected exactly one retry"


def test_the_retry_passes_the_violations_back_to_the_model(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    """A retry that does not say what was wrong is just a second dice roll."""
    check, _calls = _style_failure_once()
    monkeypatch.setattr(pipeline, "check_style", check)
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    tailor_calls = [c for c in claude_fake.calls if c.get("task") == "tailor"]
    assert len(tailor_calls) == 2
    assert "em dash" in tailor_calls[-1]["user_content"]
    assert "em dash" not in tailor_calls[0]["user_content"]


def test_two_style_failures_mark_the_application_error(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    monkeypatch.setattr(
        pipeline,
        "check_style",
        lambda resume, cover_md: ["Summary: em dash. Rewrite the sentence."],
    )
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "error"
        assert "Style check failed" in (app.error_message or "")
        assert "em dash" in (app.error_message or "")


def test_a_style_failure_never_loops(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    """Exactly two tailoring calls, never three. Burning tokens in a cycle is
    worse than surfacing the problem."""
    monkeypatch.setattr(
        pipeline, "check_style", lambda resume, cover_md: ["Summary: em dash."]
    )
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    assert len([c for c in claude_fake.calls if c.get("task") == "tailor"]) == 2


def test_the_retry_is_billed(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    """Two API calls cost two API calls. A cost that hides the retry is a lie."""
    check, _calls = _style_failure_once()
    monkeypatch.setattr(pipeline, "check_style", check)
    retried_id = seed_application(engine, claude_fake)
    pipeline.process_application(retried_id, engine=engine, claude=claude_fake)

    monkeypatch.setattr(pipeline, "check_style", lambda resume, cover_md: [])
    clean_id = seed_application(engine, claude_fake)
    pipeline.process_application(clean_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        retried = session.get(Application, retried_id)
        clean = session.get(Application, clean_id)
        assert retried.input_tokens > clean.input_tokens
        assert retried.cost_usd > clean.cost_usd


def test_truthfulness_is_still_never_retried(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    monkeypatch.setattr(
        pipeline, "verify_truthfulness", lambda resume, profile: ["invented Fake Corp"]
    )
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "error"
        assert "Truthfulness" in (app.error_message or "")
    assert len([c for c in claude_fake.calls if c.get("task") == "tailor"]) == 1


def test_a_retry_that_becomes_untruthful_is_rejected(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    """Both gates run on the retry, not just the one that failed."""
    style_calls = {"n": 0}

    def _style(resume, cover_md):
        style_calls["n"] += 1
        return ["Summary: em dash."] if style_calls["n"] == 1 else []

    truth_calls = {"n": 0}

    def _truth(resume, profile):
        truth_calls["n"] += 1
        return [] if truth_calls["n"] == 1 else ["invented Fake Corp"]

    monkeypatch.setattr(pipeline, "check_style", _style)
    monkeypatch.setattr(pipeline, "verify_truthfulness", _truth)
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "error"
        assert "Truthfulness" in (app.error_message or "")


def test_a_clean_generation_makes_exactly_one_tailoring_call(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
):
    """The retry must not fire on the happy path."""
    app_id = seed_application(engine, claude_fake)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        assert session.get(Application, app_id).status == "ready"
    assert len([c for c in claude_fake.calls if c.get("task") == "tailor"]) == 1
```

`RecordingClaude` overwrites `self.calls[-1]` with a dict carrying `task` and `user_content`, so filtering on `c.get("task") == "tailor"` is the reliable way to count tailoring calls; read its definition at the top of `tests/test_pipeline.py` before relying on it.

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_pipeline.py -q`
Expected: `AttributeError: <module 'backend.app.services.pipeline'> does not have the attribute 'check_style'` on the monkeypatching tests.

- [ ] **Step 3: Rewrite the gate section of `_tailor_and_render`**

In `backend/app/services/pipeline.py`, add the import beside the existing tailor import:

```python
from .style import check_style
```

Import it at module level, as a module attribute, because the tests monkeypatch `pipeline.check_style` exactly as they already monkeypatch `pipeline.verify_truthfulness`.

Replace lines 99-108 — from `_set_status(session, app, "tailoring")` through the end of the truthfulness `raise` — with:

```python
    _set_status(session, app, "tailoring")

    # One retry, never a loop. A second failure means something is wrong with
    # the rules or the model, and burning tokens in a cycle is worse than
    # surfacing it. Both gates run on every attempt: a retry that fixes an em
    # dash but invents an employer must still be rejected for inventing one.
    attempt_feedback = feedback
    result = None
    for attempt in (0, 1):
        result, usage = tailor_application(
            master, contact, parsed, findings, app.template, claude,
            feedback=attempt_feedback,
        )
        _add_usage(app, usage)

        violations = verify_truthfulness(result.resume, master)
        if violations:
            raise ClaudeError(
                "Truthfulness check failed: " + "; ".join(violations)
            )

        style_violations = check_style(result.resume, result.cover_letter_md)
        if not style_violations:
            break
        if attempt == 1:
            raise ClaudeError(
                "Style check failed: " + "; ".join(style_violations)
            )
        attempt_feedback = _style_retry_feedback(feedback, style_violations)
```

And add this helper above `_tailor_and_render`:

```python
def _style_retry_feedback(feedback: str | None, violations: list[str]) -> str:
    """The original feedback plus the style violations, for the single retry.

    A retry that does not say what was wrong is just a second dice roll, so the
    violations are passed back verbatim; they are written to be actionable.
    """
    block = (
        "STYLE VIOLATIONS in your previous attempt. Rewrite the flagged text "
        "in the candidate's own plain voice, keeping every fact unchanged:\n- "
        + "\n- ".join(violations)
    )
    return f"{feedback}\n\n{block}" if feedback else block
```

Everything below the loop — `app.resume_json = result.resume.model_dump_json()` onward — is unchanged, except that the existing standalone `_add_usage(app, usage)` call must be **deleted**, because usage is now accumulated inside the loop. Leaving both in would double-bill the final attempt.

- [ ] **Step 4: Run the pipeline tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_pipeline.py -q`
Expected: all pass.

If `test_the_retry_is_billed` fails, the duplicate `_add_usage` was probably not deleted, or was deleted along with the loop's copy.

- [ ] **Step 5: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures. Watch `tests/test_e2e.py` in particular: it runs the real pipeline against the real fixture, so it exercises the new gate for real rather than through a monkeypatch.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pipeline.py tests/test_pipeline.py
git commit -m "feat: enforce the voice contract in the pipeline, with one retry"
```

---

### Task 4: `Profile.voice_notes` end to end

**Files:**
- Modify: `backend/app/models.py:40-46` (`Profile`)
- Modify: `backend/app/api/profiles.py:32-35` (`ProfileUpdate`), `:43-55` (`profile_detail`), `:100-115` (`update_profile`)
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts:66-71`, `frontend/src/screens/ProfileScreen.tsx`
- Modify: `tests/test_models.py` or `tests/test_api.py`, and `frontend/src/screens/ProfileScreen.test.tsx`

**Interfaces:**
- Produces `Profile.voice_notes: str = ""`, surfaced as `voice_notes` on every profile payload and accepted by `PUT /profiles/{id}`.

**No migration code is needed and none should be written.** `init_db` already calls `_add_missing_columns`, and `_column_ddl` emits `voice_notes VARCHAR NOT NULL DEFAULT ''` for a column declared with a scalar string default. Declaring the field is the whole migration. Do not use `default_factory` or a non-scalar default: `_column_ddl` checks `default.is_scalar` and would silently drop the `NOT NULL DEFAULT` clause, producing a column that reads back as `None` on old rows.

- [ ] **Step 1: Write the failing backend tests**

Append to `tests/test_api.py`:

```python
def test_a_new_profile_has_empty_voice_notes(client):
    resp = client.post("/api/profiles", json={"name": "Ada"})
    assert resp.status_code in (200, 201)
    assert resp.json()["voice_notes"] == ""


def test_voice_notes_round_trips_through_put(client):
    profile_id = client.post("/api/profiles", json={"name": "Ada"}).json()["id"]
    notes = "Plain and direct. No salesmanship. Short sentences."
    resp = client.put(f"/api/profiles/{profile_id}", json={"voice_notes": notes})
    assert resp.status_code == 200
    assert resp.json()["voice_notes"] == notes
    assert client.get(f"/api/profiles/{profile_id}").json()["voice_notes"] == notes


def test_putting_other_fields_leaves_voice_notes_alone(client):
    profile_id = client.post("/api/profiles", json={"name": "Ada"}).json()["id"]
    client.put(f"/api/profiles/{profile_id}", json={"voice_notes": "Be plain."})
    resp = client.put(f"/api/profiles/{profile_id}", json={"name": "Ada L"})
    assert resp.json()["voice_notes"] == "Be plain."
    assert resp.json()["name"] == "Ada L"


def test_voice_notes_can_be_cleared(client):
    profile_id = client.post("/api/profiles", json={"name": "Ada"}).json()["id"]
    client.put(f"/api/profiles/{profile_id}", json={"voice_notes": "Be plain."})
    resp = client.put(f"/api/profiles/{profile_id}", json={"voice_notes": ""})
    assert resp.json()["voice_notes"] == ""
```

Match the exact profile-creation route and payload the surrounding tests in that file use; if `POST /api/profiles` takes a different body, copy theirs.

Append to `tests/test_migration.py`:

```python
def test_voice_notes_is_added_to_a_pre_existing_profile_table(tmp_path):
    """A database created before voice_notes existed must gain the column."""
    from sqlalchemy import text

    from backend.app.db import get_engine, init_db

    db = tmp_path / "old.db"
    engine = get_engine(db)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE profile ("
                "id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, "
                "contact_json VARCHAR NOT NULL, master_profile_json VARCHAR NOT NULL, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO profile VALUES "
                "(1, 'Ada', '{}', '{}', '2026-01-01', '2026-01-01')"
            )
        )

    init_db(engine)

    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(profile)"))}
        assert "voice_notes" in columns
        value = conn.execute(text("SELECT voice_notes FROM profile WHERE id=1")).scalar()
        assert value == "", "the existing row must get the default, not NULL"
```

Match the style of the existing `OLD_APPLICATION_DDL` test in that file; if it has a helper for building an old-schema database, use it rather than the inline SQL above.

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_api.py tests/test_migration.py -q -k voice`
Expected: `KeyError: 'voice_notes'` on the API tests, and the column assertion failing on the migration test.

- [ ] **Step 3: Add the column**

In `backend/app/models.py`, add to `Profile`, after `master_profile_json`:

```python
    # Free-text direction for the generated writing, e.g. "Plain and direct.
    # No salesmanship. Short sentences." Takes precedence over the register
    # inferred from the user's uploaded documents, because explicit
    # instruction beats inference.
    voice_notes: str = ""
```

A scalar string default is required here; see the note above this task.

- [ ] **Step 4: Thread it through the API**

In `backend/app/api/profiles.py`:

Add to `ProfileUpdate` (lines 32-35):

```python
    voice_notes: Optional[str] = None
```

Add to the dict returned by `profile_detail` (lines 43-55), after `"master_profile"`:

```python
        "voice_notes": profile.voice_notes,
```

Add to `update_profile` (lines 100-115), beside the other `if body.X is not None:` branches:

```python
    if body.voice_notes is not None:
        profile.voice_notes = body.voice_notes
```

`None` means leave alone and `""` means clear, which is why the guard is `is not None` rather than a truthiness check. `test_voice_notes_can_be_cleared` pins that distinction.

- [ ] **Step 5: Run the backend tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures, including the five new ones.

- [ ] **Step 6: Write the failing frontend test**

Append to `frontend/src/screens/ProfileScreen.test.tsx`:

```tsx
it("saves voice notes for the profile", async () => {
  renderScreen();
  const box = await screen.findByLabelText(/voice notes/i);
  fireEvent.change(box, {
    target: { value: "Plain and direct. Never call myself passionate." },
  });
  fireEvent.click(screen.getByRole("button", { name: /save master profile/i }));
  await waitFor(() =>
    expect(api.updateProfile).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({
        voice_notes: "Plain and direct. Never call myself passionate.",
      }),
    ),
  );
});

it("shows the voice notes already on the profile", async () => {
  vi.mocked(api.getProfile).mockResolvedValue({
    ...baseProfileDetail,
    voice_notes: "Short sentences only.",
  });
  renderScreen();
  expect(await screen.findByDisplayValue("Short sentences only.")).toBeInTheDocument();
});
```

Adapt to the file's actual helpers: use whatever it calls its render helper and its profile-detail fixture, and whichever api function it mocks for loading a profile. Add `voice_notes: ""` to that fixture so the type checker stays satisfied.

- [ ] **Step 7: Add the field to the frontend**

`frontend/src/types.ts`: add `voice_notes: string;` to `ProfileDetail`.

`frontend/src/api.ts:66-71`: add `voice_notes?: string` to `updateProfile`'s inline `patch` type.

`frontend/src/screens/ProfileScreen.tsx`: add a textarea following the file's existing `field` / `field-label` / `textarea` pattern, and include `voice_notes` in the `handleSave` payload. Place it in the same card as the summary notes:

```tsx
<div className="field">
  <label className="field-label" htmlFor="voice-notes">Voice notes</label>
  <textarea
    id="voice-notes"
    className="textarea"
    value={voiceNotes}
    placeholder="Plain and direct. No salesmanship. Short sentences. Never call myself passionate about anything."
    onChange={(e) => setVoiceNotes(e.target.value)}
  />
  <p className="muted">
    How you want your resume and cover letters to sound. This shapes the writing
    only; every fact still comes from your master profile.
  </p>
</div>
```

Add `voiceNotes` state, seed it from the loaded detail alongside the existing `setMp(...)` calls, and extend `handleSave` to send it:

```tsx
const d = await updateProfile(selectedId, { master_profile: mp, voice_notes: voiceNotes });
```

The existing `handleSave` reseeds local state from the response; reseed `voiceNotes` there too, or the field will revert on the next load.

- [ ] **Step 8: Run the frontend tests and the type checker**

Run: `cd frontend && npx vitest run`
Expected: 0 failures.

Run: `cd frontend && npx tsc --noEmit`
Expected: no output. Adding a required `voice_notes` to `ProfileDetail` will error in every test fixture that builds one; add `voice_notes: ""` to each rather than making the field optional.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models.py backend/app/api/profiles.py frontend/src tests/
git commit -m "feat: add Profile.voice_notes end to end"
```

---

### Task 5: Voice reaches the tailoring input

**Files:**
- Modify: `backend/app/services/tailor.py:44-75` (`tailor_application`)
- Modify: `backend/app/services/pipeline.py` (pass the voice arguments)
- Modify: `backend/mcp_ops.py` (`get_workflow_guide`)
- Modify: `tests/test_tailor.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces the extended signature:

```python
def tailor_application(
    profile: MasterProfile,
    contact: Contact,
    parsed: ParsedPosting,
    research: ResearchFindings | None,
    template: str,
    claude: ClaudeService,
    feedback: str | None = None,
    voice_sample: str | None = None,
    voice_notes: str | None = None,
) -> tuple[TailorResult, UsageInfo]:
```

Both new parameters are keyword-with-default and come after `feedback`, because `pipeline.py` and six sites in `tests/test_tailor.py` pass the first six arguments positionally.

- Produces `pipeline._voice_for(session, profile) -> tuple[str | None, str | None]` returning `(voice_sample, voice_notes)`.

**The safety argument, stated because it looks risky and is not.** A voice sample might tempt a model to lift an employer or a claim out of it. `verify_truthfulness` structurally rejects exactly that: any experience, education or certification entry not present in the master profile. The existing guard covers the new risk, which is the argument for having built it structurally rather than as a prompt instruction. Step 1 includes a test that proves it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tailor.py`:

```python
def test_voice_sample_reaches_the_model_labelled_as_style_only(claude_fake):
    tailor_application(
        PROFILE, CONTACT, PARSED, None, "slate", claude_fake,
        voice_sample="I fix things that are broken. I do not oversell.",
    )
    content = claude_fake.calls[-1]["user_content"]
    assert "I fix things that are broken" in content
    assert "NOT a source of facts" in content


def test_voice_notes_reach_the_model(claude_fake):
    tailor_application(
        PROFILE, CONTACT, PARSED, None, "slate", claude_fake,
        voice_notes="Plain and direct. Short sentences.",
    )
    assert "Plain and direct. Short sentences." in claude_fake.calls[-1]["user_content"]


def test_voice_notes_are_marked_as_taking_precedence(claude_fake):
    """Explicit instruction beats inference, and the prompt has to say so."""
    tailor_application(
        PROFILE, CONTACT, PARSED, None, "slate", claude_fake,
        voice_sample="Some earlier writing.",
        voice_notes="Short sentences.",
    )
    content = claude_fake.calls[-1]["user_content"]
    assert content.index("Short sentences.") < content.index("Some earlier writing.")


def test_no_voice_information_leaves_the_input_unchanged(claude_fake):
    tailor_application(PROFILE, CONTACT, PARSED, None, "slate", claude_fake)
    content = claude_fake.calls[-1]["user_content"]
    assert "register reference" not in content.lower()
    assert "VOICE" not in content


def test_the_voice_sample_is_truncated(claude_fake):
    tailor_application(
        PROFILE, CONTACT, PARSED, None, "slate", claude_fake,
        voice_sample="x" * 10000,
    )
    content = claude_fake.calls[-1]["user_content"]
    assert content.count("x") <= 2100, "a whole resume would crowd out the real input"


def test_the_system_prompt_carries_the_baseline_style_rules():
    """Enforcement is the backstop; the prompt is the mechanism, so most runs
    pass first time and the retry rarely fires."""
    from backend.app.services.tailor import TAILOR_SYSTEM

    lowered = TAILOR_SYSTEM.lower()
    assert "em dash" in lowered
    assert "emoji" in lowered
    assert "passionate about" in lowered
    assert "straight quote" in lowered
```

Append to `tests/test_pipeline.py`:

```python
def test_the_pipeline_passes_voice_notes_to_the_model(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
):
    app_id = seed_application(engine, claude_fake)
    with Session(engine) as session:
        app = session.get(Application, app_id)
        profile = session.get(Profile, app.profile_id)
        profile.voice_notes = "Plain and direct. Short sentences."
        session.add(profile)
        session.commit()

    pipeline.process_application(app_id, engine=engine, claude=claude_fake)
    tailor_calls = [c for c in claude_fake.calls if c.get("task") == "tailor"]
    assert "Plain and direct. Short sentences." in tailor_calls[-1]["user_content"]


def test_the_pipeline_passes_the_most_recent_source_document_as_voice(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked
):
    app_id = seed_application(engine, claude_fake)
    with Session(engine) as session:
        app = session.get(Application, app_id)
        session.add(
            SourceDocument(
                profile_id=app.profile_id, filename="old.txt", kind="txt",
                text="OLDER WRITING SAMPLE",
            )
        )
        session.commit()
        session.add(
            SourceDocument(
                profile_id=app.profile_id, filename="new.txt", kind="txt",
                text="NEWER WRITING SAMPLE",
            )
        )
        session.commit()

    pipeline.process_application(app_id, engine=engine, claude=claude_fake)
    content = [c for c in claude_fake.calls if c.get("task") == "tailor"][-1]["user_content"]
    assert "NEWER WRITING SAMPLE" in content
    assert "OLDER WRITING SAMPLE" not in content


def test_a_voice_sample_cannot_smuggle_in_an_employer(
    engine, claude_fake, pipeline_settings, fetched_ok, pdf_faked, monkeypatch
):
    """The voice sample is style-only, and truthfulness is what makes that true.

    A model that lifts an employer out of the sample is rejected by the existing
    structural guard, which is the argument for having built it structurally.
    """
    app_id = seed_application(engine, claude_fake)
    with Session(engine) as session:
        app = session.get(Application, app_id)
        session.add(
            SourceDocument(
                profile_id=app.profile_id, filename="v.txt", kind="txt",
                text="At Nonexistent Holdings I ran the whole platform.",
            )
        )
        session.commit()

    # Simulate the model taking the bait.
    real = pipeline.verify_truthfulness

    def _tempted(resume, profile):
        for section in resume.sections:
            if section.type == "experience" and section.items:
                section.items[0].company = "Nonexistent Holdings"
                break
        return real(resume, profile)

    monkeypatch.setattr(pipeline, "verify_truthfulness", _tempted)
    pipeline.process_application(app_id, engine=engine, claude=claude_fake)

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert app.status == "error"
        assert "Nonexistent Holdings" in (app.error_message or "")
```

Add `Profile` and `SourceDocument` to the model imports at the top of `tests/test_pipeline.py` if they are not already there.

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_tailor.py tests/test_pipeline.py -q -k "voice or baseline_style"`
Expected: `TypeError: tailor_application() got an unexpected keyword argument 'voice_sample'`.

- [ ] **Step 3: Extend `tailor_application`**

In `backend/app/services/tailor.py`, change the signature as given in the Interfaces block above, and insert this immediately after the existing `feedback` block, before `claude.structured(...)`:

```python
    if voice_notes:
        parts.append(
            "VOICE DIRECTION FROM THE CANDIDATE (highest-priority style "
            "instruction; explicit direction beats anything inferred below):\n"
            + voice_notes
        )
    if voice_sample:
        parts.append(
            "REGISTER REFERENCE - the candidate's own writing, provided so you "
            "can match their register, sentence length, and vocabulary. It is "
            "NOT a source of facts. Every fact must still come from the master "
            "profile:\n" + voice_sample[:2000]
        )
```

Order matters and a test pins it: `voice_notes` is appended first so it appears earlier in the joined prompt, because explicit instruction beats inference.

- [ ] **Step 4: Add the baseline style rules to the system prompt**

In `TAILOR_SYSTEM`, insert this section between the `RESUME:` block and the `COVER LETTER` block:

```
WRITING VOICE (this text must read as the candidate's own writing):
- Plain, concrete, specific. Prefer short sentences to long ones.
- No superlatives, no throat-clearing, no summarising what you just said.
- Prefer the vocabulary of the candidate's field to the vocabulary of recruitment.
- Never use an em dash. Use a comma, a colon, or a full stop.
- Never use an en dash except between two years, as in 2020-2023.
- Never use emoji, curly quotes, or the ellipsis character. Straight quotes and three periods are correct.
- Never write: passionate about, proven track record, results-driven, results-oriented, results-focused, wealth of experience, seamlessly, testament to, delve, tapestry, "I am excited to", "in today's ... world".
- These rules are checked server-side and a violation is rejected, so follow them the first time.
```

Write the en-dash example with a plain hyphen as shown; the point is the instruction, and putting a literal en dash in the prompt invites the model to copy the character.

- [ ] **Step 5: Wire the pipeline to supply voice**

In `backend/app/services/pipeline.py`, add:

```python
def _voice_for(session: Session, profile: Profile) -> tuple[str | None, str | None]:
    """(voice_sample, voice_notes) for a profile.

    The sample is the most recent document the user uploaded during intake:
    their own writing, already in the database. It is style-only, and
    verify_truthfulness is what makes that safe.
    """
    latest = session.exec(
        select(SourceDocument)
        .where(SourceDocument.profile_id == profile.id)
        .order_by(SourceDocument.id.desc())
    ).first()
    sample = latest.text if latest is not None and latest.text else None
    return sample, (profile.voice_notes or None)
```

Import `SourceDocument` and `select` in that module if they are not already imported.

Then, in `_tailor_and_render`, resolve the voice once before the retry loop and pass it into both attempts:

```python
    voice_sample, voice_notes = _voice_for(session, session.get(Profile, app.profile_id))
```

and add `voice_sample=voice_sample, voice_notes=voice_notes,` to the `tailor_application(...)` call inside the loop.

Resolve it once, outside the loop: the retry is about style feedback, and re-querying would be pure noise.

- [ ] **Step 6: Add the voice rules to the MCP workflow guide**

`get_workflow_guide` in `backend/mcp_ops.py:67` is an **f-string**, so any literal brace you add must be doubled. Add a section after the `COVER LETTER` block:

```
WRITING VOICE (enforced server-side, like truthfulness):
- Plain, concrete, specific. Prefer short sentences to long ones.
- No superlatives, no throat-clearing, no summarising what you just said.
- Never use an em dash. Never use an en dash except between two years.
- Never use emoji, curly quotes, or the ellipsis character.
- Never write: passionate about, proven track record, results-driven,
  results-oriented, results-focused, wealth of experience, seamlessly,
  testament to, delve, tapestry, "I am excited to", "in today's ... world".
- save_tailored_resume rejects violations and returns the list, exactly as it
  does for truthfulness. Follow these the first time and you will not see it.
```

Add an assertion to the existing `test_workflow_guide_contents` in `tests/test_mcp_ops.py`:

```python
    assert "em dash" in guide.lower()
    assert "passionate about" in guide
```

- [ ] **Step 7: Run everything**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures.

- [ ] **Step 8: Commit**

```bash
git add backend/ tests/
git commit -m "feat: carry the candidate's voice into the tailoring input"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the voice contract beside the truthfulness contract**

Find the README's existing paragraph on truthfulness enforcement ("Truthfulness enforced in the data layer, not the prompt"). Add directly after it:

```markdown
**Voice enforced the same way.** Generated text is rejected if it carries the
mechanical tells of machine writing: em dashes, emoji, curly quotes, the
ellipsis character, invisible spaces, and a short curated list of recruitment
cliches. The check runs on the write path, so it holds for both the built-in
pipeline and any MCP agent, whichever model produced the text. The API pipeline
retries once with the violations attached; an agent gets the list back and
corrects it.

The list is deliberately short. Words with real, common, pre-LLM use in resumes
- leverage, robust, scale, spearheaded - are not banned, because a false
positive blocks a truthful resume and that is worse than an occasional
stylistic miss.

Set **Voice notes** on your profile to direct the writing explicitly, for
example "Plain and direct. No salesmanship. Short sentences." Tailored also
reads the register of the documents you uploaded during intake, as style only:
every fact still has to come from your Master Profile, and the truthfulness
check is what guarantees it.
```

- [ ] **Step 2: Verify the whole thing once more**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures.

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 0 failures, no type errors.

- [ ] **Step 3: Manual check**

Start the app and, by hand:

1. Open a profile, set Voice notes to "Plain and direct. No salesmanship. Short sentences.", save, reload, and confirm it stuck.
2. Generate an application. Read the cover letter. Confirm there are no em dashes and it does not open on the writer's feelings.
3. Confirm the cost shown is a single tailoring call for a clean generation.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: the voice contract"
```

---

## Self-Review

**Spec coverage.**

| Spec section | Task |
|---|---|
| §4 `check_style` signature and violation format | 1 |
| §4.1 exact field scoping, prose only | 1 |
| §4.1 template output cannot false-positive | 1 (by construction; the check never sees HTML) |
| §4.1 master-profile facts cannot be rejected | 1 |
| §4.2 every banned character, en dash precision | 1 |
| §4.3 every banned phrase | 1 |
| §4.4 what is deliberately not banned | 1 (`ALLOWED_WORDS` plus the anti-creep test) |
| §5.1 API pipeline, one retry, then error | 3 |
| §5.2 MCP raise with the list | 2 |
| §5.3 truthfulness checked first | 2, 3 |
| §6.1 SourceDocument excerpt, ~2000 chars, labelled style-only | 5 |
| §6.2 `Profile.voice_notes` plus the profile textarea | 4 |
| §6.2 voice_notes takes precedence | 5 (ordering, with a test) |
| §6.3 baseline rules in `tailor.py` and the workflow guide | 5 |
| §7 every listed test | 1, 2, 3, 4, 5 |

No gaps.

**Two things the spec does not state that the plan adds, both flagged inline in Task 3.** The retry's output goes through *both* gates, not only the one that failed; and usage is accumulated per attempt so the cost figure does not hide the retry. Both have tests.

**Placeholder scan.** Clean. Four places tell the implementer to match an existing local convention rather than trusting a name in the snippet, each because the surrounding file was not read line by line while planning: the profile-creation route shape in Task 4 Step 1, the migration-test helper in Task 4 Step 1, the `ProfileScreen.test.tsx` render helper and fixture names in Task 4 Step 6, and the `SourceDocument`/`select` imports in Task 5 Step 5. Each names exactly what to check.

**Type consistency.** `check_style(resume: ResumeDoc, cover_md: str) -> list[str]` is identical in Task 1's definition and its call sites in Tasks 2 and 3. `_voice_for` returns `(sample, notes)` in that order in Task 5, matching the argument order at the call site. `voice_notes` is `str` on the model with a `""` default, `Optional[str]` on the API body, `string` in TypeScript, and `str | None` at the `tailor_application` boundary — the conversion is the `or None` in `_voice_for`, which is deliberate so an empty string does not append an empty prompt section.

**Verified before planning, not assumed.** All 14 prose fields of the shipped `tailor.json`, cover letter included, are already clean against every rule in Task 1, so wiring the gate in breaks no existing test. `_column_ddl` was read to confirm a scalar string default produces `NOT NULL DEFAULT ''`, which is why Task 4 needs no migration code and why it warns against `default_factory`. `pipeline.py` was read to confirm there is no existing retry, that `verify_truthfulness` is monkeypatched as a module attribute, and that a single `_add_usage` call exists today that Task 3 must delete when it moves usage accumulation into the loop.
