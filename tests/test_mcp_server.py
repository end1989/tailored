"""Integration test for backend/mcp_server.py: real stdio subprocess, real
Playwright render (marked pdf).

The SQLite database is pre-created in tmp_path with a profile seeded from the
intake fixture, then the server is spawned with TAILORED_DATA_DIR pointing at
tmp_path (TAILORED_FAKE unset) and driven through the full workflow via the
official MCP client. The final save runs the real Chromium PDF export, which
also proves the tool body executes off the event loop (Playwright's sync API
refuses to run on a running asyncio loop).
"""
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from sqlmodel import Session

from backend.app.db import get_engine, init_db
from backend.app.models import Profile, set_contact, set_master_profile
from backend.app.services.claude import ClaudeService
from backend.app.services.intake import IntakeResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = PROJECT_ROOT / "backend" / "app" / "fixtures"
SERVER_PATH = PROJECT_ROOT / "backend" / "mcp_server.py"

EXPECTED_TOOLS = {
    "get_workflow_guide",
    "list_profiles",
    "get_master_profile",
    "add_profile_evidence",
    "list_templates",
    "create_application",
    "queue_jobs",
    "next_pending_job",
    "report_fetch_blocked",
    "save_parsed_posting",
    "save_research",
    "save_tailored_resume",
    "set_application_template",
    "get_application",
}

POSTING_TEXT = (
    "Senior Backend Engineer at Northwind Labs. Python, FastAPI, PostgreSQL."
)

QUEUE_URLS = [
    "https://jobs.example.com/queue-1",
    "https://jobs.example.com/queue-2",
]


def _tool_docstrings() -> dict[str, str]:
    """Docstrings of the module-level @mcp.tool functions, from the source.

    Parsed with ast rather than imported: importing backend/mcp_server.py runs
    its module-level engine/database setup against the real data directory.
    FastMCP serves each docstring verbatim as the tool's description, which is
    what the connected agent actually reads (the description channel is
    asserted end-to-end in the pdf-marked flow test below)."""
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    return {
        node.name: ast.get_docstring(node) or ""
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }


def test_escalation_ladder_survives_in_the_tool_docstrings():
    """The design puts the fetch ladder in the tool DOCSTRINGS as well as the
    guide, because agents read tool descriptions far more reliably than they
    re-read a guide fetched once at the start of a long run. Stripping this
    wording would silently remove the more reliable channel, so pin it."""
    docs = _tool_docstrings()

    create = docs["create_application"]
    for needle in (
        "403",
        "bot check",
        "login wall",
        "400 characters",
        "user's own browser",
        "disguise automated traffic",
        "queue_jobs(profile_id, [url])",
        "report_fetch_blocked",
    ):
        assert needle in create, f"create_application docstring lost {needle!r}"

    blocked = docs["report_fetch_blocked"]
    for needle in (
        "direct fetch",
        "user's own browser",
        "403",
        "bot check",
        "login wall",
        "needs_paste",
        "queue_jobs(profile_id, [url])",
    ):
        assert needle in blocked, f"report_fetch_blocked docstring lost {needle!r}"

    queue = docs["queue_jobs"]
    for needle in ("next_pending_job", "refuses", "save_tailored_resume"):
        assert needle in queue, f"queue_jobs docstring lost {needle!r}"

    nxt = docs["next_pending_job"]
    for needle in ("null", "queue_jobs", "save_tailored_resume"):
        assert needle in nxt, f"next_pending_job docstring lost {needle!r}"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _seed_profile(data_dir: Path) -> int:
    """Pre-create <data_dir>/tailored.db with one profile from the intake fixture."""
    claude = ClaudeService(fake_mode=True, fixtures_dir=FIXTURES_DIR)
    intake, _usage = claude.structured(
        task="intake", system="seed", user_content="seed", schema_model=IntakeResult
    )
    engine = get_engine(data_dir / "tailored.db")
    init_db(engine)
    with Session(engine) as session:
        profile = Profile(name="Integration User")
        set_contact(profile, intake.contact)
        set_master_profile(profile, intake.master_profile)
        session.add(profile)
        session.commit()
        session.refresh(profile)
        profile_id = profile.id
    engine.dispose()
    return profile_id


def _payload(result) -> dict:
    """Extract a tool result's dict payload (structured or JSON text content)."""
    assert not result.isError, f"tool error: {result.content}"
    structured = getattr(result, "structuredContent", None)
    if structured:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured
    return json.loads(result.content[0].text)


async def _flow(tmp_path: Path, profile_id: int) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {k: v for k, v in os.environ.items() if k != "TAILORED_FAKE"}
    env["TAILORED_DATA_DIR"] = str(tmp_path)
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        env=env,
        cwd=str(tmp_path),  # prove the script runs from any cwd
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == EXPECTED_TOOLS

            # The docstrings must actually cross the protocol as the served
            # tool descriptions - the channel agents read most reliably.
            described = {t.name: (t.description or "") for t in tools.tools}
            assert "bot check" in described["create_application"]
            assert "report_fetch_blocked" in described["create_application"]
            assert "needs_paste" in described["report_fetch_blocked"]
            assert "null" in described["next_pending_job"]

            guide = await session.call_tool("get_workflow_guide", {})
            assert not guide.isError
            guide_text = guide.content[0].text
            assert "NEVER invent" in guide_text
            assert '"additionalProperties"' in guide_text

            master = _payload(await session.call_tool("get_master_profile", {}))
            assert master["profile_id"] == profile_id
            assert master["master_profile"]["experiences"]

            created = _payload(
                await session.call_tool(
                    "create_application",
                    {
                        "profile_id": profile_id,
                        "url": "https://jobs.example.com/senior-backend",
                        "posting_text": POSTING_TEXT,
                    },
                )
            )
            app_id = created["application_id"]
            assert created["status"] == "tailoring"

            parsed = _payload(
                await session.call_tool(
                    "save_parsed_posting",
                    {"application_id": app_id, "parsed": _fixture("parse_posting")},
                )
            )
            assert parsed["company"] == "Northwind Labs"

            tailor = _fixture("tailor")
            saved = _payload(
                await session.call_tool(
                    "save_tailored_resume",
                    {
                        "application_id": app_id,
                        "resume": tailor["resume"],
                        "cover_letter_md": tailor["cover_letter_md"],
                        "tailoring_notes": tailor.get("tailoring_notes", ""),
                    },
                )
            )
            assert saved["status"] == "ready"
            assert saved["version"] == 1

            detail = _payload(
                await session.call_tool(
                    "get_application", {"application_id": app_id}
                )
            )
            assert detail["status"] == "ready"
            assert "resume.pdf" in detail["files"]

            pdf_path = Path(saved["export_dir"]) / "resume.pdf"
            assert pdf_path.read_bytes().startswith(b"%PDF")

            # --- the batch-queue trio, through the same protocol layer ---
            # queue_jobs / next_pending_job / report_fetch_blocked cross
            # FastMCP's argument and result (de)serialization here, not just
            # the plain-Python layer test_mcp_ops.py exercises.
            queued = _payload(
                await session.call_tool(
                    "queue_jobs",
                    {"profile_id": profile_id, "urls": QUEUE_URLS},
                )
            )
            assert [q["status"] for q in queued] == ["not_started", "not_started"]

            first = _payload(
                await session.call_tool(
                    "next_pending_job", {"profile_id": profile_id}
                )
            )
            assert first == {
                "application_id": queued[0]["application_id"],
                "url": QUEUE_URLS[0],
            }

            blocked = _payload(
                await session.call_tool(
                    "report_fetch_blocked",
                    {
                        "application_id": first["application_id"],
                        "reason": "403 and a bot check",
                    },
                )
            )
            assert blocked["fetch_status"] == "blocked"
            assert blocked["status"] == "needs_paste"

            # Blocking the first job must advance the queue to the second.
            second = _payload(
                await session.call_tool(
                    "next_pending_job", {"profile_id": profile_id}
                )
            )
            assert second == {
                "application_id": queued[1]["application_id"],
                "url": QUEUE_URLS[1],
            }

            blocked2 = _payload(
                await session.call_tool(
                    "report_fetch_blocked",
                    {
                        "application_id": second["application_id"],
                        "reason": "login wall",
                    },
                )
            )
            assert blocked2["status"] == "needs_paste"

            # The empty queue crosses the wire as a null result - the exact
            # condition the guide tells the agent to terminate the loop on.
            empty = await session.call_tool(
                "next_pending_job", {"profile_id": profile_id}
            )
            assert not empty.isError, f"tool error: {empty.content}"
            assert empty.structuredContent == {"result": None}
            assert _payload(empty) is None


@pytest.mark.pdf
def test_mcp_server_full_flow_real_render(tmp_path):
    profile_id = _seed_profile(tmp_path)
    anyio.run(_flow, tmp_path, profile_id)
