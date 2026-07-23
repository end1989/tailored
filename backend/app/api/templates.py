"""Template gallery routes: metadata for all four templates plus a live HTML
preview of each, rendered from the shared sample resume fixture."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..schemas import TailorResult
from ..services.render import TEMPLATES, render_resume_html

router = APIRouter()

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

_METADATA: dict[str, dict[str, str]] = {
    "meridian": {
        "label": "Meridian",
        "description": (
            "Classic serif with small caps and hairline rules - understated and traditional."
        ),
        "best_for": "Corporate, finance, healthcare, government",
    },
    "slate": {
        "label": "Slate",
        "description": "Clean contemporary sans-serif with strong hierarchy - the default.",
        "best_for": "General purpose - safe everywhere",
    },
    "terminal": {
        "label": "Terminal",
        "description": (
            "Technical layout with monospace accents and projects placed forward."
        ),
        "best_for": "Engineering, data, technical roles",
    },
    "signal": {
        "label": "Signal",
        "description": "Bold headline treatment with a single warm accent color.",
        "best_for": "Design, marketing, creative roles",
    },
}

# Ordered to match render.TEMPLATES exactly.
TEMPLATE_META: list[dict[str, str]] = [
    {"name": name, **_METADATA[name]} for name in TEMPLATES
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
