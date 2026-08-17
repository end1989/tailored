"""The voice contract: mechanical style rules enforced on the write path.

The governing rule (spec section 4.4) is that we hard-fail only what has
near-zero legitimate use in a resume. A false positive blocks a truthful resume
and burns a retry, which is worse than an occasional stylistic miss.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.schemas import ResumeDoc, TailorResult
from backend.app.services.style import ALLOWED_WORDS, check_style

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


def test_a_character_violation_quotes_the_offending_text():
    """A character has no name of its own in the prose, so show where it sits."""
    violations = check_style(_with_bullet("Cut latency — by half"), "")
    assert "latency" in violations[0]


def test_curly_quotes_are_violations():
    """Quotation marks, not apostrophes: an intra-word U+2019 is allowed."""
    assert check_style(_with_bullet("Built the “fleet” service"), "")
    assert check_style(_with_bullet("Ran the ‘Ada’ migration"), "")


def test_a_curly_apostrophe_inside_a_word_is_allowed():
    """Spec 4.2 amendment: names and postings carry it, so rejecting it would
    block truthful text on every generation for that user or employer.
    """
    assert (
        check_style(_resume(), "I would like to work at Macy’s with O’Brien.")
        == []
    )


def test_curly_quotes_around_a_phrase_are_still_violations():
    assert check_style(_resume(), "the ‘fleet’ service")
    assert check_style(_with_bullet("Built the “fleet” service"), "")


def test_ellipsis_character_is_a_violation():
    assert check_style(_with_bullet("Shipped it… eventually"), "")


def test_emoji_is_a_violation():
    assert check_style(_with_bullet("Shipped the release \U0001F680"), "")


def test_symbols_outside_the_pictograph_block_are_violations():
    """The emoji families that live in the older, lower symbol blocks."""
    assert check_style(_with_bullet("Shipped the release \u2b50"), "")
    assert check_style(_with_bullet("Shipped the release \u23f0"), "")


def test_invisible_characters_are_violations():
    """Independently harmful: they corrupt ATS text extraction."""
    assert check_style(_with_bullet("Cut\u00a0latency by half"), "")
    assert check_style(_with_bullet("Cut\u200blatency by half"), "")


def test_unusual_space_characters_are_violations():
    assert check_style(_with_bullet("Cut\u202flatency by half"), "")
    assert check_style(_with_bullet("Cut\u00adlatency by half"), "")


def test_ordinary_ascii_punctuation_is_clean():
    """The widened character classes must not reach ASCII."""
    bullet = "Cut latency by 40% (p95), $2M ARR; see https://a.example/x?y=1&z=2"
    assert check_style(_with_bullet(bullet), "") == []


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


def test_delve_does_not_catch_a_surname_that_starts_the_same_way():
    """The rule lists the verb's forms, not every word beginning in delv."""
    assert check_style(_resume(), "Dear Ms. Delvecchio,") == []


def test_passionately_is_not_caught_by_the_passionate_about_rule():
    """Word-boundary matching, not substring matching."""
    assert check_style(_with_bullet("Worked passionately on the migration"), "") == []


def test_excited_openers_are_detected_in_the_cover_letter():
    assert check_style(_resume(), "I am excited to apply for this role.")
    assert check_style(_resume(), "I was excited to see this posting.")


def test_the_contracted_excited_opener_is_detected():
    """Both apostrophes, because the model writes either one."""
    assert check_style(_resume(), "I'm excited to apply.")
    assert check_style(_resume(), "I’m excited to apply.")


def test_in_todays_world_construction_is_detected():
    assert check_style(_resume(), "In today's fast-moving world, data matters.")
    assert check_style(_resume(), "In today's competitive landscape, speed wins.")
    assert check_style(_resume(), "In today\u2019s fast-moving world, data matters.")


# --- the anti-creep test -----------------------------------------------------


def test_legitimate_resume_vocabulary_is_not_banned():
    """Spec section 4.4. Every word here has real, common, pre-LLM resume use.

    Banning them would block truthful sentences and push the model toward
    stranger phrasing. This test exists to stop the ban list creeping, so it
    reads ALLOWED_WORDS itself: adding a word there without keeping it usable
    fails here.
    """
    for word in ALLOWED_WORDS:
        fragment = (
            "not only design but also drive"
            if word == "not only ... but also"
            else word
        )
        assert check_style(_with_bullet(f"Shipped the {fragment} work"), "") == [], word
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
