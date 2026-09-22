"""Settings routes: read/write user defaults, report API-key and fake-mode status.

Without `profile_id` these read and write the app-wide defaults in
data/settings.json. With `profile_id` they read that person's effective values
(the app-wide ones overlaid with the person's own) and write the person's own.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from ..config import load_user_settings, save_user_settings
from ..db import get_session
from ..models import (
    PROFILE_SETTING_KEYS,
    PROFILE_SETTING_VALUES,
    Profile,
    _utcnow,
    get_profile_settings,
    set_profile_settings,
)
from ..services.person_settings import settings_for
from ..services.render import TEMPLATES

router = APIRouter()

DEPTHS = PROFILE_SETTING_VALUES["default_depth"]
PAGE_SIZES = PROFILE_SETTING_VALUES["page_size"]


class SettingsUpdate(BaseModel):
    default_template: Optional[str] = None
    default_depth: Optional[str] = None
    page_size: Optional[str] = None


def _settings_payload(request: Request, profile: Profile | None = None) -> dict[str, Any]:
    settings = request.app.state.settings
    if profile is None:
        user = load_user_settings(settings.data_dir)
    else:
        user = settings_for(settings.data_dir, profile)
    return {
        "api_key_set": bool(settings.anthropic_api_key),
        "fake_mode": settings.fake_mode,
        "default_template": user.get("default_template", "slate"),
        "default_depth": user.get("default_depth", "standard"),
        "page_size": user.get("page_size", "Letter"),
    }


def _profile_or_404(session: Session, profile_id: Optional[int]) -> Profile | None:
    """None when no profile_id was given (the app-wide settings)."""
    if profile_id is None:
        return None
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return profile


@router.get("/settings")
def read_settings(
    request: Request,
    profile_id: Optional[int] = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    profile = _profile_or_404(session, profile_id)
    return _settings_payload(request, profile)


@router.put("/settings")
def write_settings(
    body: SettingsUpdate,
    request: Request,
    profile_id: Optional[int] = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    # An unknown person is a 404 before the body is judged: there is nothing
    # to write the values to, valid or not.
    profile = _profile_or_404(session, profile_id)
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
    if profile is not None:
        # Only the keys sent are stored as the person's own; the rest keep
        # following the app-wide file.
        changes = {
            key: getattr(body, key)
            for key in PROFILE_SETTING_KEYS
            if getattr(body, key) is not None
        }
        set_profile_settings(profile, {**get_profile_settings(profile), **changes})
        profile.updated_at = _utcnow()
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return _settings_payload(request, profile)
    settings = request.app.state.settings
    current = load_user_settings(settings.data_dir)
    for key in ("default_template", "default_depth", "page_size"):
        value = getattr(body, key)
        if value is not None:
            current[key] = value
    save_user_settings(settings.data_dir, current)
    return _settings_payload(request)
