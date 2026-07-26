from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db import get_engine, init_db
from backend.app.main import create_app


def test_setup_returns_running_interpreter_and_command(client):
    resp = client.get("/api/setup")
    assert resp.status_code == 200
    body = resp.json()
    assert body["python_path"] == sys.executable
    assert Path(body["mcp_server_path"]).name == "mcp_server.py"
    assert body["mcp_server_path"].replace("\\", "/").endswith("backend/mcp_server.py")
    assert body["mcp_command"].startswith("claude mcp add tailored -- ")
    assert f'"{sys.executable}"' in body["mcp_command"]
    assert body["platform"] in ("windows", "posix")
    assert body["env_line"] == "ANTHROPIC_API_KEY=sk-ant-..."
    assert body["workflow_guide_tool"] == "get_workflow_guide"
    assert isinstance(body["mcp_server_exists"], bool)


def test_setup_never_leaks_api_key(tmp_path):
    secret = "sk-ant-SECRET-should-not-appear-0000"
    settings = Settings(
        anthropic_api_key=secret,
        data_dir=tmp_path,
        fake_mode=False,
        host="127.0.0.1",
        port=8547,
    )
    engine = get_engine(tmp_path / "leak.db")
    init_db(engine)
    app = create_app(settings=settings, engine=engine)
    resp = TestClient(app).get("/api/setup")
    assert resp.status_code == 200
    assert secret not in resp.text
