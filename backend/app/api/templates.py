"""Template gallery routes: metadata for every registered template plus a live
HTML preview of each, rendered from the shared sample resume fixture."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..schemas import TailorResult
from ..services.render import TEMPLATE_REGISTRY, TEMPLATES, render_resume_html

router = APIRouter()

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# Built from the on-disk manifests, already ordered by their `order` field.
# `structure` and `order` stay internal: the UI has no use for either.
TEMPLATE_META: list[dict[str, str]] = [
    {
        "name": manifest.name,
        "label": manifest.label,
        "description": manifest.description,
        "best_for": manifest.best_for,
    }
    for manifest in TEMPLATE_REGISTRY.values()
]


@router.get("/templates")
def list_templates() -> list[dict[str, str]]:
    return TEMPLATE_META


@router.get("/templates/preview/{name}")
def preview_template(name: str) -> HTMLResponse:
    if name not in TEMPLATES:
        raise HTTPException(status_code=404, detail="unknown template")
    data = json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))
    resume = TailorResult.model_validate(data).resume
    return HTMLResponse(render_resume_html(resume, name))
