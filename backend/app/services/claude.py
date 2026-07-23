"""Claude API wrapper: structured outputs, fake mode, usage/cost tracking."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

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
