"""Demo-mode seeding and SPA serving tests (Task 13). Fully offline."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from backend.app import config
from backend.app.config import Settings
from backend.app.db import get_engine, session_scope
from backend.app.main import create_app
from backend.app.models import Application, Profile
from backend.app.services import render


@pytest.fixture
def demo_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILORED_FAKE", "1")
    monkeypatch.setenv("TAILORED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # The pipeline may consult the cached settings accessor internally; make sure
    # it re-reads the env vars set above.
    if hasattr(config.get_settings, "cache_clear"):
        config.get_settings.cache_clear()
    # Skip Chromium for speed; the demo path must survive render_pdf failure anyway.
    monkeypatch.setattr(
        render,
        "render_pdf",
        lambda html, out_path, page_size="Letter": Path(out_path).write_bytes(
            b"%PDF-1.4\n%test"
        ),
    )
    settings = Settings()
    engine = get_engine(tmp_path / "demo.db")
    return settings, engine


def test_startup_seeds_demo_and_reaches_ready(demo_env):
    settings, engine = demo_env
    app = create_app(settings=settings, engine=engine)
    with TestClient(app) as client:  # context manager -> lifespan/startup runs
        profiles = client.get("/api/profiles").json()
        assert len(profiles) == 1
        assert profiles[0]["has_master_profile"] is True

        apps = client.get("/api/applications").json()
        assert len(apps) == 1
        assert apps[0]["status"] == "ready"
        assert apps[0]["company"] == "Northwind Labs"

        detail = client.get(f"/api/applications/{apps[0]['id']}").json()
        assert detail["resume"] is not None
        assert detail["cover_letter_md"]
        assert detail["raw_text_present"] is True


def test_second_startup_does_not_duplicate(demo_env):
    settings, engine = demo_env
    with TestClient(create_app(settings=settings, engine=engine)):
        pass
    with TestClient(create_app(settings=settings, engine=engine)):
        pass
    with session_scope(engine) as session:
        assert len(session.exec(select(Profile)).all()) == 1
        assert len(session.exec(select(Application)).all()) == 1


def test_spa_fallback_and_api_passthrough(demo_env):
    settings, engine = demo_env
    app = create_app(settings=settings, engine=engine)
    with TestClient(app) as client:
        page = client.get("/applications/1")   # SPA route -> index.html
        assert page.status_code == 200
        assert "Tailored" in page.text

        root = client.get("/")                 # root also serves index.html
        assert root.status_code == 200
        assert "Tailored" in root.text

        assert client.get("/api/nope").status_code == 404  # api never falls back
