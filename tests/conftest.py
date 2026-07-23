from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.app.config import Settings
from backend.app.db import get_engine, init_db
from backend.app.main import create_app


@pytest.fixture()
def engine(tmp_path):
    """Fresh tmp SQLite file with all registered tables created."""
    eng = get_engine(tmp_path / "test.db")
    init_db(eng)
    return eng


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture()
def db_session(session):
    """Contract alias for the `session` fixture."""
    return session


@pytest.fixture()
def fake_settings(tmp_path):
    """Settings isolated from the environment: tmp data_dir, fake mode on."""
    return Settings(
        anthropic_api_key=None,
        data_dir=tmp_path,
        fake_mode=True,
        host="127.0.0.1",
        port=8547,
    )


@pytest.fixture()
def app(engine, fake_settings):
    return create_app(settings=fake_settings, engine=engine)


@pytest.fixture()
def client(app):
    return TestClient(app)


from pathlib import Path

import pytest

from backend.app.services.claude import ClaudeService

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


@pytest.fixture
def claude_fake() -> ClaudeService:
    """Fixture-backed ClaudeService; never touches the network."""
    return ClaudeService(fake_mode=True, fixtures_dir=FIXTURES_DIR)
