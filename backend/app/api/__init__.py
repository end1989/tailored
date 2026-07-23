"""API router aggregation. All routes live under the /api prefix."""
from __future__ import annotations

from fastapi import APIRouter

from . import applications, profiles, settings

api_router = APIRouter(prefix="/api")


@api_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


api_router.include_router(profiles.router)
api_router.include_router(applications.router)
api_router.include_router(settings.router)
