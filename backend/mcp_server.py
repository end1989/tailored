"""Tailored MCP server: any MCP-capable agent becomes the intelligence.

Exposes Tailored's write path as MCP tools over stdio so an agent (Claude
Code, Codex CLI, ...) can fetch and analyze postings itself, research, and
tailor - while Tailored's truthfulness guard is enforced server-side on every
resume save. No Anthropic API key is needed in this mode.

Runnable as a direct script from ANY working directory:

    <venv python> <abs path>/backend/mcp_server.py

Register with Claude Code (replace with your clone's absolute paths):

    claude mcp add tailored -- "<abs venv python>" "<abs path>/backend/mcp_server.py"
"""
from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import anyio.to_thread  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from backend import mcp_ops  # noqa: E402
from backend.app.config import get_settings  # noqa: E402
from backend.app.db import get_engine, init_db  # noqa: E402

_settings = get_settings()  # honors TAILORED_DATA_DIR from the env / .env
_engine = get_engine()      # <data_dir>/tailored.db
init_db(_engine)

mcp = FastMCP(
    "tailored",
    instructions=(
        "Tailored resume and cover-letter builder. Call get_workflow_guide "
        "FIRST - it explains the tool call order, the non-negotiable "
        "truthfulness contract, and the exact JSON shapes every tool expects."
    ),
)


async def _run(fn, /, *args):
    """Run a sync mcp_ops function in a worker thread.

    The installed mcp package (1.28.x) executes sync tools directly on the
    event loop (mcp.server.fastmcp.utilities.func_metadata calls the function
    inline), and export rendering uses Playwright's *sync* API, which refuses
    to run inside a running asyncio loop. Off-loading every tool body keeps
    Playwright (and SQLite I/O) off the loop.
    """
    return await anyio.to_thread.run_sync(partial(fn, *args))


@mcp.tool()
async def get_workflow_guide() -> str:
    """Call this FIRST, before any other Tailored tool. Returns the complete
    workflow guide: the order to call the tools in, the non-negotiable
    truthfulness contract (select/reorder/rephrase only - never invent), and
    the exact JSON schemas for the resume, parsed-posting, and research
    payloads, with a worked example."""
    return await _run(mcp_ops.get_workflow_guide)


@mcp.tool()
async def list_profiles() -> list[dict]:
    """List the candidate profiles stored in Tailored (id, name, and whether a
    master profile has been built). Call when get_master_profile reports that
    multiple profiles exist, or to check what is available."""
    return await _run(mcp_ops.list_profiles, _engine)


@mcp.tool()
async def get_master_profile(profile_id: int | None = None) -> dict:
    """Fetch a profile's contact info and master profile - the single source
    of truth containing every fact you may use when tailoring. Call this
    before tailoring anything. Omit profile_id when only one profile exists;
    with multiple profiles you get an error listing them so you can pick."""
    return await _run(mcp_ops.get_master_profile, _engine, profile_id)


@mcp.tool()
async def list_templates() -> list[dict]:
    """List the four resume templates (name, label, description, best_for).
    Call before create_application to choose deliberately: 'slate' is the safe
    default; 'terminal' is projects-forward for technical roles."""
    return await _run(mcp_ops.list_templates)


@mcp.tool()
async def create_application(
    profile_id: int, url: str, posting_text: str, template: str = "slate"
) -> dict:
    """Create a job application from a posting YOU gathered: browse/fetch the
    URL yourself (you can read login-walled postings) and pass the full posting
    text. Returns the application_id used by every later call. Next steps:
    save_parsed_posting, then save_tailored_resume."""
    return await _run(
        mcp_ops.create_application, _engine, profile_id, url, posting_text, template
    )


@mcp.tool()
async def save_parsed_posting(application_id: int, parsed: dict) -> dict:
    """Save your structured analysis of the posting as ParsedPosting JSON
    (title, company, company_domain, must_haves, nice_to_haves, keywords,
    seniority, tone - see get_workflow_guide for the schema). Call this right
    after create_application; the dashboard shows company/title from it."""
    return await _run(mcp_ops.save_parsed_posting, _engine, application_id, parsed)


@mcp.tool()
async def save_research(application_id: int, findings: dict) -> dict:
    """Optionally save company research you performed as ResearchFindings JSON
    (mission, products, news, tech_stack_signals, culture_language, sources).
    Call between save_parsed_posting and save_tailored_resume when you have
    researched the company - the cover letter should then open with a concrete
    finding."""
    return await _run(mcp_ops.save_research, _engine, application_id, findings)


@mcp.tool()
async def save_tailored_resume(
    application_id: int,
    resume: dict,
    cover_letter_md: str,
    tailoring_notes: str = "",
) -> dict:
    """The final, truthfulness-gated write. Save the tailored resume (ResumeDoc
    JSON - schema in get_workflow_guide) plus the cover letter (markdown);
    Tailored then renders and exports PDF, HTML, and ATS text. The resume is
    verified server-side against the master profile: any experience, education,
    or certification entry not present in the master profile is rejected and
    you receive the exact violation list - correct the resume to use only
    entries from the master profile and call this tool again. On success
    returns status 'ready' with the export directory and files."""
    return await _run(
        mcp_ops.save_tailored_resume,
        _engine,
        _settings.data_dir,
        application_id,
        resume,
        cover_letter_md,
        tailoring_notes,
    )


@mcp.tool()
async def get_application(application_id: int) -> dict:
    """Check an application's state: status (tailoring / rendering / ready /
    error), version, error_message, and the exported files. Call after
    save_tailored_resume to confirm 'ready', or any time to inspect progress."""
    return await _run(mcp_ops.get_application, _engine, application_id)


if __name__ == "__main__":
    mcp.run()  # stdio transport
