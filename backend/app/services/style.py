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
            r"\bin today[‘’]s\b[^.!?]{0,40}\bworld\b",
            "cut the throat-clearing and open on the specific point",
        ),
        (
            r"\bin today[‘’]s\b[^.!?]{0,40}\blandscape\b",
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
