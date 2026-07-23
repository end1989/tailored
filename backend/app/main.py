from __future__ import annotations

from fastapi import FastAPI

from .config import Settings, get_settings
from .db import get_engine, init_db


def create_app(settings: Settings | None = None, engine=None) -> FastAPI:
    """App factory. `settings`/`engine` are injectable for tests; defaults
    come from the environment (get_settings) and data_dir/tailored.db."""
    settings = settings if settings is not None else get_settings()
    app = FastAPI(title="Tailored")
    app.state.settings = settings
    app.state.engine = (
        engine if engine is not None else get_engine(settings.data_dir / "tailored.db")
    )
    init_db(app.state.engine)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
