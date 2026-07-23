from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.schemas import ParsedPosting, ResearchFindings, UsageInfo
from backend.app.services.claude import ClaudeService
from backend.app.services.research import parse_posting, research_company

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


RAW_POSTING = (
    "Senior Backend Engineer\n"
    "Acme Robotics - Portland, OR (hybrid)\n\n"
    "Acme Robotics builds fleet telemetry for warehouse robots. We are hiring a "
    "Senior Backend Engineer to own our ingestion pipeline.\n\n"
    "Requirements: 5+ years Python, FastAPI or Django, PostgreSQL, AWS.\n"
    "Nice to have: Kubernetes, Terraform, Kafka.\n"
    "Visit https://acmerobotics.example.com for more.\n"
)


def test_parse_posting_returns_fixture_and_records_call(claude_fake):
    parsed, usage = parse_posting(RAW_POSTING, claude_fake)
    assert isinstance(parsed, ParsedPosting)
    assert parsed.title
    assert parsed.company
    assert isinstance(usage, UsageInfo)
    assert usage.input_tokens == 0 and usage.output_tokens == 0
    assert len(claude_fake.calls) == 1
    call = claude_fake.calls[0]
    assert call["task"] == "parse_posting"
    assert call["user_content"] == RAW_POSTING
    assert call["schema_model"] is ParsedPosting
    assert call["tools"] is None


PARSED = ParsedPosting(
    title="Senior Backend Engineer",
    company="Acme Robotics",
    company_domain="acmerobotics.example.com",
    must_haves=["5+ years Python", "PostgreSQL"],
    nice_to_haves=["Kubernetes"],
    keywords=["Python", "FastAPI", "AWS"],
    seniority="senior",
    tone="casual startup",
)


def test_quick_returns_none_with_zero_calls(claude_fake):
    assert research_company(PARSED, "quick", claude_fake) is None
    assert claude_fake.calls == []


def test_standard_uses_single_web_fetch_tool_with_allowed_domains(claude_fake):
    result = research_company(PARSED, "standard", claude_fake)
    assert result is not None
    findings, usage = result
    assert isinstance(findings, ResearchFindings)
    assert isinstance(usage, UsageInfo)
    assert len(claude_fake.calls) == 1
    call = claude_fake.calls[0]
    assert call["task"] == "research_standard"
    assert call["schema_model"] is ResearchFindings
    assert isinstance(call["tools"], list) and len(call["tools"]) == 1
    tool = call["tools"][0]
    assert tool["type"] == "web_fetch_20260209"
    assert tool["name"] == "web_fetch"
    assert tool["max_uses"] == 8
    assert tool["allowed_domains"] == ["acmerobotics.example.com"]
    assert "https://acmerobotics.example.com" in call["user_content"]


def test_standard_without_domain_omits_allowed_domains(claude_fake):
    parsed = PARSED.model_copy(update={"company_domain": None})
    result = research_company(parsed, "standard", claude_fake)
    assert result is not None
    tool = claude_fake.calls[0]["tools"][0]
    assert "allowed_domains" not in tool


def test_deep_uses_search_then_fetch_tools(claude_fake):
    result = research_company(PARSED, "deep", claude_fake)
    assert result is not None
    findings, _usage = result
    assert isinstance(findings, ResearchFindings)
    call = claude_fake.calls[0]
    assert call["task"] == "research_deep"
    assert [t["type"] for t in call["tools"]] == [
        "web_search_20260209",
        "web_fetch_20260209",
    ]
    assert [t["max_uses"] for t in call["tools"]] == [8, 8]
