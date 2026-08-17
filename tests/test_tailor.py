from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.schemas import (
    Contact,
    MasterProfile,
    MPExperience,
    ParsedPosting,
    ResearchFindings,
    TaggedBullet,
    TailorResult,
    UsageInfo,
)
from backend.app.services.claude import ClaudeService
from backend.app.services.tailor import tailor_application, verify_truthfulness

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


class RecordingClaude(ClaudeService):
    """Fake-mode ClaudeService that records every structured() call's kwargs."""

    def __init__(self, fixtures_dir: Path):
        super().__init__(fake_mode=True, fixtures_dir=fixtures_dir)

    def structured(self, *, task, system, user_content, schema_model,
                   tools=None, max_tokens=16000):
        result = super().structured(
            task=task, system=system, user_content=user_content,
            schema_model=schema_model, tools=tools, max_tokens=max_tokens,
        )
        self.calls[-1] = {
            "task": task,
            "system": system,
            "user_content": user_content,
            "schema_model": schema_model,
            "tools": tools,
            "max_tokens": max_tokens,
        }
        return result


@pytest.fixture()
def claude_fake() -> RecordingClaude:
    return RecordingClaude(FIXTURES_DIR)


CONTACT = Contact(name="Test Person", email="tp@example.com")

PROFILE = MasterProfile(
    summary_notes="Backend engineer, 8 years, Python and cloud infrastructure.",
    experiences=[
        MPExperience(
            company="Acme Robotics",
            title="Senior Backend Engineer",
            start="2021-03",
            end=None,
            location="Portland, OR",
            bullets=[
                TaggedBullet(
                    text="Built telemetry ingestion services in Python",
                    tags=["python", "backend"],
                )
            ],
        )
    ],
)

PARSED = ParsedPosting(
    title="Staff Engineer",
    company="Initech",
    company_domain="initech.example.com",
    must_haves=["Python", "PostgreSQL"],
    keywords=["Python", "FastAPI"],
)


def test_tailor_returns_result_and_records_one_call(claude_fake):
    result, usage = tailor_application(PROFILE, CONTACT, PARSED, None, "slate", claude_fake)
    assert isinstance(result, TailorResult)
    assert isinstance(usage, UsageInfo)
    assert len(claude_fake.calls) == 1
    call = claude_fake.calls[0]
    assert call["task"] == "tailor"
    assert call["schema_model"] is TailorResult
    assert call["max_tokens"] == 32000
    assert call["tools"] is None
    assert "TRUTHFULNESS RUBRIC" in call["system"]
    assert "NEVER invent employers" in call["system"]


def test_user_content_assembly_without_research(claude_fake):
    tailor_application(PROFILE, CONTACT, PARSED, None, "slate", claude_fake)
    uc = claude_fake.calls[-1]["user_content"]
    assert "MASTER PROFILE" in uc
    assert "Test Person" in uc
    assert "Acme Robotics" in uc
    assert "RESEARCH FINDINGS:\nnone" in uc
    assert "experience-first" in uc
    assert "REGENERATION FEEDBACK" not in uc


def test_terminal_template_gets_projects_forward_hint(claude_fake):
    tailor_application(PROFILE, CONTACT, PARSED, None, "terminal", claude_fake)
    assert "projects-forward" in claude_fake.calls[-1]["user_content"]


def test_research_findings_included_when_provided(claude_fake):
    findings = ResearchFindings(
        mission="Make warehouse robots reliable",
        sources=["https://initech.example.com/about"],
    )
    tailor_application(PROFILE, CONTACT, PARSED, findings, "slate", claude_fake)
    uc = claude_fake.calls[-1]["user_content"]
    assert "Make warehouse robots reliable" in uc
    assert "RESEARCH FINDINGS:\nnone" not in uc


def test_feedback_lands_in_user_content(claude_fake):
    tailor_application(
        PROFILE, CONTACT, PARSED, None, "slate", claude_fake,
        feedback="Lead with the migration project",
    )
    uc = claude_fake.calls[-1]["user_content"]
    assert "REGENERATION FEEDBACK" in uc
    assert "Lead with the migration project" in uc


def _load_intake(claude_fake):
    from backend.app.services.intake import IntakeResult

    intake, _usage = claude_fake.structured(
        task="intake", system="fixture-load", user_content="fixture-load",
        schema_model=IntakeResult,
    )
    return intake


def test_fixture_tailor_result_passes_truthfulness(claude_fake):
    intake = _load_intake(claude_fake)
    result, _usage = tailor_application(
        intake.master_profile, intake.contact, PARSED, None, "slate", claude_fake
    )
    assert verify_truthfulness(result.resume, intake.master_profile) == []


def test_single_changed_company_yields_exactly_one_violation(claude_fake):
    intake = _load_intake(claude_fake)
    result, _usage = tailor_application(
        intake.master_profile, intake.contact, PARSED, None, "slate", claude_fake
    )
    bad = result.resume.model_copy(deep=True)
    experience_sections = [s for s in bad.sections if s.type == "experience"]
    assert experience_sections and experience_sections[0].items
    experience_sections[0].items[0].company = "Fake Corp"
    violations = verify_truthfulness(bad, intake.master_profile)
    assert len(violations) == 1
    assert "Fake Corp" in violations[0]


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
