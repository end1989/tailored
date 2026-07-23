"""FastAPI application factory: API routes, demo seeding, SPA static serving."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from . import demo
from .api import api_router
from .config import Settings, get_settings
from .db import get_engine, init_db
from .services.claude import make_claude

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(settings: Settings | None = None, engine=None) -> FastAPI:
    settings = settings or get_settings()
    if engine is None:
        engine = get_engine(settings.data_dir / "tailored.db")
    init_db(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.fake_mode:
            demo.seed_demo(engine, app.state.claude, settings.data_dir)
        yield

    app = FastAPI(title="Tailored", lifespan=lifespan)
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

    # SPA static serving with fallback. Registered AFTER api_router, so every
    # /api/* route resolves first; unknown /api paths 404 instead of serving HTML.
    @app.get("/{path:path}")
    def serve_spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        dist = FRONTEND_DIST.resolve()
        if dist.is_dir():
            if path:
                candidate = (dist / path).resolve()
                # Serve real build assets; refuse path traversal outside dist.
                if candidate.is_file() and str(candidate).startswith(str(dist)):
                    return FileResponse(candidate)
            index = dist / "index.html"
            if index.is_file():
                return FileResponse(index)
        return PlainTextResponse("frontend not built", status_code=200)

    return app
