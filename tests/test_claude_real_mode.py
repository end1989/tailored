"""Tests for backend/app/services/claude.py's real-mode path (_structured_real).

Uses a small in-test stub for the anthropic client - no real API calls, no network.
StubMessages.stream() records the kwargs it was called with and pops the next
canned message off a queue; StubStream mimics the `with client.messages.stream(...)
as stream:` context manager plus `get_final_message()`.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.app.schemas import ParsedPosting, UsageInfo
from backend.app.services.claude import (
    MODEL_ID,
    ClaudeError,
    ClaudeService,
    compute_cost,
)


def make_text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def make_message(
    *, stop_reason: str, content=None, input_tokens: int = 0, output_tokens: int = 0
) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content if content is not None else [],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class StubStream:
    """Context manager mimicking anthropic's MessageStreamManager."""

    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_final_message(self):
        return self._message


class StubMessages:
    """Stub for client.messages: records kwargs, pops canned messages off a queue."""

    def __init__(self, messages):
        self._queue = list(messages)
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        message = self._queue.pop(0)
        return StubStream(message)


def make_service(messages) -> tuple[ClaudeService, StubMessages]:
    """ClaudeService in real mode with its client swapped for a stub."""
    service = ClaudeService(api_key="test-key", fake_mode=False)
    stub_messages = StubMessages(messages)
    service._client = SimpleNamespace(messages=stub_messages)
    return service, stub_messages


VALID_POSTING = {
    "title": "Senior Backend Engineer",
    "company": "Northwind Labs",
    "company_domain": "northwindlabs.com",
    "must_haves": ["Python", "FastAPI"],
    "nice_to_haves": ["Kubernetes"],
    "keywords": ["backend", "api"],
    "seniority": "senior",
    "tone": "professional",
}


def test_happy_path_and_request_shape():
    message = make_message(
        stop_reason="end_turn",
        content=[make_text_block(json.dumps(VALID_POSTING))],
        input_tokens=1000,
        output_tokens=500,
    )
    service, stub_messages = make_service([message])

    parsed, usage = service.structured(
        task="parse_posting",
        system="You parse postings.",
        user_content="raw posting text here",
        schema_model=ParsedPosting,
    )

    assert parsed == ParsedPosting(**VALID_POSTING)
    assert usage == UsageInfo(
        input_tokens=1000,
        output_tokens=500,
        cost_usd=compute_cost(1000, 500),
    )

    assert len(stub_messages.calls) == 1
    kwargs = stub_messages.calls[0]
    assert kwargs["model"] == MODEL_ID == "claude-opus-4-8"
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "schema" in kwargs["output_config"]["format"]
    assert "max_tokens" in kwargs
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs
    assert kwargs["messages"] == [{"role": "user", "content": "raw posting text here"}]
    assert kwargs["messages"][0]["role"] == "user"
    assert all(m["role"] != "assistant" for m in kwargs["messages"])


def test_tools_passthrough():
    tools = [{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8}]
    message_a = make_message(
        stop_reason="end_turn",
        content=[make_text_block(json.dumps(VALID_POSTING))],
        input_tokens=10,
        output_tokens=10,
    )
    message_b = make_message(
        stop_reason="end_turn",
        content=[make_text_block(json.dumps(VALID_POSTING))],
        input_tokens=10,
        output_tokens=10,
    )
    service, stub_messages = make_service([message_a, message_b])

    service.structured(
        task="parse_posting",
        system="sys",
        user_content="u",
        schema_model=ParsedPosting,
        tools=tools,
    )
    assert stub_messages.calls[0]["tools"] == tools

    # claude.py only sets kwargs["tools"] when `tools` is truthy - `if tools:` -
    # so passing None omits the key entirely rather than sending tools=None.
    service.structured(
        task="parse_posting",
        system="sys",
        user_content="u",
        schema_model=ParsedPosting,
        tools=None,
    )
    assert "tools" not in stub_messages.calls[1]


def test_pause_turn_continuation():
    message1 = make_message(
        stop_reason="pause_turn",
        content=[make_text_block("partial thinking")],
        input_tokens=100,
        output_tokens=50,
    )
    message2 = make_message(
        stop_reason="end_turn",
        content=[make_text_block(json.dumps(VALID_POSTING))],
        input_tokens=200,
        output_tokens=75,
    )
    service, stub_messages = make_service([message1, message2])

    parsed, usage = service.structured(
        task="parse_posting",
        system="sys",
        user_content="raw text",
        schema_model=ParsedPosting,
    )

    assert len(stub_messages.calls) == 2
    second_kwargs = stub_messages.calls[1]
    assert second_kwargs["messages"] == [
        {"role": "user", "content": "raw text"},
        {"role": "assistant", "content": message1.content},
    ]
    assert usage == UsageInfo(
        input_tokens=300,
        output_tokens=125,
        cost_usd=compute_cost(300, 125),
    )
    assert parsed == ParsedPosting(**VALID_POSTING)


def test_pause_turn_cap_raises_claude_error():
    messages = [
        make_message(
            stop_reason="pause_turn",
            content=[make_text_block("still going")],
            input_tokens=1,
            output_tokens=1,
        )
        for _ in range(6)
    ]
    service, stub_messages = make_service(messages)

    with pytest.raises(ClaudeError) as exc_info:
        service.structured(
            task="parse_posting",
            system="sys",
            user_content="u",
            schema_model=ParsedPosting,
        )

    # 1 initial call + 5 continuations = 6 total attempts (MAX_PAUSE_TURN_CONTINUATIONS)
    assert len(stub_messages.calls) == 6
    assert "pause_turn" in str(exc_info.value)


def test_refusal_raises_claude_error_with_task_name():
    message = make_message(
        stop_reason="refusal", content=[], input_tokens=5, output_tokens=5
    )
    service, stub_messages = make_service([message])

    with pytest.raises(ClaudeError) as exc_info:
        service.structured(
            task="parse_posting",
            system="sys",
            user_content="u",
            schema_model=ParsedPosting,
        )

    assert "parse_posting" in str(exc_info.value)


def test_unparseable_json_raises_with_raw_text_snippet():
    message = make_message(
        stop_reason="end_turn",
        content=[make_text_block("not json{{{")],
        input_tokens=5,
        output_tokens=5,
    )
    service, stub_messages = make_service([message])

    with pytest.raises(ClaudeError) as exc_info:
        service.structured(
            task="parse_posting",
            system="sys",
            user_content="u",
            schema_model=ParsedPosting,
        )

    assert "not json{{{" in str(exc_info.value)


def test_no_text_block_raises_claude_error():
    message = make_message(
        stop_reason="end_turn", content=[], input_tokens=5, output_tokens=5
    )
    service, stub_messages = make_service([message])

    with pytest.raises(ClaudeError):
        service.structured(
            task="parse_posting",
            system="sys",
            user_content="u",
            schema_model=ParsedPosting,
        )
