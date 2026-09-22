"""Profile CRUD, source-document upload, and master-profile build routes."""
from __future__ import annotations

from datetime import timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from ..db import get_session
from ..models import (
    Application,
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
from ..services.inbox import inbox_url

router = APIRouter()


class ProfileCreate(BaseModel):
    name: str
    contact: Optional[Contact] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    contact: Optional[Contact] = None
    master_profile: Optional[MasterProfile] = None
    voice_notes: Optional[str] = None


def _has_master_profile(profile: Profile) -> bool:
    mp = get_master_profile(profile)
    return bool(mp.experiences or mp.projects or mp.skills or mp.education)


def _require_name(name: str) -> str:
    """The name without surrounding whitespace; 422 when nothing is left.

    Every person needs a name: it labels them in the picker, and removing a
    person means typing it exactly.
    """
    stripped = name.strip()
    if not stripped:
        raise HTTPException(status_code=422, detail="name must not be blank")
    return stripped


def profile_summary(profile: Profile) -> dict[str, Any]:
    """One row of GET /profiles. created_at lets a browser tell a person from a
    later one who was given the same id after a removal."""
    contact = get_contact(profile)
    return {
        "id": profile.id,
        "name": profile.name,
        "contact": contact.model_dump(),
        "has_master_profile": _has_master_profile(profile),
        "created_at": profile.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "inbox_url": inbox_url(contact.email),
    }


def profile_detail(session: Session, profile: Profile) -> dict[str, Any]:
    docs = session.exec(
        select(SourceDocument)
        .where(SourceDocument.profile_id == profile.id)
        .order_by(SourceDocument.id)
    ).all()
    # Every application, archived included: this is the number a person
    # removal would delete.
    application_count = session.exec(
        select(func.count())
        .select_from(Application)
        .where(Application.profile_id == profile.id)
    ).one()
    contact = get_contact(profile)
    return {
        "id": profile.id,
        "name": profile.name,
        "contact": contact.model_dump(),
        "master_profile": get_master_profile(profile).model_dump(),
        "voice_notes": profile.voice_notes,
        "created_at": profile.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "inbox_url": inbox_url(contact.email),
        "application_count": application_count,
        "documents": [
            {"id": d.id, "filename": d.filename, "kind": d.kind} for d in docs
        ],
    }


def _blank(value: Optional[str]) -> bool:
    return not (value or "").strip()


def _merge_contact(existing: Contact, found: Contact) -> Contact:
    """The person's contact, with only its empty fields filled from `found`.

    Build reads whatever documents were uploaded, and an old resume carries an
    old email and phone. What the person already has (typed on the Profiles
    screen, or kept from an earlier Build) wins; the documents only fill gaps.
    """
    return Contact(
        name=found.name if _blank(existing.name) else existing.name,
        email=found.email if _blank(existing.email) else existing.email,
        phone=found.phone if _blank(existing.phone) else existing.phone,
        location=found.location if _blank(existing.location) else existing.location,
        links=existing.links if existing.links else found.links,
    )


def _get_profile_or_404(session: Session, profile_id: int) -> Profile:
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return profile


@router.get("/profiles")
def list_profiles(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    # Ordered, so "the first person" is the same on every load.
    profiles = session.exec(select(Profile).order_by(Profile.id)).all()
    return [profile_summary(p) for p in profiles]


@router.post("/profiles")
def create_profile(
    body: ProfileCreate, session: Session = Depends(get_session)
) -> dict[str, Any]:
    name = _require_name(body.name)
    profile = Profile(name=name)
    set_contact(profile, body.contact or Contact(name=name))
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
        profile.name = _require_name(body.name)
    if body.contact is not None:
        set_contact(profile, body.contact)
    if body.master_profile is not None:
        set_master_profile(profile, body.master_profile)
    if body.voice_notes is not None:
        profile.voice_notes = body.voice_notes
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


@router.delete("/profiles/{profile_id}/documents/{doc_id}")
def delete_document(
    profile_id: int, doc_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Remove one uploaded document, e.g. a resume uploaded to the wrong person.

    The built master profile is left as it is; the next Build reads only the
    documents that remain. The voice sample changes at once: generation uses
    the newest remaining document, or none (pipeline._voice_for).
    """
    _get_profile_or_404(session, profile_id)
    doc = session.get(SourceDocument, doc_id)
    if doc is None or doc.profile_id != profile_id:
        raise HTTPException(status_code=404, detail="document not found")
    session.delete(doc)
    session.commit()
    return {"deleted": doc_id}


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
    set_contact(profile, _merge_contact(get_contact(profile), contact))
    profile.updated_at = _utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    detail = profile_detail(session, profile)
    detail["usage"] = usage.model_dump()
    return detail
