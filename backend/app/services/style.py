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
from dataclasses import dataclass

from ..schemas import ResumeDoc

# --- Characters --------------------------------------------------------------
#
# Each entry: (compiled pattern, human name, what to do instead).

BANNED_CHARACTERS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile("\u2014"),
        "em dash",
        "rewrite the sentence, or use a comma, colon or full stop",
    ),
    (
        # An en dash that does NOT sit directly between two digits. "2020-2023"
        # written with an en dash is correct typography and passes; "work - life"
        # does not. Stated precisely because the naive rule would reject a
        # truthful bullet like "Led the 2020-2023 platform migration".
        re.compile(r"(?<!\d)\u2013|\u2013(?!\d)"),
        "en dash outside a numeric range",
        "use a comma or rewrite; en dashes belong only between two years",
    ),
    (
        re.compile(
            "["
            "\U0001f000-\U0001faff"  # emoji and pictographs
            "\u2600-\u26ff"  # miscellaneous symbols
            "\u2700-\u27bf"  # dingbats
            "\u2300-\u23ff"  # miscellaneous technical
            "\u2b00-\u2bff"  # arrows and miscellaneous symbols
            "\u203c\u2049"  # double exclamation and exclamation-question
            "\ufe0f"  # variation selector, the emoji presentation marker
            "]"
        ),
        "emoji or pictograph",
        "remove it; there is no legitimate use in a resume or cover letter",
    ),
    (
        # Quotation marks, not apostrophes. A right single quotation mark
        # between two word characters is how Word spells Macy's and O'Brien,
        # so it arrives in names and postings; rejecting it would block
        # truthful text on every generation for that user or employer.
        re.compile("[\u201c\u201d\u2018]|(?<!\\w)\u2019|\u2019(?!\\w)"),
        "curly quote",
        "use a straight quote, which is always acceptable and never a tell",
    ),
    (
        re.compile("\u2026"),
        "ellipsis character",
        "use three periods, or better, finish the sentence",
    ),
    (
        re.compile("[\u00a0\u00ad\u2000-\u200f\u2028-\u202f\u205f-\u2064\u3000\ufeff]"),
        "invisible or unusual space character (non-breaking, zero-width, soft "
        "hyphen, and similar)",
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
        (
            # The verb's forms, not every word that starts with delv: a
            # surname such as Delvecchio is not a tell.
            r"\bdelv(?:e|es|ed|ing)\b",
            "use a plain verb such as studied, examined or read",
        ),
        (r"\btapestry\b", "use a plain noun"),
        (r"\bI am excited to\b", "open on a specific fact about the company or role"),
        (r"\bI was excited to\b", "open on a specific fact about the company or role"),
        (r"\bI['’]m excited to\b", "open on a specific fact about the company or role"),
        (
            r"\bin today[\u0027\u2019]s\b[^.!?]{0,40}\bworld\b",
            "cut the throat-clearing and open on the specific point",
        ),
        (
            r"\bin today[\u0027\u2019]s\b[^.!?]{0,40}\blandscape\b",
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


# --- Mechanical fixes --------------------------------------------------------
#
# The subset of the rules above that has exactly one correct answer, so the
# inline editor can offer to apply it. An em dash could become a comma, a colon
# or a full stop depending on the sentence, and a banned phrase needs a rewrite;
# neither belongs here. A curly quote has one straight equivalent and nothing
# else, which is the test for membership.
#
# The curly-quote entries repeat BANNED_CHARACTERS' apostrophe carve-out
# deliberately: a right single quotation mark between two word characters is
# how Word spells Macy's, it is never flagged, and so it must never be rewritten
# either.

MECHANICAL_FIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile("[\u201c\u201d]"), '"'),
    (re.compile("\u2018"), "'"),
    (re.compile(r"(?<!\w)\u2019|\u2019(?!\w)"), "'"),
    (re.compile("\u2026"), "..."),
    # Zero-width, directional and joining characters carry no space of
    # their own, so they are removed rather than replaced. Written as
    # escapes throughout: a literal invisible character in this file would
    # be unreviewable, and one of them is a line separator.
    (
        re.compile(
            "[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]"
        ),
        "",
    ),
    # The rest are ordinary spaces wearing a disguise.
    (
        re.compile(
            "[\u00a0\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]"
        ),
        " ",
    ),
)

MECHANICAL_RULES: frozenset[str] = frozenset(
    {
        "curly quote",
        "ellipsis character",
        "invisible or unusual space character (non-breaking, zero-width, soft "
        "hyphen, and similar)",
    }
)

PHRASE_RULE = "banned phrase"


@dataclass(frozen=True)
class StyleViolation:
    """One rule broken in one field.

    `path` addresses the field the same way the rendered edit markup does
    (data-edit-path), so the frontend can highlight the offending text where it
    sits. The cover letter is not part of the resume document and carries "".
    `message` is the sentence check_style has always returned.
    """

    field: str
    path: str
    rule: str
    excerpt: str
    advice: str
    mechanical: bool
    message: str


def _check_text(label: str, path: str, text: str) -> list[StyleViolation]:
    """Every rule violated by one piece of prose, each named and actionable."""
    if not text:
        return []
    found: list[StyleViolation] = []
    for pattern, name, advice in BANNED_CHARACTERS:
        match = pattern.search(text)
        if match:
            # A character has no name of its own in the prose, so quote where
            # it sits: the model has to find it before it can rewrite it.
            excerpt = text[max(0, match.start() - 15) : match.end() + 15]
            excerpt = excerpt.replace("\r", " ").replace("\n", " ")
            found.append(
                StyleViolation(
                    field=label,
                    path=path,
                    rule=name,
                    excerpt=excerpt,
                    advice=advice,
                    mechanical=name in MECHANICAL_RULES,
                    message=(
                        f"{label}: {name} near {excerpt!r}. "
                        f"{advice[0].upper()}{advice[1:]}."
                    ),
                )
            )
    for pattern, advice in BANNED_PHRASES:
        match = pattern.search(text)
        if match:
            found.append(
                StyleViolation(
                    field=label,
                    path=path,
                    rule=PHRASE_RULE,
                    excerpt=match.group(0),
                    advice=advice,
                    mechanical=False,
                    message=(
                        f"{label}: the phrase {match.group(0)!r} reads as "
                        f"machine-written. {advice[0].upper()}{advice[1:]}."
                    ),
                )
            )
    return found


def _prose_fields(resume: ResumeDoc, cover_md: str) -> list[tuple[str, str, str]]:
    """(label, path, text) for every field the model wrote as prose.

    Excluded on purpose: company, role, institution and credential names; start,
    end and year strings; URLs, email, phone and location; skill group labels
    and items. Those are facts carried from the master profile, and rejecting
    the user's own data would be a bug, not a feature.

    `path` addresses the field exactly as the rendered edit markup does, so a
    violation can be highlighted on the field it came from. The cover letter is
    not part of the resume document and carries "".
    """
    fields: list[tuple[str, str, str]] = [
        ("Headline", "headline", resume.headline),
        ("Summary", "summary", resume.summary),
    ]
    for si, section in enumerate(resume.sections):
        spath = f"sections.{si}"
        if section.type == "experience":
            for ii, item in enumerate(section.items):
                ipath = f"{spath}.items.{ii}"
                for i, bullet in enumerate(item.bullets, start=1):
                    fields.append(
                        (
                            f"Experience '{item.company}' bullet {i}",
                            f"{ipath}.bullets.{i - 1}",
                            bullet,
                        )
                    )
        elif section.type == "projects":
            for ii, item in enumerate(section.items):
                ipath = f"{spath}.items.{ii}"
                fields.append(
                    (
                        f"Project '{item.name}' description",
                        f"{ipath}.description",
                        item.description,
                    )
                )
                for i, bullet in enumerate(item.bullets, start=1):
                    fields.append(
                        (
                            f"Project '{item.name}' bullet {i}",
                            f"{ipath}.bullets.{i - 1}",
                            bullet,
                        )
                    )
        elif section.type == "education":
            for ii, item in enumerate(section.items):
                if item.detail:
                    fields.append(
                        (
                            f"Education '{item.credential}' detail",
                            f"{spath}.items.{ii}.detail",
                            item.detail,
                        )
                    )
        elif section.type == "extras":
            for i, entry in enumerate(section.items, start=1):
                fields.append((f"Extras item {i}", f"{spath}.items.{i - 1}", entry))
    fields.append(("Cover letter", "", cover_md))
    return fields


def style_report(resume: ResumeDoc, cover_md: str) -> list[StyleViolation]:
    """Every violation of the voice contract, addressed to the field it sits in.

    The structured form check_style is built from. The inline editor reads it to
    highlight offending text and to decide which violations it can offer to fix.
    """
    violations: list[StyleViolation] = []
    for label, path, text in _prose_fields(resume, cover_md):
        violations.extend(_check_text(label, path, text))
    return violations


def check_style(resume: ResumeDoc, cover_md: str) -> list[str]:
    """Human-readable violations of the voice contract. Empty list = clean.

    Mirrors verify_truthfulness's contract exactly, so both gates read the same
    way at their call sites.
    """
    return [violation.message for violation in style_report(resume, cover_md)]


def _clean_text(text: str) -> str:
    """Apply every fix in MECHANICAL_FIXES to one piece of prose."""
    for pattern, replacement in MECHANICAL_FIXES:
        text = pattern.sub(replacement, text)
    return text


def clean_mechanical(resume: ResumeDoc, cover_md: str) -> tuple[ResumeDoc, str]:
    """Fix the violations that have one right answer; leave the rest alone.

    Returns new objects: the caller's resume is never mutated. Reaches exactly
    the fields _prose_fields reads, so a fact carried from the master profile is
    never rewritten -- the truthfulness guard compares those verbatim, and a
    helpful substitution there would turn a valid resume into a rejected one.
    """
    cleaned = resume.model_copy(deep=True)
    cleaned.headline = _clean_text(cleaned.headline)
    cleaned.summary = _clean_text(cleaned.summary)
    for section in cleaned.sections:
        if section.type == "experience":
            for item in section.items:
                item.bullets = [_clean_text(b) for b in item.bullets]
        elif section.type == "projects":
            for item in section.items:
                item.description = _clean_text(item.description)
                item.bullets = [_clean_text(b) for b in item.bullets]
        elif section.type == "education":
            for item in section.items:
                if item.detail:
                    item.detail = _clean_text(item.detail)
        elif section.type == "extras":
            section.items = [_clean_text(entry) for entry in section.items]
    return cleaned, _clean_text(cover_md)
