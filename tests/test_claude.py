"""Tests for backend/app/services/claude.py."""
from __future__ import annotations

from pydantic import BaseModel

from backend.app.schemas import ResumeDoc
from backend.app.services.claude import (
    COST_INPUT_PER_MTOK,
    COST_OUTPUT_PER_MTOK,
    compute_cost,
    strict_schema,
)


class _Inner(BaseModel):
    value: str


class _Outer(BaseModel):
    name: str
    inner: _Inner
    rows: list[_Inner]


def _assert_all_object_nodes_strict(node) -> None:
    """Recursively assert every JSON-schema object node has additionalProperties=False."""
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            assert node.get("additionalProperties") is False, (
                f"object node missing additionalProperties=False: {node}"
            )
        for value in node.values():
            _assert_all_object_nodes_strict(value)
    elif isinstance(node, list):
        for item in node:
            _assert_all_object_nodes_strict(item)


def test_cost_constants():
    assert COST_INPUT_PER_MTOK == 5.00
    assert COST_OUTPUT_PER_MTOK == 25.00


def test_compute_cost_exact():
    assert compute_cost(0, 0) == 0.0
    assert compute_cost(1_000_000, 0) == 5.0
    assert compute_cost(0, 1_000_000) == 25.0
    # 123,456 in @ $5/MTok = 0.61728; 78,900 out @ $25/MTok = 1.9725
    assert compute_cost(123_456, 78_900) == 2.58978


def test_compute_cost_rounds_six_decimals():
    # 7 input tokens -> 0.000035; 3 output tokens -> 0.000075; total 0.00011
    assert compute_cost(7, 3) == 0.00011
    assert compute_cost(1, 0) == 0.000005


def test_strict_schema_marks_top_level_nested_and_defs():
    schema = strict_schema(_Outer)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["_Inner"]["additionalProperties"] is False
    _assert_all_object_nodes_strict(schema)


def test_strict_schema_on_resumedoc_covers_all_defs():
    schema = strict_schema(ResumeDoc)
    assert schema["additionalProperties"] is False
    for def_schema in schema["$defs"].values():
        _assert_all_object_nodes_strict(def_schema)
    _assert_all_object_nodes_strict(schema)
