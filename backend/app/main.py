"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .config import Settings, get_settings
from .db import get_engine, init_db
from .services.claude import make_claude


def create_app(settings: Settings | None = None, engine=None) -> FastAPI:
    settings = settings or get_settings()
    if engine is None:
        engine = get_engine(settings.data_dir / "tailored.db")
    init_db(engine)

    app = FastAPI(title="Tailored")
    app.state.settings = settings
    app.state.engine = engine
    app.state.claude = make_claude(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            f"http://{settings.host}:{settings.port}",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    return app
