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
    "list_templates",
    "create_application",
    "save_parsed_posting",
    "save_research",
    "save_tailored_resume",
    "get_application",
}

POSTING_TEXT = (
    "Senior Backend Engineer at Northwind Labs. Python, FastAPI, PostgreSQL."
)


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


@pytest.mark.pdf
def test_mcp_server_full_flow_real_render(tmp_path):
    profile_id = _seed_profile(tmp_path)
    anyio.run(_flow, tmp_path, profile_id)
