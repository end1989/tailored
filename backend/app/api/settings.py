"""Settings routes: read/write user defaults, report API-key and fake-mode status."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import load_user_settings, save_user_settings
from ..services.render import TEMPLATES

router = APIRouter()

DEPTHS = ("quick", "standard", "deep")
PAGE_SIZES = ("Letter", "A4")


class SettingsUpdate(BaseModel):
    default_template: Optional[str] = None
    default_depth: Optional[str] = None
    page_size: Optional[str] = None


def _settings_payload(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    user = load_user_settings(settings.data_dir)
    return {
        "api_key_set": bool(settings.anthropic_api_key),
        "fake_mode": settings.fake_mode,
        "default_template": user.get("default_template", "slate"),
        "default_depth": user.get("default_depth", "standard"),
        "page_size": user.get("page_size", "Letter"),
    }


@router.get("/settings")
def read_settings(request: Request) -> dict[str, Any]:
    return _settings_payload(request)


@router.put("/settings")
def write_settings(body: SettingsUpdate, request: Request) -> dict[str, Any]:
    if body.default_template is not None and body.default_template not in TEMPLATES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid template {body.default_template!r}; must be one of {list(TEMPLATES)}",
        )
    if body.default_depth is not None and body.default_depth not in DEPTHS:
        raise HTTPException(
            status_code=422,
            detail=f"invalid depth {body.default_depth!r}; must be one of {list(DEPTHS)}",
        )
    if body.page_size is not None and body.page_size not in PAGE_SIZES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid page size {body.page_size!r}; must be one of {list(PAGE_SIZES)}",
        )
    settings = request.app.state.settings
    current = load_user_settings(settings.data_dir)
    for key in ("default_template", "default_depth", "page_size"):
        value = getattr(body, key)
        if value is not None:
            current[key] = value
    save_user_settings(settings.data_dir, current)
    return _settings_payload(request)
