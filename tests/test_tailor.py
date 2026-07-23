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
from backend.app.services.tailor import tailor_application

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
