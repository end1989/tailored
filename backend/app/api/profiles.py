"""Profile CRUD, source-document upload, and master-profile build routes."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import (
    Profile,
    SourceDocument,
    _utcnow,
    get_contact,
    get_master_profile,
    set_contact,
    set_master_profile,
)
from ..schemas import Contact, MasterProfile
from ..services import intake
from ..services.claude import ClaudeError

router = APIRouter()


class ProfileCreate(BaseModel):
    name: str
    contact: Optional[Contact] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    contact: Optional[Contact] = None
    master_profile: Optional[MasterProfile] = None


def _has_master_profile(profile: Profile) -> bool:
    mp = get_master_profile(profile)
    return bool(mp.experiences or mp.projects or mp.skills or mp.education)


def profile_detail(session: Session, profile: Profile) -> dict[str, Any]:
    docs = session.exec(
        select(SourceDocument).where(SourceDocument.profile_id == profile.id)
    ).all()
    return {
        "id": profile.id,
        "name": profile.name,
        "contact": get_contact(profile).model_dump(),
        "master_profile": get_master_profile(profile).model_dump(),
        "documents": [
            {"id": d.id, "filename": d.filename, "kind": d.kind} for d in docs
        ],
    }


def _get_profile_or_404(session: Session, profile_id: int) -> Profile:
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return profile


@router.get("/profiles")
def list_profiles(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    profiles = session.exec(select(Profile)).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "contact": get_contact(p).model_dump(),
            "has_master_profile": _has_master_profile(p),
        }
        for p in profiles
    ]


@router.post("/profiles")
def create_profile(
    body: ProfileCreate, session: Session = Depends(get_session)
) -> dict[str, Any]:
    profile = Profile(name=body.name)
    set_contact(profile, body.contact or Contact(name=body.name))
    set_master_profile(profile, MasterProfile())
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile_detail(session, profile)


@router.get("/profiles/{profile_id}")
def get_profile(
    profile_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    profile = _get_profile_or_404(session, profile_id)
    return profile_detail(session, profile)


@router.put("/profiles/{profile_id}")
def update_profile(
    profile_id: int, body: ProfileUpdate, session: Session = Depends(get_session)
) -> dict[str, Any]:
    profile = _get_profile_or_404(session, profile_id)
    if body.name is not None:
        profile.name = body.name
    if body.contact is not None:
        set_contact(profile, body.contact)
    if body.master_profile is not None:
        set_master_profile(profile, body.master_profile)
    profile.updated_at = _utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile_detail(session, profile)


@router.post("/profiles/{profile_id}/documents")
async def add_document(
    profile_id: int, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    _get_profile_or_404(session, profile_id)
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            raise HTTPException(status_code=422, detail="multipart field 'file' is required")
        data = await upload.read()
        filename = upload.filename or "upload.txt"
        try:
            kind, text = intake.extract_text(filename, data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"could not extract text from {filename}: {exc}")
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(
                status_code=422, detail="expected a multipart file or a JSON body"
            )
        text = (body.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="'text' must be a non-empty string")
        filename = body.get("filename") or "pasted.txt"
        kind = "paste"
    doc = SourceDocument(profile_id=profile_id, filename=filename, kind=kind, text=text)
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return {"id": doc.id, "filename": doc.filename, "kind": doc.kind}


@router.post("/profiles/{profile_id}/build")
def build_profile(
    profile_id: int, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    profile = _get_profile_or_404(session, profile_id)
    docs = session.exec(
        select(SourceDocument).where(SourceDocument.profile_id == profile_id)
    ).all()
    if not docs:
        raise HTTPException(status_code=422, detail="upload at least one document first")
    try:
        master, contact, usage = intake.build_master_profile(
            [d.text for d in docs], request.app.state.claude
        )
    except ClaudeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"profile build failed: {exc}")
    set_master_profile(profile, master)
    set_contact(profile, contact)
    profile.updated_at = _utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    detail = profile_detail(session, profile)
    detail["usage"] = usage.model_dump()
    return detail
