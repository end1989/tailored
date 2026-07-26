"""Setup route: read-only environment info for the in-app Getting Started guide.

Emits the exact, OS-aware `claude mcp add` command (paths taken from the running
interpreter and the project root) so users never hand-substitute paths. Never
returns the Anthropic API key value.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from ..config import PROJECT_ROOT

router = APIRouter()

ENV_LINE_TEMPLATE = "ANTHROPIC_API_KEY=sk-ant-..."


@router.get("/setup")
def read_setup() -> dict[str, Any]:
    python_path = sys.executable
    mcp_server_path = str(PROJECT_ROOT / "backend" / "mcp_server.py")
    platform = "windows" if os.name == "nt" else "posix"
    mcp_command = f'claude mcp add tailored -- "{python_path}" "{mcp_server_path}"'
    return {
        "platform": platform,
        "python_path": python_path,
        "mcp_server_path": mcp_server_path,
        "mcp_server_exists": Path(mcp_server_path).exists(),
        "mcp_command": mcp_command,
        "env_line": ENV_LINE_TEMPLATE,
        "workflow_guide_tool": "get_workflow_guide",
    }
