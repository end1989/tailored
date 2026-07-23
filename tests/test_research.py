from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.schemas import ParsedPosting, ResearchFindings, UsageInfo
from backend.app.services.claude import ClaudeService
from backend.app.services.research import parse_posting

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
