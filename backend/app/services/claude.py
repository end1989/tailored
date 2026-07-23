"""Claude API wrapper: structured outputs, fake mode, usage/cost tracking.

All Claude traffic in the app goes through ClaudeService.structured().
fake_mode loads canned JSON fixtures (tests + offline demo mode) and records
every call on .calls so tests can assert on prompts/tools.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..schemas import UsageInfo

MODEL_ID = "claude-opus-4-8"
COST_INPUT_PER_MTOK = 5.00
COST_OUTPUT_PER_MTOK = 25.00
MAX_PAUSE_TURN_CONTINUATIONS = 5


def compute_cost(input_tokens: int, output_tokens: int) -> float:
    """USD cost for a call at Opus 4.8 rates, rounded to 6 decimal places."""
    return round(
        input_tokens / 1e6 * COST_INPUT_PER_MTOK
        + output_tokens / 1e6 * COST_OUTPUT_PER_MTOK,
        6,
    )


def _mark_objects_strict(node: Any) -> None:
    """Recursively add additionalProperties: false to every object node ($defs included)."""
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            node["additionalProperties"] = False
        for value in list(node.values()):
            _mark_objects_strict(value)
    elif isinstance(node, list):
        for item in node:
            _mark_objects_strict(item)


def strict_schema(model_cls: type[BaseModel]) -> dict:
    """model_json_schema() with additionalProperties: false injected at every object level."""
    schema = model_cls.model_json_schema()
    _mark_objects_strict(schema)
    return schema


class ClaudeError(Exception):
    """Raised on refusals, unparseable output, missing fixtures, or exhausted continuations."""


class ClaudeService:
    """Wrapper around the Anthropic client with a fixture-backed fake mode.

    .calls records every structured() invocation (both modes) as
    {"task", "system", "user_content", "tools", "schema_model_name"}
    so tests can assert on exactly what would be sent to the API.
    """

    def __init__(
        self,
        api_key: str | None = None,
        fake_mode: bool = False,
        fixtures_dir: Path | None = None,
    ) -> None:
        self.api_key = api_key
        self.fake_mode = fake_mode
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir is not None else None
        self.calls: list[dict] = []
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise ClaudeError(
                    "No API key set - add ANTHROPIC_API_KEY to .env and restart the app"
                )
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def structured(
        self,
        *,
        task: str,
        system: str,
        user_content: str,
        schema_model: type[BaseModel],
        tools: list[dict] | None = None,
        max_tokens: int = 16000,
    ) -> tuple[BaseModel, UsageInfo]:
        self.calls.append(
            {
                "task": task,
                "system": system,
                "user_content": user_content,
                "tools": tools,
                "schema_model_name": schema_model.__name__,
            }
        )
        if self.fake_mode:
            return self._structured_fake(task=task, schema_model=schema_model)
        return self._structured_real(
            task=task,
            system=system,
            user_content=user_content,
            schema_model=schema_model,
            tools=tools,
            max_tokens=max_tokens,
        )

    def _structured_fake(
        self, *, task: str, schema_model: type[BaseModel]
    ) -> tuple[BaseModel, UsageInfo]:
        if self.fixtures_dir is None:
            raise ClaudeError("fake_mode requires fixtures_dir")
        fixture_path = self.fixtures_dir / f"{task}.json"
        if not fixture_path.exists():
            raise ClaudeError(f"[{task}] no fixture at {fixture_path}")
        raw = fixture_path.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ClaudeError(
                f"[{task}] fixture {fixture_path} is not valid JSON: {exc}"
            ) from exc
        try:
            model = schema_model.model_validate(payload)
        except ValidationError as exc:
            raise ClaudeError(
                f"[{task}] fixture {fixture_path} failed "
                f"{schema_model.__name__} validation: {exc}"
            ) from exc
        return model, UsageInfo(input_tokens=0, output_tokens=0, cost_usd=0.0)

    def _structured_real(
        self,
        *,
        task: str,
        system: str,
        user_content: str,
        schema_model: type[BaseModel],
        tools: list[dict] | None,
        max_tokens: int,
    ) -> tuple[BaseModel, UsageInfo]:
        import anthropic

        client = self._get_client()
        messages: list[dict] = [{"role": "user", "content": user_content}]
        total_input = 0
        total_output = 0
        message = None
        for _ in range(1 + MAX_PAUSE_TURN_CONTINUATIONS):
            kwargs: dict = {
                "model": MODEL_ID,
                "max_tokens": max_tokens,
                "system": system,
                "messages": messages,
                "thinking": {"type": "adaptive"},
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": strict_schema(schema_model),
                    }
                },
            }
            if tools:
                kwargs["tools"] = tools
            try:
                with client.messages.stream(**kwargs) as stream:
                    message = stream.get_final_message()
            except anthropic.RateLimitError as exc:
                raise ClaudeError(
                    f"[{task}] Anthropic rate limit reached - wait a minute "
                    f"and retry ({exc})"
                ) from exc
            except anthropic.APIConnectionError as exc:
                raise ClaudeError(
                    f"[{task}] could not reach the Anthropic API - check "
                    f"your network ({exc})"
                ) from exc
            except anthropic.APIStatusError as exc:
                raise ClaudeError(
                    f"[{task}] Anthropic API error "
                    f"(HTTP {exc.status_code}) - {exc.message}"
                ) from exc
            total_input += message.usage.input_tokens
            total_output += message.usage.output_tokens
            if message.stop_reason == "pause_turn":
                messages = messages + [
                    {"role": "assistant", "content": message.content}
                ]
                continue
            break
        if message is None:
            raise ClaudeError(f"[{task}] no response from API")
        if message.stop_reason == "pause_turn":
            raise ClaudeError(
                f"[{task}] still pause_turn after "
                f"{MAX_PAUSE_TURN_CONTINUATIONS} continuations"
            )
        if message.stop_reason == "refusal":
            raise ClaudeError(f"[{task}] model refused (stop_reason=refusal)")
        text = ""
        for block in message.content:
            if getattr(block, "type", None) == "text":
                text = block.text
        if not text:
            raise ClaudeError(
                f"[{task}] response contained no text block "
                f"(stop_reason={message.stop_reason})"
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClaudeError(
                f"[{task}] response was not valid JSON: {exc}; "
                f"raw text: {text[:2000]}"
            ) from exc
        try:
            model = schema_model.model_validate(payload)
        except ValidationError as exc:
            raise ClaudeError(
                f"[{task}] response failed {schema_model.__name__} "
                f"validation: {exc}; raw text: {text[:2000]}"
            ) from exc
        usage = UsageInfo(
            input_tokens=total_input,
            output_tokens=total_output,
            cost_usd=compute_cost(total_input, total_output),
        )
        return model, usage


def make_claude(settings) -> ClaudeService:
    """Factory honoring Settings.fake_mode; fixtures always at backend/app/fixtures."""
    fixtures_dir = Path(__file__).resolve().parents[1] / "fixtures"
    if getattr(settings, "fake_mode", False):
        return ClaudeService(fake_mode=True, fixtures_dir=fixtures_dir)
    return ClaudeService(
        api_key=getattr(settings, "anthropic_api_key", None),
        fake_mode=False,
        fixtures_dir=fixtures_dir,
    )
