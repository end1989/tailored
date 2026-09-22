# Person Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One app-wide person picker, remembered per browser, so every screen shows the chosen person's profile, applications and settings, with per-person settings, document and person removal, and a per-person inbox link for the app and MCP agents.

**Architecture:** The backend gains per-person settings (`Profile.settings_json` resolved by `settings_for`, always keyed on the application's owner), removal routes backed by a `services/removal.py` module, and an `inbox_url` derived from the contact email. The frontend gains a `PersonProvider` React context (storage key `tailored-person`, validated by id plus `created_at`), a nav `PersonPicker`, and moves every screen off its own `listProfiles` call onto `usePerson()`. MCP tools keep taking an explicit `profile_id`; the only MCP change is an additive `inbox_url` key and one guide section.

**Tech Stack:** FastAPI, SQLModel/SQLite (additive migrations via `init_db`), pytest + respx; React 18, react-router-dom v7, Vite, TypeScript, vitest + @testing-library/react (jsdom).

**Spec:** `docs/superpowers/specs/2026-09-21-person-picker-design.md`

## Global Constraints

- Python interpreter: `.venv/Scripts/python.exe`, commands run from the repo root in Git Bash. Backend tests: `.venv/Scripts/python.exe -m pytest <path> -v`. Fast suite: `.venv/Scripts/python.exe -m pytest -m "not pdf" -q`.
- Frontend tests: `cd frontend && npx vitest run <path>`; full: `cd frontend && npm test`.
- Frontend changes require a rebuild before commit: `cd frontend && npm run build`, then `.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q` must pass, and `frontend/dist` is committed with the source (`git add frontend/dist`).
- No Alembic. Adding a column means adding a defaulted field to the SQLModel class; never drop, rename or retype. `settings_json: str = "{}"` gets `NOT NULL DEFAULT '{}'` from `_add_missing_columns`.
- Tests never touch the network or `data/`; use the `conftest.py` fixtures (`engine`, `session`, `fake_settings`, `app`, `client`, `claude_fake`).
- Every new backend test goes in the new test file its task names; existing tests are edited only where a task says so.
- No em dashes, en dashes outside numeric ranges, curly quotes or ellipsis characters in user-visible strings or agent-facing text, except the "Add a person…" option label, which uses U+2026 as the spec writes it.
- No `window.confirm`, `alert` or `prompt`; confirmations are inline.
- Every `localStorage` access is inside try/catch.
- MCP tools keep their arguments; `profile_id` stays explicit. The only MCP output change is the additive `inbox_url` key.
- A render always uses the application owner's settings (`settings_for(data_dir, owner)`), never the picker's person.
- The truthfulness guard is not loosened by anything in this plan.
- Commit messages use a conventional prefix (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`) and end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Match the surrounding style; no linter is configured.

## Task order

Backend (Tasks 1-9) lands first so the frontend (Tasks 10-19) builds on real endpoints; Task 20 updates the docs and runs every suite. Tasks 1-5 own `api/profiles.py` and `services/removal.py`; Tasks 6-8 own per-person settings and their consumers; Task 9 owns the MCP additions; Tasks 10-12 own the shared frontend pieces (`types.ts`, `api.ts`, `person.tsx`, `test-utils.tsx`, `PersonPicker`); Tasks 13-19 each own one screen and its test file.

---

### Task 1: Inbox URL and the profile payload (order, created_at, inbox_url, application_count, no blank names)

**Files:**
- Create: `backend/app/services/inbox.py`
- Modify: `backend/app/api/profiles.py` (import block; new `_require_name` and `profile_summary` before `profile_detail`; `profile_detail` body; `list_profiles` and the first two lines of `create_profile`; the name line of `update_profile`)
- Test: `tests/test_profile_payload.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `backend/app/services/inbox.py`: `def inbox_url(email: str | None) -> str | None`
  - `backend/app/api/profiles.py`:
    - `def profile_summary(profile: Profile) -> dict[str, Any]` with keys `id, name, contact, has_master_profile, created_at, inbox_url`
    - `GET /api/profiles` returns `[profile_summary(p) ...]` ordered by `Profile.id`
    - `profile_detail(session, profile)` gains `created_at`, `inbox_url`, `application_count` (all of the person's applications, archived included); `documents` ordered by `SourceDocument.id`
    - `def _require_name(name: str) -> str`: 422 `"name must not be blank"` when blank after `strip()`
  - Choice made here (the contract leaves it open): create and update store the name **stripped** (`"  Ada "` is saved as `"Ada"`, and a create without a contact gets `Contact(name="Ada")`). The typed-name check in Task 5 compares against the stored name exactly, so trimming on the way in keeps that check from depending on invisible whitespace.

- [ ] **Step 1: Write the failing `inbox_url` tests**

Create `tests/test_profile_payload.py` with exactly this content (the imports for Step 5's tests are included now so the file is written once):

```python
"""Profile payloads for the person picker: stable order, created_at, inbox_url,
application_count, and a name that is never blank."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import event
from sqlmodel import Session

from backend.app.models import Application, Job, Profile, _utcnow
from backend.app.services.inbox import inbox_url


# --- inbox_url -------------------------------------------------------------


@pytest.mark.parametrize(
    "email, expected",
    [
        ("ada@gmail.com", "https://mail.google.com/mail/?authuser=ada@gmail.com"),
        ("ada@googlemail.com",
         "https://mail.google.com/mail/?authuser=ada@googlemail.com"),
        # Domain matched case-insensitively after trimming; the address in the
        # URL is the trimmed one, case kept.
        ("  Ada.Lovelace@GMail.COM \n",
         "https://mail.google.com/mail/?authuser=Ada.Lovelace@GMail.COM"),
        # Everything but "@" is percent-encoded.
        ("ada+jobs@gmail.com",
         "https://mail.google.com/mail/?authuser=ada%2Bjobs@gmail.com"),
        ("ada@icloud.com", "https://www.icloud.com/mail"),
        ("ada@me.com", "https://www.icloud.com/mail"),
        ("ada@MAC.com", "https://www.icloud.com/mail"),
        ("ada@outlook.com", "https://outlook.live.com/mail/"),
        ("ada@hotmail.com", "https://outlook.live.com/mail/"),
        ("ada@live.com", "https://outlook.live.com/mail/"),
        (" ada@msn.com ", "https://outlook.live.com/mail/"),
        # Custom domains (Google Workspace included) name no provider.
        ("ada@example.com", None),
        ("ada@mail.gmail.com", None),
        ("ada@gmail.com.example.net", None),
        ("", None),
        ("   ", None),
        ("not-an-email", None),
        (None, None),
    ],
)
def test_inbox_url(email, expected):
    assert inbox_url(email) == expected
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_payload.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'backend.app.services.inbox'`.

- [ ] **Step 3: Create `backend/app/services/inbox.py`**

```python
"""The web-mail inbox for a person's contact email.

Only providers that can be known from the domain alone get a link. A custom
domain (Google Workspace included) could be hosted anywhere, so it gets none.
Only the Gmail form selects an account; the others open whichever account is
signed in on that site.
"""
from __future__ import annotations

from urllib.parse import quote

_GMAIL = ("gmail.com", "googlemail.com")
_ICLOUD = ("icloud.com", "me.com", "mac.com")
_OUTLOOK = ("outlook.com", "hotmail.com", "live.com", "msn.com")


def inbox_url(email: str | None) -> str | None:
    """The inbox URL for this address, or None when the provider is unknown."""
    if email is None:
        return None
    address = email.strip()
    if "@" not in address:
        return None
    domain = address.rsplit("@", 1)[1].lower()
    if domain in _GMAIL:
        return "https://mail.google.com/mail/?authuser=" + quote(address, safe="@")
    if domain in _ICLOUD:
        return "https://www.icloud.com/mail"
    if domain in _OUTLOOK:
        return "https://outlook.live.com/mail/"
    return None
```

- [ ] **Step 4: Run it and watch it pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_payload.py -v`
Expected: `18 passed`.

- [ ] **Step 5: Append the failing payload and name tests**

Append to the end of `tests/test_profile_payload.py`:

```python


# --- helpers ---------------------------------------------------------------


def _create(client, name, email=""):
    contact = {"name": name, "email": email, "links": []}
    resp = client.post("/api/profiles", json={"name": name, "contact": contact})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _application(engine, profile_id, archived=False):
    with Session(engine) as s:
        job = Job(url="https://jobs.example.com/posting")
        s.add(job)
        s.commit()
        s.refresh(job)
        row = Application(
            profile_id=profile_id,
            job_id=job.id,
            status="ready",
            archived_at=_utcnow() if archived else None,
        )
        s.add(row)
        s.commit()
        return row.id


@pytest.fixture()
def reversed_scans(engine):
    """SQLite returns unordered SELECTs backwards on these connections, so a
    query that leans on insertion order instead of ORDER BY comes back in the
    wrong order and the test sees it."""
    def _pragma(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA reverse_unordered_selects = ON")

    event.listen(engine, "connect", _pragma)
    engine.dispose()  # drop pooled connections opened before the listener
    yield
    event.remove(engine, "connect", _pragma)


# --- GET /api/profiles -----------------------------------------------------


def test_list_is_ordered_by_id(client, reversed_scans):
    ids = [_create(client, name) for name in ("Ada", "Ben", "Cy")]

    listing = client.get("/api/profiles").json()

    assert [p["id"] for p in listing] == sorted(ids)


def test_list_carries_created_at_and_inbox_url(client, engine):
    ada = _create(client, "Ada", "ada@gmail.com")
    ben = _create(client, "Ben", "ben@example.com")

    listing = {p["id"]: p for p in client.get("/api/profiles").json()}

    assert set(listing[ada]) == {
        "id", "name", "contact", "has_master_profile", "created_at", "inbox_url",
    }
    assert listing[ada]["inbox_url"] == "https://mail.google.com/mail/?authuser=ada@gmail.com"
    assert listing[ben]["inbox_url"] is None
    with Session(engine) as s:
        stored = s.get(Profile, ada).created_at
    assert listing[ada]["created_at"] == stored.replace(tzinfo=timezone.utc).isoformat()
    assert datetime.fromisoformat(listing[ada]["created_at"]).tzinfo is not None


# --- GET /api/profiles/{id} ------------------------------------------------


def test_detail_carries_created_at_inbox_url_and_application_count(client, engine):
    ada = _create(client, "Ada", "ada@outlook.com")
    ben = _create(client, "Ben")
    _application(engine, ada)
    _application(engine, ada, archived=True)
    _application(engine, ben)

    detail = client.get(f"/api/profiles/{ada}").json()

    assert detail["inbox_url"] == "https://outlook.live.com/mail/"
    assert detail["application_count"] == 2  # the archived one counts
    listed = {p["id"]: p for p in client.get("/api/profiles").json()}
    assert detail["created_at"] == listed[ada]["created_at"]
    assert client.get(f"/api/profiles/{ben}").json()["application_count"] == 1


def test_a_new_person_has_no_applications(client):
    resp = client.post("/api/profiles", json={"name": "Ada"})

    assert resp.json()["application_count"] == 0
    assert resp.json()["inbox_url"] is None


def test_detail_lists_documents_in_upload_order(client, reversed_scans):
    pid = _create(client, "Ada")
    for name in ("first.txt", "second.txt", "third.txt"):
        client.post(f"/api/profiles/{pid}/documents",
                    json={"filename": name, "text": f"{name} body"})

    detail = client.get(f"/api/profiles/{pid}").json()

    assert [d["filename"] for d in detail["documents"]] == [
        "first.txt", "second.txt", "third.txt",
    ]


def test_update_response_carries_the_new_keys(client, engine):
    pid = _create(client, "Ada")
    _application(engine, pid)

    resp = client.put(f"/api/profiles/{pid}",
                      json={"contact": {"name": "Ada", "email": "ada@icloud.com"}})

    assert resp.status_code == 200, resp.text
    assert resp.json()["inbox_url"] == "https://www.icloud.com/mail"
    assert resp.json()["application_count"] == 1


# --- names -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_create_rejects_a_blank_name(client, name):
    resp = client.post("/api/profiles", json={"name": name})

    assert resp.status_code == 422
    assert resp.json()["detail"] == "name must not be blank"
    assert client.get("/api/profiles").json() == []


def test_create_trims_the_name(client):
    resp = client.post("/api/profiles", json={"name": "  Ada Lovelace "})

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Ada Lovelace"
    assert resp.json()["contact"]["name"] == "Ada Lovelace"


@pytest.mark.parametrize("name", ["", "   "])
def test_update_rejects_a_blank_name(client, name):
    pid = _create(client, "Ada")

    resp = client.put(f"/api/profiles/{pid}", json={"name": name, "voice_notes": "Plain."})

    assert resp.status_code == 422
    assert resp.json()["detail"] == "name must not be blank"
    after = client.get(f"/api/profiles/{pid}").json()
    assert after["name"] == "Ada"
    assert after["voice_notes"] == ""  # nothing in the rejected body was written


def test_update_trims_the_name_and_leaves_it_alone_when_absent(client):
    pid = _create(client, "Ada")

    renamed = client.put(f"/api/profiles/{pid}", json={"name": " Ada L "})
    assert renamed.json()["name"] == "Ada L"

    untouched = client.put(f"/api/profiles/{pid}", json={"voice_notes": "Plain."})
    assert untouched.status_code == 200
    assert untouched.json()["name"] == "Ada L"
```

Why `reversed_scans`: SQLite happens to return a plain table scan in rowid order, so a missing `ORDER BY` would pass an ordinary test. `PRAGMA reverse_unordered_selects` makes every unordered SELECT come back backwards, so the ordering tests fail unless the query really orders.

- [ ] **Step 6: Run and watch the new tests fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_payload.py -v`
Expected: `13 failed, 18 passed`. `test_list_is_ordered_by_id` fails with the ids reversed (`[3, 2, 1]`), `test_detail_lists_documents_in_upload_order` with `['third.txt', 'second.txt', 'first.txt']`, the payload tests with `KeyError: 'inbox_url'` / `'application_count'` or the key-set assertion, the blank-name tests with `assert 200 == 422`, and the trim tests with `'  Ada Lovelace ' == 'Ada Lovelace'`.

- [ ] **Step 7: Implement the payload in `backend/app/api/profiles.py`**

7a. Replace the import block. Current code:

```python
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
```

Replacement:

```python
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
```

7b. Replace `profile_detail` and add the two helpers above it. Current code:

```python
def profile_detail(session: Session, profile: Profile) -> dict[str, Any]:
    docs = session.exec(
        select(SourceDocument).where(SourceDocument.profile_id == profile.id)
    ).all()
    return {
        "id": profile.id,
        "name": profile.name,
        "contact": get_contact(profile).model_dump(),
        "master_profile": get_master_profile(profile).model_dump(),
        "voice_notes": profile.voice_notes,
        "documents": [
            {"id": d.id, "filename": d.filename, "kind": d.kind} for d in docs
        ],
    }
```

Replacement:

```python
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
```

7c. Replace `list_profiles` and the start of `create_profile`. Current code:

```python
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
```

Replacement:

```python
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
```

7d. In `update_profile`, current code:

```python
    if body.name is not None:
        profile.name = body.name
```

Replacement:

```python
    if body.name is not None:
        profile.name = _require_name(body.name)
```

The check runs before any other field is assigned, and the raised `HTTPException` makes `get_session` roll back, so a rejected update writes nothing.

- [ ] **Step 8: Run the tests and the wider suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_payload.py -v`
Expected: `31 passed`.

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py tests/test_demo.py tests/test_e2e.py -m "not pdf" -q`
Expected: all pass. (`test_profile_crud` still holds: it checks individual keys, and `"Avery K."` has no surrounding whitespace.)

Run: `.venv/Scripts/python.exe -m pytest -m "not pdf" -q`
Expected: no failures.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/inbox.py backend/app/api/profiles.py tests/test_profile_payload.py
git commit -m "$(cat <<'EOF'
feat: order profiles by id and add created_at, inbox_url, application_count

GET /api/profiles is ordered by id and each row carries created_at and
inbox_url; profile detail also carries application_count (archived
included) and lists documents in upload order. Create and update reject a
blank name and store it trimmed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```


---

### Task 2: Build keeps the existing contact and fills only empty fields

**Files:**
- Modify: `backend/app/api/profiles.py` (new `_blank` and `_merge_contact` just above `_get_profile_or_404`; the `set_contact` line in `build_profile`)
- Test: `tests/test_build_keeps_contact.py` (new)

**Interfaces:**
- Consumes: from Task 1, `profile_detail` returning `inbox_url` (asserted in one test below).
- Produces: `def _merge_contact(existing: Contact, found: Contact) -> Contact` in `backend/app/api/profiles.py`. A field is kept when it is non-empty after `strip()` (`name`, `email`, `phone`, `location`) or is a non-empty list (`links`); otherwise the intake value is used. `POST /api/profiles/{id}/build` stores `_merge_contact(get_contact(profile), <intake contact>)`. `profile.name` is never touched by Build.
- Existing tests: no test in `tests/test_api.py` asserts that Build replaces the contact. `test_build_master_profile` asserts only the master profile, the documents passed to intake and the usage; its fake intake contact (`Avery Kim`, `avery.kim@example.com`) equals the profile's own, so it passes either way. `tests/test_e2e.py` asserts nothing about the built contact (its resume and preview contact come from the `tailor` fixture). No existing test changes in this task. To check, run `grep -rn '\["contact"\]' tests/test_api.py tests/test_e2e.py`. It prints three lines: `test_profile_crud`'s listing assertion (`test_api.py:108`, a created profile, no Build) and two `tailor["resume"]["contact"]` lines in `test_e2e.py`, which read the tailor fixture rather than the profile.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_build_keeps_contact.py`:

```python
"""Build keeps the contact a person already has and fills only the gaps, so a
Build over an old resume cannot move their email (or their Inbox link)."""
from __future__ import annotations

from backend.app.api.profiles import _merge_contact
from backend.app.schemas import Contact, LinkItem, MasterProfile, MPExperience, UsageInfo
from backend.app.services import intake

FOUND = Contact(
    name="Ada King",
    email="old.address@outlook.com",
    phone="(206) 555-0100",
    location="London, UK",
    links=[LinkItem(label="GitHub", url="https://github.com/old-ada")],
)

BUILT = MasterProfile(
    experiences=[MPExperience(company="Analytical Engines", title="Engineer", start="2020")],
)


def _fake_build(monkeypatch, found=FOUND):
    def fake(docs, claude):
        return BUILT, found, UsageInfo()

    monkeypatch.setattr(intake, "build_master_profile", fake)


def _person(client, name, contact):
    resp = client.post("/api/profiles", json={"name": name, "contact": contact})
    assert resp.status_code == 200, resp.text
    pid = resp.json()["id"]
    client.post(f"/api/profiles/{pid}/documents",
                json={"filename": "old_resume.txt", "text": "An old resume"})
    return pid


# --- _merge_contact --------------------------------------------------------


def test_merge_keeps_every_non_empty_field():
    existing = Contact(
        name="Ada Lovelace",
        email="ada@gmail.com",
        phone="(206) 555-0142",
        location="Seattle, WA",
        links=[LinkItem(label="Site", url="https://ada.example.com")],
    )

    assert _merge_contact(existing, FOUND) == existing


def test_merge_fills_only_the_empty_fields():
    existing = Contact(name="Ada Lovelace", email="ada@gmail.com", phone="  ",
                       location=None, links=[])

    merged = _merge_contact(existing, FOUND)

    assert merged == Contact(
        name="Ada Lovelace",
        email="ada@gmail.com",
        phone="(206) 555-0100",
        location="London, UK",
        links=[LinkItem(label="GitHub", url="https://github.com/old-ada")],
    )


def test_merge_fills_a_blank_name_and_email():
    merged = _merge_contact(Contact(name=" ", email=""), FOUND)

    assert merged.name == "Ada King"
    assert merged.email == "old.address@outlook.com"


# --- POST /profiles/{id}/build ---------------------------------------------


def test_build_keeps_the_existing_contact(client, monkeypatch):
    contact = {
        "name": "Ada Lovelace",
        "email": "ada@gmail.com",
        "phone": "(206) 555-0142",
        "location": "Seattle, WA",
        "links": [{"label": "Site", "url": "https://ada.example.com"}],
    }
    pid = _person(client, "Ada Lovelace", contact)
    _fake_build(monkeypatch)

    resp = client.post(f"/api/profiles/{pid}/build")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contact"] == contact
    assert body["name"] == "Ada Lovelace"
    assert body["inbox_url"] == "https://mail.google.com/mail/?authuser=ada@gmail.com"
    # Build still does its job: the master profile is the one intake built.
    assert body["master_profile"]["experiences"][0]["company"] == "Analytical Engines"
    assert client.get(f"/api/profiles/{pid}").json()["contact"] == contact


def test_build_fills_empty_contact_fields(client, monkeypatch):
    pid = _person(client, "Ada", {"name": "Ada", "email": "", "links": []})
    _fake_build(monkeypatch)

    contact = client.post(f"/api/profiles/{pid}/build").json()["contact"]

    assert contact == {
        "name": "Ada",
        "email": "old.address@outlook.com",
        "phone": "(206) 555-0100",
        "location": "London, UK",
        "links": [{"label": "GitHub", "url": "https://github.com/old-ada"}],
    }


def test_build_never_renames_the_person(client, monkeypatch):
    pid = _person(client, "Ada", {"name": "", "email": "ada@gmail.com"})
    _fake_build(monkeypatch)

    body = client.post(f"/api/profiles/{pid}/build").json()

    assert body["name"] == "Ada"
    assert body["contact"]["name"] == "Ada King"  # the blank contact name was filled
    assert body["contact"]["email"] == "ada@gmail.com"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_keeps_contact.py -v`
Expected: collection error, `ImportError: cannot import name '_merge_contact' from 'backend.app.api.profiles'`.

- [ ] **Step 3: Implement the merge in `backend/app/api/profiles.py`**

3a. Add the helpers directly above `_get_profile_or_404`. Current code:

```python
def _get_profile_or_404(session: Session, profile_id: int) -> Profile:
```

Replacement:

```python
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
```

3b. In `build_profile`, current code:

```python
    set_master_profile(profile, master)
    set_contact(profile, contact)
    profile.updated_at = _utcnow()
```

Replacement:

```python
    set_master_profile(profile, master)
    set_contact(profile, _merge_contact(get_contact(profile), contact))
    profile.updated_at = _utcnow()
```

- [ ] **Step 4: Run the tests and the wider suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_keeps_contact.py -v`
Expected: `6 passed`.

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py tests/test_e2e.py tests/test_intake.py tests/test_profile_payload.py -m "not pdf" -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/profiles.py tests/test_build_keeps_contact.py
git commit -m "$(cat <<'EOF'
fix: keep a person's contact on Build and fill only empty fields

Build used to replace the whole contact with whatever intake found, so a
Build over an old resume could move someone's email, and with it their
Inbox link, to an address they no longer use.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```


---

### Task 3: Remove one source document

**Files:**
- Modify: `backend/app/api/profiles.py` (new `delete_document` route directly after `add_document`)
- Test: `tests/test_document_removal.py` (new)

**Interfaces:**
- Consumes: from Task 1, `profile_detail` (documents ordered by id). `pipeline._voice_for(session, profile) -> tuple[str | None, str | None]` (existing, `backend/app/services/pipeline.py`).
- Produces: `DELETE /api/profiles/{profile_id}/documents/{doc_id}` returns `{"deleted": doc_id}`; 404 `"profile not found"` for an unknown profile; 404 `"document not found"` when the document does not exist or belongs to another profile. The master profile is not changed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_document_removal.py`:

```python
"""DELETE /api/profiles/{id}/documents/{doc_id}: repairs an upload made to the
wrong person without touching the built master profile."""
from __future__ import annotations

from sqlmodel import Session, select

from backend.app.models import Profile, SourceDocument
from backend.app.schemas import Contact, MasterProfile, UsageInfo
from backend.app.services import intake, pipeline

MASTER = {
    "summary_notes": "Backend engineer.",
    "experiences": [{
        "company": "Meridian Analytics", "title": "Senior Software Engineer",
        "start": "2021-03", "end": None, "location": "Remote",
        "bullets": [{"text": "Built APIs", "tags": ["python"]}],
    }],
    "projects": [], "skills": [], "education": [], "certifications": [], "extras": [],
}


def _person(client, name="Ada") -> int:
    resp = client.post("/api/profiles", json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _upload(client, pid, filename, text) -> int:
    resp = client.post(f"/api/profiles/{pid}/documents",
                       json={"filename": filename, "text": text})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_removes_the_document(client, engine):
    pid = _person(client)
    kept = _upload(client, pid, "resume.txt", "My resume")
    doomed = _upload(client, pid, "someone_else.txt", "Not my resume")

    resp = client.delete(f"/api/profiles/{pid}/documents/{doomed}")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": doomed}
    docs = client.get(f"/api/profiles/{pid}").json()["documents"]
    assert [d["id"] for d in docs] == [kept]
    with Session(engine) as s:
        assert s.get(SourceDocument, doomed) is None


def test_unknown_document_is_404(client):
    pid = _person(client)

    resp = client.delete(f"/api/profiles/{pid}/documents/9999")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "document not found"


def test_another_persons_document_is_404_and_kept(client):
    ada = _person(client, "Ada")
    ben = _person(client, "Ben")
    bens_doc = _upload(client, ben, "ben.txt", "Ben's resume")

    resp = client.delete(f"/api/profiles/{ada}/documents/{bens_doc}")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "document not found"
    docs = client.get(f"/api/profiles/{ben}").json()["documents"]
    assert [d["id"] for d in docs] == [bens_doc]


def test_unknown_person_is_404(client):
    resp = client.delete("/api/profiles/9999/documents/1")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "profile not found"


def test_the_master_profile_is_unchanged(client):
    pid = _person(client)
    client.put(f"/api/profiles/{pid}", json={"master_profile": MASTER})
    doc = _upload(client, pid, "resume.txt", "My resume")
    before = client.get(f"/api/profiles/{pid}").json()["master_profile"]

    assert client.delete(f"/api/profiles/{pid}/documents/{doc}").status_code == 200

    after = client.get(f"/api/profiles/{pid}").json()
    assert after["documents"] == []
    assert after["master_profile"] == before
    assert after["master_profile"]["experiences"][0]["company"] == "Meridian Analytics"


def test_the_next_build_reads_only_what_remains(client, monkeypatch):
    pid = _person(client)
    _upload(client, pid, "resume.txt", "My resume")
    doomed = _upload(client, pid, "someone_else.txt", "Not my resume")
    client.delete(f"/api/profiles/{pid}/documents/{doomed}")
    seen = {}

    def fake_build(docs, claude):
        seen["docs"] = list(docs)
        return MasterProfile(), Contact(name="Ada"), UsageInfo()

    monkeypatch.setattr(intake, "build_master_profile", fake_build)

    assert client.post(f"/api/profiles/{pid}/build").status_code == 200
    assert seen["docs"] == ["My resume"]


def test_voice_sample_falls_back_to_the_next_newest_document(client, engine):
    pid = _person(client)
    _upload(client, pid, "resume.txt", "My own writing")
    doomed = _upload(client, pid, "someone_else.txt", "Somebody else's writing")

    with Session(engine) as s:
        assert pipeline._voice_for(s, s.get(Profile, pid))[0] == "Somebody else's writing"

    client.delete(f"/api/profiles/{pid}/documents/{doomed}")

    with Session(engine) as s:
        assert pipeline._voice_for(s, s.get(Profile, pid))[0] == "My own writing"


def test_removing_the_last_document_leaves_no_voice_sample(client, engine):
    pid = _person(client)
    only = _upload(client, pid, "resume.txt", "My own writing")

    client.delete(f"/api/profiles/{pid}/documents/{only}")

    with Session(engine) as s:
        assert pipeline._voice_for(s, s.get(Profile, pid)) == (None, None)
        remaining = s.exec(
            select(SourceDocument).where(SourceDocument.profile_id == pid)
        ).all()
    assert remaining == []
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_document_removal.py -v`
Expected: `8 failed`. With no DELETE route on that path the app answers `405 Method Not Allowed`, so the status assertions fail (`assert 405 == 200` / `assert 405 == 404`), and the Build and voice-sample tests still see the document that was not removed.

- [ ] **Step 3: Add the route**

In `backend/app/api/profiles.py`, the end of `add_document` is currently:

```python
    doc = SourceDocument(profile_id=profile_id, filename=filename, kind=kind, text=text)
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return {"id": doc.id, "filename": doc.filename, "kind": doc.kind}
```

Replace it with the same lines followed by the new route:

```python
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
```

- [ ] **Step 4: Run the tests and the wider suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_document_removal.py -v`
Expected: `8 passed`.

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py tests/test_pipeline.py tests/test_profile_payload.py tests/test_build_keeps_contact.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/profiles.py tests/test_document_removal.py
git commit -m "$(cat <<'EOF'
feat: remove a single source document from a profile

DELETE /api/profiles/{id}/documents/{doc_id} repairs an upload made to the
wrong person. The master profile is left alone; the next Build and the
voice sample use only the documents that remain.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```


---

### Task 4: Shared application-row delete (`delete_application_rows`), used by the delete route

**Files:**
- Create: `backend/app/services/removal.py`
- Modify: `backend/app/api/applications.py` (one new import line after `from ..services import pipeline, render`; the docstring and the row-deleting tail of `delete_application`)
- Test: `tests/test_application_removal_rows.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `backend/app/services/removal.py`:
    ```python
    def delete_application_rows(session: Session, app_row: Application) -> None:
        """Delete one application's events, versions, research briefs (by job_id),
        job row and the application row. Does not commit and touches no files."""
    ```
    A missing Job row (already deleted) is tolerated.
  - `api/applications.py::delete_application` keeps its 404/409 checks and its `_remove_export_dir` call first, then calls `delete_application_rows(session, app_row)` and commits, so it now also removes the application's Job and ResearchBrief rows.
- Why deleting the Job is safe: every Application owns its own Job. Batch create (`api/applications.py`), MCP `create_application` and `queue_jobs` (`backend/mcp_ops.py`) and demo seeding each create a fresh `Job` per application; nothing shares one.
- `ApplicationEvent` and `ApplicationVersion` stay imported in `api/applications.py`. `ApplicationEvent` is still used by the timeline routes; `ApplicationVersion` becomes unused there but is left in place so the import block other tasks anchor on does not change.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_application_removal_rows.py`:

```python
"""delete_application_rows removes everything one application owns, and the
single-application delete route now uses it, so the Job and ResearchBrief
rows no longer outlive their application."""
from __future__ import annotations

from sqlmodel import Session, select

from backend.app.models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
)
from backend.app.services.removal import delete_application_rows


def _profile(engine, name="Ada") -> int:
    with Session(engine) as s:
        p = Profile(name=name)
        s.add(p)
        s.commit()
        return p.id


def _full_application(engine, profile_id, status="ready") -> tuple[int, int]:
    """An application with a job, two research briefs, a version and an event.
    Returns (application_id, job_id)."""
    with Session(engine) as s:
        job = Job(url="https://jobs.example.com/posting")
        s.add(job)
        s.commit()
        s.refresh(job)
        app_row = Application(profile_id=profile_id, job_id=job.id, status=status)
        s.add(app_row)
        s.commit()
        s.refresh(app_row)
        s.add(ResearchBrief(job_id=job.id, depth="standard"))
        s.add(ResearchBrief(job_id=job.id, depth="deep"))
        s.add(ApplicationVersion(application_id=app_row.id, version=1,
                                 resume_json="{}", cover_letter_md=""))
        s.add(ApplicationEvent(application_id=app_row.id, kind="note", body="x"))
        s.commit()
        return app_row.id, job.id


def _rows(engine, app_id, job_id) -> dict[str, int]:
    with Session(engine) as s:
        return {
            "application": len(s.exec(select(Application).where(Application.id == app_id)).all()),
            "job": len(s.exec(select(Job).where(Job.id == job_id)).all()),
            "briefs": len(s.exec(select(ResearchBrief).where(ResearchBrief.job_id == job_id)).all()),
            "versions": len(s.exec(select(ApplicationVersion)
                                   .where(ApplicationVersion.application_id == app_id)).all()),
            "events": len(s.exec(select(ApplicationEvent)
                                 .where(ApplicationEvent.application_id == app_id)).all()),
        }


GONE = {"application": 0, "job": 0, "briefs": 0, "versions": 0, "events": 0}
INTACT = {"application": 1, "job": 1, "briefs": 2, "versions": 1, "events": 1}


def test_deletes_every_row_the_application_owns(engine):
    pid = _profile(engine)
    doomed, doomed_job = _full_application(engine, pid)
    kept, kept_job = _full_application(engine, pid)

    with Session(engine) as s:
        delete_application_rows(s, s.get(Application, doomed))
        s.commit()

    assert _rows(engine, doomed, doomed_job) == GONE
    assert _rows(engine, kept, kept_job) == INTACT


def test_does_not_commit(engine):
    pid = _profile(engine)
    app_id, job_id = _full_application(engine, pid)

    with Session(engine) as s:
        delete_application_rows(s, s.get(Application, app_id))
        s.rollback()

    assert _rows(engine, app_id, job_id) == INTACT


def test_an_application_whose_job_is_already_gone(engine):
    pid = _profile(engine)
    app_id, job_id = _full_application(engine, pid)
    with Session(engine) as s:
        s.delete(s.get(Job, job_id))
        s.commit()

    with Session(engine) as s:
        delete_application_rows(s, s.get(Application, app_id))
        s.commit()

    assert _rows(engine, app_id, job_id) == GONE


def test_delete_route_removes_job_and_research_briefs(client, engine):
    pid = _profile(engine)
    doomed, doomed_job = _full_application(engine, pid)
    kept, kept_job = _full_application(engine, pid)

    resp = client.delete(f"/api/applications/{doomed}")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": doomed}
    assert _rows(engine, doomed, doomed_job) == GONE
    assert _rows(engine, kept, kept_job) == INTACT


def test_delete_route_still_refuses_mid_pipeline(client, engine):
    pid = _profile(engine)
    app_id, job_id = _full_application(engine, pid, status="researching")

    resp = client.delete(f"/api/applications/{app_id}")

    assert resp.status_code == 409
    assert _rows(engine, app_id, job_id) == INTACT
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_removal_rows.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'backend.app.services.removal'`.

- [ ] **Step 3: Create `backend/app/services/removal.py`**

```python
"""Permanent deletes that span several tables.

Every Application owns exactly one Job (batch create, MCP create_application
and queue_jobs each make a fresh Job per application), and the Job owns its
ResearchBrief rows, so removing an application removes those too.
"""
from __future__ import annotations

from sqlmodel import Session, select

from ..models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    Job,
    ResearchBrief,
)


def delete_application_rows(session: Session, app_row: Application) -> None:
    """Delete one application's events, versions, research briefs (by job_id),
    job row and the application row. Does not commit and touches no files."""
    for event in session.exec(
        select(ApplicationEvent).where(ApplicationEvent.application_id == app_row.id)
    ).all():
        session.delete(event)
    for version in session.exec(
        select(ApplicationVersion)
        .where(ApplicationVersion.application_id == app_row.id)
    ).all():
        session.delete(version)
    for brief in session.exec(
        select(ResearchBrief).where(ResearchBrief.job_id == app_row.job_id)
    ).all():
        session.delete(brief)
    job = session.get(Job, app_row.job_id)
    session.delete(app_row)
    if job is not None:
        session.delete(job)
```

- [ ] **Step 4: Run and confirm only the route test still fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_removal_rows.py -v`
Expected: `1 failed, 4 passed`. The failure is `test_delete_route_removes_job_and_research_briefs`: the route still deletes only events, versions and the application, so `_rows` reports `'job': 1, 'briefs': 2`.

- [ ] **Step 5: Make `delete_application` use it**

5a. In `backend/app/api/applications.py`, current imports:

```python
from ..services import pipeline, render
from ..services.render import TEMPLATES
```

Replacement:

```python
from ..services import pipeline, render
from ..services.removal import delete_application_rows
from ..services.render import TEMPLATES
```

5b. In `delete_application`, current code (from the docstring to the end of the function):

```python
    """Permanent, unrecoverable delete: rows, versions, timeline, and the
    exported files on disk. The reversible path is /archive."""
    app_row, _job = _get_app_and_job(session, application_id)
    if app_row.status in PROCESSING_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"application is currently {app_row.status}; wait for it to finish",
        )

    # Files first: if this raises, nothing below runs and nothing is
    # committed. See _remove_export_dir's docstring for why the order
    # matters -- ids are recycled, so leaving the directory behind while the
    # rows vanish lets a future application inherit a deleted one's exports.
    _remove_export_dir(request.app.state.settings.data_dir, application_id)

    for event in session.exec(
        select(ApplicationEvent).where(ApplicationEvent.application_id == application_id)
    ).all():
        session.delete(event)
    for version in session.exec(
        select(ApplicationVersion)
        .where(ApplicationVersion.application_id == application_id)
    ).all():
        session.delete(version)
    session.delete(app_row)
    session.commit()

    return {"deleted": application_id}
```

Replacement:

```python
    """Permanent, unrecoverable delete: the application, its job and research
    briefs, versions, timeline, and the exported files on disk. The
    reversible path is /archive."""
    app_row, _job = _get_app_and_job(session, application_id)
    if app_row.status in PROCESSING_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"application is currently {app_row.status}; wait for it to finish",
        )

    # Files first: if this raises, nothing below runs and nothing is
    # committed. See _remove_export_dir's docstring for why the order
    # matters -- ids are recycled, so leaving the directory behind while the
    # rows vanish lets a future application inherit a deleted one's exports.
    _remove_export_dir(request.app.state.settings.data_dir, application_id)

    delete_application_rows(session, app_row)
    session.commit()

    return {"deleted": application_id}
```

- [ ] **Step 6: Run the tests and the wider suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_removal_rows.py -v`
Expected: `5 passed`.

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracker.py tests/test_api.py -q`
Expected: all pass, including the existing delete tests in `test_tracker.py` (`test_delete_removes_rows_and_exports`, `test_delete_is_refused_by_a_locked_export_directory`, `test_delete_removes_timeline_rows`, `test_not_started_jobs_are_deletable_and_archivable`), which need no change.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/removal.py backend/app/api/applications.py tests/test_application_removal_rows.py
git commit -m "$(cat <<'EOF'
fix: delete an application's job and research briefs with it

The per-application row delete moves to services/removal.py as
delete_application_rows, which the single-application delete route now
uses. It also removes the Job and ResearchBrief rows the route used to
leave behind, and person removal will reuse it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```


---

### Task 5: Remove a person (typed-name confirm, active-work 409, staged export removal)

**Files:**
- Modify: `backend/app/services/removal.py` (created in Task 4: import block replaced and constants plus `RemovalBlocked` added; new functions appended after `delete_application_rows`)
- Modify: `backend/app/api/profiles.py` (`from ..services import intake` import line; new `delete_profile` route directly after `update_profile`)
- Test: `tests/test_person_removal.py` (new)

**Interfaces:**
- Consumes: from Task 4, `delete_application_rows(session, app_row)` in `backend/app/services/removal.py`. From Task 1, `GET /api/profiles` ordered by id (asserted after a removal).
- Produces, in `backend/app/services/removal.py`:
  ```python
  ACTIVE_STATUSES = ("queued", "fetching", "researching", "tailoring", "rendering")
  STALE_AFTER = timedelta(minutes=15)

  class RemovalBlocked(Exception):
      def __init__(self, detail: dict): ...   # self.detail is the 409 body

  def blocking_applications(session: Session, profile_id: int, now: datetime | None = None) -> list[Application]
  def remove_person(session: Session, data_dir: Path, profile: Profile, now: datetime | None = None) -> dict
  ```
  and `DELETE /api/profiles/{profile_id}?confirm_name=<name>` in `backend/app/api/profiles.py`.
- Choices made here (the contract leaves them open):
  - `remove_person` runs the active-work check itself, first, before anything else, so the service is safe to call on its own. The route only checks the name.
  - A row blocks when `updated_at > now - STALE_AFTER`, so a row exactly 15 minutes old counts as stale. `now` may be naive UTC or timezone-aware; aware values are converted to naive UTC. `None` means `models._utcnow()`.
  - Blocking entries are ordered by application id. `label` is the parsed company, else the job URL, else `"application {id}"` when the Job row is missing.
  - Active-work 409 message: `"These applications are still being worked on. Wait for them to finish, then try again."`
  - Locked-export 409 message: `"Could not remove the exported files for application {id}: a file appears to be open elsewhere (e.g. a PDF viewer). Close it and try again. Nothing was removed."`, with one entry `{"id": <app id>, "label": <OSError.filename, else the directory path>, "status": "locked"}`.
  - Moves use `os.rename` (tests monkeypatch `removal.os.rename`), and cleanup uses `shutil.rmtree` (tests monkeypatch `removal.shutil.rmtree`).
  - A `.removing-<profile_id>` directory left behind by an earlier removal whose cleanup failed is deleted before staging begins (its rows are already gone). If that fails, it is logged, and a later rename into it that collides is reported as a locked export.
  - If the row deletes or the commit raise, the session is rolled back and the directories are moved back before the error propagates.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_person_removal.py`:

```python
"""DELETE /api/profiles/{id}?confirm_name=...: removing a person, their rows
and their exported files, and nobody else's."""
from __future__ import annotations

import logging
from datetime import timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import Session, select

from backend.app.models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
    SourceDocument,
    _utcnow,
    set_parsed,
)
from backend.app.schemas import ParsedPosting
from backend.app.services import removal


# --- helpers ---------------------------------------------------------------


def _person(engine, name, documents=1) -> int:
    with Session(engine) as s:
        p = Profile(name=name)
        s.add(p)
        s.commit()
        s.refresh(p)
        for i in range(documents):
            s.add(SourceDocument(profile_id=p.id, filename=f"resume{i}.txt",
                                 kind="paste", text=f"{name}'s resume {i}"))
        s.commit()
        return p.id


def _application(engine, profile_id, *, status="ready", minutes_ago=0,
                 company=None, url="https://jobs.example.com/posting",
                 archived=False) -> int:
    """An application with a job, a research brief, a version and an event,
    last touched `minutes_ago` minutes ago."""
    with Session(engine) as s:
        job = Job(url=url)
        if company is not None:
            set_parsed(job, ParsedPosting(title="Engineer", company=company))
        s.add(job)
        s.commit()
        s.refresh(job)
        row = Application(
            profile_id=profile_id,
            job_id=job.id,
            status=status,
            archived_at=_utcnow() if archived else None,
            updated_at=_utcnow() - timedelta(minutes=minutes_ago),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        s.add(ResearchBrief(job_id=job.id, depth="standard"))
        s.add(ApplicationVersion(application_id=row.id, version=1,
                                 resume_json="{}", cover_letter_md=""))
        s.add(ApplicationEvent(application_id=row.id, kind="note", body="x"))
        s.commit()
        return row.id


def _export_dir(data_dir, app_id) -> Path:
    d = Path(data_dir) / "exports" / str(app_id)
    d.mkdir(parents=True)
    (d / "resume.pdf").write_bytes(b"%PDF-1.4")
    return d


_TABLES = {
    "profile": Profile,
    "documents": SourceDocument,
    "applications": Application,
    "jobs": Job,
    "briefs": ResearchBrief,
    "versions": ApplicationVersion,
    "events": ApplicationEvent,
}
NOTHING = {key: [] for key in _TABLES}


def _snapshot(engine, profile_id) -> dict[str, list[int]]:
    """The ids of every row the person owns, by table."""
    with Session(engine) as s:
        apps = s.exec(
            select(Application).where(Application.profile_id == profile_id)
        ).all()
        app_ids = [a.id for a in apps]
        job_ids = [a.job_id for a in apps]
        return {
            "profile": [profile_id] if s.get(Profile, profile_id) is not None else [],
            "documents": list(s.exec(select(SourceDocument.id)
                                     .where(SourceDocument.profile_id == profile_id)).all()),
            "applications": app_ids,
            "jobs": job_ids,
            "briefs": list(s.exec(select(ResearchBrief.id)
                                  .where(ResearchBrief.job_id.in_(job_ids))).all()),
            "versions": list(s.exec(select(ApplicationVersion.id)
                                    .where(ApplicationVersion.application_id.in_(app_ids))).all()),
            "events": list(s.exec(select(ApplicationEvent.id)
                                  .where(ApplicationEvent.application_id.in_(app_ids))).all()),
        }


def _surviving(engine, snapshot) -> dict[str, list[int]]:
    """Which of the snapshotted rows still exist, looked up by id."""
    with Session(engine) as s:
        return {
            key: [i for i in ids if s.get(_TABLES[key], i) is not None]
            for key, ids in snapshot.items()
        }


def _staging(data_dir, profile_id) -> Path:
    return Path(data_dir) / "exports" / f".removing-{profile_id}"


def _remove(client, profile_id, confirm_name):
    return client.delete(f"/api/profiles/{profile_id}",
                         params={"confirm_name": confirm_name})


# --- confirmation ----------------------------------------------------------


def test_unknown_person_is_404(client):
    resp = _remove(client, 9999, "Anyone")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "profile not found"


@pytest.mark.parametrize("params", [
    {},                                    # missing
    {"confirm_name": ""},                  # blank
    {"confirm_name": "   "},               # blank after strip
    {"confirm_name": "ada lovelace"},      # wrong case
    {"confirm_name": " Ada Lovelace "},    # not exactly the name
    {"confirm_name": "Ada"},               # a prefix
])
def test_a_missing_blank_or_wrong_name_is_422_and_removes_nothing(client, engine, params):
    pid = _person(engine, "Ada Lovelace")
    _application(engine, pid)
    before = _snapshot(engine, pid)

    resp = client.delete(f"/api/profiles/{pid}", params=params)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "confirm_name must equal the person's name"
    assert _surviving(engine, before) == before


# --- success ---------------------------------------------------------------


def test_removes_the_person_rows_and_files_and_nobody_elses(client, engine, fake_settings):
    ada = _person(engine, "Ada Lovelace", documents=2)
    ben = _person(engine, "Ben")
    ada_apps = [
        _application(engine, ada),
        _application(engine, ada, archived=True),
        _application(engine, ada, status="not_started"),  # a saved job
    ]
    ben_app = _application(engine, ben)
    ada_dirs = [_export_dir(fake_settings.data_dir, a) for a in ada_apps[:2]]
    ben_dir = _export_dir(fake_settings.data_dir, ben_app)
    ada_before = _snapshot(engine, ada)
    ben_before = _snapshot(engine, ben)

    resp = _remove(client, ada, "Ada Lovelace")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": ada, "applications": 3, "documents": 2}
    assert _surviving(engine, ada_before) == NOTHING
    for d in ada_dirs:
        assert not d.exists()
    assert not _staging(fake_settings.data_dir, ada).exists()
    assert _surviving(engine, ben_before) == ben_before
    assert (ben_dir / "resume.pdf").is_file()
    assert [p["id"] for p in client.get("/api/profiles").json()] == [ben]


def test_a_person_with_nothing_is_removed(client, engine):
    pid = _person(engine, "Ada", documents=0)

    resp = _remove(client, pid, "Ada")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": pid, "applications": 0, "documents": 0}
    assert client.get(f"/api/profiles/{pid}").status_code == 404


# --- active work -----------------------------------------------------------


def test_recent_active_work_is_409_and_listed(client, engine, fake_settings):
    ada = _person(engine, "Ada")
    fetching = _application(engine, ada, status="fetching", minutes_ago=1,
                            company="Northwind Labs")
    queued = _application(engine, ada, status="queued", minutes_ago=14,
                          url="https://jobs.example.com/queued")
    _application(engine, ada, status="ready")
    ada_dir = _export_dir(fake_settings.data_dir, fetching)
    before = _snapshot(engine, ada)

    resp = _remove(client, ada, "Ada")

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail["message"], str) and detail["message"]
    assert detail["blocking"] == [
        {"id": fetching, "label": "Northwind Labs", "status": "fetching"},
        {"id": queued, "label": "https://jobs.example.com/queued", "status": "queued"},
    ]
    assert _surviving(engine, before) == before
    assert (ada_dir / "resume.pdf").is_file()


@pytest.mark.parametrize("status", ["queued", "fetching", "researching", "tailoring", "rendering"])
def test_every_active_status_blocks_while_recent(client, engine, status):
    ada = _person(engine, "Ada")
    app_id = _application(engine, ada, status=status, minutes_ago=2)

    resp = _remove(client, ada, "Ada")

    assert resp.status_code == 409
    assert [b["id"] for b in resp.json()["detail"]["blocking"]] == [app_id]


def test_stale_active_rows_do_not_block_and_are_removed(client, engine):
    ada = _person(engine, "Ada")
    # A pipeline run killed by a server restart, and a row an MCP agent
    # parked in tailoring and never finished.
    _application(engine, ada, status="fetching", minutes_ago=16)
    _application(engine, ada, status="tailoring", minutes_ago=60 * 24)
    before = _snapshot(engine, ada)

    resp = _remove(client, ada, "Ada")

    assert resp.status_code == 200, resp.text
    assert resp.json()["applications"] == 2
    assert _surviving(engine, before) == NOTHING


def test_blocking_applications_uses_the_fifteen_minute_window(engine):
    ada = _person(engine, "Ada")
    app_id = _application(engine, ada, status="rendering")
    with Session(engine) as s:
        touched = s.get(Application, app_id).updated_at

        recent = removal.blocking_applications(s, ada, now=touched + timedelta(minutes=14))
        stale = removal.blocking_applications(s, ada, now=touched + timedelta(minutes=16))
        aware = removal.blocking_applications(
            s, ada, now=touched.replace(tzinfo=timezone.utc) + timedelta(minutes=1))

    assert [a.id for a in recent] == [app_id]
    assert stale == []
    assert [a.id for a in aware] == [app_id]


def test_blocking_applications_ignores_other_people_and_idle_statuses(engine):
    ada = _person(engine, "Ada")
    ben = _person(engine, "Ben")
    _application(engine, ben, status="fetching")
    for status in ("not_started", "ready", "needs_paste", "error"):
        _application(engine, ada, status=status)

    with Session(engine) as s:
        assert removal.blocking_applications(s, ada) == []


# --- files -----------------------------------------------------------------


def test_a_locked_export_directory_removes_nothing(client, engine, fake_settings, monkeypatch):
    ada = _person(engine, "Ada")
    first = _application(engine, ada)
    second = _application(engine, ada)
    first_dir = _export_dir(fake_settings.data_dir, first)
    second_dir = _export_dir(fake_settings.data_dir, second)
    before = _snapshot(engine, ada)

    real_rename = removal.os.rename

    def rename(src, dst, *args, **kwargs):
        # Windows refuses to move a directory while a file inside is open.
        if Path(src) == second_dir:
            raise PermissionError(13, "The process cannot access the file", str(src))
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(removal.os, "rename", rename)

    resp = _remove(client, ada, "Ada")

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail["message"], str) and detail["message"]
    assert len(detail["blocking"]) == 1
    assert detail["blocking"][0]["id"] == second
    assert detail["blocking"][0]["status"] == "locked"
    assert Path(detail["blocking"][0]["label"]) == second_dir
    # The first directory was moved into staging, then moved back.
    assert (first_dir / "resume.pdf").is_file()
    assert (second_dir / "resume.pdf").is_file()
    assert not _staging(fake_settings.data_dir, ada).exists()
    assert _surviving(engine, before) == before


def test_a_staging_cleanup_failure_is_logged_not_raised(
        client, engine, fake_settings, monkeypatch, caplog):
    ada = _person(engine, "Ada")
    app_id = _application(engine, ada)
    _export_dir(fake_settings.data_dir, app_id)
    before = _snapshot(engine, ada)

    def rmtree(path, *args, **kwargs):
        raise OSError("file in use")

    monkeypatch.setattr(removal.shutil, "rmtree", rmtree)

    with caplog.at_level(logging.WARNING, logger=removal.__name__):
        resp = _remove(client, ada, "Ada")

    assert resp.status_code == 200, resp.text
    assert _surviving(engine, before) == NOTHING
    staging = _staging(fake_settings.data_dir, ada)
    assert (staging / str(app_id) / "resume.pdf").is_file()  # left behind, logged
    assert any(str(staging) in r.getMessage() for r in caplog.records)


def test_a_leftover_staging_directory_is_cleared_first(client, engine, fake_settings):
    ada = _person(engine, "Ada")
    app_id = _application(engine, ada)
    _export_dir(fake_settings.data_dir, app_id)
    # Left by an earlier removal, of a person who had the same id, whose
    # cleanup failed. Its rows are long gone.
    leftover = _staging(fake_settings.data_dir, ada) / str(app_id)
    leftover.mkdir(parents=True)
    (leftover / "old.pdf").write_bytes(b"%PDF-1.4")

    resp = _remove(client, ada, "Ada")

    assert resp.status_code == 200, resp.text
    assert not _staging(fake_settings.data_dir, ada).exists()
    assert not (Path(fake_settings.data_dir) / "exports" / str(app_id)).exists()
```

Notes on the fixtures: `client`, `engine` and `fake_settings` come from `tests/conftest.py`. `client` is built on the same `engine`, and `fake_settings.data_dir` is the app's `data_dir`, so `exports/` is `tmp_path/exports`. Rows are written directly with `Session(engine)` rather than through batch create, because the conftest `client` does not stub `pipeline.process_application`, and a batch create would start a real (fake-mode) pipeline run.

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_person_removal.py -v`
Expected: `21 failed`. Route tests get `405 Method Not Allowed` (no DELETE on `/api/profiles/{id}` yet). The `blocking_applications` tests raise `AttributeError: module 'backend.app.services.removal' has no attribute 'blocking_applications'`. The locked and cleanup tests raise `AttributeError` for `removal.os` / `removal.shutil`.

- [ ] **Step 3: Extend `backend/app/services/removal.py`**

3a. Replace the import block that Task 4 wrote. Current code:

```python
from __future__ import annotations

from sqlmodel import Session, select

from ..models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    Job,
    ResearchBrief,
)
```

Replacement:

```python
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, select

from ..models import (
    Application,
    ApplicationEvent,
    ApplicationVersion,
    Job,
    Profile,
    ResearchBrief,
    SourceDocument,
    _utcnow,
    get_parsed,
)

logger = logging.getLogger(__name__)

# Statuses in which something may still be writing to the application: the
# pipeline (queued..rendering) or an MCP agent that parked it in tailoring.
ACTIVE_STATUSES = ("queued", "fetching", "researching", "tailoring", "rendering")
# The pipeline stamps updated_at on every transition, so a row in an active
# status that has not moved for this long is abandoned (a server restart kills
# background tasks; an agent can walk away from a parked row). Without a
# cutoff, one stuck row would make a person impossible to remove.
STALE_AFTER = timedelta(minutes=15)


class RemovalBlocked(Exception):
    """Removing a person was refused and nothing was deleted.

    `detail` is the 409 body: {"message": str, "blocking": [{"id", "label",
    "status"}]}. For active work each entry is an application (label: its
    company, else its URL); for a locked export it is the application whose
    directory could not be moved (label: the path, status "locked").
    """

    def __init__(self, detail: dict):
        super().__init__(detail["message"])
        self.detail = detail
```

3b. Append the rest after `delete_application_rows`. Its last lines are currently:

```python
    job = session.get(Job, app_row.job_id)
    session.delete(app_row)
    if job is not None:
        session.delete(job)
```

Replace them with the same lines followed by the new functions:

```python
    job = session.get(Job, app_row.job_id)
    session.delete(app_row)
    if job is not None:
        session.delete(job)


def _naive_utc(now: datetime | None) -> datetime:
    """`now` in the stored convention (naive UTC); the current time if None."""
    if now is None:
        return _utcnow()
    if now.tzinfo is None:
        return now
    return now.astimezone(timezone.utc).replace(tzinfo=None)


def blocking_applications(session: Session, profile_id: int,
                          now: datetime | None = None) -> list[Application]:
    """Applications of the profile in ACTIVE_STATUSES whose updated_at is within STALE_AFTER of now."""
    cutoff = _naive_utc(now) - STALE_AFTER
    rows = session.exec(
        select(Application)
        .where(Application.profile_id == profile_id)
        .where(Application.status.in_(ACTIVE_STATUSES))
        .order_by(Application.id)
    ).all()
    return [row for row in rows if row.updated_at > cutoff]


def _label(session: Session, app_row: Application) -> str:
    job = session.get(Job, app_row.job_id)
    if job is None:
        return f"application {app_row.id}"
    parsed = get_parsed(job)
    if parsed is not None and parsed.company:
        return parsed.company
    return job.url


def _move_back(moved: list[tuple[Path, Path]], staging: Path) -> None:
    """Undo the staging renames, newest first, then drop the empty staging dir."""
    for source, target in reversed(moved):
        try:
            os.rename(target, source)
        except OSError:
            logger.exception("could not move %s back to %s", target, source)
    try:
        staging.rmdir()
    except OSError:
        pass  # absent, or not empty because a move back failed (logged above)


def remove_person(session: Session, data_dir: Path, profile: Profile,
                  now: datetime | None = None) -> dict:
    """Stage export dirs by rename into exports/.removing-<profile_id>/<id>
    (roll back and raise RemovalBlocked on any rename failure), delete rows in
    one transaction (applications via delete_application_rows, then the
    profile's SourceDocuments, then the profile), commit, then rmtree the
    staging dir (log, do not raise, on failure). Returns
    {"deleted": profile_id, "applications": n, "documents": m}."""
    profile_id = profile.id

    blocking = blocking_applications(session, profile_id, now)
    if blocking:
        raise RemovalBlocked({
            "message": "These applications are still being worked on. Wait "
                       "for them to finish, then try again.",
            "blocking": [
                {"id": row.id, "label": _label(session, row), "status": row.status}
                for row in blocking
            ],
        })

    apps = list(session.exec(
        select(Application)
        .where(Application.profile_id == profile_id)
        .order_by(Application.id)
    ).all())
    docs = list(session.exec(
        select(SourceDocument).where(SourceDocument.profile_id == profile_id)
    ).all())

    # Files first, by rename: a rename either happens or it does not, so a
    # directory Windows refuses to move (a file inside is open) stops the
    # removal while every earlier move can still be undone. Paths are built
    # from data_dir and integer ids only.
    exports_dir = Path(data_dir) / "exports"
    staging = exports_dir / f".removing-{profile_id}"
    if staging.exists():
        # Left by an earlier removal whose cleanup failed; its rows are gone.
        try:
            shutil.rmtree(staging)
        except OSError:
            logger.warning("could not clear leftover %s", staging, exc_info=True)
    moved: list[tuple[Path, Path]] = []
    for row in apps:
        source = exports_dir / str(row.id)
        if not source.is_dir():
            continue
        target = staging / str(row.id)
        try:
            staging.mkdir(parents=True, exist_ok=True)
            os.rename(source, target)
        except OSError as exc:
            _move_back(moved, staging)
            raise RemovalBlocked({
                "message": f"Could not remove the exported files for "
                           f"application {row.id}: a file appears to be open "
                           f"elsewhere (e.g. a PDF viewer). Close it and try "
                           f"again. Nothing was removed.",
                "blocking": [{
                    "id": row.id,
                    "label": str(exc.filename or source),
                    "status": "locked",
                }],
            }) from exc
        moved.append((source, target))

    try:
        for row in apps:
            delete_application_rows(session, row)
        for doc in docs:
            session.delete(doc)
        session.delete(profile)
        session.commit()
    except Exception:
        session.rollback()
        _move_back(moved, staging)
        raise

    if staging.exists():
        try:
            shutil.rmtree(staging)
        except OSError:
            logger.warning(
                "removed profile %s but could not delete %s; delete it by hand",
                profile_id, staging, exc_info=True,
            )

    return {"deleted": profile_id, "applications": len(apps), "documents": len(docs)}
```

- [ ] **Step 4: Add the route in `backend/app/api/profiles.py`**

4a. Current import line:

```python
from ..services import intake
```

Replacement:

```python
from ..services import intake, removal
```

4b. Add `delete_profile` directly after `update_profile`. The end of `update_profile` is currently (unchanged by Tasks 1 to 3):

```python
    if body.voice_notes is not None:
        profile.voice_notes = body.voice_notes
    profile.updated_at = _utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile_detail(session, profile)
```

Replace it with the same lines followed by the new route:

```python
    if body.voice_notes is not None:
        profile.voice_notes = body.voice_notes
    profile.updated_at = _utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile_detail(session, profile)


@router.delete("/profiles/{profile_id}")
def delete_profile(
    profile_id: int,
    request: Request,
    confirm_name: Optional[str] = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Permanently remove a person: their applications (archived included,
    with each one's job, research, versions and timeline), their documents,
    the profile, and their exported files.

    The typed-name check is here, not only in the UI, so a stray call cannot
    remove anyone. Recent pipeline or parked-MCP work refuses with 409 (see
    removal.remove_person), as does an export directory that cannot be moved.
    """
    profile = _get_profile_or_404(session, profile_id)
    if confirm_name is None or not confirm_name.strip() or confirm_name != profile.name:
        raise HTTPException(
            status_code=422, detail="confirm_name must equal the person's name"
        )
    try:
        return removal.remove_person(
            session, request.app.state.settings.data_dir, profile
        )
    except removal.RemovalBlocked as exc:
        raise HTTPException(status_code=409, detail=exc.detail)
```

`HTTPException(detail=<dict>)` serializes as `{"detail": {"message": ..., "blocking": [...]}}`, which is the body the Profiles screen (Task 16) reads.

- [ ] **Step 5: Run the tests and the wider suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_person_removal.py -v`
Expected: `21 passed`.

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_removal_rows.py tests/test_document_removal.py tests/test_build_keeps_contact.py tests/test_profile_payload.py tests/test_tracker.py tests/test_api.py -q`
Expected: all pass.

Run: `.venv/Scripts/python.exe -m pytest -m "not pdf" -q`
Expected: no failures.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/removal.py backend/app/api/profiles.py tests/test_person_removal.py
git commit -m "$(cat <<'EOF'
feat: remove a person with a typed-name confirmation

DELETE /api/profiles/{id}?confirm_name=<name> deletes the person's
applications (with jobs, research, versions and timeline), documents,
profile and export directories. It refuses with 422 unless the name
matches exactly, and with 409 while an application was active in the last
15 minutes or an export directory cannot be moved. Export directories are
staged by rename, so a locked file leaves everything in place.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```


---

### Task 6: Per-person settings column, typed helpers and the `settings_for` resolver

**Files:**
- Modify: `backend/app/models.py` (the `import` block; two new constants after `EVENT_KINDS`; one field on `class Profile`; three helpers after `set_master_profile`)
- Create: `backend/app/services/person_settings.py`
- Test: `tests/test_person_settings.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks. Uses what exists today: `backend.app.config.load_user_settings(data_dir) -> dict`, `backend.app.config.DEFAULT_USER_SETTINGS`, `backend.app.config.save_user_settings`, `backend.app.db._column_ddl`, `backend.app.db.init_db`, `backend.app.db.get_engine`, `backend.app.services.render.TEMPLATES`, `backend.app.api.settings.DEPTHS`, `backend.app.api.settings.PAGE_SIZES`.
- Produces (used by Tasks 7 and 8):
  - `backend.app.models.PROFILE_SETTING_KEYS = ("default_template", "default_depth", "page_size")`
  - `backend.app.models.PROFILE_SETTING_VALUES = {"default_depth": ("quick", "standard", "deep"), "page_size": ("Letter", "A4")}` (new name, added so the helpers can keep spec 5.1's "valid values" rule without importing the API layer)
  - `backend.app.models.Profile.settings_json: str = "{}"` (declared right after `voice_notes`; `_add_missing_columns` emits `settings_json VARCHAR NOT NULL DEFAULT '{}'`)
  - `backend.app.models.get_profile_settings(profile: Profile) -> dict[str, str]`
  - `backend.app.models.set_profile_settings(profile: Profile, values: dict[str, str]) -> None`
  - `backend.app.services.person_settings.settings_for(data_dir: Path, profile: Profile | None) -> dict[str, str]`
- Choices made where the contract left room:
  - "str values" means non-empty `str`. An empty string is treated as unset, both when stored and when read, so a blank can never override a real app-wide value.
  - Spec 5.1 says the helpers accept only the known keys "with valid values". Validity is enforced in two places, because `models.py` must not load the template registry:
    - `default_depth` and `page_size` are checked in the helpers against `PROFILE_SETTING_VALUES`, on write and on read. A value outside the tuple is dropped (not an error), so a hand-edited or stale row never reaches a render. `PROFILE_SETTING_VALUES` duplicates `api/settings.py`'s `DEPTHS` and `PAGE_SIZES`; a test asserts the two agree, so widening one without the other fails the suite.
    - `default_template` is kept by the helpers as any non-empty string and checked by `settings_for` against `render.TEMPLATES`. A template that is not registered (a typo, or a template directory removed after it was chosen) is dropped there, so the person inherits the app-wide template. `person_settings.py` imports `TEMPLATES` at module top, as `api/settings.py` already does; this creates no import cycle, because `services/render.py` imports only `..schemas`.
  - Both helpers return and store keys in `PROFILE_SETTING_KEYS` order; `set_profile_settings` writes `json.dumps(...)` with default separators (so `{"page_size": "A4"}` is stored as `'{"page_size": "A4"}'`).
  - Malformed JSON, and valid JSON that is not an object (`[1, 2]`, `"A4"`, `null`), all read as `{}`.
  - `api/settings.py` still validates before calling `set_profile_settings` and returns 422 for a bad value (Task 7). The helpers only drop bad values, so they never raise.
  - `settings_for` accepts `data_dir` as `Path` or `str` (it wraps it in `Path`) and always returns a fresh dict. It does not validate the app-wide file's values; `load_user_settings` behaves exactly as today.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_person_settings.py` with exactly this content:

```python
"""Per-person settings (spec 5.1, 5.2): the Profile.settings_json column, its
typed helpers, and the one resolver every render and default goes through."""
from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session

from backend.app.api.settings import DEPTHS, PAGE_SIZES
from backend.app.config import DEFAULT_USER_SETTINGS, save_user_settings
from backend.app.db import _column_ddl, get_engine, init_db
from backend.app.models import (
    PROFILE_SETTING_KEYS,
    PROFILE_SETTING_VALUES,
    Profile,
    get_profile_settings,
    set_profile_settings,
)
from backend.app.services.person_settings import settings_for


# --- the helpers ---------------------------------------------------------


def test_the_keys_are_the_app_wide_settings_keys():
    assert PROFILE_SETTING_KEYS == ("default_template", "default_depth", "page_size")
    assert set(PROFILE_SETTING_KEYS) == set(DEFAULT_USER_SETTINGS)


def test_the_allowed_values_are_the_ones_the_settings_api_accepts():
    # models.py cannot import api/settings.py, so the tuples are written twice.
    # Widening one without the other would make the API accept a value that
    # set_profile_settings then silently drops.
    assert PROFILE_SETTING_VALUES == {"default_depth": DEPTHS, "page_size": PAGE_SIZES}


def test_a_new_profile_has_no_settings_of_its_own():
    profile = Profile(name="Ada")
    assert profile.settings_json == "{}"
    assert get_profile_settings(profile) == {}


def test_set_then_get_round_trips_the_known_keys():
    profile = Profile(name="Ada")
    set_profile_settings(profile, {"default_template": "terminal", "page_size": "A4"})
    assert get_profile_settings(profile) == {
        "default_template": "terminal",
        "page_size": "A4",
    }


def test_set_replaces_rather_than_merges():
    profile = Profile(name="Ada")
    set_profile_settings(profile, {"page_size": "A4"})
    set_profile_settings(profile, {"default_depth": "deep"})
    assert get_profile_settings(profile) == {"default_depth": "deep"}


def test_set_stores_only_known_keys_with_non_empty_string_values():
    profile = Profile(name="Ada")
    set_profile_settings(
        profile,
        {
            "page_size": "A4",
            "default_depth": 3,          # not a string
            "default_template": "",      # empty means unset
            "bogus": "x",                # not a setting
        },
    )
    assert get_profile_settings(profile) == {"page_size": "A4"}
    assert profile.settings_json == '{"page_size": "A4"}'


def test_set_drops_invalid_values():
    profile = Profile(name="Ada")
    set_profile_settings(
        profile,
        {"page_size": "Tabloid", "default_depth": "extreme", "default_template": "slate"},
    )
    assert get_profile_settings(profile) == {"default_template": "slate"}
    assert profile.settings_json == '{"default_template": "slate"}'


def test_get_ignores_unknown_keys_and_non_string_values_in_the_column():
    profile = Profile(
        name="Ada",
        settings_json='{"page_size": 3, "bogus": "x", "default_depth": "deep"}',
    )
    assert get_profile_settings(profile) == {"default_depth": "deep"}


def test_get_drops_invalid_values_already_in_the_column():
    # A row written by hand, or before a value was retired, must not reach a render.
    profile = Profile(
        name="Ada",
        settings_json='{"page_size": "Tabloid", "default_depth": "extreme", "default_template": "terminal"}',
    )
    assert get_profile_settings(profile) == {"default_template": "terminal"}


def test_malformed_or_non_object_json_reads_as_no_settings():
    for raw in ("not json", "[1, 2]", '"A4"', "null", ""):
        profile = Profile(name="Ada", settings_json=raw)
        assert get_profile_settings(profile) == {}, raw


def test_settings_persist_through_the_database(engine):
    with Session(engine) as session:
        profile = Profile(name="Ada")
        set_profile_settings(profile, {"page_size": "A4"})
        session.add(profile)
        session.commit()
        session.refresh(profile)
        profile_id = profile.id

    with Session(engine) as session:
        assert get_profile_settings(session.get(Profile, profile_id)) == {"page_size": "A4"}


# --- the resolver --------------------------------------------------------


def test_settings_for_no_profile_is_the_app_wide_values(tmp_path):
    assert settings_for(tmp_path, None) == DEFAULT_USER_SETTINGS

    save_user_settings(tmp_path, {"page_size": "A4"})
    assert settings_for(tmp_path, None) == {**DEFAULT_USER_SETTINGS, "page_size": "A4"}


def test_a_profile_without_its_own_values_inherits_the_app_wide_ones(tmp_path):
    save_user_settings(tmp_path, {"default_template": "terminal", "page_size": "A4"})
    assert settings_for(tmp_path, Profile(name="Ada")) == {
        "default_template": "terminal",
        "default_depth": "standard",
        "page_size": "A4",
    }


def test_the_profiles_own_values_win_key_by_key(tmp_path):
    save_user_settings(tmp_path, {"default_template": "terminal", "page_size": "A4"})
    profile = Profile(name="Ada")
    set_profile_settings(profile, {"page_size": "Letter", "default_depth": "deep"})
    assert settings_for(tmp_path, profile) == {
        "default_template": "terminal",   # app-wide, not overridden
        "default_depth": "deep",          # the person's own
        "page_size": "Letter",            # the person's own beats app-wide A4
    }


def test_settings_for_ignores_an_unknown_template(tmp_path):
    save_user_settings(tmp_path, {"default_template": "terminal"})
    profile = Profile(
        name="Ada",
        settings_json='{"default_template": "gone", "page_size": "A4"}',
    )
    resolved = settings_for(tmp_path, profile)
    assert resolved["default_template"] == "terminal"   # the app-wide value, not "gone"
    assert resolved["page_size"] == "A4"                # the person's other values still apply


def test_a_damaged_profile_column_falls_back_to_the_app_wide_values(tmp_path):
    save_user_settings(tmp_path, {"page_size": "A4"})
    profile = Profile(name="Ada", settings_json="{broken")
    assert settings_for(tmp_path, profile)["page_size"] == "A4"


def test_settings_for_returns_a_fresh_dict(tmp_path):
    first = settings_for(tmp_path, Profile(name="Ada"))
    first["page_size"] = "Tabloid"
    assert settings_for(tmp_path, Profile(name="Ada"))["page_size"] == "Letter"
    assert DEFAULT_USER_SETTINGS["page_size"] == "Letter"


# --- the migration -------------------------------------------------------

# The `profile` table exactly as it existed before settings_json.
PRE_SETTINGS_PROFILE_DDL = """
CREATE TABLE profile (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    contact_json VARCHAR NOT NULL,
    master_profile_json VARCHAR NOT NULL,
    voice_notes VARCHAR NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""

PRE_SETTINGS_PROFILE_ROWS = """
INSERT INTO profile VALUES
    (1, 'Ada', '{}', '{}', '', '2026-01-01 00:00:00.000000', '2026-01-01 00:00:00.000000')
"""


def _columns(engine, table: str) -> set[str]:
    with engine.begin() as conn:
        return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}


def test_the_column_is_added_as_not_null_with_an_empty_object_default():
    assert _column_ddl(Profile.__table__.c.settings_json) == (
        "settings_json VARCHAR NOT NULL DEFAULT '{}'"
    )


def test_settings_json_is_added_to_a_pre_existing_profile_table(tmp_path):
    engine = get_engine(tmp_path / "old_profile.db")
    with engine.begin() as conn:
        conn.execute(text(PRE_SETTINGS_PROFILE_DDL))
        conn.execute(text(PRE_SETTINGS_PROFILE_ROWS))
    assert "settings_json" not in _columns(engine, "profile")

    init_db(engine)

    assert "settings_json" in _columns(engine, "profile")
    with engine.begin() as conn:
        value = conn.execute(text("SELECT settings_json FROM profile WHERE id=1")).scalar()
    assert value == "{}", "the existing row must get the default, not NULL"
    with Session(engine) as session:
        assert get_profile_settings(session.get(Profile, 1)) == {}

    init_db(engine)  # idempotent: a second pass adds nothing and does not raise
    assert "settings_json" in _columns(engine, "profile")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_person_settings.py -v`

Expected: collection fails with
`ImportError: cannot import name 'PROFILE_SETTING_KEYS' from 'backend.app.models'`
and pytest reports `1 error during collection`.

- [ ] **Step 3: Add the column, the constants and the helpers to `backend/app/models.py`**

Four edits. No earlier task touches this file.

Edit 1 (imports). Current:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
```

Replace with:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
```

Edit 2 (the constants, right after `EVENT_KINDS`). Current:

```python
EVENT_KINDS = (
    "applied",
    "callback",
    "interview",
    "offer",
    "rejection",
    "followup",
    "note",
)
```

Replace with:

```python
EVENT_KINDS = (
    "applied",
    "callback",
    "interview",
    "offer",
    "rejection",
    "followup",
    "note",
)

# The settings a person can hold for themselves: the same three keys as the
# app-wide data/settings.json (config.DEFAULT_USER_SETTINGS). A key the person
# has not set comes from the app-wide file (services/person_settings.py).
PROFILE_SETTING_KEYS = ("default_template", "default_depth", "page_size")

# The allowed values of the keys that have a fixed set. These must equal
# api/settings.py's DEPTHS and PAGE_SIZES (tests/test_person_settings.py
# checks). default_template is not listed: the template registry is loaded by
# services/render.py, so services/person_settings.settings_for checks it.
PROFILE_SETTING_VALUES = {
    "default_depth": ("quick", "standard", "deep"),
    "page_size": ("Letter", "A4"),
}
```

Edit 3 (the field on `Profile`, after `voice_notes`). Current:

```python
    voice_notes: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SourceDocument(SQLModel, table=True):
```

Replace with:

```python
    voice_notes: str = ""
    # This person's own settings, a JSON object over PROFILE_SETTING_KEYS.
    # "{}" means every value comes from the app-wide data/settings.json. Read
    # it through services.person_settings.settings_for, which does the overlay.
    settings_json: str = "{}"
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SourceDocument(SQLModel, table=True):
```

Edit 4 (the typed helpers, after `set_master_profile`). Current:

```python
def set_master_profile(p: Profile, mp: MasterProfile) -> None:
    p.master_profile_json = mp.model_dump_json()
```

Replace with:

```python
def set_master_profile(p: Profile, mp: MasterProfile) -> None:
    p.master_profile_json = mp.model_dump_json()


def _known_settings(values: object) -> dict[str, str]:
    """The PROFILE_SETTING_KEYS entries of `values` that hold a non-empty str
    allowed by PROFILE_SETTING_VALUES, in PROFILE_SETTING_KEYS order."""
    if not isinstance(values, dict):
        return {}
    known: dict[str, str] = {}
    for key in PROFILE_SETTING_KEYS:
        value = values.get(key)
        if not isinstance(value, str) or not value:
            continue
        allowed = PROFILE_SETTING_VALUES.get(key)
        if allowed is not None and value not in allowed:
            continue
        known[key] = value
    return known


def get_profile_settings(profile: Profile) -> dict[str, str]:
    """The valid values this person set for themselves (possibly none).

    Malformed or non-object JSON reads as no values, and a value outside
    PROFILE_SETTING_VALUES is dropped, so a damaged row falls back to the
    app-wide settings instead of failing every render.
    """
    try:
        stored = json.loads(profile.settings_json or "{}")
    except ValueError:
        return {}
    return _known_settings(stored)


def set_profile_settings(profile: Profile, values: dict[str, str]) -> None:
    """Replace this person's own values with the valid known keys of `values`.

    Invalid values are dropped, not raised: api/settings.py rejects them with
    a 422 before calling this. default_template is kept as any non-empty str;
    settings_for ignores one that is not in the template registry.
    """
    profile.settings_json = json.dumps(_known_settings(values))
```

No migration code is needed: `init_db` already runs `_add_missing_columns`, and the scalar default `"{}"` makes it emit `ALTER TABLE profile ADD COLUMN settings_json VARCHAR NOT NULL DEFAULT '{}'`, so existing rows need no backfill.

- [ ] **Step 4: Create the resolver `backend/app/services/person_settings.py`**

```python
"""Which settings apply to a person: the one resolver (spec 5.2).

Every render and every web default reads settings through settings_for with
the application's OWNER, never with whoever is picked in a browser. That is
what keeps an MCP agent's renders independent of the web app's person picker.
"""
from __future__ import annotations

from pathlib import Path

from ..config import load_user_settings
from ..models import Profile, get_profile_settings
from .render import TEMPLATES


def settings_for(data_dir: Path, profile: Profile | None) -> dict[str, str]:
    """load_user_settings(data_dir) overlaid with get_profile_settings(profile).

    That is DEFAULT_USER_SETTINGS, then data/settings.json, then the person's
    own values, key by key. With no profile it is the app-wide values alone.
    A person's default_template that is not a registered template (a typo, or
    a template removed after it was chosen) is ignored, so the app-wide one
    applies. Always a fresh dict.
    """
    values = load_user_settings(Path(data_dir))
    if profile is not None:
        own = get_profile_settings(profile)
        if "default_template" in own and own["default_template"] not in TEMPLATES:
            del own["default_template"]
        values.update(own)
    return values
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_person_settings.py -v`

Expected: `19 passed`.

Then the neighbouring suites (migration, models, db, config) and the fast suite:

Run: `.venv/Scripts/python.exe -m pytest tests/test_migration.py tests/test_models.py tests/test_db.py tests/test_config.py -q`
Expected: all pass (the existing `test_voice_notes_is_added_to_a_pre_existing_profile_table` now also gets `settings_json` added to its old table, which it does not assert against).

Run: `.venv/Scripts/python.exe -m pytest -m "not pdf" -q`
Expected: all pass. No existing test needs editing: nothing reads the new column yet, and every existing `Profile(...)` gets the `"{}"` default.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/app/services/person_settings.py tests/test_person_settings.py
git commit -m "$(cat <<'EOF'
feat: per-person settings column and settings_for resolver

Profile.settings_json holds a person's own default_template, default_depth
and page_size; "{}" inherits the app-wide data/settings.json. The helpers
keep only known keys with allowed values, settings_for ignores a template
that is not registered, and it is the one place later consumers read
settings from.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```


---

### Task 7: `GET/PUT /api/settings?profile_id=N` read and write one person's settings

**Files:**
- Modify: `backend/app/api/settings.py` (module docstring and imports; `_settings_payload` and `read_settings`; `write_settings`)
- Test: `tests/test_settings_per_person.py` (new)

**Interfaces:**
- Consumes (Task 6): `backend.app.models.PROFILE_SETTING_KEYS`, `backend.app.models.get_profile_settings(profile) -> dict[str, str]`, `backend.app.models.set_profile_settings(profile, values) -> None`, `backend.app.services.person_settings.settings_for(data_dir, profile) -> dict[str, str]`. Also existing: `backend.app.db.get_session`, `backend.app.models._utcnow`.
- Produces (used by Task 10's `getSettings(profileId?)` / `updateSettings(patch, profileId?)` and the screens in Tasks 14 and 18):
  - `GET /api/settings?profile_id=N` returns `{"api_key_set": bool, "fake_mode": bool, "default_template": str, "default_depth": str, "page_size": str}`, the three values being `settings_for(data_dir, profile)`.
  - `PUT /api/settings?profile_id=N` with body `{default_template?, default_depth?, page_size?}` validates exactly as the app-wide PUT (same 422 details), stores `{**get_profile_settings(profile), **changes}` on that profile only (never touches `data/settings.json`), bumps `profile.updated_at`, commits, and returns the same shape with the person's effective values.
  - Unknown `profile_id` on either route: 404 `{"detail": "profile not found"}`.
  - No `profile_id`: unchanged from today (reads and writes `data/settings.json`).
- Choices made where the contract left room:
  - On PUT, the unknown-profile 404 is checked before the body is validated, so `PUT ?profile_id=9999` with an invalid value is a 404, not a 422.
  - Only the keys present (non-null) in the PUT body become the person's own values; unsent keys keep following the app-wide file. A person's row therefore never freezes a copy of the app-wide values.
  - A per-person PUT bumps `Profile.updated_at` (as `PUT /api/profiles/{id}` does); `created_at` is untouched, so the frontend's `{id, created_at}` check (spec 4.1) is unaffected.
  - The new private helper `_profile_or_404(session, profile_id) -> Profile | None` lives in settings.py (returns `None` when `profile_id` is `None`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_per_person.py` with exactly this content (it uses the conftest `client`, whose `fake_settings` has `anthropic_api_key=None`, `fake_mode=True` and `data_dir=tmp_path`):

```python
"""GET/PUT /api/settings?profile_id=N (spec 5.3): a person's effective
settings, and writes that land on that person only."""
from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from backend.app.models import Profile, get_profile_settings


def _person(client, name: str) -> int:
    resp = client.post("/api/profiles", json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _own_values(client, profile_id: int) -> dict[str, str]:
    with Session(client.app.state.engine) as session:
        return get_profile_settings(session.get(Profile, profile_id))


def _app_wide_file(client) -> Path:
    return Path(client.app.state.settings.data_dir) / "settings.json"


def test_without_profile_id_the_shape_is_unchanged(client):
    assert client.get("/api/settings").json() == {
        "api_key_set": False,
        "fake_mode": True,
        "default_template": "slate",
        "default_depth": "standard",
        "page_size": "Letter",
    }
    resp = client.put("/api/settings", json={"page_size": "A4"})
    assert resp.status_code == 200
    assert resp.json()["page_size"] == "A4"
    assert _app_wide_file(client).exists()


def test_a_person_with_no_values_of_their_own_inherits_the_app_wide_ones(client):
    pid = _person(client, "Ada")
    client.put("/api/settings", json={"default_template": "terminal", "page_size": "A4"})

    resp = client.get("/api/settings", params={"profile_id": pid})
    assert resp.status_code == 200
    assert resp.json() == {
        "api_key_set": False,
        "fake_mode": True,
        "default_template": "terminal",
        "default_depth": "standard",
        "page_size": "A4",
    }


def test_person_round_trip_writes_the_person_and_not_the_app_wide_file(client):
    pid = _person(client, "Ada")

    resp = client.put(
        "/api/settings",
        params={"profile_id": pid},
        json={"default_template": "terminal", "page_size": "A4"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["default_template"] == "terminal"
    assert body["default_depth"] == "standard"
    assert body["page_size"] == "A4"
    assert set(body) == {
        "api_key_set", "fake_mode", "default_template", "default_depth", "page_size",
    }

    again = client.get("/api/settings", params={"profile_id": pid}).json()
    assert again["default_template"] == "terminal"
    assert again["page_size"] == "A4"

    assert _own_values(client, pid) == {"default_template": "terminal", "page_size": "A4"}
    assert not _app_wide_file(client).exists()
    assert client.get("/api/settings").json()["page_size"] == "Letter"


def test_a_person_put_merges_with_their_earlier_values_and_stores_only_what_was_sent(client):
    pid = _person(client, "Ada")
    client.put("/api/settings", params={"profile_id": pid}, json={"page_size": "A4"})
    client.put("/api/settings", params={"profile_id": pid}, json={"default_depth": "deep"})

    assert _own_values(client, pid) == {"default_depth": "deep", "page_size": "A4"}

    # default_template was never set for this person, so a later app-wide
    # change still reaches them: effective values are not frozen into the row.
    client.put("/api/settings", json={"default_template": "terminal"})
    effective = client.get("/api/settings", params={"profile_id": pid}).json()
    assert effective["default_template"] == "terminal"
    assert effective["default_depth"] == "deep"
    assert effective["page_size"] == "A4"


def test_two_people_keep_separate_values(client):
    ada = _person(client, "Ada")
    bea = _person(client, "Bea")
    client.put("/api/settings", params={"profile_id": ada}, json={"page_size": "A4"})
    client.put("/api/settings", params={"profile_id": bea}, json={"default_depth": "quick"})

    ada_now = client.get("/api/settings", params={"profile_id": ada}).json()
    bea_now = client.get("/api/settings", params={"profile_id": bea}).json()
    assert (ada_now["page_size"], ada_now["default_depth"]) == ("A4", "standard")
    assert (bea_now["page_size"], bea_now["default_depth"]) == ("Letter", "quick")


def test_person_put_validates_exactly_as_the_app_wide_put(client):
    pid = _person(client, "Ada")
    for bad in (
        {"default_depth": "extreme"},
        {"default_template": "papyrus"},
        {"page_size": "Legal"},
    ):
        resp = client.put("/api/settings", params={"profile_id": pid}, json=bad)
        assert resp.status_code == 422, bad
        assert resp.json()["detail"] == client.put("/api/settings", json=bad).json()["detail"]
    assert _own_values(client, pid) == {}


def test_an_unknown_person_is_404(client):
    get = client.get("/api/settings", params={"profile_id": 9999})
    assert get.status_code == 404
    assert get.json()["detail"] == "profile not found"

    put = client.put("/api/settings", params={"profile_id": 9999}, json={"page_size": "A4"})
    assert put.status_code == 404
    assert put.json()["detail"] == "profile not found"
    assert not _app_wide_file(client).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_per_person.py -v`

Expected: `4 failed, 3 passed`. Today FastAPI ignores the unknown `profile_id` query parameter, so every call reads and writes the app-wide file:
- `test_person_round_trip_writes_the_person_and_not_the_app_wide_file` FAILS: `assert {} == {'default_template': 'terminal', 'page_size': 'A4'}`
- `test_a_person_put_merges_with_their_earlier_values_and_stores_only_what_was_sent` FAILS: `assert {} == {'default_depth': 'deep', 'page_size': 'A4'}`
- `test_two_people_keep_separate_values` FAILS: `assert ('A4', 'quick') == ('A4', 'standard')`
- `test_an_unknown_person_is_404` FAILS: `assert 200 == 404`
- `test_without_profile_id_the_shape_is_unchanged`, `test_a_person_with_no_values_of_their_own_inherits_the_app_wide_ones` and `test_person_put_validates_exactly_as_the_app_wide_put` already pass (they pin behaviour that must survive the change).

- [ ] **Step 3: Update the imports in `backend/app/api/settings.py`**

No earlier task touches this file. Current:

```python
"""Settings routes: read/write user defaults, report API-key and fake-mode status."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import load_user_settings, save_user_settings
from ..services.render import TEMPLATES
```

Replace with:

```python
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
    Profile,
    _utcnow,
    get_profile_settings,
    set_profile_settings,
)
from ..services.person_settings import settings_for
from ..services.render import TEMPLATES
```

- [ ] **Step 4: Make the payload and the GET route person-aware**

Current:

```python
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
```

Replace with:

```python
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
```

- [ ] **Step 5: Make the PUT route write the person's own values**

Current:

```python
@router.put("/settings")
def write_settings(body: SettingsUpdate, request: Request) -> dict[str, Any]:
    if body.default_template is not None and body.default_template not in TEMPLATES:
```

Replace with:

```python
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
```

Then, at the end of the same function, current:

```python
    if body.page_size is not None and body.page_size not in PAGE_SIZES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid page size {body.page_size!r}; must be one of {list(PAGE_SIZES)}",
        )
    settings = request.app.state.settings
    current = load_user_settings(settings.data_dir)
```

Replace with:

```python
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
```

The three validation blocks between these two edits and the app-wide tail (the `for key in (...)` loop, `save_user_settings(...)`, `return _settings_payload(request)`) stay exactly as they are, so the no-`profile_id` path is unchanged.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_per_person.py -v`
Expected: `7 passed`.

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py tests/test_config.py tests/test_person_settings.py -q`
Expected: all pass, including the unchanged `tests/test_api.py::test_settings_round_trip` (no existing test needs editing).

Run: `.venv/Scripts/python.exe -m pytest -m "not pdf" -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/settings.py tests/test_settings_per_person.py
git commit -m "$(cat <<'EOF'
feat: per-person GET/PUT /api/settings?profile_id=N

With profile_id the routes read that person's effective settings and write
only the keys sent to that person's own values; unknown person is 404.
Without profile_id they behave exactly as before.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```


---

### Task 8: Every settings consumer uses the application's owner

**Files:**
- Modify: `backend/app/api/applications.py` (imports; `create_batch` defaults; `set_template` render; `update_content` render)
- Modify: `backend/app/services/pipeline.py` (imports; the render step of `_tailor_and_render`)
- Modify: `backend/mcp_ops.py` (imports; the render in `set_application_template`; the render in `save_tailored_resume`)
- Test: `tests/test_settings_owner.py` (new)

**Interfaces:**
- Consumes (Task 6): `backend.app.services.person_settings.settings_for(data_dir: Path, profile: Profile | None) -> dict[str, str]`, `backend.app.models.set_profile_settings(profile, values)`. Existing: `backend.app.services.render.export_application(application_id, resume, cover_md, contact, template, data_dir, page_size="Letter") -> Path`, `backend.mcp_ops.EXPORT_FILES`, `mcp_ops.create_application`, `mcp_ops.save_tailored_resume`, `mcp_ops.set_application_template`, `pipeline.process_application`.
- Produces: no new names. After this task `load_user_settings` is no longer imported by `api/applications.py`, `services/pipeline.py` or `mcp_ops.py`; each of the six call sites reads `settings_for(<data_dir>, <owner profile>)`:
  - `create_batch`: the `profile` it already loads from `body.profile_id` for its 404.
  - `set_template` and `update_content`: the `profile` each already loads with `session.get(Profile, app_row.profile_id)`.
  - `pipeline._tailor_and_render`: its `profile` parameter (both callers, `_run_from_research` and `regenerate_application`, pass the application's owner).
  - `mcp_ops.set_application_template` and `mcp_ops.save_tailored_resume`: the `profile` each already loads with `session.get(Profile, app.profile_id)`.
- Choices made where the contract left room: none beyond the above. Precedence in batch create is unchanged in shape: per-job value, then request `default_*`, then `settings_for` (person's own, then app-wide file, then built-in default). Per spec 5.4, MCP `create_application`/`queue_jobs` keep their own hard-coded defaults and are not touched here.
- Monkeypatch target: every caller reaches `export_application` through the render module object (`from ..services import pipeline, render` in `api/applications.py`, `from . import fetcher, render` in `services/pipeline.py`, `from .app.services import render` in `mcp_ops.py`, each calling `render.export_application(...)`), so a single `monkeypatch.setattr(render, "export_application", fake)` on `backend.app.services.render` intercepts all five render paths.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_owner.py` with exactly this content:

```python
"""Every settings consumer uses the application's OWNER (spec 5.2, 9).

Two people with different settings, one application each, through every path
that reads settings: batch create (template and depth), the pipeline render,
the web template switch and content save, and both MCP render paths (page
size). Every render caller reaches export_application through the render
module attribute (`from ..services import pipeline, render` in
api/applications.py, `from . import fetcher, render` in services/pipeline.py,
`from .app.services import render` in mcp_ops.py), so one monkeypatch on
`render.export_application` intercepts all of them.

The two page sizes are A4 and Letter, the only two there are, so each test
asserts BOTH people: reading the app-wide file gives both the same value, and
reading the wrong person gives one of them the other's.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session

from backend import mcp_ops
from backend.app.config import save_user_settings
from backend.app.models import (
    Application,
    Job,
    Profile,
    set_contact,
    set_master_profile,
    set_profile_settings,
)
from backend.app.schemas import TailorResult
from backend.app.services import pipeline, render
from backend.app.services.intake import IntakeResult

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"

POSTING_TEXT = (
    "Senior Backend Engineer at Northwind Labs. Python, FastAPI, PostgreSQL, "
    "event-driven pipelines. Remote friendly."
)

ADA_SETTINGS = {"default_template": "terminal", "default_depth": "deep", "page_size": "A4"}
BEA_SETTINGS = {"default_template": "ledger", "default_depth": "quick", "page_size": "Letter"}


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture()
def exports(monkeypatch) -> list[tuple[int, str]]:
    """Record (application_id, page_size) for every export; write stub files.

    The MCP paths list the export directory after rendering, so the stub
    writes the real file names.
    """
    calls: list[tuple[int, str]] = []

    def fake_export(application_id, resume, cover_md, contact, template, data_dir,
                    page_size="Letter"):
        calls.append((application_id, page_size))
        out = Path(data_dir) / "exports" / str(application_id)
        out.mkdir(parents=True, exist_ok=True)
        for name in mcp_ops.EXPORT_FILES:
            (out / name).write_bytes(b"%PDF-1.4 fake" if name.endswith(".pdf") else b"text")
        return out

    monkeypatch.setattr(render, "export_application", fake_export)
    return calls


@pytest.fixture()
def people(engine, claude_fake) -> dict[str, int]:
    """Ada (A4) and Bea (Letter), both with the intake fixture's master profile,
    which the tailor fixture's resume passes the truthfulness guard against."""
    intake, _usage = claude_fake.structured(
        task="intake", system="seed", user_content="seed", schema_model=IntakeResult
    )
    ids: dict[str, int] = {}
    with Session(engine) as session:
        for name, own in (("Ada", ADA_SETTINGS), ("Bea", BEA_SETTINGS)):
            profile = Profile(name=name)
            set_contact(profile, intake.contact)
            set_master_profile(profile, intake.master_profile)
            set_profile_settings(profile, own)
            session.add(profile)
            session.commit()
            session.refresh(profile)
            ids[name] = profile.id
    return ids


def _ready_application(engine, profile_id: int) -> int:
    """An application that already has content, so it can be re-rendered."""
    resume_json = TailorResult.model_validate(_fixture("tailor")).resume.model_dump_json()
    with Session(engine) as session:
        job = Job(url="https://jobs.example.com/senior-backend", raw_text=POSTING_TEXT)
        session.add(job)
        session.commit()
        session.refresh(job)
        app_row = Application(
            profile_id=profile_id,
            job_id=job.id,
            template="slate",
            status="ready",
            stage="drafted",
            resume_json=resume_json,
            cover_letter_md="Dear team,",
        )
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
        return app_row.id


def _batch(client, profile_id: int, **extra) -> dict:
    resp = client.post("/api/applications/batch", json={
        "profile_id": profile_id,
        "jobs": [{"url": "https://jobs.example.com/a"}],
        "generate": False,  # nothing scheduled: no pipeline run in this test
        **extra,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()[0]


# --- batch create: the person's default template and depth -----------------


def test_batch_create_uses_each_persons_default_template_and_depth(client, people):
    ada = _batch(client, people["Ada"])
    bea = _batch(client, people["Bea"])
    assert (ada["template"], ada["depth"]) == ("terminal", "deep")
    assert (bea["template"], bea["depth"]) == ("ledger", "quick")


def test_batch_create_request_values_still_beat_the_persons_defaults(client, people):
    from_body = _batch(
        client, people["Ada"], default_template="slate", default_depth="standard"
    )
    assert (from_body["template"], from_body["depth"]) == ("slate", "standard")

    resp = client.post("/api/applications/batch", json={
        "profile_id": people["Ada"],
        "jobs": [{"url": "https://jobs.example.com/b", "template": "ledger", "depth": "quick"}],
        "generate": False,
    })
    assert (resp.json()[0]["template"], resp.json()[0]["depth"]) == ("ledger", "quick")


def test_batch_create_for_a_person_without_own_values_uses_the_app_wide_ones(
    client, engine, fake_settings
):
    save_user_settings(fake_settings.data_dir, {"default_template": "terminal",
                                                "default_depth": "deep"})
    with Session(engine) as session:
        profile = Profile(name="Cy")
        session.add(profile)
        session.commit()
        session.refresh(profile)
        pid = profile.id
    row = _batch(client, pid)
    assert (row["template"], row["depth"]) == ("terminal", "deep")


# --- page size: every render path -------------------------------------------


def test_pipeline_render_uses_the_owners_page_size(
    engine, claude_fake, fake_settings, people, exports, monkeypatch
):
    monkeypatch.setattr(pipeline, "get_settings", lambda: fake_settings)
    app_ids = {}
    for name in ("Ada", "Bea"):
        with Session(engine) as session:
            # raw_text skips the fetch; depth "quick" skips research.
            job = Job(url=f"https://jobs.example.com/{name}", raw_text=POSTING_TEXT,
                      depth="quick")
            session.add(job)
            session.commit()
            session.refresh(job)
            app_row = Application(profile_id=people[name], job_id=job.id)
            session.add(app_row)
            session.commit()
            session.refresh(app_row)
            app_ids[name] = app_row.id
        pipeline.process_application(app_ids[name], engine=engine, claude=claude_fake)
        with Session(engine) as session:
            app_row = session.get(Application, app_ids[name])
            assert app_row.status == "ready", app_row.error_message

    assert exports == [(app_ids["Ada"], "A4"), (app_ids["Bea"], "Letter")]


def test_template_switch_uses_the_owners_page_size(client, engine, people, exports):
    ada_app = _ready_application(engine, people["Ada"])
    bea_app = _ready_application(engine, people["Bea"])
    for app_id in (ada_app, bea_app):
        resp = client.patch(f"/api/applications/{app_id}/template",
                            json={"template": "ledger"})
        assert resp.status_code == 200, resp.text

    assert exports == [(ada_app, "A4"), (bea_app, "Letter")]


def test_content_save_uses_the_owners_page_size(client, engine, people, exports):
    ada_app = _ready_application(engine, people["Ada"])
    bea_app = _ready_application(engine, people["Bea"])
    for app_id in (ada_app, bea_app):
        resp = client.put(f"/api/applications/{app_id}/content",
                          json={"cover_letter_md": "Dear Northwind team,"})
        assert resp.status_code == 200, resp.text

    assert exports == [(ada_app, "A4"), (bea_app, "Letter")]


def test_mcp_set_application_template_uses_the_owners_page_size(
    engine, tmp_path, people, exports
):
    ada_app = _ready_application(engine, people["Ada"])
    bea_app = _ready_application(engine, people["Bea"])
    for app_id in (ada_app, bea_app):
        mcp_ops.set_application_template(engine, tmp_path, app_id, "ledger")

    assert exports == [(ada_app, "A4"), (bea_app, "Letter")]


def test_mcp_save_tailored_resume_uses_the_owners_page_size(
    engine, tmp_path, people, exports
):
    tailor = _fixture("tailor")
    app_ids = []
    for name in ("Ada", "Bea"):
        created = mcp_ops.create_application(
            engine, people[name], f"https://jobs.example.com/{name}", POSTING_TEXT, "slate"
        )
        app_id = created["application_id"]
        result = mcp_ops.save_tailored_resume(
            engine, tmp_path, app_id, tailor["resume"], tailor["cover_letter_md"],
            tailor.get("tailoring_notes", ""),
        )
        assert result["status"] == "ready"
        app_ids.append(app_id)

    assert exports == [(app_ids[0], "A4"), (app_ids[1], "Letter")]
```

Notes on the fixtures used: `client`, `engine`, `fake_settings` and `claude_fake` come from `tests/conftest.py`; the conftest `client` shares the `engine` and `fake_settings` (`data_dir=tmp_path`) of the same test, so `tmp_path` passed to the MCP functions is the same data directory. Batch create is called with `"generate": False` because the conftest `client` does not stub `pipeline.process_application`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_owner.py -v`

Expected: `6 failed, 2 passed`. Every consumer still reads only the app-wide file (no `settings.json` in `tmp_path`, so Letter / slate / standard):
- `test_batch_create_uses_each_persons_default_template_and_depth` FAILS: `assert ('slate', 'standard') == ('terminal', 'deep')`
- `test_pipeline_render_uses_the_owners_page_size`, `test_template_switch_uses_the_owners_page_size`, `test_content_save_uses_the_owners_page_size`, `test_mcp_set_application_template_uses_the_owners_page_size`, `test_mcp_save_tailored_resume_uses_the_owners_page_size` each FAIL with `assert [(1, 'Letter'), (2, 'Letter')] == [(1, 'A4'), (2, 'Letter')]`
- `test_batch_create_request_values_still_beat_the_persons_defaults` and `test_batch_create_for_a_person_without_own_values_uses_the_app_wide_ones` already pass (they pin the precedence the change must keep).

- [ ] **Step 3: Switch `backend/app/api/applications.py` to the owner's settings**

Task 4 edited this file earlier (it added an import of `delete_application_rows` and rewrote the body of `delete_application`); none of the five regions below is one it changed, so the quoted code is as Task 4 left it.

Edit 1 (drop the now-unused import). Current:

```python
from ..config import load_user_settings
from ..db import get_session
```

Replace with:

```python
from ..db import get_session
```

Edit 2 (add the resolver import; anchor on this one line, whatever Task 4 put after it). Current:

```python
from ..services import pipeline, render
```

Replace with:

```python
from ..services import pipeline, render
from ..services.person_settings import settings_for
```

Edit 3 (`create_batch`; `profile` is the row it just loaded for the 404). Current:

```python
    user_settings = load_user_settings(request.app.state.settings.data_dir)
    fallback_depth = body.default_depth or user_settings.get("default_depth", "standard")
```

Replace with:

```python
    # The person's own defaults, over the app-wide ones (spec 5.2).
    user_settings = settings_for(request.app.state.settings.data_dir, profile)
    fallback_depth = body.default_depth or user_settings.get("default_depth", "standard")
```

Edit 4 (`set_template`). Current:

```python
    profile = session.get(Profile, app_row.profile_id)
    settings = request.app.state.settings
    user_settings = load_user_settings(settings.data_dir)
    # Render before committing anything: a row claiming a template its exports
```

Replace with:

```python
    profile = session.get(Profile, app_row.profile_id)
    settings = request.app.state.settings
    # The owner's page size, never another person's (spec 5.2).
    user_settings = settings_for(settings.data_dir, profile)
    # Render before committing anything: a row claiming a template its exports
```

Edit 5 (`update_content`, indented one level deeper). Current:

```python
        profile = session.get(Profile, app_row.profile_id)
        settings = request.app.state.settings
        user_settings = load_user_settings(settings.data_dir)
        export_dir = render.export_application(
```

Replace with:

```python
        profile = session.get(Profile, app_row.profile_id)
        settings = request.app.state.settings
        # The owner's page size, never another person's (spec 5.2).
        user_settings = settings_for(settings.data_dir, profile)
        export_dir = render.export_application(
```

- [ ] **Step 4: Switch `backend/app/services/pipeline.py` to the owner's page size**

No earlier task changes this file. Edit 1. Current:

```python
from ..config import get_settings, load_user_settings
```

Replace with:

```python
from ..config import get_settings
```

Edit 2. Current:

```python
from .claude import ClaudeError, ClaudeService, make_claude
```

Replace with:

```python
from .claude import ClaudeError, ClaudeService, make_claude
from .person_settings import settings_for
```

Edit 3 (the render step at the end of `_tailor_and_render`). Current:

```python
    settings = get_settings()
    user_settings = load_user_settings(settings.data_dir)
    page_size = (user_settings or {}).get("page_size", "Letter")
```

Replace with:

```python
    settings = get_settings()
    # The owner's page size (spec 5.2): `profile` is this application's owner.
    page_size = settings_for(settings.data_dir, profile).get("page_size", "Letter")
```

`settings = get_settings()` stays: it supplies `data_dir` for the export call below it, and the pipeline tests redirect it with `monkeypatch.setattr(pipeline, "get_settings", ...)`.

- [ ] **Step 5: Switch both MCP render paths in `backend/mcp_ops.py`**

No earlier task changes this file (Task 9, later, adds `inbox_url`). Edit 1. Current:

```python
from .app.api.templates import TEMPLATE_META
from .app.config import load_user_settings
from .app.models import (
```

Replace with:

```python
from .app.api.templates import TEMPLATE_META
from .app.models import (
```

Edit 2. Current:

```python
from .app.services.claude import strict_schema
```

Replace with:

```python
from .app.services.claude import strict_schema
from .app.services.person_settings import settings_for
```

Edit 3 (`set_application_template`). Current:

```python
        profile = session.get(Profile, app.profile_id)
        contact = get_contact(profile)

        user_settings = load_user_settings(Path(data_dir))
```

Replace with:

```python
        profile = session.get(Profile, app.profile_id)
        contact = get_contact(profile)

        # The owner's page size, whoever is picked in any browser (spec 5.2).
        user_settings = settings_for(Path(data_dir), profile)
```

Edit 4 (`save_tailored_resume`, inside its `try:`). Current:

```python
            _set_status(session, app, "rendering")
            user_settings = load_user_settings(Path(data_dir))
```

Replace with:

```python
            _set_status(session, app, "rendering")
            # The owner's page size, whoever is picked in any browser (spec 5.2).
            user_settings = settings_for(Path(data_dir), profile)
```

`profile` there is the row the function loaded and null-checked before the truthfulness gate; it is still attached to the open session, so reading its `settings_json` after the intervening commits simply reloads it.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_owner.py -v`
Expected: `8 passed`.

Run: `grep -n "load_user_settings" backend/app/api/applications.py backend/app/services/pipeline.py backend/mcp_ops.py`
Expected: no output (exit status 1).

Run the suites that exercise these call sites:
`.venv/Scripts/python.exe -m pytest tests/test_api.py tests/test_template_switch.py tests/test_pipeline.py tests/test_mcp_ops.py tests/test_mcp_server.py tests/test_inline_edit.py tests/test_person_settings.py tests/test_settings_per_person.py -q`
Expected: all pass. No existing test needs editing: every profile those tests create has `settings_json == "{}"`, so `settings_for` returns exactly what `load_user_settings` did (for example `tests/test_api.py::test_content_edit` still gets `exports == [(app_id, "slate", "Letter")]`). `tests/test_mcp_server.py` includes `pdf`-marked tests that launch Chromium; if Chromium is not installed, add `-m "not pdf"`.

Run: `.venv/Scripts/python.exe -m pytest -m "not pdf" -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/applications.py backend/app/services/pipeline.py backend/mcp_ops.py tests/test_settings_owner.py
git commit -m "$(cat <<'EOF'
feat: renders and web defaults follow the application's owner

Batch create, template switch, content save, the pipeline render and both
MCP render paths read settings_for(data_dir, owner) instead of the app-wide
file alone, so a render always uses its owner's page size.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```


---

### Task 9: MCP `inbox_url` and the guide's inbox rules

**Files:**
- Create: `tests/test_mcp_inbox.py`
- Modify: `backend/mcp_ops.py` (the `.app.services` import lines; `get_workflow_guide()` text between the WRITING VOICE and JSON SHAPES sections; `get_master_profile` docstring and return dict)
- Modify: `backend/mcp_server.py` (docstring of the `get_master_profile` tool)
- Modify: `docs/EXTENDING.md` (§1 tool table, the `get_master_profile` row)
- Test: `tests/test_mcp_inbox.py`

**Interfaces:**
- Consumes: `backend.app.services.inbox.inbox_url(email: str | None) -> str | None` (Task 1). Existing `backend.app.models.get_contact(profile) -> Contact` and `backend.app.schemas.Contact` (`email: str = ""`).
- Produces: `mcp_ops.get_master_profile(engine, profile_id=None)` returns the same dict as today plus the key `"inbox_url"` (a `str`, or `None`). No new functions or names. The workflow guide gains the `CANDIDATE'S INBOX` section verbatim from the contract, placed after WRITING VOICE and before JSON SHAPES.
- Choices made here (the contract leaves them open):
  - `inbox_url` is always present in the result and is `None` (JSON `null`) when the provider is not recognised or there is no email. It is never omitted.
  - It is computed on every call from `get_contact(profile).email` and never stored, so it follows the email when the user edits it.
  - The EXTENDING.md row is rewritten, so its existing em dash becomes a colon (global rule: no em dashes in text we write).
- Order and overlap: Task 8 edits `backend/mcp_ops.py` too (its imports and the render calls in `set_application_template` and `save_tailored_resume`). The code this task anchors on (the line `from .app.services.claude import strict_schema`, the guide text, and `get_master_profile`) is outside Task 8's edits, so the quotes below match the file as Task 8 leaves it. The working tree uses CRLF line endings (`core.autocrlf=true`), so make these edits with an editor or the Edit tool, not with a script that writes LF.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_inbox.py` with exactly this content:

```python
"""The candidate's inbox, as an MCP agent sees it.

get_master_profile carries a derived inbox_url, and the workflow guide tells
the agent how to use it: open that URL, never an account picked by position,
check the mailbox address before reading anything, and stop at a sign-in page.
The guide and the tool docstring are what the agent actually reads, so both are
pinned here along with the EXTENDING.md row that documents the key.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlmodel import Session

from backend import mcp_ops
from backend.app.models import Profile, set_contact
from backend.app.schemas import Contact

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PROJECT_ROOT / "backend" / "mcp_server.py"
EXTENDING_PATH = PROJECT_ROOT / "docs" / "EXTENDING.md"

# Verbatim from the person-picker plan contract. The guide must carry exactly
# this text, so an edit that drops one of the rules fails here.
INBOX_SECTION = """CANDIDATE'S INBOX (only when the user asks you to work in their mail):
- get_master_profile returns inbox_url when the candidate's email is on a
  provider Tailored recognises. Open that URL in the user's own browser. Never
  pick an account by position (such as /mail/u/1/).
- Before reading anything, confirm the mailbox address shown on the page is
  the candidate's contact email. If it differs, stop and say which account is
  open.
- A sign-in page means that account is not signed in in this browser: say so
  and stop. Never sign in on the user's behalf.
- If inbox_url is null, open no inbox. Ask the user which one to use."""

# Characters the voice contract bans in agent-facing text.
MACHINE_TELLS = tuple(chr(c) for c in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019))


def _seed(engine, name: str, email: str | None) -> int:
    """One profile; email None leaves contact_json at its '{}' default."""
    with Session(engine) as session:
        profile = Profile(name=name)
        if email is not None:
            set_contact(profile, Contact(name=name, email=email))
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile.id


# --- get_master_profile ---

@pytest.mark.parametrize(
    ("email", "expected"),
    [
        (
            "jordan.rivera+jobs@gmail.com",
            "https://mail.google.com/mail/?authuser=jordan.rivera%2Bjobs@gmail.com",
        ),
        ("jordan@icloud.com", "https://www.icloud.com/mail"),
        ("jordan@hotmail.com", "https://outlook.live.com/mail/"),
        ("jordan.rivera@example.com", None),
        ("", None),
    ],
)
def test_get_master_profile_returns_inbox_url(engine, email, expected):
    profile_id = _seed(engine, "Jordan Rivera", email)

    data = mcp_ops.get_master_profile(engine, profile_id)

    assert "inbox_url" in data, "the key is always present, null when unknown"
    assert data["inbox_url"] == expected
    # Additive: the existing keys are all still there.
    assert {"profile_id", "name", "contact", "voice_notes", "master_profile"} <= set(data)
    assert data["contact"]["email"] == email


def test_get_master_profile_inbox_url_without_any_contact(engine):
    """A profile created with no contact at all falls back to Contact(name=...),
    whose email is empty, so there is no inbox to point at."""
    profile_id = _seed(engine, "No Contact Yet", None)

    data = mcp_ops.get_master_profile(engine, profile_id)

    assert data["inbox_url"] is None


def test_get_master_profile_inbox_url_on_the_sole_profile_path(engine):
    """profile_id omitted resolves the sole profile; the key comes with it."""
    _seed(engine, "Only Person", "only.person@gmail.com")

    data = mcp_ops.get_master_profile(engine)

    assert data["inbox_url"] == (
        "https://mail.google.com/mail/?authuser=only.person@gmail.com"
    )


def test_get_master_profile_inbox_url_is_per_person(engine):
    """Two people, two inboxes: each profile_id gets its own candidate's link,
    which is the whole point of not picking a mailbox by position."""
    first = _seed(engine, "First Person", "first.person@gmail.com")
    second = _seed(engine, "Second Person", "second.person@outlook.com")

    assert mcp_ops.get_master_profile(engine, first)["inbox_url"] == (
        "https://mail.google.com/mail/?authuser=first.person@gmail.com"
    )
    assert mcp_ops.get_master_profile(engine, second)["inbox_url"] == (
        "https://outlook.live.com/mail/"
    )


# --- workflow guide ---

def test_workflow_guide_has_the_inbox_section_verbatim():
    guide = mcp_ops.get_workflow_guide()
    assert INBOX_SECTION in guide


def test_workflow_guide_inbox_section_follows_writing_voice():
    guide = mcp_ops.get_workflow_guide()
    assert "CANDIDATE'S INBOX" in guide
    voice = guide.index("WRITING VOICE")
    inbox = guide.index("CANDIDATE'S INBOX")
    shapes = guide.index("JSON SHAPES")
    assert voice < inbox < shapes


def test_workflow_guide_inbox_section_has_no_machine_tells():
    guide = mcp_ops.get_workflow_guide()
    assert "CANDIDATE'S INBOX" in guide
    section = guide[guide.index("CANDIDATE'S INBOX"):guide.index("JSON SHAPES")]
    for char in MACHINE_TELLS:
        assert char not in section, f"inbox section contains U+{ord(char):04X}"


# --- what the agent reads besides the guide ---

def _tool_docstring(name: str) -> str:
    """One @mcp.tool function's docstring, parsed from source with ast.

    Not imported: importing backend/mcp_server.py runs its module-level engine
    setup against the real data directory (same reason as test_mcp_server.py).
    """
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return ast.get_docstring(node) or ""
    raise AssertionError(f"no tool function named {name!r} in mcp_server.py")


def test_get_master_profile_docstring_mentions_inbox_url():
    doc = _tool_docstring("get_master_profile")
    assert "inbox_url" in doc
    assert "null" in doc
    assert "get_workflow_guide" in doc
    for char in MACHINE_TELLS:
        assert char not in doc, f"docstring contains U+{ord(char):04X}"


def test_extending_md_documents_inbox_url():
    lines = EXTENDING_PATH.read_text(encoding="utf-8").splitlines()
    row = next(
        (line for line in lines if line.startswith("| `get_master_profile(")),
        None,
    )
    assert row is not None, "EXTENDING.md lost its get_master_profile row"
    assert "`inbox_url`" in row
```

The expected URLs are the contract's `inbox_url` rules (Task 1): Gmail is `"https://mail.google.com/mail/?authuser=" + quote(email.strip(), safe="@")`, so the `+` becomes `%2B`; iCloud and Outlook are fixed URLs; `example.com` and a blank email give `None`. The test does not import `inbox_url` itself; it checks what the agent receives.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_inbox.py -v`

Expected: `13 failed`. The reasons:
- the five `test_get_master_profile_returns_inbox_url[...]` cases fail with `AssertionError: the key is always present, null when unknown`
- `..._without_any_contact`, `..._on_the_sole_profile_path` and `..._is_per_person` fail with `KeyError: 'inbox_url'`
- the three guide tests fail on `assert INBOX_SECTION in guide` / `assert "CANDIDATE'S INBOX" in guide`
- the docstring test fails on `assert "inbox_url" in doc`
- the EXTENDING test fails on ``assert "`inbox_url`" in row``

If a run after Step 3 fails with `ModuleNotFoundError: No module named 'backend.app.services.inbox'`, Task 1 has not been done; do it first.

- [ ] **Step 3: Return `inbox_url` from `get_master_profile` in `backend/mcp_ops.py`**

3a. Import the helper. Find this line in the import block (the line that follows it may be different after Task 8; leave it as it is):

```python
from .app.services.claude import strict_schema
```

Replace it with:

```python
from .app.services.claude import strict_schema
from .app.services.inbox import inbox_url
```

3b. In `def get_master_profile(engine, profile_id: int | None = None) -> dict:`, replace the docstring:

```python
    """Contact + master profile for one profile.

    profile_id None resolves to the sole profile; ambiguous (multiple profiles)
    raises with a listing so the agent can pick one.
    """
```

with:

```python
    """Contact + master profile for one profile, plus the derived inbox_url.

    profile_id None resolves to the sole profile; ambiguous (multiple profiles)
    raises with a listing so the agent can pick one. inbox_url is the
    candidate's webmail link from services/inbox.py, or None when the contact
    email's provider is not one Tailored recognises.
    """
```

3c. In the same function, replace the return statement:

```python
        return {
            "profile_id": profile.id,
            "name": profile.name,
            "contact": get_contact(profile).model_dump(),
            "voice_notes": profile.voice_notes,
            "master_profile": _master_profile_of(profile).model_dump(),
        }
```

with:

```python
        contact = get_contact(profile)
        return {
            "profile_id": profile.id,
            "name": profile.name,
            "contact": contact.model_dump(),
            "voice_notes": profile.voice_notes,
            "master_profile": _master_profile_of(profile).model_dump(),
            # Derived on every call, never stored, so it follows the contact
            # email when the user edits it on the Profiles screen.
            "inbox_url": inbox_url(contact.email),
        }
```

`contact` is a new local name inside this function only; nothing else in the function uses that name. `get_contact` never returns `None` (an empty `contact_json` falls back to `Contact(name=profile.name)` with `email=""`), so `contact.email` is always a string.

- [ ] **Step 4: Add the inbox section to the workflow guide**

`get_workflow_guide()` returns one f-string. The new section has no `{` or `}`, so nothing in it needs escaping. Find the end of the WRITING VOICE section and the start of JSON SHAPES:

```text
- save_tailored_resume rejects violations and returns the list, exactly as it
  does for truthfulness. Follow these the first time and you will not see it.

JSON SHAPES (strict: every object level carries "additionalProperties": false -
```

Replace it with (the only change is the new block and its trailing blank line; the apostrophes are straight ASCII `'`):

```text
- save_tailored_resume rejects violations and returns the list, exactly as it
  does for truthfulness. Follow these the first time and you will not see it.

CANDIDATE'S INBOX (only when the user asks you to work in their mail):
- get_master_profile returns inbox_url when the candidate's email is on a
  provider Tailored recognises. Open that URL in the user's own browser. Never
  pick an account by position (such as /mail/u/1/).
- Before reading anything, confirm the mailbox address shown on the page is
  the candidate's contact email. If it differs, stop and say which account is
  open.
- A sign-in page means that account is not signed in in this browser: say so
  and stop. Never sign in on the user's behalf.
- If inbox_url is null, open no inbox. Ask the user which one to use.

JSON SHAPES (strict: every object level carries "additionalProperties": false -
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_inbox.py -v`

Expected: `11 passed, 2 failed`. Still failing: `test_get_master_profile_docstring_mentions_inbox_url` and `test_extending_md_documents_inbox_url` (Steps 5 and 6 fix them).

- [ ] **Step 5: Mention `inbox_url` in the MCP tool docstring (`backend/mcp_server.py`)**

MCPServer serves each tool's docstring verbatim as its description, so this is what a connected agent reads for `get_master_profile`. Replace the docstring of `async def get_master_profile(profile_id: int | None = None) -> dict:`:

```python
    """Fetch a profile's contact info and master profile - the single source
    of truth containing every fact you may use when tailoring. Call this
    before tailoring anything. Omit profile_id when only one profile exists;
    with multiple profiles you get an error listing them so you can pick."""
```

with:

```python
    """Fetch a profile's contact info and master profile - the single source
    of truth containing every fact you may use when tailoring. Call this
    before tailoring anything. Omit profile_id when only one profile exists;
    with multiple profiles you get an error listing them so you can pick.
    Also returns inbox_url: the candidate's webmail link when their contact
    email is on a provider Tailored recognises (Gmail, iCloud, Outlook), else
    null. Use it only when the user asks you to work in their mail, and follow
    the CANDIDATE'S INBOX rules in get_workflow_guide."""
```

The function body (`return await _run(mcp_ops.get_master_profile, _engine, profile_id)`) is unchanged. `tests/test_mcp_server.py::test_escalation_ladder_survives_in_the_tool_docstrings` pins only the `create_application`, `report_fetch_blocked`, `queue_jobs` and `next_pending_job` docstrings, so it is unaffected.

- [ ] **Step 6: Document the key in `docs/EXTENDING.md` §1**

In the tool table, replace this row (it contains an em dash today):

```markdown
| `get_master_profile(profile_id?)` | Contact + master profile — the only facts an agent may use. Omitting `profile_id` resolves the sole profile; ambiguity returns an error listing the profiles. |
```

with:

```markdown
| `get_master_profile(profile_id?)` | Contact + master profile: the only facts an agent may use. Omitting `profile_id` resolves the sole profile; ambiguity returns an error listing the profiles. Also returns `inbox_url`, the candidate's webmail link when the contact email is on Gmail, iCloud or Outlook, else null; the guide's CANDIDATE'S INBOX section says how an agent may use it. |
```

- [ ] **Step 7: Run the tests and the wider suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_inbox.py -v`

Expected: `13 passed`.

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_ops.py tests/test_mcp_server.py tests/test_fetcher.py -v`

Expected: all pass. None of these need editing: `test_workflow_guide_contents` and `test_fetcher.py`'s guide check assert substrings that are unchanged; the `test_get_master_profile_*` tests in `test_mcp_ops.py` read individual keys and never the exact key set; the pdf-marked stdio flow in `test_mcp_server.py` (needs Chromium from `playwright install chromium`) reads `profile_id` and `master_profile` from the served result, and the extra `inbox_url: null` crosses the wire with it.

Run: `.venv/Scripts/python.exe -m pytest -m "not pdf" -q`

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/mcp_ops.py backend/mcp_server.py docs/EXTENDING.md tests/test_mcp_inbox.py
git commit -m "$(cat <<'EOF'
feat: give MCP agents the candidate's inbox_url and inbox rules

get_master_profile returns a derived inbox_url (null when the provider is
not recognised), and the workflow guide gains a CANDIDATE'S INBOX section:
open that URL, never an account chosen by position, confirm the mailbox
address before reading, stop at a sign-in page, never sign in for the user.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```


---

### Task 10: Frontend types and API client for people, documents and per-person settings

**Files:**
- Modify: `frontend/src/types.ts` (`ProfileSummary` and `ProfileDetail` interfaces)
- Modify: `frontend/src/api.ts` (profiles section after `buildProfile`; settings section)
- Modify: `frontend/src/screens/AddJobsScreen.test.tsx` (the typed `listProfiles` fixture in `beforeEach`)
- Modify: `frontend/src/screens/GettingStartedScreen.test.tsx` (three typed `listProfiles` fixtures)
- Modify: `frontend/src/screens/ProfileScreen.test.tsx` (the `baseProfileDetail` fixture)
- Create: `frontend/src/api.test.ts`
- Test: `frontend/src/api.test.ts`

**Interfaces:**
- Consumes: the backend payloads from Tasks 1, 3, 5 and 7: `GET /api/profiles` items carry `created_at` and `inbox_url`; profile detail carries `created_at`, `inbox_url`, `application_count`; `DELETE /api/profiles/{id}/documents/{doc_id}` returns `{"deleted": doc_id}`; `DELETE /api/profiles/{id}?confirm_name=...` returns `{"deleted", "applications", "documents"}` or 422/409; `GET|PUT /api/settings?profile_id=N`.
- Produces (binding for Tasks 11-19):
  - `ProfileSummary` gains `created_at: string; inbox_url: string | null;`
  - `ProfileDetail` gains `created_at: string; inbox_url: string | null; application_count: number;`
  - `export function deleteDocument(profileId: number, docId: number): Promise<{ deleted: number }>` (DELETE `/api/profiles/{profileId}/documents/{docId}`)
  - `export function deleteProfile(profileId: number, confirmName: string): Promise<{ deleted: number; applications: number; documents: number }>` (DELETE `/api/profiles/{profileId}?confirm_name=${encodeURIComponent(confirmName)}`)
  - `export function getSettings(profileId?: number): Promise<SettingsShape>` (adds `?profile_id=N` only when `profileId` is given)
  - `export function updateSettings(patch: { default_template?: TemplateName; default_depth?: Depth; page_size?: PageSize }, profileId?: number): Promise<SettingsShape>`
  - Error shape (unchanged `request()` behaviour, now pinned by a test): a non-2xx response rejects with `Error("API <status>: <detail>")` where `<detail>` is `body.detail` when it is a string, otherwise `JSON.stringify(body)`. So a 409 from `deleteProfile` rejects with the message `API 409: {"detail":{"message":"...","blocking":[{"id":12,"label":"Acme","status":"fetching"}]}}`; Task 16 recovers the blocking list with `JSON.parse(message.slice(message.indexOf("{")))`.
  - Choice: every existing call site keeps compiling unchanged, because both new parameters are optional.

Adding required fields to `ProfileSummary`/`ProfileDetail` breaks `tsc` (which `npm run build` runs, and which type-checks test files) in three existing test files whose fixtures are typed through `vi.mocked(...)`. They are updated in this task. Fixtures built inside `vi.mock` factories are untyped and need no change.

- [ ] **Step 1: Write the failing API client tests**

Create `frontend/src/api.test.ts`:

```ts
import { deleteDocument, deleteProfile, getSettings, updateSettings } from "./api";

const SETTINGS = {
  api_key_set: false,
  fake_mode: true,
  default_template: "slate",
  default_depth: "standard",
  page_size: "Letter",
};

function jsonResponse(body: unknown, status = 200, statusText = "OK"): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText,
    headers: { "Content-Type": "application/json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** The URL and init of the one fetch call the test made. */
function onlyCall(): [string, RequestInit | undefined] {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0];
  return [url as string, init as RequestInit | undefined];
}

describe("deleteDocument", () => {
  it("sends DELETE to the document under its profile and returns the body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ deleted: 7 }));
    await expect(deleteDocument(3, 7)).resolves.toEqual({ deleted: 7 });
    const [url, init] = onlyCall();
    expect(url).toBe("/api/profiles/3/documents/7");
    expect(init?.method).toBe("DELETE");
  });

  it("rejects with the server's detail on a 404", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "document not found" }, 404, "Not Found"));
    await expect(deleteDocument(3, 99)).rejects.toThrow("API 404: document not found");
  });
});

describe("deleteProfile", () => {
  it("sends DELETE with the typed name URL-encoded in confirm_name", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ deleted: 3, applications: 2, documents: 1 }));
    await expect(deleteProfile(3, "Sam O'Neil & Co+")).resolves.toEqual({
      deleted: 3,
      applications: 2,
      documents: 1,
    });
    const [url, init] = onlyCall();
    expect(url).toBe("/api/profiles/3?confirm_name=Sam%20O'Neil%20%26%20Co%2B");
    expect(init?.method).toBe("DELETE");
  });

  it("rejects with the 422 detail when the name does not match", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "confirm_name must equal the person's name" }, 422, "Unprocessable Entity")
    );
    await expect(deleteProfile(3, "Sam")).rejects.toThrow(
      "API 422: confirm_name must equal the person's name"
    );
  });

  it("carries a 409's structured body in the error message", async () => {
    const body = {
      detail: {
        message: "Sam Lee has work in progress.",
        blocking: [{ id: 12, label: "Acme", status: "fetching" }],
      },
    };
    fetchMock.mockResolvedValue(jsonResponse(body, 409, "Conflict"));
    await expect(deleteProfile(3, "Sam Lee")).rejects.toThrow(`API 409: ${JSON.stringify(body)}`);
  });
});

describe("settings for a person", () => {
  it("getSettings() reads the app-wide settings, as before", async () => {
    fetchMock.mockResolvedValue(jsonResponse(SETTINGS));
    await expect(getSettings()).resolves.toEqual(SETTINGS);
    const [url, init] = onlyCall();
    expect(url).toBe("/api/settings");
    expect(init).toBeUndefined();
  });

  it("getSettings(id) reads that person's settings", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...SETTINGS, page_size: "A4" }));
    await expect(getSettings(4)).resolves.toMatchObject({ page_size: "A4" });
    const [url] = onlyCall();
    expect(url).toBe("/api/settings?profile_id=4");
  });

  it("updateSettings(patch) writes the app-wide settings, as before", async () => {
    fetchMock.mockResolvedValue(jsonResponse(SETTINGS));
    await updateSettings({ page_size: "Letter" });
    const [url, init] = onlyCall();
    expect(url).toBe("/api/settings");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ page_size: "Letter" });
  });

  it("updateSettings(patch, id) writes that person's settings", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...SETTINGS, page_size: "A4" }));
    await updateSettings({ page_size: "A4" }, 4);
    const [url, init] = onlyCall();
    expect(url).toBe("/api/settings?profile_id=4");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ page_size: "A4" });
  });
});
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd frontend && npx vitest run src/api.test.ts`

Expected: `Tests  7 failed | 2 passed (9)`. The failures are `TypeError: deleteDocument is not a function` (2 tests), `TypeError: deleteProfile is not a function` (3 tests), and `AssertionError: expected '/api/settings' to be '/api/settings?profile_id=4'` (2 tests). The two "as before" settings tests already pass.

- [ ] **Step 3: Add the new fields to the profile types**

In `frontend/src/types.ts`, replace the current code (verbatim):

```ts
export interface ProfileSummary {
  id: number;
  name: string;
  contact: Contact;
  has_master_profile: boolean;
}

export interface ProfileDetail {
  id: number;
  name: string;
  contact: Contact;
  master_profile: MasterProfile;
  voice_notes: string;
  documents: DocumentInfo[];
  usage?: UsageInfo;
}
```

with:

```ts
export interface ProfileSummary {
  id: number;
  name: string;
  contact: Contact;
  has_master_profile: boolean;
  /** ISO timestamp. With the id it identifies a person: SQLite reuses a removed person's id. */
  created_at: string;
  /** Webmail link for the contact email's provider; null when the provider is unknown. */
  inbox_url: string | null;
}

export interface ProfileDetail {
  id: number;
  name: string;
  contact: Contact;
  master_profile: MasterProfile;
  voice_notes: string;
  documents: DocumentInfo[];
  created_at: string;
  inbox_url: string | null;
  /** Every application of this person, archived included. */
  application_count: number;
  usage?: UsageInfo;
}
```

Run: `cd frontend && npx tsc`

Expected: it now fails with `TS2739 ... missing the following properties from type 'ProfileSummary': created_at, inbox_url` at `src/screens/AddJobsScreen.test.tsx(26,7)` and `src/screens/GettingStartedScreen.test.tsx` lines 33, 67 and 85, and `TS2345 ... missing the following properties from type 'ProfileDetail': created_at, inbox_url, application_count` at `src/screens/ProfileScreen.test.tsx` lines 66, 89 and 102. Step 4 fixes exactly these.

- [ ] **Step 4: Update the typed fixtures in three existing screen tests**

In `frontend/src/screens/AddJobsScreen.test.tsx`, inside `beforeEach`, replace the current code (verbatim):

```tsx
      { id: 1, name: "Jordan Rivera", contact, has_master_profile: true },
```

with:

```tsx
      {
        id: 1,
        name: "Jordan Rivera",
        contact,
        has_master_profile: true,
        created_at: "2026-01-01T00:00:00+00:00",
        inbox_url: null,
      },
```

In `frontend/src/screens/GettingStartedScreen.test.tsx`, replace all three occurrences (lines ~33, ~67, ~85; use replace-all) of the current code (verbatim):

```tsx
      { id: 1, name: "Me", contact, has_master_profile: true },
```

with:

```tsx
      {
        id: 1,
        name: "Me",
        contact,
        has_master_profile: true,
        created_at: "2026-01-01T00:00:00+00:00",
        inbox_url: null,
      },
```

In `frontend/src/screens/ProfileScreen.test.tsx`, at the end of the `baseProfileDetail` object inside `vi.hoisted`, replace the current code (verbatim):

```tsx
    voice_notes: "",
    documents: [{ id: 5, filename: "resume.pdf", kind: "pdf" }],
  };
```

with:

```tsx
    voice_notes: "",
    documents: [{ id: 5, filename: "resume.pdf", kind: "pdf" }],
    created_at: "2026-01-01T00:00:00+00:00",
    inbox_url: null,
    application_count: 0,
  };
```

Run: `cd frontend && npx tsc`

Expected: exits 0 with no output.

- [ ] **Step 5: Add the API functions**

In `frontend/src/api.ts`, replace the current code (verbatim):

```ts
export function buildProfile(id: number): Promise<ProfileDetail> {
  return request<ProfileDetail>(`/profiles/${id}/build`, { method: "POST" });
}
```

with:

```ts
export function buildProfile(id: number): Promise<ProfileDetail> {
  return request<ProfileDetail>(`/profiles/${id}/build`, { method: "POST" });
}

export function deleteDocument(profileId: number, docId: number): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/profiles/${profileId}/documents/${docId}`, {
    method: "DELETE",
  });
}

/**
 * Removes a person and everything of theirs. The server refuses (422) unless
 * confirmName is exactly the person's name, and refuses (409) while any of
 * their applications is actively generating or an export file is locked; the
 * 409 error message carries the JSON body, `{"detail":{"message","blocking"}}`.
 */
export function deleteProfile(
  profileId: number,
  confirmName: string
): Promise<{ deleted: number; applications: number; documents: number }> {
  return request<{ deleted: number; applications: number; documents: number }>(
    `/profiles/${profileId}?confirm_name=${encodeURIComponent(confirmName)}`,
    { method: "DELETE" }
  );
}
```

Then, in the `// ---- settings ----` section, replace the current code (verbatim):

```ts
export function getSettings(): Promise<SettingsShape> {
  return request<SettingsShape>("/settings");
}

export function updateSettings(patch: {
  default_template?: TemplateName;
  default_depth?: Depth;
  page_size?: PageSize;
}): Promise<SettingsShape> {
  return request<SettingsShape>("/settings", jsonInit("PUT", patch));
}
```

with:

```ts
// With a profileId these read and write that person's settings; without one,
// the app-wide defaults in data/settings.json, exactly as before.
function settingsPath(profileId?: number): string {
  return profileId === undefined ? "/settings" : `/settings?profile_id=${profileId}`;
}

export function getSettings(profileId?: number): Promise<SettingsShape> {
  return request<SettingsShape>(settingsPath(profileId));
}

export function updateSettings(
  patch: {
    default_template?: TemplateName;
    default_depth?: Depth;
    page_size?: PageSize;
  },
  profileId?: number
): Promise<SettingsShape> {
  return request<SettingsShape>(settingsPath(profileId), jsonInit("PUT", patch));
}
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `cd frontend && npx vitest run src/api.test.ts`

Expected: `Tests  9 passed (9)`.

Run: `cd frontend && npx tsc && npm test`

Expected: `tsc` prints nothing; vitest reports every file passed, 0 failed (the existing screen suites are unaffected: nothing calls the new parameters yet).

- [ ] **Step 7: Rebuild the bundle and check the stamp**

Run: `cd frontend && npm run build`

Expected: ends with `stamp-build: recorded <n> build inputs`.

Run (repo root): `.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q`

Expected: `3 passed`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/api.test.ts frontend/src/screens/AddJobsScreen.test.tsx frontend/src/screens/GettingStartedScreen.test.tsx frontend/src/screens/ProfileScreen.test.tsx frontend/dist
git commit -m "$(cat <<'EOF'
feat: frontend client for people, document removal and per-person settings

ProfileSummary and ProfileDetail carry created_at and inbox_url (and the
detail's application_count); api.ts gains deleteDocument, deleteProfile and
an optional profileId on getSettings/updateSettings.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```


---

### Task 11: PersonProvider (the active person) and the renderWithPerson test helper

**Files:**
- Create: `frontend/src/person.tsx`
- Create: `frontend/src/test-utils.tsx`
- Create: `frontend/src/person.test.tsx`
- Test: `frontend/src/person.test.tsx`

**Interfaces:**
- Consumes: `listProfiles(): Promise<ProfileSummary[]>` from `frontend/src/api.ts`; `ProfileSummary.created_at` and `ProfileSummary.inbox_url` (Task 10).
- Produces (binding for Tasks 12-19), all from `frontend/src/person.tsx`:
  - `export const PERSON_STORAGE_KEY = "tailored-person"` (value: JSON `{"id": number, "created_at": string}`)
  - `export type SwitchTarget = number | "new"`
  - `export interface PersonContextValue` exactly as in the contract: `people, person, loading, error, notice, setNotice, setPersonId, requestSwitch, pendingSwitch, confirmSwitch, cancelSwitch, refreshPeople, setSwitchGuard, labelFor`
  - `export const PersonContext: React.Context<PersonContextValue | null>`
  - `export function PersonProvider({ children }: { children: ReactNode })`
  - `export function usePerson(): PersonContextValue` (throws `Error("usePerson must be used inside <PersonProvider>")` outside a provider)
- Produces, from `frontend/src/test-utils.tsx`:
  - `export function makePerson(p?: Partial<ProfileSummary>): ProfileSummary` (defaults exactly as the contract)
  - `export interface PersonTestOptions { people?; personId?; loading?; route?; path?; overrides? }`
  - `export type PersonRenderResult = RenderResult & { ctx: PersonContextValue; switchTo(id: number | null): void }`
  - `export function renderWithPerson(ui: ReactElement, opts?: PersonTestOptions): PersonRenderResult`
- Behaviour choices this task makes (screens may rely on them):
  - First load: the stored `{id, created_at}` is used only when a person with both that id and that `created_at` exists; otherwise (missing, unparseable, not an object, wrong types, gone, or id reused) the first person is selected and written to storage. With no people nothing is written.
  - `setPersonId(id, opts)` checks `id` against the latest loaded list (held in a ref, not the render's closure), so it works immediately after `await refreshPeople()`. An id not in that list is a no-op. It bypasses the guard, does not touch `notice` or `pendingSwitch`, and writes storage unless `remember: false`.
  - `refreshPeople(selectId?)` never rejects. With `selectId` present in the new list it switches to that person and remembers them. Without it, the current person is kept (and picks up renamed fields, a new `inbox_url`, etc.). If the current person is missing, or the same id now has a different `created_at`, it sets `notice` to `"{label} was removed."` (label computed against the previous list) and falls back to the first person; the stored entry is rewritten only when it no longer names anyone, so a `remember: false` visit does not change where the browser opens. A failed refresh after a good load keeps the last list and person and leaves `error` null; only a failed first load sets `error`. Responses from a superseded refresh, or after unmount, are dropped. Screens that need to know whether an id exists after a refresh read `people` on the next render.
  - The provider refreshes on `visibilitychange` when `document.visibilityState === "visible"`.
  - `requestSwitch(target)`: target equal to the current id returns true and does nothing; with a guard set it stores `pendingSwitch = { target, message: <guard> }` and returns false; otherwise it clears `notice`, performs a numeric switch (remembered) and returns true. For `"new"` it clears `notice`, switches nobody and returns true (the caller navigates).
  - `confirmSwitch()` clears `pendingSwitch`, clears `notice`, performs a numeric pending switch (remembered), and returns the pending target (or null when nothing is pending). It does not clear the guard: the screen that set it owns it (spec §4.4 lifecycle).
  - `setSwitchGuard` stores the message in a ref (no re-render). Only `requestSwitch` reads it.
  - `labelFor(p)`: `p.name`; if another person has the same trimmed name, `"{name} ({email})"` when `p` has an email that no same-named person shares, else `"{name} #{id}"`. (The same-email case is not in the spec; falling back to the id keeps the labels distinct.)
  - `renderWithPerson`: renders `<MemoryRouter initialEntries={[route]}><PersonContext.Provider value={ctx}>{ui}</PersonContext.Provider></MemoryRouter>`; with `path`, `ui` is the element of `<Route path={path}>` inside `<Routes>`. `person` is `null` when `loading` is true or `personId` is null, else `people.find(id)`. Defaults: `error: null`, `notice: null`, `pendingSwitch: null`, `setNotice`/`setPersonId`/`cancelSwitch`/`setSwitchGuard` plain `vi.fn()`, `requestSwitch` returns `true`, `confirmSwitch` returns `null`, `refreshPeople` resolves `undefined`, `labelFor` returns `p.name`. `overrides` are spread last and win (including `person`). The same `vi.fn()` instances survive `switchTo`, and `result.ctx` is replaced by the value `switchTo` renders. `result.rerender(node)` re-renders a new element inside the same context and router.

The provider is not mounted in the app until Task 12; this task only adds the module and its tests. `test-utils.tsx` is a source file as far as `scripts/stamp-build.mjs` is concerned (no `.test.` in its name), so the bundle stamp must be rebuilt in this task even though the emitted JavaScript does not change.

- [ ] **Step 1: Write the failing provider and helper tests**

Create `frontend/src/person.test.tsx`:

```tsx
import { act, render, screen, waitFor } from "@testing-library/react";
import { useParams } from "react-router-dom";
import { PERSON_STORAGE_KEY, PersonProvider, usePerson } from "./person";
import type { PersonContextValue } from "./person";
import * as api from "./api";
import { makePerson, renderWithPerson } from "./test-utils";
import type { ProfileSummary } from "./types";

vi.mock("./api", () => ({ listProfiles: vi.fn() }));

const JORDAN = makePerson();
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
  created_at: "2026-02-01T00:00:00+00:00",
});
const ALEX = makePerson({
  id: 3,
  name: "Alex Kim",
  contact: { name: "Alex Kim", email: "alex@example.com", links: [] },
  created_at: "2026-03-01T00:00:00+00:00",
});

// The value the Probe last rendered with; tests call its functions in act().
let latest: PersonContextValue;

function Probe() {
  const ctx = usePerson();
  latest = ctx;
  const shown = ctx.loading
    ? "loading"
    : ctx.person
      ? `${ctx.person.id}:${ctx.labelFor(ctx.person)}`
      : "none";
  return (
    <div>
      <p data-testid="person">{shown}</p>
      <p data-testid="error">{ctx.error ?? ""}</p>
      <p data-testid="notice">{ctx.notice ?? ""}</p>
      <p data-testid="pending">
        {ctx.pendingSwitch ? `${ctx.pendingSwitch.target}|${ctx.pendingSwitch.message}` : ""}
      </p>
    </div>
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function store(value: unknown) {
  localStorage.setItem(
    PERSON_STORAGE_KEY,
    typeof value === "string" ? value : JSON.stringify(value)
  );
}

function stored(): unknown {
  return JSON.parse(localStorage.getItem(PERSON_STORAGE_KEY) ?? "null");
}

const shown = () => screen.getByTestId("person");

async function renderProvider(first: ProfileSummary[]) {
  vi.mocked(api.listProfiles).mockResolvedValueOnce(first);
  render(
    <PersonProvider>
      <Probe />
    </PersonProvider>
  );
  await waitFor(() => expect(shown()).not.toHaveTextContent("loading"));
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(api.listProfiles).mockReset();
});

describe("PersonProvider: remembering the person", () => {
  it("is loading with no person until the list arrives, then picks the first and remembers it", async () => {
    const list = deferred<ProfileSummary[]>();
    vi.mocked(api.listProfiles).mockReturnValueOnce(list.promise);
    render(
      <PersonProvider>
        <Probe />
      </PersonProvider>
    );
    expect(shown()).toHaveTextContent("loading");
    expect(latest.person).toBeNull();

    await act(async () => list.resolve([JORDAN, SAM]));

    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(latest.people.map((p) => p.id)).toEqual([1, 2]);
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it("restores the stored person when both id and created_at match", async () => {
    store({ id: 2, created_at: SAM.created_at });
    await renderProvider([JORDAN, SAM]);
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(stored()).toEqual({ id: 2, created_at: SAM.created_at });
  });

  it("falls back to the first person and overwrites the entry when the stored person is gone", async () => {
    store({ id: 9, created_at: "2026-05-01T00:00:00+00:00" });
    await renderProvider([JORDAN, SAM]);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it("falls back when the stored id now belongs to someone created later", async () => {
    // SQLite reissued id 2 after the remembered person was removed.
    store({ id: 2, created_at: "2025-12-01T00:00:00+00:00" });
    await renderProvider([JORDAN, SAM]);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it.each([
    ["not JSON", "{not json"],
    ["an array", "[2]"],
    ["a number", "2"],
    ["null", "null"],
    ["a string id", JSON.stringify({ id: "2", created_at: "2026-02-01T00:00:00+00:00" })],
    ["no created_at", JSON.stringify({ id: 2 })],
  ])("falls back when the stored value is %s", async (_label, raw) => {
    store(raw);
    await renderProvider([JORDAN, SAM]);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it("works in memory when localStorage throws", async () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    try {
      await renderProvider([JORDAN, SAM]);
      expect(shown()).toHaveTextContent("1:Jordan Rivera");
      act(() => latest.setPersonId(2));
      expect(shown()).toHaveTextContent("2:Sam Lee");
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it("changes the stored entry only for a remembered switch", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setPersonId(2, { remember: false }));
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });

    act(() => latest.setPersonId(2));
    expect(stored()).toEqual({ id: 2, created_at: SAM.created_at });
  });

  it("ignores setPersonId for an id nobody has", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setPersonId(42));
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
  });

  it("reports a failed first load as an error, with no person", async () => {
    vi.mocked(api.listProfiles).mockRejectedValueOnce(new Error("API 500: boom"));
    render(
      <PersonProvider>
        <Probe />
      </PersonProvider>
    );
    await waitFor(() => expect(shown()).toHaveTextContent("none"));
    expect(screen.getByTestId("error")).toHaveTextContent("API 500: boom");
    expect(latest.people).toEqual([]);
  });

  it("has no person and no error when there are no people", async () => {
    await renderProvider([]);
    expect(shown()).toHaveTextContent("none");
    expect(latest.error).toBeNull();
    expect(localStorage.getItem(PERSON_STORAGE_KEY)).toBeNull();
  });
});

describe("PersonProvider: refreshing", () => {
  it("refreshPeople(selectId) switches to that person and remembers them", async () => {
    await renderProvider([JORDAN]);
    vi.mocked(api.listProfiles).mockResolvedValueOnce([JORDAN, SAM]);
    await act(() => latest.refreshPeople(2));
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(stored()).toEqual({ id: 2, created_at: SAM.created_at });
  });

  it("keeps the current person and picks up edits to them", async () => {
    store({ id: 2, created_at: SAM.created_at });
    await renderProvider([JORDAN, SAM]);
    vi.mocked(api.listProfiles).mockResolvedValueOnce([
      JORDAN,
      { ...SAM, name: "Sam Lee-Park", inbox_url: "https://outlook.live.com/mail/" },
    ]);
    await act(() => latest.refreshPeople());
    expect(shown()).toHaveTextContent("2:Sam Lee-Park");
    expect(latest.person?.inbox_url).toBe("https://outlook.live.com/mail/");
    expect(screen.getByTestId("notice")).toHaveTextContent("");
  });

  it("falls back to the first person with a notice when the current person is gone", async () => {
    store({ id: 2, created_at: SAM.created_at });
    await renderProvider([JORDAN, SAM]);
    vi.mocked(api.listProfiles).mockResolvedValueOnce([JORDAN]);
    await act(() => latest.refreshPeople());
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(screen.getByTestId("notice")).toHaveTextContent("Sam Lee was removed.");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it("treats a changed created_at as a removal, since the id was reissued", async () => {
    store({ id: 2, created_at: SAM.created_at });
    await renderProvider([JORDAN, SAM]);
    vi.mocked(api.listProfiles).mockResolvedValueOnce([
      JORDAN,
      { ...ALEX, id: 2 },
    ]);
    await act(() => latest.refreshPeople());
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(screen.getByTestId("notice")).toHaveTextContent("Sam Lee was removed.");
  });

  it("keeps a stored entry that still names someone when falling back", async () => {
    // Alex is remembered; Sam was shown for one visit only (remember: false).
    store({ id: 3, created_at: ALEX.created_at });
    await renderProvider([JORDAN, SAM, ALEX]);
    act(() => latest.setPersonId(2, { remember: false }));
    vi.mocked(api.listProfiles).mockResolvedValueOnce([JORDAN, ALEX]);
    await act(() => latest.refreshPeople());
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(stored()).toEqual({ id: 3, created_at: ALEX.created_at });
  });

  it("uses the distinguishing label in the removed notice", async () => {
    const samA = { ...SAM, id: 2 };
    const samB = { ...SAM, id: 3, contact: { ...SAM.contact, email: "" }, created_at: ALEX.created_at };
    store({ id: 3, created_at: samB.created_at });
    await renderProvider([samA, samB]);
    vi.mocked(api.listProfiles).mockResolvedValueOnce([samA]);
    await act(() => latest.refreshPeople());
    expect(screen.getByTestId("notice")).toHaveTextContent("Sam Lee #3 was removed.");
  });

  describe("when the tab becomes visible again", () => {
    let visibility: DocumentVisibilityState = "visible";
    beforeEach(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => visibility,
      });
    });
    afterEach(() => {
      delete (document as unknown as Record<string, unknown>).visibilityState;
    });

    it("refreshes the list", async () => {
      await renderProvider([JORDAN]);
      vi.mocked(api.listProfiles).mockResolvedValueOnce([{ ...JORDAN, name: "Jordan R. Rivera" }]);
      visibility = "visible";
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await waitFor(() => expect(shown()).toHaveTextContent("1:Jordan R. Rivera"));
    });

    it("does not refresh while hidden", async () => {
      await renderProvider([JORDAN]);
      visibility = "hidden";
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      expect(api.listProfiles).toHaveBeenCalledTimes(1);
    });
  });

  it("keeps the last good list when a later refresh fails", async () => {
    await renderProvider([JORDAN]);
    vi.mocked(api.listProfiles).mockRejectedValueOnce(new Error("API 500: boom"));
    await act(() => latest.refreshPeople());
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(latest.error).toBeNull();
  });

  it("ignores a response that arrives after a newer refresh", async () => {
    store({ id: 2, created_at: SAM.created_at });
    await renderProvider([JORDAN, SAM]);
    const older = deferred<ProfileSummary[]>();
    const newer = deferred<ProfileSummary[]>();
    vi.mocked(api.listProfiles).mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = latest.refreshPeople();
      second = latest.refreshPeople();
    });
    await act(async () => {
      newer.resolve([JORDAN, SAM]);
      await second;
    });
    await act(async () => {
      older.resolve([JORDAN]);
      await first;
    });
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(screen.getByTestId("notice")).toHaveTextContent("");
  });
});

describe("PersonProvider: the switch guard", () => {
  const GUARD = "Jordan Rivera has unsaved profile changes.";

  it("switches at once, and remembers, when no guard is set", async () => {
    await renderProvider([JORDAN, SAM]);
    let done = false;
    act(() => {
      done = latest.requestSwitch(2);
    });
    expect(done).toBe(true);
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(stored()).toEqual({ id: 2, created_at: SAM.created_at });
  });

  it("holds a guarded switch as pending until it is confirmed", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setSwitchGuard(GUARD));
    let done = true;
    act(() => {
      done = latest.requestSwitch(2);
    });
    expect(done).toBe(false);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(screen.getByTestId("pending")).toHaveTextContent(`2|${GUARD}`);

    let target: unknown;
    act(() => {
      target = latest.confirmSwitch();
    });
    expect(target).toBe(2);
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(screen.getByTestId("pending")).toHaveTextContent("");
    expect(stored()).toEqual({ id: 2, created_at: SAM.created_at });
  });

  it("stays on the current person when the pending switch is cancelled", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setSwitchGuard(GUARD));
    act(() => {
      latest.requestSwitch(2);
    });
    act(() => latest.cancelSwitch());
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(screen.getByTestId("pending")).toHaveTextContent("");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it("guards 'Add a person' too, and hands 'new' back on confirm", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setSwitchGuard(GUARD));
    let done = true;
    act(() => {
      done = latest.requestSwitch("new");
    });
    expect(done).toBe(false);
    expect(screen.getByTestId("pending")).toHaveTextContent(`new|${GUARD}`);
    let target: unknown;
    act(() => {
      target = latest.confirmSwitch();
    });
    expect(target).toBe("new");
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
  });

  it("returns true for 'new' without a guard and leaves the person alone", async () => {
    await renderProvider([JORDAN, SAM]);
    let done = false;
    act(() => {
      done = latest.requestSwitch("new");
    });
    expect(done).toBe(true);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(screen.getByTestId("pending")).toHaveTextContent("");
  });

  it("lets switches through again once the guard is cleared", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setSwitchGuard(GUARD));
    act(() => latest.setSwitchGuard(null));
    let done = false;
    act(() => {
      done = latest.requestSwitch(2);
    });
    expect(done).toBe(true);
    expect(shown()).toHaveTextContent("2:Sam Lee");
  });

  it("does not guard setPersonId, the programmatic path", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setSwitchGuard(GUARD));
    act(() => latest.setPersonId(2, { remember: false }));
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(screen.getByTestId("pending")).toHaveTextContent("");
  });

  it("confirmSwitch with nothing pending returns null", async () => {
    await renderProvider([JORDAN, SAM]);
    let target: unknown = "unset";
    act(() => {
      target = latest.confirmSwitch();
    });
    expect(target).toBeNull();
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
  });

  it("clears the notice when the person is switched from the picker", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setNotice("Switched to Sam Lee to show this application."));
    act(() => {
      latest.requestSwitch(2);
    });
    expect(screen.getByTestId("notice")).toHaveTextContent("");
  });
});

describe("PersonProvider: labels", () => {
  it("uses the name, and tells duplicates apart by email or else by id", async () => {
    const samA = { ...SAM, id: 2 };
    const samB = { ...SAM, id: 3, contact: { ...SAM.contact, email: "" }, created_at: ALEX.created_at };
    await renderProvider([JORDAN, samA, samB]);
    expect(latest.labelFor(JORDAN)).toBe("Jordan Rivera");
    expect(latest.labelFor(samA)).toBe("Sam Lee (sam@example.com)");
    expect(latest.labelFor(samB)).toBe("Sam Lee #3");
  });

  it("falls back to the id when two people share both name and email", async () => {
    const samA = { ...SAM, id: 2 };
    const samB = { ...SAM, id: 3, created_at: ALEX.created_at };
    await renderProvider([samA, samB]);
    expect(latest.labelFor(samA)).toBe("Sam Lee #2");
    expect(latest.labelFor(samB)).toBe("Sam Lee #3");
  });
});

describe("usePerson", () => {
  it("throws outside a PersonProvider", () => {
    // React reports the render error through console.error and a window
    // "error" event before rethrowing; silence both so the run stays readable.
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const swallow = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", swallow);
    try {
      expect(() => render(<Probe />)).toThrow("usePerson must be used inside <PersonProvider>");
    } finally {
      window.removeEventListener("error", swallow);
      quiet.mockRestore();
    }
  });
});

describe("renderWithPerson", () => {
  it("provides the given people and person, and switchTo re-renders with another", () => {
    const r = renderWithPerson(<Probe />, { people: [JORDAN, SAM], personId: 2 });
    expect(shown()).toHaveTextContent("2:Sam Lee");
    const guard = r.ctx.setSwitchGuard;

    r.switchTo(1);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(r.ctx.person?.id).toBe(1);
    expect(r.ctx.setSwitchGuard).toBe(guard);

    r.switchTo(null);
    expect(shown()).toHaveTextContent("none");
  });

  it("defaults to one person, selected", () => {
    const r = renderWithPerson(<Probe />);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(r.ctx.people).toEqual([JORDAN]);
  });

  it("gives no person while loading", () => {
    renderWithPerson(<Probe />, { loading: true });
    expect(shown()).toHaveTextContent("loading");
    expect(latest.person).toBeNull();
  });

  it("mounts the ui at a route pattern", () => {
    function Param() {
      const { id } = useParams();
      return <p>application {id}</p>;
    }
    renderWithPerson(<Param />, { route: "/applications/7", path: "/applications/:id" });
    expect(screen.getByText("application 7")).toBeInTheDocument();
  });

  it("applies overrides over the defaults", () => {
    renderWithPerson(<Probe />, { overrides: { notice: "Sam Lee was removed." } });
    expect(screen.getByTestId("notice")).toHaveTextContent("Sam Lee was removed.");
  });
});
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd frontend && npx vitest run src/person.test.tsx`

Expected: `FAIL  src/person.test.tsx` with `Error: Failed to resolve import "./person" from "src/person.test.tsx". Does the file exist?` and `Tests  no tests`.

- [ ] **Step 3: Write the provider**

Create `frontend/src/person.tsx`:

```tsx
// The active person: who this browser is working for.
//
// One install serves several people. The choice lives in this browser only
// (localStorage, so each Chrome profile keeps its own) and never on the
// server: an MCP agent always names its profile_id, and what it writes must
// not depend on what happens to be selected in some browser tab.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { listProfiles } from "./api";
import type { ProfileSummary } from "./types";

export const PERSON_STORAGE_KEY = "tailored-person";

/** A person's id, or "new" for the picker's "Add a person" option. */
export type SwitchTarget = number | "new";

export interface PersonContextValue {
  /** Every person, ordered by id (as GET /api/profiles returns them). */
  people: ProfileSummary[];
  /** Null while loading, after a failed first load, or with no people. */
  person: ProfileSummary | null;
  /** True until the first listProfiles() settles. */
  loading: boolean;
  /** The first load's failure; a failed later refresh keeps the last list. */
  error: string | null;
  /** One line shown under the picker. */
  notice: string | null;
  setNotice(message: string | null): void;
  /** Programmatic switch: bypasses the guard; remember defaults to true; no-op for an unknown id. */
  setPersonId(id: number, opts?: { remember?: boolean }): void;
  /** Picker switch: honours the guard. True means done now (for "new", the caller navigates). */
  requestSwitch(target: SwitchTarget): boolean;
  pendingSwitch: { target: SwitchTarget; message: string } | null;
  /** Performs the pending switch (remembered) and returns its target, or null if none. */
  confirmSwitch(): SwitchTarget | null;
  cancelSwitch(): void;
  /** Reloads the list; with selectId, switches to (and remembers) that person. Never rejects. */
  refreshPeople(selectId?: number): Promise<void>;
  /** A message while a screen holds work a switch would lose; null to clear. */
  setSwitchGuard(message: string | null): void;
  /** The name; for duplicate names "name (email)", or "name #id" without a distinct email. */
  labelFor(p: ProfileSummary): string;
}

export const PersonContext = createContext<PersonContextValue | null>(null);

/** What identifies a person across reloads. The id alone is not enough:
 * SQLite hands a removed person's id to the next person created. */
interface PersonKey {
  id: number;
  created_at: string;
}

function keyOf(p: ProfileSummary): PersonKey {
  return { id: p.id, created_at: p.created_at };
}

function findByKey(list: ProfileSummary[], key: PersonKey | null): ProfileSummary | undefined {
  if (!key) return undefined;
  return list.find((p) => p.id === key.id && p.created_at === key.created_at);
}

function readStored(): PersonKey | null {
  try {
    const raw = localStorage.getItem(PERSON_STORAGE_KEY);
    if (raw === null) return null;
    const value: unknown = JSON.parse(raw);
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const { id, created_at } = value as Record<string, unknown>;
      if (typeof id === "number" && typeof created_at === "string") return { id, created_at };
    }
  } catch {
    // Storage blocked, or a value that is not JSON: treat as nothing stored.
  }
  return null;
}

function writeStored(p: ProfileSummary): void {
  try {
    localStorage.setItem(PERSON_STORAGE_KEY, JSON.stringify(keyOf(p)));
  } catch {
    // Storage blocked: the choice lives in memory for this visit.
  }
}

/** The person's name, made distinct when someone else has the same name. */
function labelIn(p: ProfileSummary, people: ProfileSummary[]): string {
  const name = p.name.trim();
  const others = people.filter((o) => o.id !== p.id && o.name.trim() === name);
  if (others.length === 0) return p.name;
  const email = (p.contact?.email ?? "").trim();
  const emailIsShared = others.some((o) => (o.contact?.email ?? "").trim() === email);
  return email && !emailIsShared ? `${p.name} (${email})` : `${p.name} #${p.id}`;
}

export function PersonProvider({ children }: { children: ReactNode }) {
  const [people, setPeople] = useState<ProfileSummary[]>([]);
  const [selected, setSelected] = useState<PersonKey | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingSwitch, setPendingSwitch] = useState<{ target: SwitchTarget; message: string } | null>(
    null
  );

  // Mirrors of the state above, read by callbacks that must see the latest
  // values (a refresh that resolves after a switch, a setPersonId called right
  // after `await refreshPeople()`), not the ones from the render that made them.
  const peopleRef = useRef<ProfileSummary[]>([]);
  const selectedRef = useRef<PersonKey | null>(null);
  const pendingRef = useRef<{ target: SwitchTarget; message: string } | null>(null);
  const guardRef = useRef<string | null>(null);
  const loadedRef = useRef(false);
  const seqRef = useRef(0);
  const selectAfterLoadRef = useRef<number | undefined>(undefined);

  const select = useCallback((p: ProfileSummary | null, remember: boolean) => {
    const key = p ? keyOf(p) : null;
    selectedRef.current = key;
    setSelected(key);
    if (p && remember) writeStored(p);
  }, []);

  const setPending = useCallback((next: { target: SwitchTarget; message: string } | null) => {
    pendingRef.current = next;
    setPendingSwitch(next);
  }, []);

  const applyList = useCallback(
    (list: ProfileSummary[], selectId: number | undefined) => {
      const previousPeople = peopleRef.current;
      const previous = findByKey(previousPeople, selectedRef.current);
      peopleRef.current = list;
      setPeople(list);

      const wanted = selectId === undefined ? undefined : list.find((p) => p.id === selectId);
      if (wanted) {
        select(wanted, true);
        return;
      }
      const still = findByKey(list, selectedRef.current);
      if (still) {
        select(still, false);
        return;
      }
      const storedPerson = findByKey(list, readStored());
      if (previous) {
        // The current person is gone (or their id now belongs to someone
        // new). Fall back to the first person. Rewrite the stored entry only
        // when it names nobody, so a person shown for one visit
        // (remember: false) does not change where this browser opens.
        setNotice(`${labelIn(previous, previousPeople)} was removed.`);
        select(list[0] ?? null, !storedPerson);
        return;
      }
      // First good load: the remembered person if they still exist, else the
      // first person, remembered from now on.
      if (storedPerson) {
        select(storedPerson, false);
        return;
      }
      select(list[0] ?? null, true);
    },
    [select]
  );

  const refreshPeople = useCallback(
    async (selectId?: number): Promise<void> => {
      const seq = ++seqRef.current;
      if (selectId !== undefined) selectAfterLoadRef.current = selectId;
      try {
        const list = await listProfiles();
        if (seq !== seqRef.current) return;
        const want = selectAfterLoadRef.current;
        selectAfterLoadRef.current = undefined;
        loadedRef.current = true;
        setError(null);
        applyList(list, want);
      } catch (e) {
        if (seq !== seqRef.current) return;
        // After a good load, a failed refresh keeps the last list and person
        // rather than blanking every screen over a blip.
        if (!loadedRef.current) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (seq === seqRef.current) setLoading(false);
      }
    },
    [applyList]
  );

  useEffect(() => {
    void refreshPeople();
    return () => {
      // Drop whatever is still in flight: it belongs to an unmounted provider.
      seqRef.current += 1;
    };
  }, [refreshPeople]);

  useEffect(() => {
    function onVisibility() {
      if (document.visibilityState === "visible") void refreshPeople();
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [refreshPeople]);

  const setPersonId = useCallback(
    (id: number, opts?: { remember?: boolean }) => {
      const target = peopleRef.current.find((p) => p.id === id);
      if (!target) return;
      select(target, opts?.remember ?? true);
    },
    [select]
  );

  const switchNow = useCallback(
    (target: SwitchTarget) => {
      setNotice(null);
      if (target !== "new") setPersonId(target, { remember: true });
    },
    [setPersonId]
  );

  const requestSwitch = useCallback(
    (target: SwitchTarget): boolean => {
      if (target !== "new" && target === selectedRef.current?.id) {
        setPending(null);
        return true;
      }
      const guard = guardRef.current;
      if (guard) {
        setPending({ target, message: guard });
        return false;
      }
      setPending(null);
      switchNow(target);
      return true;
    },
    [setPending, switchNow]
  );

  const confirmSwitch = useCallback((): SwitchTarget | null => {
    const pending = pendingRef.current;
    setPending(null);
    if (!pending) return null;
    switchNow(pending.target);
    return pending.target;
  }, [setPending, switchNow]);

  const cancelSwitch = useCallback(() => setPending(null), [setPending]);

  const setSwitchGuard = useCallback((message: string | null) => {
    guardRef.current = message;
  }, []);

  const person = useMemo(() => findByKey(people, selected) ?? null, [people, selected]);
  const labelFor = useCallback((p: ProfileSummary) => labelIn(p, people), [people]);

  const value = useMemo<PersonContextValue>(
    () => ({
      people,
      person,
      loading,
      error,
      notice,
      setNotice,
      setPersonId,
      requestSwitch,
      pendingSwitch,
      confirmSwitch,
      cancelSwitch,
      refreshPeople,
      setSwitchGuard,
      labelFor,
    }),
    [
      people,
      person,
      loading,
      error,
      notice,
      setPersonId,
      requestSwitch,
      pendingSwitch,
      confirmSwitch,
      cancelSwitch,
      refreshPeople,
      setSwitchGuard,
      labelFor,
    ]
  );

  return <PersonContext.Provider value={value}>{children}</PersonContext.Provider>;
}

export function usePerson(): PersonContextValue {
  const ctx = useContext(PersonContext);
  if (!ctx) throw new Error("usePerson must be used inside <PersonProvider>");
  return ctx;
}
```

- [ ] **Step 4: Write the test helper**

Create `frontend/src/test-utils.tsx`:

```tsx
// Test helper: render a screen inside a fixed person context and a router.
//
// Nothing in the app imports this file, so Vite never bundles it; tsc still
// type-checks it with the rest of src. Its name has no ".test.", so
// scripts/stamp-build.mjs hashes it as a build input: after editing it, run
// `npm run build` like after any other src change.
import { render } from "@testing-library/react";
import type { RenderResult } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { PersonContext } from "./person";
import type { PersonContextValue } from "./person";
import type { ProfileSummary } from "./types";

export function makePerson(p: Partial<ProfileSummary> = {}): ProfileSummary {
  return {
    id: 1,
    name: "Jordan Rivera",
    contact: { name: "Jordan Rivera", email: "jordan@example.com", links: [] },
    has_master_profile: true,
    created_at: "2026-01-01T00:00:00+00:00",
    inbox_url: null,
    ...p,
  };
}

export interface PersonTestOptions {
  people?: ProfileSummary[];
  personId?: number | null;
  loading?: boolean;
  route?: string;
  path?: string;
  overrides?: Partial<PersonContextValue>;
}

export type PersonRenderResult = RenderResult & {
  ctx: PersonContextValue;
  switchTo(id: number | null): void;
};

/**
 * Renders `ui` with a static PersonContext value, inside a MemoryRouter at
 * `route`. Every context function is a vi.fn() (labelFor returns the name,
 * requestSwitch returns true, confirmSwitch returns null, refreshPeople
 * resolves), shared across switchTo so a test can assert calls made before
 * and after a switch. `ctx` always holds the value currently rendered.
 */
export function renderWithPerson(ui: ReactElement, opts: PersonTestOptions = {}): PersonRenderResult {
  const people = opts.people ?? [makePerson()];
  const loading = opts.loading ?? false;
  const route = opts.route ?? "/";

  const fns = {
    setNotice: vi.fn(),
    setPersonId: vi.fn(),
    requestSwitch: vi.fn().mockReturnValue(true),
    confirmSwitch: vi.fn().mockReturnValue(null),
    cancelSwitch: vi.fn(),
    refreshPeople: vi.fn().mockResolvedValue(undefined),
    setSwitchGuard: vi.fn(),
    labelFor: vi.fn((p: ProfileSummary) => p.name),
  };

  function contextFor(personId: number | null): PersonContextValue {
    const person =
      loading || personId === null ? null : people.find((p) => p.id === personId) ?? null;
    return {
      people,
      person,
      loading,
      error: null,
      notice: null,
      pendingSwitch: null,
      ...fns,
      ...opts.overrides,
    };
  }

  let current: ReactNode = ui;
  function tree(value: PersonContextValue): ReactElement {
    return (
      <MemoryRouter initialEntries={[route]}>
        <PersonContext.Provider value={value}>
          {opts.path ? (
            <Routes>
              <Route path={opts.path} element={current} />
            </Routes>
          ) : (
            current
          )}
        </PersonContext.Provider>
      </MemoryRouter>
    );
  }

  const initialId = opts.personId === undefined ? people[0]?.id ?? null : opts.personId;
  const ctx = contextFor(initialId);
  const result = render(tree(ctx));
  const out: PersonRenderResult = {
    ...result,
    ctx,
    // Re-render a new element inside the same context and router.
    rerender(next: ReactNode) {
      current = next;
      result.rerender(tree(out.ctx));
    },
    switchTo(id: number | null) {
      out.ctx = contextFor(id);
      result.rerender(tree(out.ctx));
    },
  };
  return out;
}
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `cd frontend && npx vitest run src/person.test.tsx`

Expected: `Tests  42 passed (42)`, with no React "not wrapped in act" warnings and no uncaught-error noise (the one test that renders outside a provider silences both).

Run: `cd frontend && npx tsc && npm test`

Expected: `tsc` prints nothing; every vitest file passes, 0 failed.

- [ ] **Step 6: Rebuild the bundle and check the stamp**

Run: `cd frontend && npm run build`

Expected: ends with `stamp-build: recorded <n> build inputs` (two more than before: `src/person.tsx` and `src/test-utils.tsx`).

Run (repo root): `.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q`

Expected: `3 passed`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/person.tsx frontend/src/test-utils.tsx frontend/src/person.test.tsx frontend/dist
git commit -m "$(cat <<'EOF'
feat: PersonProvider, the app-wide active person

Remembers {id, created_at} per browser and falls back to the first person
when that person is gone or their id was reissued; refreshes on tab focus;
announces a removed person; holds guarded switches for an inline prompt.
Adds renderWithPerson/makePerson for screen tests.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```


---

### Task 12: The person picker in the nav

**Files:**
- Create: `frontend/src/components/PersonPicker.tsx`
- Create: `frontend/src/components/PersonPicker.test.tsx`
- Modify: `frontend/src/main.tsx` (mount `PersonProvider` inside `BrowserRouter`)
- Modify: `frontend/src/App.tsx` (import; wrap the theme toggle and the picker in `.nav-end`)
- Modify: `frontend/src/styles.css` (replace the `.nav-theme-toggle` rule; extend the 640px media query)
- Modify: `frontend/src/App.test.tsx` (mount App inside `PersonProvider`; two new tests)
- Test: `frontend/src/components/PersonPicker.test.tsx`, `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes (Task 11): `usePerson()` and its `people`, `person`, `loading`, `error`, `notice`, `setNotice`, `requestSwitch`, `pendingSwitch`, `confirmSwitch`, `cancelSwitch`, `labelFor`; `PersonProvider`; `SwitchTarget`; test helpers `renderWithPerson`, `makePerson`, `PersonTestOptions` from `frontend/src/test-utils.tsx`.
- Produces:
  - `frontend/src/components/PersonPicker.tsx`, default export `PersonPicker()` (no props), rendered once in the nav by `App`. Screens never render it.
  - The picker's DOM contract, which later screen tests can query when they render `App`: `<select aria-label="Person">` whose options are `labelFor(p)` for each person then `Add a person…` (value `"new"`; the last character is U+2026); with no people a link named `Add a person` to `/profiles?new=1`; an `Inbox` link (`target="_blank"`, `rel="noopener noreferrer"`) when `person.inbox_url` is set; a held switch as `role="alert"` with buttons `Switch anyway` and `Stay`; the notice as `role="status"` with a button labelled `Dismiss`.
  - Navigation rules: after a switch to `"new"` (immediate or confirmed) the picker navigates to `/profiles?new=1`; after a numeric switch (immediate or confirmed) while `location.pathname` starts with `/applications/` it navigates to `/`. A switch the guard held back does not navigate.
  - While loading, and after a failed first load, the picker renders neither the select nor the link (so "no people" is never claimed while the API is down).
  - `main.tsx` tree: `<React.StrictMode><BrowserRouter><PersonProvider><App /></PersonProvider></BrowserRouter></React.StrictMode>`. Any test that renders `<App />` must wrap it in `<MemoryRouter><PersonProvider>...</PersonProvider></MemoryRouter>` (as `App.test.tsx` now does) or use `renderWithPerson`.
  - CSS classes: `.nav-end`, `.person-picker`, `.person-select`, `.person-popovers`, `.person-popover`, `.person-popover-message`.

At this point the screens still fetch their own profile lists (Tasks 13-19 move them onto `usePerson`), so `App.test.tsx`'s `listProfiles` mock is called both by the provider and by the Dashboard. The tests below therefore set it with `mockResolvedValue` (not `...Once`) and reset it in `beforeEach`.

- [ ] **Step 1: Write the failing picker tests**

Create `frontend/src/components/PersonPicker.test.tsx` (the `ADD_OPTION` constant ends in the single character U+2026, not three dots):

```tsx
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import PersonPicker from "./PersonPicker";
import { PersonProvider, usePerson } from "../person";
import type { PersonContextValue } from "../person";
import * as api from "../api";
import { makePerson, renderWithPerson } from "../test-utils";
import type { PersonTestOptions } from "../test-utils";

vi.mock("../api", () => ({ listProfiles: vi.fn() }));

const ADD_OPTION = "Add a person…"; // U+2026, as the spec writes it

const JORDAN = makePerson();
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
  created_at: "2026-02-01T00:00:00+00:00",
});

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function renderPicker(opts: PersonTestOptions = {}) {
  return renderWithPerson(
    <>
      <PersonPicker />
      <Where />
    </>,
    { people: [JORDAN, SAM], ...opts }
  );
}

const picker = () => screen.getByRole("combobox", { name: "Person" });
const where = () => screen.getByTestId("where");

describe("PersonPicker with people", () => {
  it("lists every person plus Add a person, with the current person selected", () => {
    renderPicker({ personId: 2 });
    const options = within(picker()).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Jordan Rivera", "Sam Lee", ADD_OPTION]);
    expect(picker()).toHaveValue("2");
  });

  it("labels options with labelFor", () => {
    renderPicker({
      overrides: { labelFor: (p) => `${p.name} (${p.contact.email})` },
    });
    expect(within(picker()).getByRole("option", { name: "Sam Lee (sam@example.com)" })).toBeInTheDocument();
  });

  it("asks the provider to switch, and stays on the page", () => {
    const r = renderPicker({ route: "/add" });
    fireEvent.change(picker(), { target: { value: "2" } });
    expect(r.ctx.requestSwitch).toHaveBeenCalledWith(2);
    expect(where()).toHaveTextContent("/add");
  });

  it("goes back to the dashboard after a switch made on an application page", () => {
    renderPicker({ route: "/applications/5" });
    fireEvent.change(picker(), { target: { value: "2" } });
    expect(where()).toHaveTextContent(/^\/$/);
  });

  it("stays on the application page when the guard holds the switch back", () => {
    renderPicker({
      route: "/applications/5",
      overrides: { requestSwitch: vi.fn().mockReturnValue(false) },
    });
    fireEvent.change(picker(), { target: { value: "2" } });
    expect(where()).toHaveTextContent("/applications/5");
    expect(picker()).toHaveValue("1");
  });

  it("opens the create form for Add a person and snaps back to the current person", () => {
    const r = renderPicker();
    fireEvent.change(picker(), { target: { value: "new" } });
    expect(r.ctx.requestSwitch).toHaveBeenCalledWith("new");
    expect(where()).toHaveTextContent("/profiles?new=1");
    expect(picker()).toHaveValue("1");
  });

  it("links the current person's inbox in a new tab", () => {
    renderPicker({
      people: [makePerson({ inbox_url: "https://mail.google.com/mail/?authuser=jordan@gmail.com" })],
    });
    const inbox = screen.getByRole("link", { name: "Inbox" });
    expect(inbox).toHaveAttribute("href", "https://mail.google.com/mail/?authuser=jordan@gmail.com");
    expect(inbox).toHaveAttribute("target", "_blank");
    expect(inbox).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows no Inbox link when the person has no inbox_url", () => {
    renderPicker();
    expect(screen.queryByRole("link", { name: "Inbox" })).not.toBeInTheDocument();
  });
});

describe("PersonPicker without a person", () => {
  it("offers an Add a person link when there are no people", () => {
    renderPicker({ people: [] });
    expect(screen.queryByRole("combobox", { name: "Person" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add a person" })).toHaveAttribute(
      "href",
      "/profiles?new=1"
    );
  });

  it("shows neither the select nor the link while loading", () => {
    renderPicker({ loading: true });
    expect(screen.queryByRole("combobox", { name: "Person" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Add a person" })).not.toBeInTheDocument();
  });

  it("does not claim there are no people when the list failed to load", () => {
    renderPicker({ people: [], overrides: { error: "API 500: boom" } });
    expect(screen.queryByRole("link", { name: "Add a person" })).not.toBeInTheDocument();
  });
});

describe("PersonPicker prompts", () => {
  const pending: PersonContextValue["pendingSwitch"] = {
    target: 2,
    message: "Jordan Rivera has unsaved profile changes.",
  };

  it("shows a held switch inline with Switch anyway and Stay", () => {
    const r = renderPicker({
      route: "/applications/5",
      overrides: { pendingSwitch: pending, confirmSwitch: vi.fn().mockReturnValue(2) },
    });
    const prompt = screen.getByRole("alert");
    expect(prompt).toHaveTextContent("Jordan Rivera has unsaved profile changes.");
    fireEvent.click(within(prompt).getByRole("button", { name: "Switch anyway" }));
    expect(r.ctx.confirmSwitch).toHaveBeenCalled();
    expect(where()).toHaveTextContent(/^\/$/);
  });

  it("Stay cancels the held switch", () => {
    const r = renderPicker({ overrides: { pendingSwitch: pending } });
    fireEvent.click(screen.getByRole("button", { name: "Stay" }));
    expect(r.ctx.cancelSwitch).toHaveBeenCalled();
    expect(where()).toHaveTextContent(/^\/$/);
  });

  it("opens the create form when a held Add a person is confirmed", () => {
    renderPicker({
      overrides: {
        pendingSwitch: { target: "new", message: pending.message },
        confirmSwitch: vi.fn().mockReturnValue("new"),
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Switch anyway" }));
    expect(where()).toHaveTextContent("/profiles?new=1");
  });

  it("shows the notice with a Dismiss button", () => {
    const r = renderPicker({ overrides: { notice: "Sam Lee was removed." } });
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Sam Lee was removed.");
    fireEvent.click(within(notice).getByRole("button", { name: "Dismiss" }));
    expect(r.ctx.setNotice).toHaveBeenCalledWith(null);
  });

  it("shows no prompt and no notice by default", () => {
    renderPicker();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("PersonPicker with the real provider", () => {
  let latest: PersonContextValue;

  function Guard({ message }: { message: string | null }) {
    const ctx = usePerson();
    latest = ctx;
    const { setSwitchGuard } = ctx;
    useEffect(() => {
      setSwitchGuard(message);
      return () => setSwitchGuard(null);
    }, [message, setSwitchGuard]);
    return null;
  }

  function renderLive(message: string | null) {
    render(
      <MemoryRouter>
        <PersonProvider>
          <Guard message={message} />
          <PersonPicker />
        </PersonProvider>
      </MemoryRouter>
    );
  }

  beforeEach(() => {
    localStorage.clear();
    vi.mocked(api.listProfiles).mockReset();
  });

  it("holds a guarded pick, keeps showing the current person, then switches on confirm", async () => {
    vi.mocked(api.listProfiles).mockResolvedValue([JORDAN, SAM]);
    renderLive("Jordan Rivera has unsaved profile changes.");
    await screen.findByRole("combobox", { name: "Person" });

    fireEvent.change(picker(), { target: { value: "2" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Jordan Rivera has unsaved profile changes.");
    expect(picker()).toHaveValue("1");

    fireEvent.click(screen.getByRole("button", { name: "Switch anyway" }));
    expect(picker()).toHaveValue("2");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("switches straight away without a guard", async () => {
    vi.mocked(api.listProfiles).mockResolvedValue([JORDAN, SAM]);
    renderLive(null);
    await screen.findByRole("combobox", { name: "Person" });
    fireEvent.change(picker(), { target: { value: "2" } });
    expect(picker()).toHaveValue("2");
  });

  it("updates the Inbox link when a refresh brings a new email", async () => {
    vi.mocked(api.listProfiles).mockResolvedValueOnce([JORDAN]);
    renderLive(null);
    await screen.findByRole("combobox", { name: "Person" });
    expect(screen.queryByRole("link", { name: "Inbox" })).not.toBeInTheDocument();

    vi.mocked(api.listProfiles).mockResolvedValueOnce([
      { ...JORDAN, inbox_url: "https://mail.google.com/mail/?authuser=jordan@gmail.com" },
    ]);
    await act(() => latest.refreshPeople());
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Inbox" })).toHaveAttribute(
        "href",
        "https://mail.google.com/mail/?authuser=jordan@gmail.com"
      )
    );
  });
});
```

- [ ] **Step 2: Update App.test.tsx for the provider and add the nav tests**

`App` will call `usePerson()` through the picker, so every existing render of `<App />` must sit inside `PersonProvider`. In `frontend/src/App.test.tsx`, the two existing tests currently render (verbatim, twice):

```tsx
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
```

They now call `renderApp()`, which wraps `App` in `PersonProvider`. The existing assertions are unchanged. Replace the whole file with:

```tsx
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import * as api from "./api";
import { PersonProvider } from "./person";

vi.mock("./api", () => ({
  listProfiles: vi.fn().mockResolvedValue([]),
  listApplications: vi.fn().mockResolvedValue([]),
  getSettings: vi.fn().mockResolvedValue({
    api_key_set: false,
    fake_mode: true,
    default_template: "slate",
    default_depth: "standard",
    page_size: "Letter",
  }),
  createProfile: vi.fn(),
  getProfile: vi.fn(),
  updateProfile: vi.fn(),
  uploadDocument: vi.fn(),
  buildProfile: vi.fn(),
  createApplications: vi.fn(),
  getApplication: vi.fn(),
  pasteJobText: vi.fn(),
  updateContent: vi.fn(),
  regenerate: vi.fn(),
  updateSettings: vi.fn(),
  previewUrl: (id: number) => `/api/applications/${id}/preview`,
  exportUrl: (id: number, kind: string) => `/api/applications/${id}/exports/${kind}`,
}));

function renderApp(route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <PersonProvider>
        <App />
      </PersonProvider>
    </MemoryRouter>
  );
}

describe("App shell", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(api.listProfiles).mockResolvedValue([]);
  });

  it("renders the brand and all nav links", () => {
    renderApp();
    expect(screen.getByText("Tailored")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    const nav = screen.getByRole("navigation");
    expect(within(nav).getByRole("link", { name: "Getting Started" })).toHaveAttribute(
      "href",
      "/getting-started"
    );
    expect(screen.getByRole("link", { name: "Add Jobs" })).toHaveAttribute("href", "/add");
    expect(screen.getByRole("link", { name: "Templates" })).toHaveAttribute("href", "/templates");
    expect(screen.getByRole("link", { name: "Profiles" })).toHaveAttribute("href", "/profiles");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");

    const themeToggle = screen.getByRole("button", { name: /switch to (light|dark) theme/i });
    expect(themeToggle).toBeInTheDocument();
    expect(themeToggle).toHaveAttribute("aria-label");
  });

  it("renders the real Dashboard screen on /", async () => {
    renderApp();
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("puts the person picker in the nav, just before the theme toggle", async () => {
    vi.mocked(api.listProfiles).mockResolvedValue([
      {
        id: 1,
        name: "Jordan Rivera",
        contact: { name: "Jordan Rivera", email: "jordan@example.com", links: [] },
        has_master_profile: true,
        created_at: "2026-01-01T00:00:00+00:00",
        inbox_url: null,
      },
    ]);
    renderApp();
    const nav = screen.getByRole("navigation");
    const picker = await within(nav).findByRole("combobox", { name: "Person" });
    expect(picker).toHaveValue("1");
    const toggle = within(nav).getByRole("button", { name: /switch to (light|dark) theme/i });
    expect(picker.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(picker.closest(".nav-end")).toBe(toggle.closest(".nav-end"));
  });

  it("offers Add a person in the nav when there are no people", async () => {
    renderApp();
    const nav = screen.getByRole("navigation");
    expect(await within(nav).findByRole("link", { name: "Add a person" })).toHaveAttribute(
      "href",
      "/profiles?new=1"
    );
    expect(within(nav).queryByRole("combobox", { name: "Person" })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `cd frontend && npx vitest run src/components/PersonPicker.test.tsx src/App.test.tsx`

Expected: `src/components/PersonPicker.test.tsx` fails to load with `Error: Failed to resolve import "./PersonPicker" from "src/components/PersonPicker.test.tsx". Does the file exist?`. In `src/App.test.tsx`, `Tests  2 failed | 2 passed (4)`: "puts the person picker in the nav, just before the theme toggle" fails with `Unable to find role="combobox" and name "Person"`, and "offers Add a person in the nav when there are no people" fails with `Unable to find role="link" and name "Add a person"`. The two existing tests pass (the provider renders its children; nothing calls `usePerson` yet).

- [ ] **Step 4: Write the picker**

Create `frontend/src/components/PersonPicker.tsx` (the `ADD_A_PERSON_OPTION` string ends in the single character U+2026, the one ellipsis the voice rules allow, because the spec writes the option that way; the Dismiss glyph is U+00D7):

```tsx
import type { ChangeEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { usePerson } from "../person";
import type { SwitchTarget } from "../person";

/** Where "Add a person" goes: the Profiles screen's create form. */
const NEW_PERSON_PATH = "/profiles?new=1";

// The one ellipsis character the voice rules allow: the spec writes it this way.
const ADD_A_PERSON_OPTION = "Add a person…";

/**
 * The app-wide person switch in the nav. The select is controlled by the
 * provider's person, so after any pick it shows whoever is actually selected:
 * the "Add a person" option can be picked again, and a switch the guard held
 * back shows the unchanged person.
 */
export default function PersonPicker() {
  const {
    people,
    person,
    loading,
    error,
    notice,
    setNotice,
    requestSwitch,
    pendingSwitch,
    confirmSwitch,
    cancelSwitch,
    labelFor,
  } = usePerson();
  const navigate = useNavigate();
  const location = useLocation();

  function afterSwitch(target: SwitchTarget) {
    if (target === "new") {
      navigate(NEW_PERSON_PATH);
    } else if (location.pathname.startsWith("/applications/")) {
      // The open application belongs to the previous person.
      navigate("/");
    }
  }

  function onChange(e: ChangeEvent<HTMLSelectElement>) {
    const target: SwitchTarget = e.target.value === "new" ? "new" : Number(e.target.value);
    if (requestSwitch(target)) afterSwitch(target);
  }

  function onConfirm() {
    const target = confirmSwitch();
    if (target !== null) afterSwitch(target);
  }

  const noPeople = !loading && !error && people.length === 0;

  return (
    <div className="person-picker">
      {person ? (
        <select
          className="select person-select"
          aria-label="Person"
          value={person.id}
          onChange={onChange}
        >
          {people.map((p) => (
            <option key={p.id} value={p.id}>
              {labelFor(p)}
            </option>
          ))}
          <option value="new">{ADD_A_PERSON_OPTION}</option>
        </select>
      ) : noPeople ? (
        <Link to={NEW_PERSON_PATH} className="nav-link">
          Add a person
        </Link>
      ) : null}
      {person?.inbox_url ? (
        <a
          href={person.inbox_url}
          target="_blank"
          rel="noopener noreferrer"
          className="nav-link"
        >
          Inbox
        </a>
      ) : null}
      {pendingSwitch || notice ? (
        <div className="person-popovers">
          {pendingSwitch ? (
            <div role="alert" className="person-popover">
              <span className="person-popover-message">{pendingSwitch.message}</span>
              <button type="button" className="btn btn-small btn-danger" onClick={onConfirm}>
                Switch anyway
              </button>
              <button type="button" className="btn btn-small btn-primary" onClick={cancelSwitch}>
                Stay
              </button>
            </div>
          ) : null}
          {notice ? (
            <div role="status" className="person-popover">
              <span className="person-popover-message">{notice}</span>
              <button
                type="button"
                className="btn btn-ghost btn-small"
                aria-label="Dismiss"
                onClick={() => setNotice(null)}
              >
                ×
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 5: Mount the provider and place the picker in the nav**

In `frontend/src/main.tsx`, replace the current code (verbatim):

```tsx
import App from "./App";
import { initTheme } from "./theme";
```

with:

```tsx
import App from "./App";
import { PersonProvider } from "./person";
import { initTheme } from "./theme";
```

and replace the current code (verbatim):

```tsx
    <BrowserRouter>
      <App />
    </BrowserRouter>
```

with:

```tsx
    <BrowserRouter>
      <PersonProvider>
        <App />
      </PersonProvider>
    </BrowserRouter>
```

In `frontend/src/App.tsx`, replace the current code (verbatim):

```tsx
import SettingsScreen from "./screens/SettingsScreen";
```

with:

```tsx
import SettingsScreen from "./screens/SettingsScreen";
import PersonPicker from "./components/PersonPicker";
```

and replace the current code (verbatim; the two glyphs are U+2600 and U+263E, already in the file):

```tsx
          <button
            type="button"
            className="btn btn-ghost nav-theme-toggle"
            onClick={toggleTheme}
            aria-label={resolved === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          >
            {resolved === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
```

with:

```tsx
          <div className="nav-end">
            <PersonPicker />
            <button
              type="button"
              className="btn btn-ghost nav-theme-toggle"
              onClick={toggleTheme}
              aria-label={resolved === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            >
              {resolved === "dark" ? "☀ Light" : "☾ Dark"}
            </button>
          </div>
```

- [ ] **Step 6: Style the picker**

The toggle used to push itself right with `margin-left: auto`; the `.nav-end` wrapper now does that for picker and toggle together. In `frontend/src/styles.css`, replace the current code (verbatim):

```css
.nav-theme-toggle { margin-left: auto; }
```

with:

```css
/* ---- nav: person picker + theme toggle, kept together at the right ---- */
.nav-end { margin-left: auto; display: flex; align-items: center; gap: 0.75rem; }
.person-picker { position: relative; display: flex; align-items: center; gap: 0.75rem; }
.person-select { width: auto; max-width: 16rem; padding: 0.3rem 0.5rem; }
/* The held-switch prompt and the notice hang under the picker instead of
   pushing the nav taller. */
.person-popovers {
  position: absolute; top: calc(100% + 0.5rem); right: 0; z-index: 40;
  display: flex; flex-direction: column; gap: 0.5rem;
  width: max-content; max-width: min(22rem, calc(100vw - 2rem));
}
.person-popover {
  display: flex; align-items: center; gap: 0.5rem;
  background: var(--surface); color: var(--ink);
  border: 1px solid var(--border); border-left: 4px solid var(--accent);
  border-radius: var(--radius); box-shadow: 0 4px 12px var(--shadow-color);
  padding: 0.6rem 0.75rem; font-size: var(--fs-sm);
}
.person-popover-message { flex: 1 1 auto; min-width: 0; }
```

and replace the current code (verbatim):

```css
@media (max-width: 640px) {
  .nav-inner { flex-wrap: wrap; gap: 0.75rem; }
  .row { flex-direction: column; align-items: stretch; }
}
```

with:

```css
@media (max-width: 640px) {
  .nav-inner { flex-wrap: wrap; gap: 0.75rem; }
  .nav-end, .person-picker { flex-wrap: wrap; }
  .person-select { max-width: 11rem; }
  /* On a phone the prompt joins the flow on its own line, full width,
     rather than hanging off an edge of the screen. */
  .person-popovers { position: static; flex-basis: 100%; width: auto; max-width: none; }
  .row { flex-direction: column; align-items: stretch; }
}
```

Colors come only from the existing tokens (`--surface`, `--ink`, `--border`, `--accent`, `--shadow-color`), so dark mode needs nothing extra. At 390px wide the nav wraps: brand and links, then a line with the select (capped at 11rem), Inbox and the theme toggle; a notice or held-switch prompt takes its own full-width line under the select instead of hanging off the screen edge. On desktop they hang under the picker, right-aligned, without making the nav taller.

- [ ] **Step 7: Run the tests and watch them pass**

Run: `cd frontend && npx vitest run src/components/PersonPicker.test.tsx src/App.test.tsx`

Expected: `Test Files  2 passed (2)`, `Tests  23 passed (23)` (19 picker, 4 App).

Run: `cd frontend && npx tsc && npm test`

Expected: `tsc` prints nothing; every vitest file passes, 0 failed. The other screen suites render screens without `App`, so they are unaffected.

- [ ] **Step 8: Rebuild the bundle and check the stamp**

Run: `cd frontend && npm run build`

Expected: `tsc` and `vite build` succeed and the output ends with `stamp-build: recorded <n> build inputs`. `frontend/dist/assets/` now holds a new `index-*.js` and `index-*.css` (the old hashed files are deleted by the build).

Run (repo root): `.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q`

Expected: `3 passed`.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/PersonPicker.tsx frontend/src/components/PersonPicker.test.tsx frontend/src/main.tsx frontend/src/App.tsx frontend/src/styles.css frontend/src/App.test.tsx frontend/dist
git commit -m "$(cat <<'EOF'
feat: person picker in the nav

One select on every screen, beside the theme toggle: every person, then
the "Add a person" option; an Add a person link when there is nobody; the current
person's Inbox link; the held-switch prompt and the removed-person notice
inline under it. PersonProvider now wraps the app.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

`git status` must be clean afterwards; if `frontend/dist` still shows changes, the rebuilt assets were not added.


---

### Task 13: Dashboard lists the current person's applications

**Files:**
- Modify: `frontend/src/screens/DashboardScreen.tsx` (imports; `usePolling`; the top of `DashboardScreen` through `runBulk`; the "Profile" dropdown block in the JSX; the table's empty row)
- Modify: `frontend/src/screens/DashboardScreen.test.tsx` (rewritten onto `renderWithPerson`; new describe block)
- Rebuild: `frontend/dist` (committed)
- Test: `frontend/src/screens/DashboardScreen.test.tsx`

**Interfaces:**
- Consumes: `usePerson()` from `frontend/src/person.tsx` (Task 11), reading `person: ProfileSummary | null`, `loading: boolean` and `error: string | null`. `makePerson(p?: Partial<ProfileSummary>): ProfileSummary` and `renderWithPerson(ui, opts?: PersonTestOptions): RenderResult & { ctx; switchTo(id: number | null): void }` from `frontend/src/test-utils.tsx` (Task 11). Existing `listApplications(profileId?: number, opts?: { stage?: Stage; archived?: boolean })` from `frontend/src/api.ts` (unchanged).
- Produces: no new exports. `usePolling(profileId: number | undefined, archived: boolean, reloadKey: number): ApplicationSummary[]` keeps its exported signature. Nothing later in the plan relies on this task's internals.
- Choices made here (the contract leaves them open):
  - `usePolling` makes no request while `profileId` is `undefined`, and stores each response together with the id it was fetched for. It returns only the rows fetched for the current `profileId` (otherwise an empty array), so on the very render where the person changes the table is already empty, before any effect has run. A response that lands after the person, tab or reload key changed is dropped by the existing `stopped` flag.
  - On a person change the screen also clears the row selection (as today on a tab change), closes an open "Delete permanently?" confirmation (it lists the previous person's rows and would still delete them), and clears the error line.
  - An action (`run`, `runBulk`) that settles after a switch does not set the error line: it describes the previous person's rows. It still calls `reload()`, which refetches for whoever is current.
  - No heading or label change on the Dashboard: the nav picker already names the person.
  - Spec 4.1 (nothing person-dependent until the people list has loaded): while `loading` is true the table's empty row reads `Loading...`, and after a failed first load it shows the provider's `error` text. The onboarding line ("No applications yet. New here? ...") and the per-tab "Nothing ..." lines appear only once `loading` is false and `error` is null, since neither is true before then. `loading` and `error` are destructured as `peopleLoading` and `peopleError`, because `error` already names the screen's action-error state. The tabs and their counts still render, as they do today before the first poll lands.
  - `listProfiles` is removed from the test file's `../api` mock on purpose. vitest throws on any access to an export a factory mock does not define, so a regression that makes the screen fetch its own profile list fails every test in the file.
- Order and overlap: no earlier task edits `DashboardScreen.tsx` or its test. Task 12's `App.test.tsx` renders the real Dashboard under the real `PersonProvider` with `listProfiles` resolving `[]`; after this task the Dashboard makes no request there and still renders its "Dashboard" heading, so that test is unaffected. The working tree uses CRLF line endings (`core.autocrlf=true`); make the edits with an editor or the Edit tool rather than a script that rewrites line endings.

- [ ] **Step 1: Rewrite the Dashboard tests onto `renderWithPerson` and add the per-person tests**

Replace the entire contents of `frontend/src/screens/DashboardScreen.test.tsx` with the file below. What changes in the existing tests, and why:

- The `../api` mock loses `listProfiles` (and the `contact` const it used). Old: `listProfiles: vi.fn().mockResolvedValue([{ id: 1, name: "Jordan Rivera", contact, has_master_profile: true }]),`. New: absent; the screen must not call it.
- Every `render(<MemoryRouter><DashboardScreen /></MemoryRouter>)` (and the multi-line one in the empty-state test) becomes `renderWithPerson(<DashboardScreen />)`. The helper's default person is `makePerson()` with `id: 1`, so `expect(api.listApplications).toHaveBeenCalledWith(1, { archived: true })` in the archived test is unchanged and still proves the id comes from the person.
- A file-level `beforeEach(() => { vi.clearAllMocks(); })` is added, because the new tests assert "not called". It clears call history only; implementations set with `mockResolvedValue` stay, so the first test still gets the factory's two rows.
- The new describe block "DashboardScreen and the current person" has 9 tests. Two of them cover the provider's `loading` and `error` states. `renderWithPerson` fixes `loading` for the whole render (its `switchTo` changes only the person), so no test combines `loading: true` with `switchTo`.
- The comment in "refreshes the table even when an action fails" no longer claims that "profileId resolving async triggers its own refetch" (the person now arrives synchronously from context). Its assertions are unchanged.

```tsx
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import DashboardScreen from "./DashboardScreen";
import * as api from "../api";
import { makePerson, renderWithPerson } from "../test-utils";
import type { ApplicationDetail, ApplicationSummary } from "../types";

// listProfiles is deliberately absent. The screen reads the person from
// PersonContext; vitest throws on any access to an export this factory does
// not define, so a screen that fetched its own profile list would fail here.
vi.mock("../api", () => {
  return {
    listApplications: vi.fn().mockResolvedValue([
      {
        id: 10,
        profile_id: 1,
        status: "ready",
        version: 2,
        template: "slate",
        depth: "standard",
        url: "https://example.com/a",
        company: "Acme",
        title: "Backend Engineer",
        cost_usd: 0.4321,
        created_at: "2026-07-22T10:00:00",
        error_message: null,
        stage: "applied",
        applied_at: "2026-07-22T10:30:00+00:00",
        archived_at: null,
        last_activity_at: "2026-07-22T10:30:00+00:00",
      },
      {
        id: 11,
        profile_id: 1,
        status: "tailoring",
        version: 1,
        template: "terminal",
        depth: "deep",
        url: "https://example.com/b",
        company: "Globex",
        title: "Platform Engineer",
        cost_usd: 0.1,
        created_at: "2026-07-22T11:00:00",
        error_message: null,
        stage: "drafted",
        applied_at: null,
        archived_at: null,
        last_activity_at: "2026-07-22T11:00:00+00:00",
      },
    ]),
    patchApplication: vi.fn().mockResolvedValue(undefined),
    archiveApplication: vi.fn().mockResolvedValue(undefined),
    restoreApplication: vi.fn().mockResolvedValue(undefined),
    deleteApplication: vi.fn().mockResolvedValue(undefined),
    generateApplication: vi.fn().mockResolvedValue(undefined),
  };
});

const BASE_APP = {
  id: 10,
  profile_id: 1,
  status: "ready" as const,
  version: 2,
  template: "slate" as const,
  depth: "standard" as const,
  url: "https://example.com/a",
  company: "Acme",
  title: "Backend Engineer",
  cost_usd: 0.4321,
  created_at: "2026-07-22T10:00:00",
  error_message: null,
  stage: "applied" as const,
  applied_at: "2026-07-22T10:30:00+00:00",
  archived_at: null,
  last_activity_at: "2026-07-22T10:30:00+00:00",
};

const JORDAN = makePerson();
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
  created_at: "2026-02-01T00:00:00+00:00",
});

// One row per person, both on the default "To apply" tab (stage drafted) and
// both terminal (status ready), so no poll timer is left running.
const JORDAN_ROW: ApplicationSummary = {
  ...BASE_APP,
  id: 10,
  profile_id: 1,
  company: "JordanCo",
  stage: "drafted",
  applied_at: null,
};
const SAM_ROW: ApplicationSummary = {
  ...BASE_APP,
  id: 20,
  profile_id: 2,
  company: "SamCo",
  stage: "drafted",
  applied_at: null,
};

beforeEach(() => {
  // Call history only; the implementations set with mockResolvedValue stay.
  vi.clearAllMocks();
});

/**
 * Renders on the All tab, where every fixture row is visible whatever its
 * stage. The screen opens on "To apply", which deliberately hides anything
 * already sent -- so tests about badges, stage editing, deletion, and refetch
 * say "All" explicitly rather than depending on the default.
 */
async function renderOnAllTab() {
  renderWithPerson(<DashboardScreen />);
  fireEvent.click(await screen.findByRole("button", { name: /^all/i }));
}

describe("DashboardScreen", () => {
  it("renders one row per application with per-status badges", async () => {
    await renderOnAllTab();
    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("Globex")).toBeInTheDocument();
    // Badges name the artifact, not the enum: "ready" alone read as "ready to
    // apply" and collided with the Stage column.
    expect(screen.getByText("Docs ready")).toHaveClass("badge", "badge-ready");
    expect(screen.getByText("Writing")).toHaveClass("badge", "badge-tailoring");
    expect(screen.getByLabelText(/stage for row 1/i)).toHaveValue("applied");
    expect(screen.getAllByText("Open")).toHaveLength(2);
  });

  it("separates what still needs sending from what is already out", async () => {
    // The whole point of the tabs: "which have I applied for and which haven't"
    // must be answerable without reading a stage column row by row.
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 1, company: "NotSentYet", stage: "drafted", applied_at: null },
      { ...BASE_APP, id: 2, company: "AlsoNotSent", stage: "saved", status: "not_started", applied_at: null },
      { ...BASE_APP, id: 3, company: "AlreadySent", stage: "applied" },
      { ...BASE_APP, id: 4, company: "Interviewing", stage: "interview" },
      { ...BASE_APP, id: 5, company: "TurnedDown", stage: "rejected" },
    ]);
    renderWithPerson(<DashboardScreen />);

    // Opens on "To apply": only the two that have not gone out.
    expect(await screen.findByText("NotSentYet")).toBeInTheDocument();
    expect(screen.getByText("AlsoNotSent")).toBeInTheDocument();
    expect(screen.queryByText("AlreadySent")).not.toBeInTheDocument();
    expect(screen.queryByText("TurnedDown")).not.toBeInTheDocument();

    // "Applied" holds everything sent and still live -- including later
    // stages, since an interview is a sent application that progressed.
    fireEvent.click(screen.getByRole("button", { name: /^applied/i }));
    expect(await screen.findByText("AlreadySent")).toBeInTheDocument();
    expect(screen.getByText("Interviewing")).toBeInTheDocument();
    expect(screen.queryByText("NotSentYet")).not.toBeInTheDocument();
    expect(screen.queryByText("TurnedDown")).not.toBeInTheDocument();

    // "Closed" isolates the dead ones so they stop padding the live count.
    fireEvent.click(screen.getByRole("button", { name: /^closed/i }));
    expect(await screen.findByText("TurnedDown")).toBeInTheDocument();
    expect(screen.queryByText("AlreadySent")).not.toBeInTheDocument();
  });

  it("counts every bucket so the split is readable without switching tabs", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 1, company: "A", stage: "drafted", applied_at: null },
      { ...BASE_APP, id: 2, company: "B", stage: "applied" },
      { ...BASE_APP, id: 3, company: "C", stage: "offer" },
      { ...BASE_APP, id: 4, company: "D", stage: "rejected" },
    ]);
    renderWithPerson(<DashboardScreen />);

    expect(await screen.findByRole("button", { name: /to apply 1/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /applied 2/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /closed 1/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /all 4/i })).toBeInTheDocument();
  });

  it("shows Getting Started and profile links in the empty state", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([]);
    renderWithPerson(<DashboardScreen />);
    expect(
      await screen.findByRole("link", { name: /Getting Started/ })
    ).toHaveAttribute("href", "/getting-started");
    expect(screen.getByRole("link", { name: /create your Master Profile/ })).toHaveAttribute(
      "href",
      "/profiles"
    );
    expect(screen.getByRole("link", { name: /add job URLs/ })).toHaveAttribute("href", "/add");
    expect(screen.queryByText("Acme")).not.toBeInTheDocument();
  });

  it("stops polling when every application is in a terminal state", async () => {
    vi.useFakeTimers();
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 1, status: "not_started", stage: "saved" },
    ]);

    renderWithPerson(<DashboardScreen />);
    await vi.advanceTimersByTimeAsync(0);
    const callsAfterFirstTick = vi.mocked(api.listApplications).mock.calls.length;

    await vi.advanceTimersByTimeAsync(10_000);

    expect(vi.mocked(api.listApplications).mock.calls.length).toBe(callsAfterFirstTick);
    vi.useRealTimers();
  });

  it("filters to archived applications when the tab is selected", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([{ ...BASE_APP, id: 1 }]);
    renderWithPerson(<DashboardScreen />);

    fireEvent.click(await screen.findByRole("button", { name: /archived/i }));

    await waitFor(() =>
      expect(api.listApplications).toHaveBeenCalledWith(1, { archived: true })
    );
  });

  it("changes stage from the row without opening the application", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 7, stage: "applied" },
    ]);
    vi.mocked(api.patchApplication).mockResolvedValue({ ...BASE_APP, id: 7, stage: "interview" } as never);
    await renderOnAllTab();

    const select = await screen.findByLabelText(/stage for row 1/i);
    fireEvent.change(select, { target: { value: "interview" } });

    expect(api.patchApplication).toHaveBeenCalledWith(7, { stage: "interview" });
  });

  it("disables the Saved stage option for a ready row", async () => {
    // Regression for I2(a): the backend 422s on stage="saved" once status is
    // "ready"; the dashboard's row dropdown must not offer that choice.
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 7, status: "ready", stage: "applied" },
    ]);
    await renderOnAllTab();

    const select = await screen.findByLabelText(/stage for row 1/i);
    const savedOption = within(select).getByRole("option", { name: "Saved" }) as HTMLOptionElement;
    expect(savedOption.disabled).toBe(true);
  });

  it("asks for confirmation naming the role before deleting", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 3, company: "Initech", title: "Staff Engineer" },
    ]);
    await renderOnAllTab();

    fireEvent.click(await screen.findByLabelText(/select row 1/i));
    fireEvent.click(screen.getByRole("button", { name: /delete permanently/i }));

    expect(screen.getByRole("dialog")).toHaveTextContent("Initech");
    expect(screen.getByRole("dialog")).toHaveTextContent("Staff Engineer");
    expect(api.deleteApplication).not.toHaveBeenCalled();
  });

  it("renders Last activity on its LOCAL calendar day, matching the Application screen's convention", async () => {
    // last_activity_at IS an event's occurred_at (backend derives it as
    // MAX(occurred_at)) -- same value kind as ApplicationScreen's timeline,
    // so it must follow the same local-on-both-sides convention. Built at
    // 23:00 local so local and UTC days genuinely differ under the stubbed
    // TZ, regardless of the runner's own zone.
    vi.stubEnv("TZ", "America/New_York");
    try {
      const instant = new Date(2026, 6, 20, 23, 0, 0); // 2026-07-20 23:00 local
      const expectedLocalDay = instant.toLocaleDateString();
      vi.mocked(api.listApplications).mockResolvedValue([
        { ...BASE_APP, id: 5, last_activity_at: instant.toISOString() },
      ]);

      await renderOnAllTab();

      expect(await screen.findByText(expectedLocalDay)).toBeInTheDocument();
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("refreshes the table even when an action fails", async () => {
    // Regression: reload() used to sit inside the try, so a rejection left the
    // table showing rows the server had already changed until the next poll.
    //
    // Asserted via an observable outcome, not a call count: swapping what the
    // API returns AFTER the screen has settled means the new company name can
    // only appear if a refetch happened following the failed action. A call
    // count would only say a request went out, not that its rows replaced
    // the stale ones.
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 5, company: "Before Co" },
    ]);
    vi.mocked(api.patchApplication).mockRejectedValueOnce(new Error("API 422: nope"));
    await renderOnAllTab();
    await screen.findByText("Before Co");

    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 5, company: "Refetched Co" },
    ]);
    fireEvent.change(await screen.findByLabelText(/stage for row 1/i), {
      target: { value: "offer" },
    });

    await waitFor(() => expect(screen.getByText(/API 422: nope/)).toBeInTheDocument());
    expect(await screen.findByText("Refetched Co")).toBeInTheDocument();
  });

  it("reports how many items failed in a bulk action, not just the first", async () => {
    // Promise.all surfaces only the FIRST rejection, so a 2-of-3 failure would
    // report one error and silently drop the other. allSettled counts them.
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 1, company: "One" },
      { ...BASE_APP, id: 2, company: "Two" },
      { ...BASE_APP, id: 3, company: "Three" },
    ]);
    vi.mocked(api.archiveApplication)
      .mockRejectedValueOnce(new Error("API 409: busy"))
      .mockResolvedValueOnce(undefined as never)
      .mockRejectedValueOnce(new Error("API 500: boom"));
    await renderOnAllTab();
    await screen.findByText("One");

    for (const n of [1, 2, 3]) {
      fireEvent.click(screen.getByLabelText(new RegExp(`select row ${n}`, "i")));
    }
    fireEvent.click(screen.getByRole("button", { name: /^archive$/i }));

    // All three attempted despite two failures, and the count is reported.
    await waitFor(() =>
      expect(screen.getByText(/2 of 3 could not be archived/i)).toBeInTheDocument()
    );
    expect(vi.mocked(api.archiveApplication)).toHaveBeenCalledTimes(3);
  });
});

describe("DashboardScreen and the current person", () => {
  it("lists the current person's applications, not the first person's", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([SAM_ROW]);
    renderWithPerson(<DashboardScreen />, { people: [JORDAN, SAM], personId: 2 });

    expect(await screen.findByText("SamCo")).toBeInTheDocument();
    const ids = vi.mocked(api.listApplications).mock.calls.map(([id]) => id);
    expect(ids.length).toBeGreaterThan(0);
    expect(ids.every((id) => id === 2)).toBe(true);
  });

  it("makes no request while there is no person, then lists the person once there is one", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([JORDAN_ROW]);
    const { switchTo } = renderWithPerson(<DashboardScreen />, {
      people: [JORDAN],
      personId: null,
    });

    // Regression for the unfiltered first poll: with no person the screen
    // must not fetch every person's applications.
    expect(api.listApplications).not.toHaveBeenCalled();

    act(() => switchTo(1));

    expect(await screen.findByText("JordanCo")).toBeInTheDocument();
    expect(api.listApplications).toHaveBeenCalledWith(1, undefined);
    expect(api.listApplications).not.toHaveBeenCalledWith(undefined, undefined);
  });

  it("makes no request with no people and still points at the first steps", async () => {
    renderWithPerson(<DashboardScreen />, { people: [], personId: null });

    expect(await screen.findByRole("link", { name: /Getting Started/ })).toHaveAttribute(
      "href",
      "/getting-started"
    );
    expect(api.listApplications).not.toHaveBeenCalled();
  });

  it("makes no request and shows no first steps while the people list is loading", () => {
    // Jordan is in the list, but the provider has not settled: no person yet.
    renderWithPerson(<DashboardScreen />, { people: [JORDAN], loading: true });

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /create your Master Profile/ })
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Getting Started/ })).not.toBeInTheDocument();
    expect(api.listApplications).not.toHaveBeenCalled();
  });

  it("shows why there is nothing to list when the people list failed to load", () => {
    renderWithPerson(<DashboardScreen />, {
      people: [],
      personId: null,
      overrides: { error: "API 500: boom" },
    });

    expect(screen.getByText("API 500: boom")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /create your Master Profile/ })
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/No applications yet/)).not.toBeInTheDocument();
    expect(api.listApplications).not.toHaveBeenCalled();
  });

  it("clears the previous person's rows the moment the person changes", async () => {
    vi.mocked(api.listApplications).mockImplementation((profileId) =>
      profileId === 1
        ? Promise.resolve([JORDAN_ROW])
        : new Promise<ApplicationSummary[]>(() => {}) // Sam's list never arrives
    );
    const { switchTo } = renderWithPerson(<DashboardScreen />, { people: [JORDAN, SAM] });
    expect(await screen.findByText("JordanCo")).toBeInTheDocument();

    act(() => switchTo(2));

    // Not after a fetch: straight away, while Sam's list is still pending.
    expect(screen.queryByText("JordanCo")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/stage for row 1/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/select row 1/i)).not.toBeInTheDocument();
    expect(api.listApplications).toHaveBeenLastCalledWith(2, undefined);
  });

  it("ignores a response for the previous person that arrives after a switch", async () => {
    let resolveJordan!: (rows: ApplicationSummary[]) => void;
    vi.mocked(api.listApplications).mockImplementation((profileId) =>
      profileId === 1
        ? new Promise<ApplicationSummary[]>((resolve) => {
            resolveJordan = resolve;
          })
        : Promise.resolve([SAM_ROW])
    );
    const { switchTo } = renderWithPerson(<DashboardScreen />, { people: [JORDAN, SAM] });
    expect(api.listApplications).toHaveBeenCalledWith(1, undefined);

    act(() => switchTo(2));
    expect(await screen.findByText("SamCo")).toBeInTheDocument();

    await act(async () => {
      resolveJordan([JORDAN_ROW]);
    });

    expect(screen.queryByText("JordanCo")).not.toBeInTheDocument();
    expect(screen.getByText("SamCo")).toBeInTheDocument();
  });

  it("closes an open delete confirmation when the person changes", async () => {
    vi.mocked(api.listApplications).mockImplementation((profileId) =>
      Promise.resolve(profileId === 1 ? [JORDAN_ROW] : [])
    );
    const { switchTo } = renderWithPerson(<DashboardScreen />, { people: [JORDAN, SAM] });
    fireEvent.click(await screen.findByLabelText(/select row 1/i));
    fireEvent.click(screen.getByRole("button", { name: /delete permanently/i }));
    expect(screen.getByRole("dialog")).toHaveTextContent("JordanCo");

    act(() => switchTo(2));

    // The dialog listed Jordan's row and its button would still delete it.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.deleteApplication).not.toHaveBeenCalled();
  });

  it("drops an action's error when the action settles after a switch", async () => {
    vi.mocked(api.listApplications).mockImplementation((profileId) =>
      Promise.resolve(profileId === 1 ? [JORDAN_ROW] : [SAM_ROW])
    );
    let rejectPatch!: (reason: Error) => void;
    vi.mocked(api.patchApplication).mockReturnValueOnce(
      new Promise<ApplicationDetail>((_resolve, reject) => {
        rejectPatch = reject;
      })
    );
    const { switchTo } = renderWithPerson(<DashboardScreen />, { people: [JORDAN, SAM] });
    fireEvent.change(await screen.findByLabelText(/stage for row 1/i), {
      target: { value: "applied" },
    });
    expect(api.patchApplication).toHaveBeenCalledWith(10, { stage: "applied" });

    act(() => switchTo(2));
    expect(await screen.findByText("SamCo")).toBeInTheDocument();

    await act(async () => {
      rejectPatch(new Error("API 409: busy"));
    });

    // Jordan's failure is not reported on Sam's dashboard.
    expect(screen.queryByText(/API 409: busy/)).not.toBeInTheDocument();
    expect(screen.getByText("SamCo")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the Dashboard tests and confirm they fail**

Run: `cd frontend && npx vitest run src/screens/DashboardScreen.test.tsx`

Expected: FAIL. Every test errors with `[vitest] No "listProfiles" export is defined on the "../api" mock. Did you forget to return it from "vi.mock"?`, because the screen still fetches its own profile list in an effect. (`tsc` is not involved here; vitest strips types.)

- [ ] **Step 3: Move the Dashboard onto the current person**

All edits are in `frontend/src/screens/DashboardScreen.tsx`.

3a. Imports. Replace this code:

```tsx
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  archiveApplication,
  deleteApplication,
  generateApplication,
  listApplications,
  listProfiles,
  patchApplication,
  restoreApplication,
} from "../api";
import { STATUS_LABELS, TERMINAL_STATUSES } from "../statuses";
import type { ApplicationSummary, ProfileSummary, Stage } from "../types";
```

with:

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  archiveApplication,
  deleteApplication,
  generateApplication,
  listApplications,
  patchApplication,
  restoreApplication,
} from "../api";
import { usePerson } from "../person";
import { STATUS_LABELS, TERMINAL_STATUSES } from "../statuses";
import type { ApplicationSummary, Stage } from "../types";
```

3b. `usePolling`. Replace this code:

```tsx
/**
 * Polls listApplications every 2000ms while any application status is outside
 * TERMINAL. Cleans up on unmount, on profile change, and on tab change.
 */
export function usePolling(
  profileId: number | undefined,
  archived: boolean,
  reloadKey: number
): ApplicationSummary[] {
  const [apps, setApps] = useState<ApplicationSummary[]>([]);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;

    async function tick() {
      let active = false;
      try {
        const list = await listApplications(profileId, archived ? { archived: true } : undefined);
        if (stopped) return;
        setApps(list);
        active = list.some((a) => !TERMINAL_STATUSES.includes(a.status));
      } catch {
        active = false; // stop polling on fetch error; navigating back restarts it
      }
      if (!stopped && active) {
        timer = window.setTimeout(tick, 2000);
      }
    }

    tick();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [profileId, archived, reloadKey]);

  return apps;
}
```

with:

```tsx
const NO_APPS: ApplicationSummary[] = [];

/**
 * Polls listApplications(profileId) every 2000ms while any application status
 * is outside TERMINAL. Makes no request at all while profileId is undefined
 * (no person yet, or none exist). Cleans up on unmount, on person change, and
 * on tab change; a response that lands after any of those is dropped.
 *
 * Rows are kept together with the person they were fetched for, and only the
 * current person's rows are returned. On the very render where the person
 * changes the list is already empty, before any effect has run, so the
 * previous person's rows are never painted with live controls under the new
 * person.
 */
export function usePolling(
  profileId: number | undefined,
  archived: boolean,
  reloadKey: number
): ApplicationSummary[] {
  const [fetched, setFetched] = useState<{ profileId: number; list: ApplicationSummary[] } | null>(
    null
  );

  useEffect(() => {
    if (profileId === undefined) return;
    const id = profileId;
    let stopped = false;
    let timer: number | undefined;

    async function tick() {
      let active = false;
      try {
        const list = await listApplications(id, archived ? { archived: true } : undefined);
        if (stopped) return;
        setFetched({ profileId: id, list });
        active = list.some((a) => !TERMINAL_STATUSES.includes(a.status));
      } catch {
        active = false; // stop polling on fetch error; navigating back restarts it
      }
      if (!stopped && active) {
        timer = window.setTimeout(tick, 2000);
      }
    }

    tick();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [profileId, archived, reloadKey]);

  return fetched !== null && fetched.profileId === profileId ? fetched.list : NO_APPS;
}
```

3c. The top of the component through `runBulk`. Replace this code:

```tsx
export default function DashboardScreen() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [profileId, setProfileId] = useState<number | undefined>(undefined);
  const [tab, setTab] = useState<Tab>("to_apply");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirming, setConfirming] = useState<ApplicationSummary[] | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const apps = usePolling(profileId, tab === "archived", reloadKey);
  const rows = visible(apps, tab);
  const counts = tabCounts(apps, tab);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    listProfiles()
      .then((list) => {
        setProfiles(list);
        if (list.length > 0) setProfileId((cur) => cur ?? list[0].id);
      })
      .catch(() => setProfiles([]));
  }, []);

  useEffect(() => setSelected(new Set()), [tab, profileId]);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(String(e));
    } finally {
      // Always reload, including on failure. Showing rows the server has
      // already changed is worse than showing an error beside fresh data.
      reload();
    }
  }

  /**
   * Bulk actions: one request per id. There is no bulk endpoint by design, so
   * `Promise.allSettled` rather than `Promise.all` -- the latter surfaces only
   * the FIRST rejection, which for a 5-row delete where 2 fail reports one
   * error and silently drops the other. Reports the count instead.
   */
  async function runBulk(
    ids: number[],
    op: (id: number) => Promise<unknown>,
    pastTense: string
  ) {
    setError(null);
    const results = await Promise.allSettled(ids.map(op));
    const failures = results.filter((r) => r.status === "rejected");
    if (failures.length > 0) {
      const first = failures[0] as PromiseRejectedResult;
      setError(
        `${failures.length} of ${ids.length} could not be ${pastTense}. First error: ${String(first.reason)}`
      );
    }
    reload();
  }
```

with:

```tsx
export default function DashboardScreen() {
  const { person, loading: peopleLoading, error: peopleError } = usePerson();
  const personId = person?.id;
  const [tab, setTab] = useState<Tab>("to_apply");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirming, setConfirming] = useState<ApplicationSummary[] | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const apps = usePolling(personId, tab === "archived", reloadKey);
  const rows = visible(apps, tab);
  const counts = tabCounts(apps, tab);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  // The person shown now. An action compares it with the person it started
  // for: one that settles after a switch reports on someone else's rows.
  const personRef = useRef(personId);
  useEffect(() => {
    personRef.current = personId;
  }, [personId]);

  useEffect(() => setSelected(new Set()), [tab, personId]);

  // An open delete confirmation lists the previous person's rows and its
  // button would still delete them; an error describes the previous person's
  // action. Neither survives a switch.
  useEffect(() => {
    setConfirming(null);
    setError(null);
  }, [personId]);

  async function run(action: () => Promise<unknown>) {
    const startedFor = personRef.current;
    setError(null);
    try {
      await action();
    } catch (e) {
      if (personRef.current === startedFor) setError(String(e));
    } finally {
      // Always reload, including on failure. Showing rows the server has
      // already changed is worse than showing an error beside fresh data.
      reload();
    }
  }

  /**
   * Bulk actions: one request per id. There is no bulk endpoint by design, so
   * `Promise.allSettled` rather than `Promise.all` -- the latter surfaces only
   * the FIRST rejection, which for a 5-row delete where 2 fail reports one
   * error and silently drops the other. Reports the count instead.
   */
  async function runBulk(
    ids: number[],
    op: (id: number) => Promise<unknown>,
    pastTense: string
  ) {
    const startedFor = personRef.current;
    setError(null);
    const results = await Promise.allSettled(ids.map(op));
    const failures = results.filter((r) => r.status === "rejected");
    if (failures.length > 0 && personRef.current === startedFor) {
      const first = failures[0] as PromiseRejectedResult;
      setError(
        `${failures.length} of ${ids.length} could not be ${pastTense}. First error: ${String(first.reason)}`
      );
    }
    reload();
  }
```

3d. Remove the Dashboard's own dropdown. Replace this code:

```tsx
      {error && <div className="alert alert-error">{error}</div>}

      {profiles.length > 1 && (
        <div className="field" style={{ maxWidth: "20rem" }}>
          <label className="field-label">Profile</label>
          <select
            className="select"
            value={profileId ?? ""}
            onChange={(e) => setProfileId(Number(e.target.value))}
          >
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
      )}

      <div className="tabs">
```

with:

```tsx
      {error && <div className="alert alert-error">{error}</div>}

      <div className="tabs">
```

3e. The table's empty row says nothing about the person until the people list has loaded. Replace this code:

```tsx
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  {apps.length === 0 && tab !== "archived" ? (
                    <>
                      No applications yet. New here? Start with{" "}
                      <Link to="/getting-started">Getting Started</Link>, or{" "}
                      <Link to="/profiles">create your Master Profile</Link> and then{" "}
                      <Link to="/add">add job URLs</Link>.
                    </>
                  ) : (
                    EMPTY_MESSAGE[tab]
                  )}
                </td>
              </tr>
            )}
```

with:

```tsx
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  {/* Until the people list has loaded, neither the first steps
                      nor a tab's "Nothing ..." line is true yet. */}
                  {peopleLoading ? (
                    "Loading..."
                  ) : peopleError ? (
                    peopleError
                  ) : apps.length === 0 && tab !== "archived" ? (
                    <>
                      No applications yet. New here? Start with{" "}
                      <Link to="/getting-started">Getting Started</Link>, or{" "}
                      <Link to="/profiles">create your Master Profile</Link> and then{" "}
                      <Link to="/add">add job URLs</Link>.
                    </>
                  ) : (
                    EMPTY_MESSAGE[tab]
                  )}
                </td>
              </tr>
            )}
```

Nothing else in the file changes: the table, the tabs and the confirmation modal already read `apps`, `rows`, `selected` and `confirming`.

- [ ] **Step 4: Run the Dashboard tests, then the whole frontend suite**

Run: `cd frontend && npx vitest run src/screens/DashboardScreen.test.tsx`

Expected: PASS, all 21 tests (12 existing, 9 in "DashboardScreen and the current person").

Run: `cd frontend && npm test`

Expected: PASS. In particular `src/App.test.tsx` (Task 12's version, real `PersonProvider`, `listProfiles` resolving `[]`) still finds the "Dashboard" heading on `/`; the Dashboard now simply makes no `listApplications` call there.

- [ ] **Step 5: Rebuild the bundle and check it**

Run: `cd frontend && npm run build`

Expected: `tsc` reports no errors (it type-checks the test file too), Vite writes `frontend/dist`, and the last line is `stamp-build: recorded <N> build inputs`.

Run (from the repo root): `.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

Run (from the repo root):

```bash
git add frontend/src/screens/DashboardScreen.tsx frontend/src/screens/DashboardScreen.test.tsx frontend/dist
git commit -m "$(cat <<'EOF'
feat: dashboard lists the current person's applications

The Dashboard reads the person from PersonContext instead of fetching
its own profile list and showing its own dropdown. It makes no request
while there is no person, so the unfiltered first poll is gone. Rows
are stored with the person they were fetched for, so a switch empties
the table on the same render and a late response for the previous
person is dropped. A switch also closes an open delete confirmation,
and an action that settles after a switch does not report its error
on the new person's dashboard. Until the people list has loaded, the
empty table says Loading... (or shows the load error) instead of the
first-steps hint.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
git status --short
```

Expected: `git status --short` prints nothing (a dirty `frontend/dist` means the rebuild was not added).


---

### Task 14: Add Jobs queues for the current person with that person's settings

**Files:**
- Modify: `frontend/src/screens/AddJobsScreen.tsx` (imports; state and effects at the top of `AddJobsScreen`; `handleSubmit`; the "Profile" field at the top of the first card; the submit button)
- Modify: `frontend/src/screens/AddJobsScreen.test.tsx` (rewritten onto `renderWithPerson`; new describe block)
- Rebuild: `frontend/dist` (committed)
- Test: `frontend/src/screens/AddJobsScreen.test.tsx`

**Interfaces:**
- Consumes: `usePerson()` from `frontend/src/person.tsx` (Task 11), reading `person`, `people`, `loading`, `error` and `labelFor(p)`. `getSettings(profileId?: number): Promise<SettingsShape>` from `frontend/src/api.ts` (Task 10; adds `?profile_id=N`). `makePerson`, `renderWithPerson` and the `PersonTestOptions` type from `frontend/src/test-utils.tsx` (Task 11). The `/profiles?new=1` create-form route from Task 12. Existing `createApplications(profileId, jobs, defaultDepth?, defaultTemplate?, generate = true)` and `listTemplates()` (unchanged).
- Produces: no new exports. User-visible strings: `Adding jobs for {label}` and `Add a person first`. Nothing later in the plan relies on this task's internals.
- Choices made here (the contract leaves them open):
  - "Adding jobs for {label}" is the first line of the first card (`div.card-title`), built with `labelFor(person)`, shown whenever `person` is not null. The screen's own Profile select is removed.
  - "No people" is `!loading && !error && people.length === 0`, as in spec §4.1. Then the card starts with a link `Add a person first` to `/profiles?new=1`, and the submit button, which appears once URLs are typed, is disabled and labelled `Add a person first`. While the provider is loading the screen shows neither the label line nor the link.
  - When the provider has an `error` (the people list failed to load), the card shows it in an `alert alert-error` and submit stays disabled. This replaces today's display of the `listProfiles()` failure.
  - Settings are fetched with `getSettings(person.id)` in an effect keyed on `person.id`. A response is applied only if the effect for that id is still current, so a late response for the previous person is dropped. Submit is enabled only when the loaded settings belong to `person.id` (`settingsFor === person.id`); on a switch it disables at once and re-enables when the new person's settings land. No request is made while `person` is null.
  - A `getSettings` failure is now shown in the screen's error line and keeps submit disabled. Today it is swallowed and submit goes ahead with hard-coded defaults, which the spec's "disabled until that person's settings have loaded" rules out.
  - The typed URLs and per-row overrides are kept across a switch; the defaults and the error line are replaced. The submit captures `person.id` at click and navigates to `/` on success (unchanged).
- Order and overlap: no earlier task edits `AddJobsScreen.tsx` or its test. Task 10 has already changed `getSettings` to take an optional id. The working tree uses CRLF line endings (`core.autocrlf=true`); make the edits with an editor or the Edit tool rather than a script that rewrites line endings.

- [ ] **Step 1: Rewrite the Add Jobs tests onto `renderWithPerson` and add the per-person tests**

Replace the entire contents of `frontend/src/screens/AddJobsScreen.test.tsx` with the file below. What changes in the existing tests, and why:

- The `../api` mock loses `listProfiles`, and `beforeEach` loses `vi.mocked(api.listProfiles).mockResolvedValue([...])` (and the `contact` const). The screen must not call it, and vitest throws if it does.
- `beforeEach` gains `vi.clearAllMocks()` (the new tests assert "not called" and exact call lists) and a default `vi.mocked(api.getSettings).mockResolvedValue(SETTINGS)`, so the eight identical per-test `getSettings` fixtures collapse to `SETTINGS` or a one-field spread of it.
- `render(<MemoryRouter><AddJobsScreen /></MemoryRouter>)` becomes `renderWithPerson(<AddJobsScreen />, opts)` inside `renderScreen(opts?)`. The default person is `makePerson()`, `id: 1`.
- Old: `await screen.findByRole("option", { name: "Jordan Rivera" });` (five tests). That option came from the removed Profile select. New: `await enterUrls(...)`, which types the URLs and waits until the submit button is enabled, i.e. until the person's settings have loaded.
- "sends generate:false when saving without generating". Old: `expect.any(Number)` as the first argument. New: `1`, the current person's id.
- "generates immediately by default". Old: `expect(call?.[4]).toBe(true);` on the last call. New: `expect(api.createApplications).toHaveBeenCalledWith(1, [{ url: "https://example.com/a", depth: "standard", template: "slate" }], "standard", "slate", true)`.
- The first option assertion in each template test changes from `within(select).getByRole(...)` to `await within(select).findByRole(...)`, so it waits for `listTemplates()` itself instead of relying on an earlier `await` having flushed it.

```tsx
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import AddJobsScreen from "./AddJobsScreen";
import * as api from "../api";
import { makePerson, renderWithPerson, type PersonTestOptions } from "../test-utils";
import type { SettingsShape, TemplateInfo } from "../types";

// listProfiles is deliberately absent. The screen reads the person from
// PersonContext; vitest throws on any access to an export this factory does
// not define, so a screen that fetched its own profile list would fail here.
vi.mock("../api", () => ({
  getSettings: vi.fn(),
  createApplications: vi.fn(),
  listTemplates: vi.fn(),
}));

const SETTINGS: SettingsShape = {
  api_key_set: true,
  fake_mode: false,
  default_template: "slate",
  default_depth: "standard",
  page_size: "Letter",
};

// A second person's own defaults, different in both fields from SETTINGS.
const SAM_SETTINGS: SettingsShape = { ...SETTINGS, default_template: "meridian", default_depth: "deep" };

const MERIDIAN: TemplateInfo = { name: "meridian", label: "Meridian", description: "d", best_for: "b" };
const SLATE: TemplateInfo = { name: "slate", label: "Slate", description: "d", best_for: "b" };
const LEDGER: TemplateInfo = { name: "ledger", label: "Ledger", description: "d", best_for: "b" };
const PLAINWORK: TemplateInfo = { name: "plainwork", label: "Plainwork", description: "d", best_for: "b" };

const JORDAN = makePerson();
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
  created_at: "2026-02-01T00:00:00+00:00",
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function renderScreen(opts?: PersonTestOptions) {
  return renderWithPerson(<AddJobsScreen />, opts);
}

/**
 * Types the URLs and returns the submit button once it is enabled. It stays
 * disabled until the current person's settings have loaded, so this is also
 * the wait for those settings.
 */
async function enterUrls(value: string): Promise<HTMLElement> {
  fireEvent.change(screen.getByPlaceholderText("https://..."), { target: { value } });
  const submit = screen.getByRole("button", { name: /add and generate/i });
  await waitFor(() => expect(submit).toBeEnabled());
  return submit;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.createApplications).mockResolvedValue([]);
  vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN, SLATE]);
});

describe("AddJobsScreen", () => {
  it("parses three URL lines into three preview rows", async () => {
    renderScreen();
    await enterUrls("https://a.example/j1\nhttps://b.example/j2\n\nhttps://c.example/j3\n");
    expect(screen.getAllByTestId("job-row")).toHaveLength(3);
    expect(screen.getByText("3 jobs to queue")).toBeInTheDocument();
  });

  it("shows a warning when no API key is set and demo mode is off", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, api_key_set: false });
    renderScreen();
    expect(await screen.findByText(/No API key set/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/Generated with your Anthropic API key/i)
    ).not.toBeInTheDocument();
  });

  it("shows the plain mode note (no warning) when an API key is set", async () => {
    renderScreen();
    expect(
      await screen.findByText(/Generated with your Anthropic API key/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/No API key set/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /See MCP mode/ })).toHaveAttribute(
      "href",
      "/getting-started"
    );
  });

  it("sends generate:false when saving without generating", async () => {
    renderScreen();
    await enterUrls("https://example.com/a\nhttps://example.com/b");
    fireEvent.click(screen.getByLabelText(/save without generating/i));
    fireEvent.click(screen.getByRole("button", { name: /save for later/i }));

    await waitFor(() =>
      expect(api.createApplications).toHaveBeenCalledWith(
        1,
        expect.any(Array),
        expect.any(String),
        expect.any(String),
        false
      )
    );
  });

  it("generates immediately by default", async () => {
    renderScreen();
    fireEvent.click(await enterUrls("https://example.com/a"));

    await waitFor(() =>
      expect(api.createApplications).toHaveBeenCalledWith(
        1,
        [{ url: "https://example.com/a", depth: "standard", template: "slate" }],
        "standard",
        "slate",
        true
      )
    );
  });

  it("renders template options from the API, not a hardcoded list", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, default_template: "meridian" });
    vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN, LEDGER, PLAINWORK]);
    renderScreen();
    const select = await screen.findByLabelText(/default template/i);
    expect(await within(select).findByRole("option", { name: "Ledger" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "Plainwork" })).toBeInTheDocument();
  });

  it("shows template labels rather than raw ids in the default select", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, default_template: "meridian" });
    vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN]);
    renderScreen();
    const select = await screen.findByLabelText(/default template/i);
    expect(await within(select).findByRole("option", { name: "Meridian" })).toBeInTheDocument();
    expect(within(select).queryByRole("option", { name: "meridian" })).toBeNull();
  });

  it("renders per-row template options from the API", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, default_template: "meridian" });
    vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN, LEDGER]);
    renderScreen();
    await enterUrls("https://a.example/j1");
    const row = screen.getByLabelText("Template for row 1");
    expect(await within(row).findByRole("option", { name: "Ledger" })).toBeInTheDocument();
    expect(within(row).getByRole("option", { name: "Meridian" })).toBeInTheDocument();
    expect(within(row).queryByRole("option", { name: "meridian" })).toBeNull();
  });

  // The label is display, the name is the contract: api/applications.py rejects any
  // template not in the registry, so an option that carries the label as its value
  // renders correctly and fails every submit.
  it("queues the template id, not the label, from the default template select", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, default_template: "meridian" });
    vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN, LEDGER]);
    renderScreen();
    const submit = await enterUrls("https://a.example/j1");
    const select = screen.getByLabelText(/default template/i) as HTMLSelectElement;
    const ledger = (await within(select).findByRole("option", { name: "Ledger" })) as HTMLOptionElement;
    expect(ledger.value).toBe("ledger");
    // the saved default must resolve to a real option, or the select shows the wrong entry
    expect(select.value).toBe("meridian");

    fireEvent.change(select, { target: { value: "ledger" } });
    fireEvent.click(submit);

    await waitFor(() => {
      const calls = vi.mocked(api.createApplications).mock.calls;
      const call = calls[calls.length - 1];
      expect(call?.[1]).toEqual([
        { url: "https://a.example/j1", depth: "standard", template: "ledger" },
      ]);
      expect(call?.[3]).toBe("ledger");
    });
  });

  it("queues the template id, not the label, from a per-row override", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, default_template: "meridian" });
    vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN, LEDGER]);
    renderScreen();
    const submit = await enterUrls("https://a.example/j1");
    const row = screen.getByLabelText("Template for row 1") as HTMLSelectElement;
    const ledger = (await within(row).findByRole("option", { name: "Ledger" })) as HTMLOptionElement;
    expect(ledger.value).toBe("ledger");
    expect(row.value).toBe("meridian");

    fireEvent.change(row, { target: { value: "ledger" } });
    fireEvent.click(submit);

    await waitFor(() => {
      const calls = vi.mocked(api.createApplications).mock.calls;
      const call = calls[calls.length - 1];
      expect(call?.[1]).toEqual([
        { url: "https://a.example/j1", depth: "standard", template: "ledger" },
      ]);
    });
  });
});

describe("AddJobsScreen and the current person", () => {
  it("says whose jobs these are with the person's label, and has no person select of its own", async () => {
    renderScreen({ overrides: { labelFor: (p) => `${p.name} (${p.contact.email})` } });

    expect(
      await screen.findByText("Adding jobs for Jordan Rivera (jordan@example.com)")
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Jordan Rivera/ })).not.toBeInTheDocument();
  });

  it("queues for the current person with that person's defaults, then opens the dashboard", async () => {
    vi.mocked(api.getSettings).mockImplementation((profileId) =>
      Promise.resolve(profileId === 2 ? SAM_SETTINGS : SETTINGS)
    );
    renderWithPerson(
      <Routes>
        <Route path="/add" element={<AddJobsScreen />} />
        <Route path="/" element={<p>Dashboard stub</p>} />
      </Routes>,
      { people: [JORDAN, SAM], personId: 2, route: "/add" }
    );

    const submit = await enterUrls("https://a.example/j1");
    expect(screen.getByText("Adding jobs for Sam Lee")).toBeInTheDocument();
    expect(screen.getByLabelText(/default template/i)).toHaveValue("meridian");
    expect(screen.getByLabelText("Depth for row 1")).toHaveValue("deep");

    fireEvent.click(submit);

    await waitFor(() =>
      expect(api.createApplications).toHaveBeenCalledWith(
        2,
        [{ url: "https://a.example/j1", depth: "deep", template: "meridian" }],
        "deep",
        "meridian",
        true
      )
    );
    expect(await screen.findByText("Dashboard stub")).toBeInTheDocument();
    // One settings request, for Sam: none for the first person, none app-wide.
    expect(vi.mocked(api.getSettings).mock.calls).toEqual([[2]]);
  });

  it("keeps submit disabled until the person's settings have loaded", async () => {
    const settings = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockReturnValue(settings.promise);
    renderScreen();
    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1" },
    });
    const submit = screen.getByRole("button", { name: /add and generate/i });

    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(api.createApplications).not.toHaveBeenCalled();

    await act(async () => {
      settings.resolve(SETTINGS);
    });

    await waitFor(() => expect(submit).toBeEnabled());
  });

  it("shows a settings failure and keeps submit disabled", async () => {
    vi.mocked(api.getSettings).mockRejectedValue(new Error("API 404: profile not found"));
    renderScreen();

    expect(await screen.findByText(/API 404: profile not found/)).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1" },
    });
    expect(screen.getByRole("button", { name: /add and generate/i })).toBeDisabled();
  });

  it("disables submit on a switch until the new person's settings land", async () => {
    const samSettings = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((profileId) =>
      profileId === 2 ? samSettings.promise : Promise.resolve(SETTINGS)
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });
    const submit = await enterUrls("https://a.example/j1");
    expect(screen.getByLabelText(/default template/i)).toHaveValue("slate");

    act(() => switchTo(2));

    expect(screen.getByText("Adding jobs for Sam Lee")).toBeInTheDocument();
    expect(submit).toBeDisabled();

    await act(async () => {
      samSettings.resolve(SAM_SETTINGS);
    });

    await waitFor(() => expect(submit).toBeEnabled());
    expect(screen.getByLabelText(/default template/i)).toHaveValue("meridian");
    expect(screen.getByLabelText("Depth for row 1")).toHaveValue("deep");
  });

  it("ignores the previous person's settings when they arrive after a switch", async () => {
    const jordanSettings = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((profileId) =>
      profileId === 1 ? jordanSettings.promise : Promise.resolve(SAM_SETTINGS)
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });
    expect(api.getSettings).toHaveBeenCalledWith(1);

    act(() => switchTo(2));
    const submit = await enterUrls("https://a.example/j1");
    expect(screen.getByLabelText(/default template/i)).toHaveValue("meridian");

    await act(async () => {
      jordanSettings.resolve({ ...SETTINGS, default_template: "slate", default_depth: "quick" });
    });

    // Jordan's late defaults did not replace Sam's, and did not disable submit.
    expect(screen.getByLabelText(/default template/i)).toHaveValue("meridian");
    expect(screen.getByLabelText("Depth for row 1")).toHaveValue("deep");
    expect(submit).toBeEnabled();

    fireEvent.click(submit);
    await waitFor(() =>
      expect(api.createApplications).toHaveBeenCalledWith(
        2,
        [{ url: "https://a.example/j1", depth: "deep", template: "meridian" }],
        "deep",
        "meridian",
        true
      )
    );
  });

  it("with no people, points to the create form and cannot submit", () => {
    renderScreen({ people: [], personId: null });

    expect(screen.getByRole("link", { name: "Add a person first" })).toHaveAttribute(
      "href",
      "/profiles?new=1"
    );
    expect(screen.queryByText(/^Adding jobs for/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1" },
    });
    expect(screen.getByRole("button", { name: "Add a person first" })).toBeDisabled();
    expect(api.getSettings).not.toHaveBeenCalled();
  });

  it("shows nothing person-dependent while people are loading", () => {
    renderScreen({ people: [], personId: null, loading: true });

    expect(screen.queryByText(/Add a person first/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Adding jobs for/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1" },
    });
    expect(screen.getByRole("button", { name: /add and generate/i })).toBeDisabled();
    expect(api.getSettings).not.toHaveBeenCalled();
  });

  it("shows why it cannot submit when the people list failed to load", () => {
    renderScreen({ people: [], personId: null, overrides: { error: "API 500: boom" } });

    expect(screen.getByText("API 500: boom")).toBeInTheDocument();
    expect(screen.queryByText(/Add a person first/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1" },
    });
    expect(screen.getByRole("button", { name: /add and generate/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run the Add Jobs tests and confirm they fail**

Run: `cd frontend && npx vitest run src/screens/AddJobsScreen.test.tsx`

Expected: FAIL. Every test errors with `[vitest] No "listProfiles" export is defined on the "../api" mock. Did you forget to return it from "vi.mock"?`, because the screen still calls `listProfiles()` in its mount effect.

- [ ] **Step 3: Move Add Jobs onto the current person**

All edits are in `frontend/src/screens/AddJobsScreen.tsx`.

3a. Imports. Replace this code:

```tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createApplications, getSettings, listProfiles, listTemplates } from "../api";
import type {
  Depth,
  JobRequest,
  ProfileSummary,
  TemplateInfo,
  TemplateName,
} from "../types";
```

with:

```tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createApplications, getSettings, listTemplates } from "../api";
import { usePerson } from "../person";
import type { Depth, JobRequest, TemplateInfo, TemplateName } from "../types";
```

3b. State and effects. Replace this code:

```tsx
export default function AddJobsScreen() {
  const navigate = useNavigate();
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [profileId, setProfileId] = useState<number | undefined>(undefined);
  const [defaultDepth, setDefaultDepth] = useState<Depth>("standard");
  const [defaultTemplate, setDefaultTemplate] = useState<TemplateName>("slate");
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [apiKeySet, setApiKeySet] = useState(true);
  const [fakeMode, setFakeMode] = useState(false);
  const [text, setText] = useState("");
  const [generate, setGenerate] = useState(true);
  const [overrides, setOverrides] = useState<Record<number, RowOverride>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listProfiles()
      .then((list) => {
        setProfiles(list);
        if (list.length > 0) {
          setProfileId((cur) => cur ?? list[0].id);
        }
      })
      .catch((e) => setError(String(e)));
    getSettings()
      .then((s) => {
        setDefaultDepth(s.default_depth);
        setDefaultTemplate(s.default_template);
        setApiKeySet(s.api_key_set);
        setFakeMode(s.fake_mode);
      })
      .catch(() => undefined);
    listTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, []);
```

with:

```tsx
export default function AddJobsScreen() {
  const navigate = useNavigate();
  const { person, people, loading, error: peopleError, labelFor } = usePerson();
  const personId = person?.id;
  // Whose settings the defaults below came from. Submit waits until this is
  // the current person, so jobs are never queued with someone else's defaults.
  const [settingsFor, setSettingsFor] = useState<number | null>(null);
  const [defaultDepth, setDefaultDepth] = useState<Depth>("standard");
  const [defaultTemplate, setDefaultTemplate] = useState<TemplateName>("slate");
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [apiKeySet, setApiKeySet] = useState(true);
  const [fakeMode, setFakeMode] = useState(false);
  const [text, setText] = useState("");
  const [generate, setGenerate] = useState(true);
  const [overrides, setOverrides] = useState<Record<number, RowOverride>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    setSettingsFor(null);
    setError(null);
    if (personId === undefined) return; // no person: nothing to load, submit stays disabled
    let current = true;
    getSettings(personId)
      .then((s) => {
        if (!current) return; // arrived after a switch: these are someone else's defaults
        setDefaultDepth(s.default_depth);
        setDefaultTemplate(s.default_template);
        setApiKeySet(s.api_key_set);
        setFakeMode(s.fake_mode);
        setSettingsFor(personId);
      })
      .catch((e) => {
        if (current) setError(String(e));
      });
    return () => {
      current = false;
    };
  }, [personId]);

  const noPeople = !loading && !peopleError && people.length === 0;
  const settingsReady = person !== null && settingsFor === person.id;
```

3c. `handleSubmit`. Replace this code:

```tsx
  async function handleSubmit() {
    if (profileId === undefined || urls.length === 0) return;
    setSubmitting(true);
```

with:

```tsx
  async function handleSubmit() {
    if (person === null || !settingsReady || urls.length === 0) return;
    // Captured at click: the jobs belong to the person shown when Submit was
    // pressed, even if the picker changes while the request is in flight.
    const profileId = person.id;
    setSubmitting(true);
```

The rest of `handleSubmit` is unchanged: it already calls `createApplications(profileId, jobs, defaultDepth, defaultTemplate, generate)` and then `navigate("/")`, and `profileId` is now the local captured above.

3d. Replace the Profile field with the person line. Replace this code:

```tsx
      <div className="card">
        <div className="row">
          <div className="field">
            <label className="field-label">Profile</label>
            <select
              className="select"
              value={profileId ?? ""}
              onChange={(e) => setProfileId(Number(e.target.value))}
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label">Default depth</label>
```

with:

```tsx
      <div className="card">
        {person !== null && (
          <div className="card-title">{`Adding jobs for ${labelFor(person)}`}</div>
        )}
        {noPeople && (
          <div className="callout">
            <Link to="/profiles?new=1">Add a person first</Link>
          </div>
        )}
        {peopleError && <div className="alert alert-error">{peopleError}</div>}
        <div className="row">
          <div className="field">
            <label className="field-label">Default depth</label>
```

3e. The submit button. Replace this code:

```tsx
          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={submitting || profileId === undefined}
          >
            {submitting ? "Queueing..." : generate ? "Add and generate" : "Save for later"}
          </button>
```

with:

```tsx
          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={submitting || !settingsReady}
          >
            {noPeople
              ? "Add a person first"
              : submitting
                ? "Queueing..."
                : generate
                  ? "Add and generate"
                  : "Save for later"}
          </button>
```

Nothing else in the file changes. `profileId` no longer exists at component scope; the only remaining use is the local in `handleSubmit`.

- [ ] **Step 4: Run the Add Jobs tests, then the whole frontend suite**

Run: `cd frontend && npx vitest run src/screens/AddJobsScreen.test.tsx`

Expected: PASS, all 19 tests (10 existing, 9 in "AddJobsScreen and the current person").

Run: `cd frontend && npm test`

Expected: PASS. No other test renders `AddJobsScreen` (`App.test.tsx` renders `/` only).

- [ ] **Step 5: Rebuild the bundle and check it**

Run: `cd frontend && npm run build`

Expected: `tsc` reports no errors (it type-checks the test file too; `getSettings(personId)` relies on Task 10's optional parameter), Vite writes `frontend/dist`, and the last line is `stamp-build: recorded <N> build inputs`.

Run (from the repo root): `.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

Run (from the repo root):

```bash
git add frontend/src/screens/AddJobsScreen.tsx frontend/src/screens/AddJobsScreen.test.tsx frontend/dist
git commit -m "$(cat <<'EOF'
feat: add jobs queues for the current person with their settings

Add Jobs reads the person from PersonContext instead of its own profile
list and select, and says "Adding jobs for {label}". Defaults come from
getSettings(person.id); a response that arrives after a switch is
dropped, and submit stays disabled until the current person's settings
have loaded (a settings failure is shown instead of silently falling
back). With no people the screen links to the create form and the
submit reads "Add a person first". The submit still uses the id
captured at click and then opens the dashboard.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
git status --short
```

Expected: `git status --short` prints nothing (a dirty `frontend/dist` means the rebuild was not added).


---

### Task 15: Profiles screen edits the current person

**Files:**
- Modify: `frontend/src/screens/ProfileScreen.tsx` (the import block; the component head from `export default function ProfileScreen() {` through its load effect; the `// ---- actions ----` block; the JSX from `return (` through the end of the Documents card; the `disabled` prop of the Build and Save buttons)
- Modify: `frontend/src/screens/ProfileScreen.test.tsx` (rewritten whole onto `renderWithPerson`)
- Rebuild: `frontend/dist` (committed)
- Test: `frontend/src/screens/ProfileScreen.test.tsx`

**Interfaces:**
- Consumes:
  - Task 10: `deleteDocument(profileId: number, docId: number): Promise<{ deleted: number }>` in `frontend/src/api.ts`; `ProfileDetail` has `created_at: string; inbox_url: string | null; application_count: number`; `ProfileSummary` has `created_at: string; inbox_url: string | null`. Existing, unchanged: `getProfile`, `createProfile(name, contact?)`, `updateProfile(id, { name?, contact?, master_profile?, voice_notes? })`, `uploadDocument`, `buildProfile`.
  - Task 11: `usePerson()` from `frontend/src/person.tsx`, reading `people`, `person`, `loading`, `error`, `refreshPeople(selectId?)`, `setSwitchGuard(message | null)`, `labelFor(p)`; `PersonProvider`. From `frontend/src/test-utils.tsx`: `makePerson(p?)`, `renderWithPerson(ui, { people, personId, loading, route, overrides })` and the returned `switchTo(id)` and `unmount()`. The tests pass their own `vi.fn()` spies through `overrides` and rely on `switchTo` re-rendering with the same `overrides` and the person from `people` with that id.
  - Task 12: `App` renders the nav `PersonPicker`, which shows an `Inbox` link (`href = person.inbox_url`) when the current person has one; the picker's "Add a person…" option and "Add a person" link go to `/profiles?new=1`.
- Produces (Task 16 edits these exact names in `ProfileScreen.tsx`):
  - Module level: `deepEqual(a, b)`, `type Action = "build" | "save-profile" | "save-identity" | "upload" | "remove-document"`, `const BUSY_WORD: Record<Action, string>`, `type Part = "mp" | "voice" | "identity"`.
  - `export default function ProfileScreen()` (outer: heading, list error, create form or editor), `function CreatePersonForm({ onCancel })`, `function PersonEditor({ person }: { person: ProfileSummary })`.
  - Inside `PersonEditor`: `label` (`labelFor(person)`), `detail`, `busy`/`setBusy` (`Action | null`), `error`/`setError`, `alive` (ref, false once unmounted), `loadDetail(d)`, `applyResponse(d, prev, take)`, `run<T>(action, call, apply): Promise<boolean>`, `handleSaveIdentity()`, and the switch-guard effect that sets `` `${label}'s profile is ${BUSY_WORD[busy]}.` `` while `busy` is set.
  - In `ProfileScreen.test.tsx`: the file-level `vi.mock("../api", ...)` factory, a file-level `beforeEach`, and the constants `contact`, `baseProfileDetail: ProfileDetail`, `JORDAN`, `SAM`, `samDetail`, plus `LocationProbe`.
- Choices made here (the contract leaves them open):
  - `ProfileScreen` renders `<PersonEditor key={`${person.id}@${person.created_at}`} person={person} />`. A switch therefore mounts a fresh editor: no typed state carries over, and a response to an earlier person's request arrives at an unmounted editor, where `run` drops it (`alive.current` is false). Every handler still captures `person.id` when it starts. `created_at` is in the key because SQLite reissues a removed person's id.
  - Create form strings: card title `Add a person`, fields labelled `Name` and `Email`, button `Create person` (disabled while the name is blank), `Cancel` only when people exist. It shows when `!loading && !error` and (`people.length === 0` or `?new=1`), and replaces the editor while shown. After a create: `setSwitchGuard(null)`, then `await refreshPeople(newId)`, then `?new=1` is removed (replace). `?new=1` is also removed by Cancel and when the person changes while the form is open (a pick in the nav), but not on the first load.
  - The provider's `error` is shown on this screen as an `alert alert-error`.
  - Name and email: a `Name and email` card with fields labelled `Name` and `Email` and a `Save name and email` button, disabled while busy, while the name is blank (`A person needs a name.` is shown) or while both fields equal the saved values. It sends `updateProfile(id, { name: trimmedName, contact })` where `contact` is the saved contact with `email` replaced by the trimmed email and, only when the name changed, `name` replaced by the new name. An email-only edit therefore leaves a resume-derived `contact.name` alone.
  - Dirty state: `detail` is the baseline (last loaded or last write response). Dirty when `deepEqual(mp, {...emptyMP, ...detail.master_profile})` is false, or voice notes, name or email differ. When a write comes back, `applyResponse` makes the response the baseline; the fields the write covered take the server's value and every other field keeps an unsaved edit (and follows the server when it had none). So uploading or removing a document no longer discards unsaved master-profile edits, and a Build that fills an empty email shows it.
  - One request at a time: while `busy` is set every write control is disabled (Build, both Saves, upload, paste, document Remove and Yes).
  - Guard messages: `{label} has unsaved profile changes.` and `{label}'s profile is building.` / `saving.` / `uploading.` / `removing.` (the spec's words substituted literally). The guard effect sets the message and clears it in its cleanup, so it clears when the condition ends and on unmount.
  - Document Remove: a `Remove` button per document with `aria-label="Remove {filename}"`, which turns that row into `Remove {filename}?` with `Yes` / `No`. `Yes` calls `deleteDocument(person.id, doc.id)` then reloads the detail.
  - `refreshPeople()` (no argument) runs after every successful write: both saves, Build, upload, paste and document removal, including one whose editor has since unmounted.
- Order and overlap: Tasks 10 to 14 do not touch `ProfileScreen.tsx`, so the quoted code below is today's. The test file is replaced whole, so any fixture fields Task 10 added to it are superseded. The working tree uses CRLF line endings (`core.autocrlf=true`); make the edits with the Edit tool or an editor, not a script that rewrites line endings.

- [ ] **Step 1: Rewrite the Profiles tests onto `renderWithPerson` and add the person-scoped tests**

Replace the entire contents of `frontend/src/screens/ProfileScreen.test.tsx` with the file below. What changes in the five existing tests, and why:

- The `../api` mock loses the `listProfiles` default (the screen must not call it; the key stays as a bare `vi.fn()` so the one real-provider test can drive it) and gains `deleteDocument`. `baseProfileDetail` leaves `vi.hoisted` (the factory no longer reads it) and is typed `ProfileDetail`, with Task 10's `created_at`, `inbox_url` and `application_count`.
- A file-level `beforeEach` resets every mock and restores the `getProfile` default, because several new tests queue one-off responses or assert call counts.
- `render(<ProfileScreen />)` becomes `renderWithPerson(<ProfileScreen />, ...)`.
- "renders profiles, documents, and the master profile editor" is renamed "renders the current person's documents and master profile editor" and also asserts `getProfile` was called with `1`, the person's id.
- "saves voice notes for the profile". Old: `expect(api.updateProfile).toHaveBeenCalledWith(expect.any(Number), ...)`. New: first argument `1`, plus `refreshPeople` is called.
- "building the master profile keeps unsaved voice notes". Old: checked the box right after `buildProfile` was called, before the response was applied. New: waits for the Build button to come back (the response has been applied), then checks the box, and asserts `buildProfile` was called with `1`.

```tsx
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import App from "../App";
import ProfileScreen from "./ProfileScreen";
import * as api from "../api";
import { PersonProvider } from "../person";
import { makePerson, renderWithPerson } from "../test-utils";
import type { ProfileDetail } from "../types";

vi.mock("../api", () => ({
  listProfiles: vi.fn(),
  getProfile: vi.fn(),
  createProfile: vi.fn(),
  updateProfile: vi.fn(),
  uploadDocument: vi.fn(),
  buildProfile: vi.fn(),
  deleteDocument: vi.fn(),
}));

const contact = { name: "Jordan Rivera", email: "e@example.com", phone: null, location: null, links: [] };

const baseProfileDetail: ProfileDetail = {
  id: 1,
  name: "Jordan Rivera",
  contact,
  master_profile: {
    summary_notes: "Seasoned engineer notes",
    experiences: [
      {
        company: "Acme",
        title: "Engineer",
        start: "2020-01",
        end: null,
        location: null,
        bullets: [{ text: "Did a thing", tags: ["python"] }],
      },
    ],
    projects: [],
    skills: [],
    education: [],
    certifications: [],
    extras: [],
  },
  voice_notes: "",
  documents: [{ id: 5, filename: "resume.pdf", kind: "pdf" }],
  created_at: "2026-01-01T00:00:00+00:00",
  inbox_url: null,
  application_count: 0,
};

const JORDAN = makePerson();
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
  created_at: "2026-02-01T00:00:00+00:00",
});

const samDetail: ProfileDetail = {
  ...baseProfileDetail,
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", phone: null, location: null, links: [] },
  master_profile: { ...baseProfileDetail.master_profile, summary_notes: "Sam's notes", experiences: [] },
  documents: [],
  created_at: "2026-02-01T00:00:00+00:00",
};

/** Shows the router location, so a test can see ?new=1 come and go. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

// Mocks are not reset between tests otherwise, and several tests here queue
// one-off responses or assert call counts.
beforeEach(() => {
  vi.mocked(api.listProfiles).mockReset();
  vi.mocked(api.getProfile).mockReset().mockResolvedValue(baseProfileDetail);
  vi.mocked(api.createProfile).mockReset();
  vi.mocked(api.updateProfile).mockReset();
  vi.mocked(api.uploadDocument).mockReset();
  vi.mocked(api.buildProfile).mockReset();
  vi.mocked(api.deleteDocument).mockReset();
  localStorage.clear();
});

describe("ProfileScreen", () => {
  it("renders the current person's documents and master profile editor", async () => {
    renderWithPerson(<ProfileScreen />, { route: "/profiles" });
    expect(await screen.findByDisplayValue("Seasoned engineer notes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Jordan Rivera" })).toBeInTheDocument();
    expect(screen.getByText("resume.pdf")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Acme")).toBeInTheDocument();
    expect(api.getProfile).toHaveBeenCalledWith(1);
  });

  it("has no person picker of its own and never lists profiles itself", async () => {
    renderWithPerson(<ProfileScreen />, { people: [JORDAN, SAM] });
    await screen.findByDisplayValue("Seasoned engineer notes");
    expect(screen.queryByText("Your profiles")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sam Lee" })).not.toBeInTheDocument();
    expect(api.listProfiles).not.toHaveBeenCalled();
    expect(api.getProfile).toHaveBeenCalledTimes(1);
  });

  it("edits the person the picker has chosen", async () => {
    vi.mocked(api.getProfile).mockImplementation(async (id: number) =>
      id === 2 ? samDetail : baseProfileDetail,
    );
    renderWithPerson(<ProfileScreen />, { people: [JORDAN, SAM], personId: 2 });
    expect(await screen.findByDisplayValue("Sam's notes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sam Lee" })).toBeInTheDocument();
    expect(api.getProfile).toHaveBeenCalledWith(2);
    expect(api.getProfile).not.toHaveBeenCalledWith(1);
  });

  it("adding a bullet grows the bullet input list", async () => {
    renderWithPerson(<ProfileScreen />);
    await screen.findByDisplayValue("Seasoned engineer notes");
    expect(screen.getAllByPlaceholderText("Bullet text")).toHaveLength(1);
    fireEvent.click(screen.getByText("Add bullet"));
    expect(screen.getAllByPlaceholderText("Bullet text")).toHaveLength(2);
  });

  it("saves voice notes for the profile and refreshes the people list", async () => {
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    vi.mocked(api.updateProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      voice_notes: "Plain and direct. Never call myself passionate.",
    });
    renderWithPerson(<ProfileScreen />, { overrides: { refreshPeople } });
    const box = await screen.findByLabelText(/voice notes/i);
    fireEvent.change(box, {
      target: { value: "Plain and direct. Never call myself passionate." },
    });
    fireEvent.click(screen.getByRole("button", { name: /save master profile/i }));
    await waitFor(() =>
      expect(api.updateProfile).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          voice_notes: "Plain and direct. Never call myself passionate.",
        }),
      ),
    );
    await waitFor(() => expect(refreshPeople).toHaveBeenCalled());
  });

  it("building the master profile keeps unsaved voice notes", async () => {
    // Build runs intake, which never touches voice notes; reseeding the box
    // from its response would silently discard what the user just typed.
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    vi.mocked(api.buildProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      voice_notes: "",
    });
    renderWithPerson(<ProfileScreen />, { overrides: { refreshPeople } });
    const box = await screen.findByLabelText(/voice notes/i);
    fireEvent.change(box, { target: { value: "Short sentences only." } });
    fireEvent.click(screen.getByRole("button", { name: /build master profile/i }));
    expect(api.buildProfile).toHaveBeenCalledWith(1);
    // The button reads "Building..." until the response has been applied.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /build master profile/i })).toBeEnabled(),
    );
    expect(screen.getByLabelText(/voice notes/i)).toHaveValue("Short sentences only.");
    expect(refreshPeople).toHaveBeenCalled();
  });

  it("shows the voice notes already on the profile", async () => {
    vi.mocked(api.getProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      voice_notes: "Short sentences only.",
    });
    renderWithPerson(<ProfileScreen />);
    expect(await screen.findByDisplayValue("Short sentences only.")).toBeInTheDocument();
  });

  it("renders nothing that depends on a person while the list is loading", () => {
    renderWithPerson(<ProfileScreen />, { people: [], loading: true });
    expect(screen.getByRole("heading", { name: "Profiles" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(api.getProfile).not.toHaveBeenCalled();
  });

  it("shows the list error instead of a create form when people could not be loaded", () => {
    renderWithPerson(<ProfileScreen />, {
      people: [],
      overrides: { error: "API 500: Internal Server Error" },
    });
    expect(screen.getByText("API 500: Internal Server Error")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create person" })).not.toBeInTheDocument();
  });

  it("shows the create form when there are no people; creating clears the guard, then selects the new person", async () => {
    const calls: string[] = [];
    const setSwitchGuard = vi.fn((message: string | null) => {
      calls.push(`guard:${message}`);
    });
    const refreshPeople = vi.fn(async (selectId?: number) => {
      calls.push(`refresh:${selectId}`);
    });
    vi.mocked(api.createProfile).mockResolvedValueOnce({ ...samDetail, id: 7 });
    renderWithPerson(<ProfileScreen />, {
      people: [],
      overrides: { setSwitchGuard, refreshPeople },
    });
    expect(screen.getByText("Add a person")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    const create = screen.getByRole("button", { name: "Create person" });
    expect(create).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "  Sam Lee " } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "sam@example.com" } });
    fireEvent.click(create);

    await waitFor(() => expect(refreshPeople).toHaveBeenCalledWith(7));
    expect(api.createProfile).toHaveBeenCalledWith("Sam Lee", {
      name: "Sam Lee",
      email: "sam@example.com",
      links: [],
    });
    expect(calls[calls.indexOf("refresh:7") - 1]).toBe("guard:null");
  });

  it("?new=1 opens the create form in place of the editor, and Cancel goes back", async () => {
    renderWithPerson(
      <>
        <ProfileScreen />
        <LocationProbe />
      </>,
      { route: "/profiles?new=1" },
    );
    expect(screen.getByRole("button", { name: "Create person" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save master profile/i })).not.toBeInTheDocument();
    expect(api.getProfile).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/profiles$/);
    expect(await screen.findByDisplayValue("Seasoned engineer notes")).toBeInTheDocument();
  });

  it("creating from ?new=1 drops the parameter after the new person is selected", async () => {
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    vi.mocked(api.createProfile).mockResolvedValueOnce({ ...samDetail, id: 7 });
    renderWithPerson(
      <>
        <ProfileScreen />
        <LocationProbe />
      </>,
      { route: "/profiles?new=1", overrides: { refreshPeople } },
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Sam Lee" } });
    fireEvent.click(screen.getByRole("button", { name: "Create person" }));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(/^\/profiles$/),
    );
    expect(refreshPeople).toHaveBeenCalledWith(7);
  });

  it("choosing another person in the nav closes the create form", async () => {
    vi.mocked(api.getProfile).mockImplementation(async (id: number) =>
      id === 2 ? samDetail : baseProfileDetail,
    );
    const { switchTo } = renderWithPerson(
      <>
        <ProfileScreen />
        <LocationProbe />
      </>,
      { people: [JORDAN, SAM], route: "/profiles?new=1" },
    );
    expect(screen.getByRole("button", { name: "Create person" })).toBeInTheDocument();

    act(() => switchTo(2));

    expect(await screen.findByDisplayValue("Sam's notes")).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/profiles$/);
    expect(api.getProfile).toHaveBeenCalledWith(2);
    expect(api.getProfile).not.toHaveBeenCalledWith(1);
  });

  it("renames a person and changes their email through updateProfile, then refreshes the list", async () => {
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    const saved = { ...contact, name: "Jordan A. Rivera", email: "jordan@gmail.com" };
    vi.mocked(api.updateProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      name: "Jordan A. Rivera",
      contact: saved,
    });
    renderWithPerson(<ProfileScreen />, { overrides: { refreshPeople } });
    const nameBox = await screen.findByLabelText("Name");
    const emailBox = screen.getByLabelText("Email");
    expect(nameBox).toHaveValue("Jordan Rivera");
    expect(emailBox).toHaveValue("e@example.com");
    const save = screen.getByRole("button", { name: "Save name and email" });
    expect(save).toBeDisabled();

    fireEvent.change(nameBox, { target: { value: "Jordan A. Rivera " } });
    fireEvent.change(emailBox, { target: { value: "jordan@gmail.com" } });
    fireEvent.click(save);

    await waitFor(() => expect(refreshPeople).toHaveBeenCalled());
    expect(api.updateProfile).toHaveBeenCalledWith(1, { name: "Jordan A. Rivera", contact: saved });
    expect(screen.getByLabelText("Name")).toHaveValue("Jordan A. Rivera");
    expect(screen.getByRole("button", { name: "Save name and email" })).toBeDisabled();
  });

  it("an email-only edit leaves a contact name that came from a resume alone", async () => {
    const resumeContact = { ...contact, name: "Jordan A. Rivera" };
    vi.mocked(api.getProfile).mockResolvedValueOnce({ ...baseProfileDetail, contact: resumeContact });
    vi.mocked(api.updateProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      contact: { ...resumeContact, email: "new@example.com" },
    });
    renderWithPerson(<ProfileScreen />);
    fireEvent.change(await screen.findByLabelText("Email"), {
      target: { value: "new@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save name and email" }));
    await waitFor(() =>
      expect(api.updateProfile).toHaveBeenCalledWith(1, {
        name: "Jordan Rivera",
        contact: { ...resumeContact, email: "new@example.com" },
      }),
    );
  });

  it("will not save a blank name", async () => {
    renderWithPerson(<ProfileScreen />);
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "   " } });
    expect(screen.getByText("A person needs a name.")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save name and email" });
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(api.updateProfile).not.toHaveBeenCalled();
  });

  it("a Build that fills an empty email shows it in the Email box", async () => {
    vi.mocked(api.getProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      contact: { ...contact, email: "" },
    });
    vi.mocked(api.buildProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      contact: { ...contact, email: "found@example.com" },
    });
    renderWithPerson(<ProfileScreen />);
    expect(await screen.findByLabelText("Email")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: /build master profile/i }));
    await waitFor(() =>
      expect(screen.getByLabelText("Email")).toHaveValue("found@example.com"),
    );
    // The filled email is the saved value now, not an unsaved edit.
    expect(screen.getByRole("button", { name: "Save name and email" })).toBeDisabled();
  });

  it("sets the switch guard while edits are unsaved, comparing by value", async () => {
    const setSwitchGuard = vi.fn();
    renderWithPerson(<ProfileScreen />, {
      overrides: { setSwitchGuard, labelFor: (p) => `${p.name} (work)` },
    });
    const company = await screen.findByDisplayValue("Acme");
    expect(screen.getByRole("heading", { name: "Jordan Rivera (work)" })).toBeInTheDocument();
    expect(setSwitchGuard).not.toHaveBeenCalledWith(expect.any(String));

    fireEvent.change(company, { target: { value: "Acme Corp" } });
    expect(setSwitchGuard).toHaveBeenLastCalledWith(
      "Jordan Rivera (work) has unsaved profile changes.",
    );

    // Typing the old value back is not an unsaved change, even though the
    // editor now holds a different object than the one it loaded.
    fireEvent.change(screen.getByDisplayValue("Acme Corp"), { target: { value: "Acme" } });
    expect(setSwitchGuard).toHaveBeenLastCalledWith(null);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "other@example.com" } });
    expect(setSwitchGuard).toHaveBeenLastCalledWith(
      "Jordan Rivera (work) has unsaved profile changes.",
    );
  });

  it("sets the switch guard while a build is in flight", async () => {
    const setSwitchGuard = vi.fn();
    let finishBuild: (d: ProfileDetail) => void = () => {};
    vi.mocked(api.buildProfile).mockReturnValueOnce(
      new Promise<ProfileDetail>((resolve) => {
        finishBuild = resolve;
      }),
    );
    renderWithPerson(<ProfileScreen />, { overrides: { setSwitchGuard } });
    await screen.findByDisplayValue("Seasoned engineer notes");

    fireEvent.click(screen.getByRole("button", { name: /build master profile/i }));
    expect(setSwitchGuard).toHaveBeenLastCalledWith("Jordan Rivera's profile is building.");
    expect(screen.getByRole("button", { name: /save master profile/i })).toBeDisabled();

    await act(async () => {
      finishBuild(baseProfileDetail);
    });
    await waitFor(() => expect(setSwitchGuard).toHaveBeenLastCalledWith(null));
  });

  it("a build that finishes after a switch never reaches the new person's editor", async () => {
    vi.mocked(api.getProfile).mockImplementation(async (id: number) =>
      id === 2 ? samDetail : baseProfileDetail,
    );
    let finishBuild: (d: ProfileDetail) => void = () => {};
    vi.mocked(api.buildProfile).mockReturnValueOnce(
      new Promise<ProfileDetail>((resolve) => {
        finishBuild = resolve;
      }),
    );
    vi.mocked(api.updateProfile).mockResolvedValueOnce(samDetail);
    const { switchTo } = renderWithPerson(<ProfileScreen />, { people: [JORDAN, SAM] });
    await screen.findByDisplayValue("Seasoned engineer notes");
    fireEvent.click(screen.getByRole("button", { name: /build master profile/i }));
    expect(api.buildProfile).toHaveBeenCalledWith(1);

    act(() => switchTo(2));
    expect(await screen.findByDisplayValue("Sam's notes")).toBeInTheDocument();

    await act(async () => {
      finishBuild({
        ...baseProfileDetail,
        master_profile: { ...baseProfileDetail.master_profile, summary_notes: "Built for Jordan" },
      });
    });
    expect(screen.queryByDisplayValue("Built for Jordan")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Sam's notes")).toBeInTheDocument();

    // Saving now writes Sam's own profile to Sam, and nothing to Jordan.
    fireEvent.click(screen.getByRole("button", { name: /save master profile/i }));
    await waitFor(() =>
      expect(api.updateProfile).toHaveBeenCalledWith(
        2,
        expect.objectContaining({
          master_profile: expect.objectContaining({ summary_notes: "Sam's notes" }),
        }),
      ),
    );
    expect(api.updateProfile).not.toHaveBeenCalledWith(1, expect.anything());
  });

  it("leaving the screen with unsaved edits clears the guard", async () => {
    const setSwitchGuard = vi.fn();
    const { unmount } = renderWithPerson(<ProfileScreen />, { overrides: { setSwitchGuard } });
    fireEvent.change(await screen.findByDisplayValue("Seasoned engineer notes"), {
      target: { value: "Changed" },
    });
    expect(setSwitchGuard).toHaveBeenLastCalledWith("Jordan Rivera has unsaved profile changes.");
    unmount();
    expect(setSwitchGuard).toHaveBeenLastCalledWith(null);
  });

  it("adding a pasted document keeps unsaved edits and refreshes the list", async () => {
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    vi.mocked(api.uploadDocument).mockResolvedValueOnce({ id: 6, filename: "notes.txt", kind: "paste" });
    vi.mocked(api.getProfile)
      .mockResolvedValueOnce(baseProfileDetail)
      .mockResolvedValueOnce({
        ...baseProfileDetail,
        documents: [...baseProfileDetail.documents, { id: 6, filename: "notes.txt", kind: "paste" }],
      });
    renderWithPerson(<ProfileScreen />, { overrides: { refreshPeople } });
    const box = await screen.findByLabelText(/voice notes/i);
    fireEvent.change(box, { target: { value: "Short sentences only." } });
    fireEvent.change(screen.getByPlaceholderText("Document name"), { target: { value: "notes.txt" } });
    fireEvent.change(screen.getByPlaceholderText("Paste resume or notes text"), {
      target: { value: "Led the migration." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add pasted text" }));

    expect(await screen.findByText("notes.txt")).toBeInTheDocument();
    expect(api.uploadDocument).toHaveBeenCalledWith(1, {
      filename: "notes.txt",
      text: "Led the migration.",
    });
    expect(screen.getByLabelText(/voice notes/i)).toHaveValue("Short sentences only.");
    expect(refreshPeople).toHaveBeenCalled();
  });

  it("removes a document after an inline confirm", async () => {
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    vi.mocked(api.deleteDocument).mockResolvedValueOnce({ deleted: 5 });
    vi.mocked(api.getProfile)
      .mockResolvedValueOnce(baseProfileDetail)
      .mockResolvedValueOnce({ ...baseProfileDetail, documents: [] });
    renderWithPerson(<ProfileScreen />, { overrides: { refreshPeople } });

    fireEvent.click(await screen.findByRole("button", { name: "Remove resume.pdf" }));
    expect(screen.getByText("Remove resume.pdf?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "No" }));
    expect(screen.queryByText("Remove resume.pdf?")).not.toBeInTheDocument();
    expect(api.deleteDocument).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Remove resume.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(api.deleteDocument).toHaveBeenCalledWith(1, 5));
    expect(await screen.findByText(/Upload your existing resumes/)).toBeInTheDocument();
    expect(screen.queryByText("resume.pdf")).not.toBeInTheDocument();
    await waitFor(() => expect(refreshPeople).toHaveBeenCalled());
  });

  it("saving a new email updates the Inbox link in the nav", async () => {
    // The real provider and nav: the link comes from the refreshed list.
    const gmail = "jordan.rivera@gmail.com";
    const before = makePerson({ contact, inbox_url: null });
    const after = {
      ...before,
      contact: { ...contact, email: gmail },
      inbox_url: `https://mail.google.com/mail/?authuser=${gmail}`,
    };
    let saved = false;
    vi.mocked(api.listProfiles).mockImplementation(async () => [saved ? after : before]);
    vi.mocked(api.updateProfile).mockImplementation(async (_id, patch) => {
      saved = true;
      return { ...baseProfileDetail, contact: patch.contact ?? contact };
    });
    render(
      <MemoryRouter initialEntries={["/profiles"]}>
        <PersonProvider>
          <App />
        </PersonProvider>
      </MemoryRouter>,
    );
    const emailBox = await screen.findByLabelText("Email");
    expect(screen.queryByRole("link", { name: "Inbox" })).not.toBeInTheDocument();

    fireEvent.change(emailBox, { target: { value: gmail } });
    fireEvent.click(screen.getByRole("button", { name: "Save name and email" }));

    const inbox = await screen.findByRole("link", { name: "Inbox" });
    expect(inbox).toHaveAttribute("href", after.inbox_url);
    expect(api.updateProfile).toHaveBeenCalledWith(1, {
      name: "Jordan Rivera",
      contact: { ...contact, email: gmail },
    });
  });
});
```

- [ ] **Step 2: Run the Profiles tests and watch them fail**

Run: `cd frontend && npx vitest run src/screens/ProfileScreen.test.tsx`

Expected: FAIL, all 24 tests. The screen still loads through its own `listProfiles()` call, which this mock leaves returning `undefined`, so `getProfile` is never called and the old "Your profiles" row crashes with `TypeError: Cannot read properties of undefined (reading 'map')`. The tests that wait for the editor then fail with `Unable to find an element with the display value: Seasoned engineer notes`. "renders nothing that depends on a person while the list is loading" fails because the old create inputs are always rendered (`Found multiple elements with the role "textbox"`), the create-form tests fail with `Unable to find a label with the text of: Name`, and "removes a document after an inline confirm" with `Unable to find role="button" and name "Remove resume.pdf"`.

- [ ] **Step 3: Replace the imports**

In `frontend/src/screens/ProfileScreen.tsx`, replace:

```tsx
import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import {
  buildProfile,
  createProfile,
  getProfile,
  listProfiles,
  updateProfile,
  uploadDocument,
} from "../api";
import type {
  MasterProfile,
```

with:

```tsx
import { useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { useSearchParams } from "react-router-dom";
import {
  buildProfile,
  createProfile,
  deleteDocument,
  getProfile,
  updateProfile,
  uploadDocument,
} from "../api";
import { usePerson } from "../person";
import type {
  Contact,
  MasterProfile,
```

(`ProfileSummary` stays in the type import: `PersonEditor` takes one as its prop.)

- [ ] **Step 4: Split the component into the screen, the create form and the per-person editor**

Replace the component head, from its signature through its load effect:

```tsx
export default function ProfileScreen() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ProfileDetail | null>(null);
  const [mp, setMp] = useState<MasterProfile>(emptyMP);
  const [voiceNotes, setVoiceNotes] = useState("");
  const [newName, setNewName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [pasteName, setPasteName] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [building, setBuilding] = useState(false);
  const [buildUsage, setBuildUsage] = useState<UsageInfo | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function selectProfile(id: number) {
    setSelectedId(id);
    const d = await getProfile(id);
    setDetail(d);
    setMp({ ...emptyMP, ...d.master_profile });
    setVoiceNotes(d.voice_notes);
  }

  async function refreshProfiles(selectId?: number) {
    const list = await listProfiles();
    setProfiles(list);
    const target = selectId ?? selectedId ?? (list.length > 0 ? list[0].id : null);
    if (target !== null) {
      await selectProfile(target);
    }
  }

  useEffect(() => {
    refreshProfiles().catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
```

with:

```tsx
/**
 * Structural equality for the editor's JSON-shaped state, so an edit typed
 * and then reverted reads as clean. A key missing on one side and undefined
 * on the other counts as equal.
 */
function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((item, i) => deepEqual(item, b[i]));
  }
  const ao = a as Record<string, unknown>;
  const bo = b as Record<string, unknown>;
  for (const key of new Set([...Object.keys(ao), ...Object.keys(bo)])) {
    if (!deepEqual(ao[key], bo[key])) return false;
  }
  return true;
}

/** Every request the editor makes that a person switch would cut short. */
type Action = "build" | "save-profile" | "save-identity" | "upload" | "remove-document";

/** How the switch guard words each one: "{label}'s profile is building." */
const BUSY_WORD: Record<Action, string> = {
  build: "building",
  "save-profile": "saving",
  "save-identity": "saving",
  upload: "uploading",
  "remove-document": "removing",
};

/** Editor fields that take the server's value when a write comes back. */
type Part = "mp" | "voice" | "identity";

export default function ProfileScreen() {
  const { people, person, loading, error: peopleError } = usePerson();
  const [searchParams, setSearchParams] = useSearchParams();
  const listed = !loading && peopleError === null;
  const showCreate = listed && (people.length === 0 || searchParams.get("new") === "1");
  // created_at is part of the key because SQLite reissues a removed person's id.
  const personKey = person ? `${person.id}@${person.created_at}` : null;

  // Choosing a person in the nav while the create form is open means "show me
  // this person", so the form gives way to their editor. The first load
  // (nobody, then someone) is not a choice.
  const prevKey = useRef(personKey);
  useEffect(() => {
    const was = prevKey.current;
    prevKey.current = personKey;
    if (was !== null && was !== personKey && searchParams.get("new") === "1") {
      setSearchParams({}, { replace: true });
    }
    // Only a change of person matters here, not a change of the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personKey]);

  return (
    <div>
      <h1>Profiles</h1>
      {peopleError !== null && <div className="alert alert-error">{peopleError}</div>}
      {showCreate ? (
        <CreatePersonForm onCancel={people.length > 0 ? () => setSearchParams({}) : null} />
      ) : (
        // Keyed on the person: a switch mounts a fresh editor, so nothing typed
        // for one person, and no late response to their requests, can land in
        // another person's fields.
        person !== null &&
        personKey !== null && <PersonEditor key={personKey} person={person} />
      )}
    </div>
  );
}

function CreatePersonForm({ onCancel }: { onCancel: (() => void) | null }) {
  const { refreshPeople, setSwitchGuard } = usePerson();
  const [searchParams, setSearchParams] = useSearchParams();
  const [newName, setNewName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    const name = newName.trim();
    if (name === "") return;
    const fromPicker = searchParams.get("new") === "1";
    setCreating(true);
    setError(null);
    try {
      const d = await createProfile(name, { name, email: newEmail.trim(), links: [] });
      // Nothing may hold back the switch refreshPeople makes to the new person.
      setSwitchGuard(null);
      await refreshPeople(d.id);
      setNewName("");
      setNewEmail("");
      if (fromPicker) setSearchParams({}, { replace: true });
    } catch (err) {
      setError(String(err));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title">Add a person</div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="field">
        <label className="field-label" htmlFor="new-person-name">Name</label>
        <input
          id="new-person-name"
          className="input"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="new-person-email">Email</label>
        <input
          id="new-person-email"
          className="input"
          type="email"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
        />
      </div>
      <div className="row">
        <button
          className="btn btn-primary"
          onClick={handleCreate}
          disabled={creating || newName.trim() === ""}
        >
          {creating ? "Creating..." : "Create person"}
        </button>
        {onCancel && (
          <button className="btn" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * The editor for one person. ProfileScreen mounts a new one per person, so
 * `person.id` is fixed for the life of this component.
 */
function PersonEditor({ person }: { person: ProfileSummary }) {
  const { refreshPeople, setSwitchGuard, labelFor } = usePerson();
  const label = labelFor(person);
  const [detail, setDetail] = useState<ProfileDetail | null>(null);
  const [mp, setMp] = useState<MasterProfile>(emptyMP);
  const [voiceNotes, setVoiceNotes] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [pasteName, setPasteName] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [buildUsage, setBuildUsage] = useState<UsageInfo | null>(null);
  const [busy, setBusy] = useState<Action | null>(null);
  const [confirmDocId, setConfirmDocId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const building = busy === "build";
  const saving = busy === "save-profile";

  // False once this editor is gone. A request that finishes after that still
  // refreshes the people list, but applies nothing to the screen.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  /** The first load: every field starts from the server. */
  function loadDetail(d: ProfileDetail) {
    setDetail(d);
    setMp({ ...emptyMP, ...d.master_profile });
    setVoiceNotes(d.voice_notes);
    setName(d.name);
    setEmail(d.contact.email);
  }

  /**
   * A write came back: `d` becomes the baseline the dirty check compares
   * against. Fields named in `take` show the server's value. Every other field
   * keeps an unsaved edit and follows the server only when it had none, so a
   * Build that fills an empty email shows it instead of leaving a blank box
   * that the next save would write back.
   */
  function applyResponse(d: ProfileDetail, prev: ProfileDetail, take: Part[]) {
    const prevMp = { ...emptyMP, ...prev.master_profile };
    const nextMp = { ...emptyMP, ...d.master_profile };
    setDetail(d);
    setMp((m) => (take.includes("mp") || deepEqual(m, prevMp) ? nextMp : m));
    setVoiceNotes((v) => (take.includes("voice") || v === prev.voice_notes ? d.voice_notes : v));
    setName((n) => (take.includes("identity") || n === prev.name ? d.name : n));
    setEmail((e) => (take.includes("identity") || e === prev.contact.email ? d.contact.email : e));
  }

  useEffect(() => {
    getProfile(person.id)
      .then((d) => {
        if (alive.current) loadDetail(d);
      })
      .catch((e) => {
        if (alive.current) setError(String(e));
      });
    // Runs once: this editor never changes person (see ProfileScreen).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty =
    detail !== null &&
    (!deepEqual(mp, { ...emptyMP, ...detail.master_profile }) ||
      voiceNotes !== detail.voice_notes ||
      name !== detail.name ||
      email !== detail.contact.email);
  const guard =
    busy !== null
      ? `${label}'s profile is ${BUSY_WORD[busy]}.`
      : dirty
        ? `${label} has unsaved profile changes.`
        : null;

  // Set while a switch would lose something; cleared when that ends and when
  // this editor unmounts. The setter is read through a ref so the effect
  // depends on the message alone, not on the setter's identity.
  const setGuard = useRef(setSwitchGuard);
  setGuard.current = setSwitchGuard;
  useEffect(() => {
    if (guard === null) return;
    setGuard.current(guard);
    return () => setGuard.current(null);
  }, [guard]);
```

The typed master-profile editor helpers that follow (`updateExperience` through `removeExtra`) are unchanged; they now sit inside `PersonEditor`.

- [ ] **Step 5: Replace the actions**

Replace the whole actions block:

```tsx
  // ---- actions ----

  async function handleCreate() {
    if (newName.trim() === "") return;
    try {
      const d = await createProfile(newName.trim(), {
        name: newName.trim(),
        email: newEmail.trim(),
        links: [],
      });
      setNewName("");
      setNewEmail("");
      await refreshProfiles(d.id);
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleFile(e: ChangeEvent<HTMLInputElement>) {
    if (selectedId === null || !e.target.files || e.target.files.length === 0) return;
    try {
      await uploadDocument(selectedId, e.target.files[0]);
      e.target.value = "";
      await selectProfile(selectedId);
    } catch (err) {
      setError(String(err));
    }
  }

  async function handlePasteDoc() {
    if (selectedId === null || pasteText.trim() === "") return;
    try {
      await uploadDocument(selectedId, {
        filename: pasteName.trim() !== "" ? pasteName.trim() : "pasted.txt",
        text: pasteText,
      });
      setPasteName("");
      setPasteText("");
      await selectProfile(selectedId);
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleBuild() {
    if (selectedId === null) return;
    setBuilding(true);
    setError(null);
    try {
      const d = await buildProfile(selectedId);
      setDetail(d);
      setMp({ ...emptyMP, ...d.master_profile });
      // Voice notes are deliberately not reseeded here: build runs intake,
      // which never touches them, so reseeding would discard unsaved edits.
      setBuildUsage(d.usage ?? null);
    } catch (err) {
      setError(String(err));
    } finally {
      setBuilding(false);
    }
  }

  async function handleSave() {
    if (selectedId === null) return;
    setSaving(true);
    setError(null);
    try {
      const d = await updateProfile(selectedId, { master_profile: mp, voice_notes: voiceNotes });
      setDetail(d);
      setMp({ ...emptyMP, ...d.master_profile });
      setVoiceNotes(d.voice_notes);
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }
```

with:

```tsx
  // ---- actions ----
  //
  // Each write captures person.id when it starts (in run). The editor is
  // remounted per person, so a response that lands after a switch reaches an
  // unmounted editor and is dropped there: a Build that returns late can never
  // load one person's master profile into another's editor, where the next
  // Save would write it.

  async function run<T>(
    action: Action,
    call: (id: number) => Promise<T>,
    apply: (result: T) => void
  ): Promise<boolean> {
    const id = person.id;
    setBusy(action);
    setError(null);
    try {
      const result = await call(id);
      const applied = alive.current;
      if (applied) apply(result);
      // The list carries names, emails, inbox links and has_master_profile, so
      // it is refreshed after every write, including one whose editor is gone.
      await refreshPeople();
      return applied;
    } catch (err) {
      if (alive.current) setError(String(err));
      return false;
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  async function handleFile(e: ChangeEvent<HTMLInputElement>) {
    const input = e.target;
    if (detail === null || !input.files || input.files.length === 0) return;
    const file = input.files[0];
    const prev = detail;
    await run(
      "upload",
      async (id) => {
        await uploadDocument(id, file);
        return getProfile(id);
      },
      (d) => applyResponse(d, prev, [])
    );
    input.value = "";
  }

  async function handlePasteDoc() {
    if (detail === null || pasteText.trim() === "") return;
    const prev = detail;
    const source = {
      filename: pasteName.trim() !== "" ? pasteName.trim() : "pasted.txt",
      text: pasteText,
    };
    const applied = await run(
      "upload",
      async (id) => {
        await uploadDocument(id, source);
        return getProfile(id);
      },
      (d) => applyResponse(d, prev, [])
    );
    if (applied) {
      setPasteName("");
      setPasteText("");
    }
  }

  async function handleRemoveDocument(docId: number) {
    if (detail === null) return;
    const prev = detail;
    setConfirmDocId(null);
    await run(
      "remove-document",
      async (id) => {
        await deleteDocument(id, docId);
        return getProfile(id);
      },
      (d) => applyResponse(d, prev, [])
    );
  }

  async function handleBuild() {
    if (detail === null) return;
    const prev = detail;
    await run(
      "build",
      (id) => buildProfile(id),
      (d) => {
        // Build replaces the structured profile. Voice notes are deliberately
        // not taken from its response: build runs intake, which never touches
        // them, so taking them would discard unsaved edits. Name and email
        // keep an unsaved edit the same way.
        applyResponse(d, prev, ["mp"]);
        setBuildUsage(d.usage ?? null);
      }
    );
  }

  async function handleSave() {
    if (detail === null) return;
    const prev = detail;
    const patch = { master_profile: mp, voice_notes: voiceNotes };
    await run(
      "save-profile",
      (id) => updateProfile(id, patch),
      (d) => applyResponse(d, prev, ["mp", "voice"])
    );
  }

  async function handleSaveIdentity() {
    if (detail === null) return;
    const trimmed = name.trim();
    if (trimmed === "") return;
    const prev = detail;
    const contact: Contact = {
      ...prev.contact,
      email: email.trim(),
      // Renaming the person renames them on their resume too. An email-only
      // edit leaves a contact name that Build took from a resume alone.
      ...(trimmed !== prev.name ? { name: trimmed } : {}),
    };
    await run(
      "save-identity",
      (id) => updateProfile(id, { name: trimmed, contact }),
      (d) => applyResponse(d, prev, ["identity"])
    );
  }
```

- [ ] **Step 6: Replace the top of the page: no picker row, a name and email card, document Remove**

Replace, from the start of the JSX through the end of the Documents card:

```tsx
  return (
    <div>
      <h1>Profiles</h1>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        <div className="card-title">Your profiles</div>
        <div className="row">
          {profiles.map((p) => (
            <button
              key={p.id}
              className={p.id === selectedId ? "btn btn-primary" : "btn"}
              onClick={() => selectProfile(p.id).catch((e) => setError(String(e)))}
            >
              {p.name}
            </button>
          ))}
          {profiles.length === 0 && <span className="muted">No profiles yet — create one below.</span>}
        </div>
        <div className="row">
          <input
            className="input"
            placeholder="Name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <input
            className="input"
            placeholder="Email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
          />
          <button className="btn" onClick={handleCreate}>
            Create profile
          </button>
        </div>
      </div>

      {detail && (
        <>
          <h2>{detail.name}</h2>

          <div className="card">
            <div className="card-title">Documents</div>
            <ul>
              {detail.documents.map((d) => (
                <li key={d.id}>
                  {d.filename} <span className="muted">({d.kind})</span>
                </li>
              ))}
            </ul>
            {detail.documents.length === 0 && (
              <p className="muted">Upload your existing resumes and notes to build a master profile.</p>
            )}
            <div className="field">
              <label className="field-label">Upload file (.pdf, .docx, .txt)</label>
              <input type="file" accept=".pdf,.docx,.txt" onChange={handleFile} />
            </div>
            <div className="field">
              <label className="field-label">Or paste text</label>
              <input
                className="input"
                placeholder="Document name"
                value={pasteName}
                onChange={(e) => setPasteName(e.target.value)}
              />
              <textarea
                className="textarea"
                placeholder="Paste resume or notes text"
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
              />
              <button className="btn" onClick={handlePasteDoc}>
                Add pasted text
              </button>
            </div>
          </div>
```

with (the `<h1>` now lives in `ProfileScreen`; the nesting depth is unchanged so the Build and Master profile cards below keep their indentation):

```tsx
  return (
    <div>
      {error && <div className="alert alert-error">{error}</div>}

      {detail && (
        <>
          <h2>{label}</h2>

          <div className="card">
            <div className="card-title">Name and email</div>
            <div className="field">
              <label className="field-label" htmlFor="person-name">Name</label>
              <input
                id="person-name"
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              {name.trim() === "" && <p className="muted">A person needs a name.</p>}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="person-email">Email</label>
              <input
                id="person-email"
                className="input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <button
              className="btn"
              onClick={handleSaveIdentity}
              disabled={
                busy !== null ||
                name.trim() === "" ||
                (name === detail.name && email === detail.contact.email)
              }
            >
              {busy === "save-identity" ? "Saving..." : "Save name and email"}
            </button>
          </div>

          <div className="card">
            <div className="card-title">Documents</div>
            <ul>
              {detail.documents.map((d) => (
                <li key={d.id}>
                  {confirmDocId === d.id ? (
                    <>
                      <span>Remove {d.filename}?</span>{" "}
                      <button
                        className="btn btn-danger btn-small"
                        onClick={() => handleRemoveDocument(d.id)}
                        disabled={busy !== null}
                      >
                        Yes
                      </button>{" "}
                      <button className="btn btn-small" onClick={() => setConfirmDocId(null)}>
                        No
                      </button>
                    </>
                  ) : (
                    <>
                      {d.filename} <span className="muted">({d.kind})</span>{" "}
                      <button
                        className="btn btn-ghost btn-small"
                        aria-label={`Remove ${d.filename}`}
                        onClick={() => setConfirmDocId(d.id)}
                        disabled={busy !== null}
                      >
                        Remove
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
            {detail.documents.length === 0 && (
              <p className="muted">Upload your existing resumes and notes to build a master profile.</p>
            )}
            <div className="field">
              <label className="field-label">Upload file (.pdf, .docx, .txt)</label>
              <input
                type="file"
                accept=".pdf,.docx,.txt"
                onChange={handleFile}
                disabled={busy !== null}
              />
            </div>
            <div className="field">
              <label className="field-label">Or paste text</label>
              <input
                className="input"
                placeholder="Document name"
                value={pasteName}
                onChange={(e) => setPasteName(e.target.value)}
              />
              <textarea
                className="textarea"
                placeholder="Paste resume or notes text"
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
              />
              <button className="btn" onClick={handlePasteDoc} disabled={busy !== null}>
                Add pasted text
              </button>
            </div>
          </div>
```

- [ ] **Step 7: Disable Build and Save while any write is in flight**

Replace:

```tsx
            <button className="btn btn-primary" onClick={handleBuild} disabled={building}>
```

with:

```tsx
            <button className="btn btn-primary" onClick={handleBuild} disabled={busy !== null}>
```

Replace:

```tsx
              <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
```

with:

```tsx
              <button className="btn btn-primary" onClick={handleSave} disabled={busy !== null}>
```

The spinner and the "Building..." / "Saving..." labels keep reading `building` and `saving`, which are now derived from `busy`. The rest of the file (the Build card text, the Master profile card, the closing `</>`, `)}`, `</div>`) is unchanged.

- [ ] **Step 8: Run the Profiles tests**

Run: `cd frontend && npx vitest run src/screens/ProfileScreen.test.tsx`

Expected: PASS, all 24 tests.

- [ ] **Step 9: Run the whole frontend suite**

Run: `cd frontend && npm test`

Expected: PASS. `src/App.test.tsx` renders `/` only, so it never mounts this screen.

- [ ] **Step 10: Rebuild the bundle and check it**

Run: `cd frontend && npm run build`

Expected: `tsc` reports no errors (it type-checks the test file too), Vite writes `frontend/dist`, and the last line is `stamp-build: recorded <N> build inputs`.

Run (from the repo root): `.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q`

Expected: PASS.

- [ ] **Step 11: Commit**

Run (from the repo root):

```bash
git add frontend/src/screens/ProfileScreen.tsx frontend/src/screens/ProfileScreen.test.tsx frontend/dist
git commit -m "$(cat <<'EOF'
feat: profiles screen edits the current person

The screen edits the person from PersonContext instead of keeping its
own profile list and button row. The create form shows when there are
no people or at /profiles?new=1, and creating selects the new person.
Name and email are editable and saved through PUT /api/profiles/{id}.

A switch guard covers unsaved edits (compared by value) and requests in
flight. The editor is remounted per person, so a response that lands
after a switch is dropped instead of loading one person's profile into
another's editor. Upload, removal and Build no longer discard unsaved
edits, and each document can be removed with an inline confirm. The
people list is refreshed after every write.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
git status --short
```

Expected: `git status --short` prints nothing (a dirty `frontend/dist` means the rebuild was not added).


---

### Task 16: Profiles screen "Remove this person" panel

**Files:**
- Modify: `frontend/src/screens/ProfileScreen.tsx` (the import block; the `Action` / `BUSY_WORD` declarations plus new module-level helpers; `PersonEditor`'s state, actions, a summary const before its `return (`, and a new card after the Master profile card)
- Modify: `frontend/src/screens/ProfileScreen.test.tsx` (two import lines, the `../api` mock factory, and a new describe block appended)
- Rebuild: `frontend/dist` (committed)
- Test: `frontend/src/screens/ProfileScreen.test.tsx`

**Interfaces:**
- Consumes:
  - Task 10: `deleteProfile(profileId: number, confirmName: string): Promise<{ deleted: number; applications: number; documents: number }>` in `frontend/src/api.ts`; `ProfileDetail.application_count: number`. Existing, unchanged: `listApplications(profileId?: number, opts?: { stage?: Stage; archived?: boolean })`, and `request()`'s error format: when the response body's `detail` is not a string, the thrown `Error` message is `API <status>: <JSON.stringify(body)>`.
  - Task 5: a 409 from `DELETE /api/profiles/{id}` has body `{"detail": {"message": str, "blocking": [{"id": int, "label": str, "status": str}]}}` (`status` is an application status, or `"locked"` for an export file that could not be moved).
  - Task 15 (`ProfileScreen.tsx`): `type Action`, `BUSY_WORD`, and inside `PersonEditor`: `person`, `label`, `detail`, `busy`/`setBusy`, `alive`, `refreshPeople`, `setSwitchGuard`, `handleSaveIdentity()` and the guard effect (it words `"remove-person"` through `BUSY_WORD`). Task 15 (`ProfileScreen.test.tsx`): the file-level mock factory and `beforeEach`, `baseProfileDetail`, `renderWithPerson`.
  - `STATUS_LABELS` from `frontend/src/statuses.ts` (existing).
- Produces: no new exports. User-visible strings: button `Remove this person` (also the card title); the panel sentence `This permanently deletes {label}'s profile, {m} document(s) and {n} application(s) (archived included), plus their exported files. It cannot be undone.`; `{k} saved job(s), including any an agent is working on, will be removed.`; field `Type {name} to confirm`; buttons `Remove {label}` (reads `Removing...` while in flight) and `Cancel`. Nothing later in the plan relies on this task's internals.
- Choices made here (the contract leaves them open):
  - Counts: `m = detail.documents.length`, `n = detail.application_count`. Nouns are singular for 1 ("1 document"). The spec writes the template as "{m} documents and {n} applications"; a literal "1 documents" would be the only ungrammatical string in the app, so the noun follows the count.
  - The saved-jobs line (spec 6.2, queue-driven MCP work) needs `k`, the person's `not_started` applications, archived ones included. Opening the panel fetches `listApplications(id)` and `listApplications(id, { archived: true })` and counts `status === "not_started"`. The line is shown only when `k > 0`: with no `not_started` row there is no queued job for an agent to be working on. If either fetch fails the line is omitted; the rest of the panel and the removal still work.
  - The Remove button is enabled only when the field equals `person.name` exactly (no trimming, case-sensitive), matching the server's check, and never while any request is in flight. It sends the typed text as `confirm_name`.
  - While the removal is in flight `busy` is `"remove-person"`, so the guard reads `{label}'s profile is removing.` and every write control is disabled.
  - After a successful delete: `setSwitchGuard(null)` (only if this editor is still mounted), then `refreshPeople()` with no argument, which falls back to the first remaining person or to the create form. The panel is not closed by hand: the refresh changes the person, which unmounts this editor.
  - A 409 is parsed from the `Error` message (`removalProblem`): its `message` and one `Link` per blocking entry to `/applications/{id}`, labelled with the entry's `label` and followed by the status in the Dashboard's words (`STATUS_LABELS`; `locked` shows as is). Any other failure shows `String(err)`. Both render in a `role="alert"` box inside the panel, which stays open with the typed name kept.
- Order and overlap: this task edits code Task 15 wrote; every "replace" below quotes Task 15's version. The working tree uses CRLF line endings (`core.autocrlf=true`); make the edits with the Edit tool or an editor.

- [ ] **Step 1: Add the failing tests**

In `frontend/src/screens/ProfileScreen.test.tsx`, replace:

```tsx
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
```

with:

```tsx
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
```

Replace:

```tsx
import type { ProfileDetail } from "../types";
```

with:

```tsx
import type { AppStatus, ApplicationSummary, ProfileDetail } from "../types";
```

Replace the mock factory:

```tsx
vi.mock("../api", () => ({
  listProfiles: vi.fn(),
  getProfile: vi.fn(),
  createProfile: vi.fn(),
  updateProfile: vi.fn(),
  uploadDocument: vi.fn(),
  buildProfile: vi.fn(),
  deleteDocument: vi.fn(),
}));
```

with:

```tsx
vi.mock("../api", () => ({
  listProfiles: vi.fn(),
  getProfile: vi.fn(),
  createProfile: vi.fn(),
  updateProfile: vi.fn(),
  uploadDocument: vi.fn(),
  buildProfile: vi.fn(),
  deleteDocument: vi.fn(),
  deleteProfile: vi.fn(),
  listApplications: vi.fn(),
}));
```

Then append the new describe block after the last test of the existing one. Replace the end of the file:

```tsx
    expect(api.updateProfile).toHaveBeenCalledWith(1, {
      name: "Jordan Rivera",
      contact: { ...contact, email: gmail },
    });
  });
});
```

with:

```tsx
    expect(api.updateProfile).toHaveBeenCalledWith(1, {
      name: "Jordan Rivera",
      contact: { ...contact, email: gmail },
    });
  });
});

type Removed = { deleted: number; applications: number; documents: number };

function appRow(id: number, status: AppStatus, archived: boolean): ApplicationSummary {
  return {
    id,
    profile_id: 1,
    status,
    version: 1,
    template: "slate",
    depth: "standard",
    url: `https://jobs.example.com/${id}`,
    company: null,
    title: null,
    cost_usd: 0,
    created_at: "2026-09-01T00:00:00+00:00",
    stage: "saved",
    applied_at: null,
    archived_at: archived ? "2026-09-02T00:00:00+00:00" : null,
    last_activity_at: "2026-09-01T00:00:00+00:00",
  };
}

async function openRemovePanel() {
  fireEvent.click(await screen.findByRole("button", { name: "Remove this person" }));
}

function typeConfirmName(value: string) {
  fireEvent.change(screen.getByLabelText("Type Jordan Rivera to confirm"), { target: { value } });
}

describe("ProfileScreen: Remove this person", () => {
  beforeEach(() => {
    vi.mocked(api.deleteProfile).mockReset();
    vi.mocked(api.listApplications).mockReset().mockResolvedValue([]);
  });

  it("states what will be deleted, with counts from the server", async () => {
    vi.mocked(api.getProfile).mockResolvedValue({ ...baseProfileDetail, application_count: 4 });
    vi.mocked(api.listApplications).mockImplementation(async (_profileId, opts) =>
      opts?.archived
        ? [appRow(9, "not_started", true)]
        : [appRow(7, "not_started", false), appRow(8, "ready", false)],
    );
    renderWithPerson(<ProfileScreen />);
    await openRemovePanel();
    expect(
      screen.getByText(
        "This permanently deletes Jordan Rivera's profile, 1 document and 4 applications " +
          "(archived included), plus their exported files. It cannot be undone.",
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("2 saved jobs, including any an agent is working on, will be removed."),
    ).toBeInTheDocument();
    expect(api.listApplications).toHaveBeenCalledWith(1);
    expect(api.listApplications).toHaveBeenCalledWith(1, { archived: true });
  });

  it("enables Remove only for the exact name, and Cancel closes the panel", async () => {
    renderWithPerson(<ProfileScreen />);
    await openRemovePanel();
    await waitFor(() => expect(api.listApplications).toHaveBeenCalledTimes(2));
    await act(async () => {});
    // No not-built jobs, so no warning about agent work.
    expect(screen.queryByText(/saved job/)).not.toBeInTheDocument();

    const remove = screen.getByRole("button", { name: "Remove Jordan Rivera" });
    expect(remove).toBeDisabled();
    for (const attempt of ["Jordan", "jordan rivera", "Jordan Rivera "]) {
      typeConfirmName(attempt);
      expect(remove).toBeDisabled();
    }
    typeConfirmName("Jordan Rivera");
    expect(remove).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Type Jordan Rivera to confirm")).not.toBeInTheDocument();
    expect(api.deleteProfile).not.toHaveBeenCalled();
  });

  it("removes the person, clearing the guard before refreshing people", async () => {
    const calls: string[] = [];
    const setSwitchGuard = vi.fn((message: string | null) => {
      calls.push(`guard:${message}`);
    });
    const refreshPeople = vi.fn(async (selectId?: number) => {
      calls.push(`refresh:${selectId ?? ""}`);
    });
    let finish: (r: Removed) => void = () => {};
    vi.mocked(api.deleteProfile).mockReturnValueOnce(
      new Promise<Removed>((resolve) => {
        finish = resolve;
      }),
    );
    renderWithPerson(<ProfileScreen />, { overrides: { setSwitchGuard, refreshPeople } });
    await openRemovePanel();
    typeConfirmName("Jordan Rivera");
    fireEvent.click(screen.getByRole("button", { name: "Remove Jordan Rivera" }));

    expect(api.deleteProfile).toHaveBeenCalledWith(1, "Jordan Rivera");
    expect(setSwitchGuard).toHaveBeenLastCalledWith("Jordan Rivera's profile is removing.");
    expect(screen.getByRole("button", { name: "Removing..." })).toBeDisabled();

    await act(async () => {
      finish({ deleted: 1, applications: 0, documents: 1 });
    });
    await waitFor(() => expect(refreshPeople).toHaveBeenCalledTimes(1));
    expect(refreshPeople).toHaveBeenCalledWith();
    expect(calls[calls.indexOf("refresh:") - 1]).toBe("guard:null");
  });

  it("a 409 lists the blocking applications as links and removes nothing", async () => {
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    const body = {
      detail: {
        message: "Jordan Rivera has work in progress.",
        blocking: [
          { id: 3, label: "Acme", status: "fetching" },
          { id: 4, label: "https://jobs.example.com/4", status: "tailoring" },
        ],
      },
    };
    // api.ts's request() puts a non-string detail into the message as the whole body.
    vi.mocked(api.deleteProfile).mockRejectedValueOnce(
      new Error(`API 409: ${JSON.stringify(body)}`),
    );
    renderWithPerson(<ProfileScreen />, { overrides: { refreshPeople } });
    await openRemovePanel();
    typeConfirmName("Jordan Rivera");
    fireEvent.click(screen.getByRole("button", { name: "Remove Jordan Rivera" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Jordan Rivera has work in progress.")).toBeInTheDocument();
    expect(within(alert).getByRole("link", { name: "Acme" })).toHaveAttribute(
      "href",
      "/applications/3",
    );
    expect(within(alert).getByRole("link", { name: "https://jobs.example.com/4" })).toHaveAttribute(
      "href",
      "/applications/4",
    );
    expect(within(alert).getByText("(Fetching posting)")).toBeInTheDocument();
    expect(within(alert).getByText("(Writing)")).toBeInTheDocument();
    expect(refreshPeople).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Remove Jordan Rivera" })).toBeEnabled();
  });

  it("shows any other failure as it came back", async () => {
    vi.mocked(api.deleteProfile).mockRejectedValueOnce(
      new Error("API 422: confirm_name must equal the person's name"),
    );
    renderWithPerson(<ProfileScreen />);
    await openRemovePanel();
    typeConfirmName("Jordan Rivera");
    fireEvent.click(screen.getByRole("button", { name: "Remove Jordan Rivera" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "API 422: confirm_name must equal the person's name",
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the Profiles tests and watch the new ones fail**

Run: `cd frontend && npx vitest run src/screens/ProfileScreen.test.tsx`

Expected: FAIL, 5 failed and 24 passed. Each test in "ProfileScreen: Remove this person" fails with `Unable to find role="button" and name "Remove this person"`; Task 15's 24 tests still pass.

- [ ] **Step 3: Import what the panel uses**

In `frontend/src/screens/ProfileScreen.tsx`, replace:

```tsx
import { useSearchParams } from "react-router-dom";
import {
  buildProfile,
  createProfile,
  deleteDocument,
  getProfile,
  updateProfile,
  uploadDocument,
} from "../api";
import { usePerson } from "../person";
import type {
  Contact,
```

with:

```tsx
import { Link, useSearchParams } from "react-router-dom";
import {
  buildProfile,
  createProfile,
  deleteDocument,
  deleteProfile,
  getProfile,
  listApplications,
  updateProfile,
  uploadDocument,
} from "../api";
import { usePerson } from "../person";
import { STATUS_LABELS } from "../statuses";
import type {
  AppStatus,
  Contact,
```

- [ ] **Step 4: Add the "remove-person" action and the panel's helpers**

Replace:

```tsx
/** Every request the editor makes that a person switch would cut short. */
type Action = "build" | "save-profile" | "save-identity" | "upload" | "remove-document";

/** How the switch guard words each one: "{label}'s profile is building." */
const BUSY_WORD: Record<Action, string> = {
  build: "building",
  "save-profile": "saving",
  "save-identity": "saving",
  upload: "uploading",
  "remove-document": "removing",
};
```

with:

```tsx
/** Every request the editor makes that a person switch would cut short. */
type Action =
  | "build"
  | "save-profile"
  | "save-identity"
  | "upload"
  | "remove-document"
  | "remove-person";

/** How the switch guard words each one: "{label}'s profile is building." */
const BUSY_WORD: Record<Action, string> = {
  build: "building",
  "save-profile": "saving",
  "save-identity": "saving",
  upload: "uploading",
  "remove-document": "removing",
  "remove-person": "removing",
};

/** "1 document", "4 applications". */
function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** The Dashboard's words for a status; a locked export file reads "locked". */
function statusLabel(status: string): string {
  return Object.prototype.hasOwnProperty.call(STATUS_LABELS, status)
    ? STATUS_LABELS[status as AppStatus]
    : status;
}

/** One application, or one locked export file, standing in the way of a removal. */
interface RemovalBlocking {
  id: number;
  label: string;
  status: string;
}

interface RemovalProblem {
  message: string;
  blocking: RemovalBlocking[];
}

/**
 * Reads a failed DELETE /profiles/{id}. A 409's detail is an object
 * ({message, blocking}), and api.ts's request() puts a non-string detail into
 * the Error message as the whole JSON body ("API 409: {"detail": {...}}"), so
 * the blocking list is recovered from there. Anything else is shown as is.
 */
function removalProblem(err: unknown): RemovalProblem {
  const text = err instanceof Error ? err.message : String(err);
  const match = /^API 409: ([\s\S]*)$/.exec(text);
  if (match) {
    try {
      const detail = JSON.parse(match[1])?.detail;
      if (detail && typeof detail.message === "string" && Array.isArray(detail.blocking)) {
        return { message: detail.message, blocking: detail.blocking as RemovalBlocking[] };
      }
    } catch {
      // Not the structured body; fall through to the raw message.
    }
  }
  return { message: String(err), blocking: [] };
}
```

- [ ] **Step 5: Add the panel's state to `PersonEditor`**

Replace (the second line makes this unique; `CreatePersonForm` has the same `error` line):

```tsx
  const [error, setError] = useState<string | null>(null);
  const building = busy === "build";
```

with:

```tsx
  const [error, setError] = useState<string | null>(null);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [savedJobs, setSavedJobs] = useState<number | null>(null);
  const [removeProblem, setRemoveProblem] = useState<RemovalProblem | null>(null);
  const building = busy === "build";
```

- [ ] **Step 6: Add the open and remove handlers after `handleSaveIdentity`**

Replace the end of `handleSaveIdentity`:

```tsx
    await run(
      "save-identity",
      (id) => updateProfile(id, { name: trimmed, contact }),
      (d) => applyResponse(d, prev, ["identity"])
    );
  }
```

with:

```tsx
    await run(
      "save-identity",
      (id) => updateProfile(id, { name: trimmed, contact }),
      (d) => applyResponse(d, prev, ["identity"])
    );
  }

  function openRemovePanel() {
    const id = person.id;
    setRemoveOpen(true);
    setConfirmName("");
    setRemoveProblem(null);
    setSavedJobs(null);
    // An agent working a queued job leaves no status trace, so the panel says
    // how many not-yet-built jobs go with this person, archived ones included.
    Promise.all([listApplications(id), listApplications(id, { archived: true })])
      .then(([active, archived]) => {
        if (!alive.current) return;
        setSavedJobs([...active, ...archived].filter((a) => a.status === "not_started").length);
      })
      .catch(() => {
        // The count is a warning, not a precondition: without it the panel
        // still states everything the server will delete.
      });
  }

  async function handleRemovePerson() {
    if (confirmName !== person.name) return;
    const id = person.id;
    setBusy("remove-person");
    setRemoveProblem(null);
    try {
      await deleteProfile(id, confirmName);
      // This person is gone. Clear the guard before refreshPeople(), which
      // falls back to the first remaining person, or to the create form.
      if (alive.current) setSwitchGuard(null);
      await refreshPeople();
    } catch (err) {
      if (alive.current) setRemoveProblem(removalProblem(err));
    } finally {
      if (alive.current) setBusy(null);
    }
  }
```

- [ ] **Step 7: Compute the panel sentence before the JSX**

Replace the start of `PersonEditor`'s JSX (this is `PersonEditor`'s return, the one whose first child is the error line; `ProfileScreen`'s starts with `<h1>`):

```tsx
  return (
    <div>
      {error && <div className="alert alert-error">{error}</div>}
```

with:

```tsx
  const removalSummary =
    detail === null
      ? ""
      : `This permanently deletes ${label}'s profile, ${count(detail.documents.length, "document")} ` +
        `and ${count(detail.application_count, "application")} (archived included), ` +
        "plus their exported files. It cannot be undone.";

  return (
    <div>
      {error && <div className="alert alert-error">{error}</div>}
```

- [ ] **Step 8: End the page with the "Remove this person" card**

Replace the end of the Master profile card:

```tsx
                {saving ? "Saving..." : "Save master profile"}
              </button>
            </div>
          </div>
        </>
```

with:

```tsx
                {saving ? "Saving..." : "Save master profile"}
              </button>
            </div>
          </div>

          <div className="card">
            <div className="card-title">Remove this person</div>
            {!removeOpen ? (
              <button className="btn btn-danger" onClick={openRemovePanel} disabled={busy !== null}>
                Remove this person
              </button>
            ) : (
              <>
                <p>{removalSummary}</p>
                {savedJobs !== null && savedJobs > 0 && (
                  <p>
                    {`${count(savedJobs, "saved job")}, including any an agent is working on, will be removed.`}
                  </p>
                )}
                <div className="field">
                  <label className="field-label" htmlFor="confirm-remove-name">
                    Type {person.name} to confirm
                  </label>
                  <input
                    id="confirm-remove-name"
                    className="input"
                    autoComplete="off"
                    value={confirmName}
                    onChange={(e) => setConfirmName(e.target.value)}
                  />
                </div>
                {removeProblem && (
                  <div className="alert alert-error" role="alert">
                    <p>{removeProblem.message}</p>
                    {removeProblem.blocking.length > 0 && (
                      <ul>
                        {removeProblem.blocking.map((b) => (
                          <li key={`${b.id}-${b.label}`}>
                            <Link to={`/applications/${b.id}`}>{b.label}</Link>{" "}
                            <span className="muted">({statusLabel(b.status)})</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
                <div className="row">
                  <button
                    className="btn btn-danger"
                    onClick={handleRemovePerson}
                    disabled={busy !== null || confirmName !== person.name}
                  >
                    {busy === "remove-person" ? "Removing..." : `Remove ${label}`}
                  </button>
                  <button
                    className="btn"
                    onClick={() => setRemoveOpen(false)}
                    disabled={busy === "remove-person"}
                  >
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
        </>
```

- [ ] **Step 9: Run the Profiles tests**

Run: `cd frontend && npx vitest run src/screens/ProfileScreen.test.tsx`

Expected: PASS, all 29 tests (24 in "ProfileScreen", 5 in "ProfileScreen: Remove this person").

- [ ] **Step 10: Run the whole frontend suite**

Run: `cd frontend && npm test`

Expected: PASS.

- [ ] **Step 11: Rebuild the bundle and check it**

Run: `cd frontend && npm run build`

Expected: `tsc` reports no errors (it type-checks the test file too), Vite writes `frontend/dist`, and the last line is `stamp-build: recorded <N> build inputs`.

Run (from the repo root): `.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q`

Expected: PASS.

- [ ] **Step 12: Commit**

Run (from the repo root):

```bash
git add frontend/src/screens/ProfileScreen.tsx frontend/src/screens/ProfileScreen.test.tsx frontend/dist
git commit -m "$(cat <<'EOF'
feat: remove a person from the Profiles screen

The page ends with "Remove this person". The panel states what goes,
with the document count and the server's application_count (archived
included), and warns about saved jobs an agent may be working on. The
button enables only when the typed name matches exactly. A 409 lists
the blocking applications as links to them. After a removal the screen
clears its switch guard and refreshes the people list, which falls back
to the first remaining person.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
git status --short
```

Expected: `git status --short` prints nothing (a dirty `frontend/dist` means the rebuild was not added).


---

### Task 17: Getting Started and the MCP prompts follow the current person

**Files:**
- Modify: `frontend/src/components/McpSetup.tsx` (imports and prompt constants at the top, through `const command = ...`; the two prompt fields "2. Ask your agent" and "Or hand it a whole list")
- Modify: `frontend/src/screens/GettingStartedScreen.tsx` (imports, state, the settings effect and the derived flags at the top of the component; the error line and the "Master Profile:" line in "Your setup at a glance")
- Modify: `frontend/src/components/McpSetup.test.tsx` (whole file rewritten onto `renderWithPerson`; new person tests)
- Modify: `frontend/src/screens/GettingStartedScreen.test.tsx` (whole file rewritten onto `renderWithPerson`; new person tests)
- Rebuild: `frontend/dist` (committed)
- Test: `frontend/src/components/McpSetup.test.tsx`, `frontend/src/screens/GettingStartedScreen.test.tsx`

**Interfaces:**
- Consumes: `usePerson()` from `frontend/src/person.tsx` (Task 11), reading `person`, `loading`, `error` and `labelFor(p)`. `makePerson`, `renderWithPerson` and the `PersonTestOptions` type from `frontend/src/test-utils.tsx` (Task 11). `ProfileSummary.created_at` / `inbox_url` (Task 10), only through `makePerson`. Existing `getSettings()` and `getSetup()` from `frontend/src/api.ts` (Getting Started calls `getSettings()` with no id).
- Produces: no new exports. Nothing later in the plan relies on this task's internals.
- Choices made here (the contract leaves them open):
  - **McpSetup reads `usePerson()` itself and takes no props.** It renders on two screens (Getting Started and Settings). Reading the context means both follow the picker with no prop threading, and a future caller cannot forget to pass the person. Both screens keep rendering `<McpSetup />` unchanged. `usePerson()` throws outside a provider, so every test that renders the real McpSetup uses `renderWithPerson`; the Getting Started and Settings tests keep mocking it.
  - The prompts use `person.name`, not `labelFor(person)`. The `profile_id` already tells two people with the same name apart, and a label such as `Sam Lee (sam@example.com)` would put a second pair of parentheses into the prompt. Exact strings, where `G` is `Read Tailored's workflow guide (the get_workflow_guide tool), then ` (with its trailing space):
    - with a person: `G + "tailor a resume and cover letter for {name} (profile_id {id}) from <job url>."` and `G + "queue these jobs for {name} (profile_id {id}) and work through them one at a time:\n<paste your job URLs, one per line>"`;
    - with no person (no people, or the person list failed to load): today's two strings, byte for byte (`G + "tailor my profile for <job url>."` and `G + "queue these jobs for my profile and work through them one at a time:\n<paste your job URLs, one per line>"`).
  - While `loading` is true, McpSetup renders the register command but not the two prompt fields, so a "my profile" prompt never flashes and cannot be copied before the person is known (spec §4.1: nothing person-dependent renders until loading is false).
  - Getting Started judges "Master Profile" by `person?.has_master_profile`. With a person the line reads `Master Profile for {labelFor(person)}:`; with no people it stays `Master Profile:`. The link text `Create your profile →` and its target `/profiles` are unchanged (with no people the Profiles screen opens on its create form, Task 15). The verdict waits for both the settings request and `!loading`. A person-list `error` is shown in the existing error line, exactly like a settings failure. `getSettings()` is called once, with no id, because only the app-wide `api_key_set` and `fake_mode` are read; a switch does not refetch.
  - The error line is rewritten, so its em dash becomes a colon (`Couldn't check your setup: {error}`), per the plan's character rule. Other existing copy on both screens is left as it is.
- Order and overlap: no earlier task edits these four files, except that Task 10 may have added `created_at`/`inbox_url` to the profile literals in `GettingStartedScreen.test.tsx` to keep `tsc` green. This task replaces that whole file, so those literals disappear. The working tree uses CRLF line endings (`core.autocrlf=true`); make the edits with an editor or the Edit tool, which match the code below regardless.

- [ ] **Step 1: Rewrite the McpSetup tests onto `renderWithPerson` and add the person tests**

Replace the entire contents of `frontend/src/components/McpSetup.test.tsx` with the file below. What changes in the existing tests, and why:

- `render(<McpSetup />)` becomes `renderWithPerson(<McpSetup />)` in all four existing tests. McpSetup now calls `usePerson()`, which throws outside a provider. The default person is `makePerson()`: Jordan Rivera, id 1.
- The per-test `vi.mocked(api.getSetup).mockResolvedValue(SETUP);` moves into a `beforeEach`; the two tests that need a different answer still override it.
- "shows the batch queue prompt with a copy button". Old: `expect(await screen.findByText(/queue these jobs for my profile/i)).toBeInTheDocument();` New: `expect(await screen.findByText(/queue these jobs for Jordan Rivera \(profile_id 1\)/i)).toBeInTheDocument();` With a person present the prompt names them. The "my profile" wording now belongs to the no-people case, which the new test "keeps the 'my profile' prompts when there are no people" asserts exactly.
- `switchTo` is wrapped in `act` so the re-render is flushed before the next assertion, whichever way Task 11 implements it.

```tsx
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import McpSetup from "./McpSetup";
import * as api from "../api";
import { makePerson, renderWithPerson } from "../test-utils";

vi.mock("../api", () => ({ getSetup: vi.fn() }));

const SETUP = {
  platform: "windows" as const,
  python_path: "C:\\proj\\.venv\\Scripts\\python.exe",
  mcp_server_path: "C:\\proj\\backend\\mcp_server.py",
  mcp_server_exists: true,
  mcp_command:
    'claude mcp add tailored -- "C:\\proj\\.venv\\Scripts\\python.exe" "C:\\proj\\backend\\mcp_server.py"',
  env_line: "ANTHROPIC_API_KEY=sk-ant-...",
  workflow_guide_tool: "get_workflow_guide",
};

const GUIDE = "Read Tailored's workflow guide (the get_workflow_guide tool), then ";
const URL_LIST = "<paste your job URLs, one per line>";

// The <pre> under a field label is exactly what its Copy button copies.
function promptUnder(label: string): string | null {
  const field = screen.getByText(label).closest(".field");
  return field?.querySelector("pre")?.textContent ?? null;
}

function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

describe("McpSetup", () => {
  beforeEach(() => {
    vi.mocked(api.getSetup).mockResolvedValue(SETUP);
  });

  it("renders the auto-filled mcp command from the backend", async () => {
    renderWithPerson(<McpSetup />);
    expect(await screen.findByText(SETUP.mcp_command)).toBeInTheDocument();
    expect(screen.queryByText(/couldn't find it/i)).not.toBeInTheDocument();
  });

  it("falls back to a manual template when setup detection fails", async () => {
    vi.mocked(api.getSetup).mockRejectedValue(new Error("boom"));
    renderWithPerson(<McpSetup />);
    expect(
      await screen.findByText(/Couldn't detect your paths automatically/)
    ).toBeInTheDocument();
    expect(screen.getByText(/backend\/mcp_server\.py/)).toBeInTheDocument();
  });

  it("warns when the MCP server file is missing", async () => {
    vi.mocked(api.getSetup).mockResolvedValue({ ...SETUP, mcp_server_exists: false });
    renderWithPerson(<McpSetup />);
    expect(await screen.findByText(/couldn't find it/i)).toBeInTheDocument();
  });

  it("shows the batch queue prompt with a copy button", async () => {
    renderWithPerson(<McpSetup />);
    expect(
      await screen.findByText(/queue these jobs for Jordan Rivera \(profile_id 1\)/i)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy batch prompt/i })).toBeInTheDocument();
  });

  it("names the current person and their profile_id in both prompts", async () => {
    renderWithPerson(<McpSetup />, { people: [makePerson({ id: 3, name: "Sam Lee" })] });
    await screen.findByText(SETUP.mcp_command);
    expect(promptUnder("2. Ask your agent")).toBe(
      `${GUIDE}tailor a resume and cover letter for Sam Lee (profile_id 3) from <job url>.`
    );
    expect(promptUnder("Or hand it a whole list")).toBe(
      `${GUIDE}queue these jobs for Sam Lee (profile_id 3) and work through them one at a time:\n${URL_LIST}`
    );
    expect(screen.queryByText(/my profile/)).not.toBeInTheDocument();
  });

  it("copies the prompt that names the person", async () => {
    const writeText = stubClipboard();
    renderWithPerson(<McpSetup />, { people: [makePerson({ id: 3, name: "Sam Lee" })] });
    await screen.findByText(SETUP.mcp_command);
    fireEvent.click(screen.getByRole("button", { name: "Copy prompt" }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        `${GUIDE}tailor a resume and cover letter for Sam Lee (profile_id 3) from <job url>.`
      )
    );
  });

  it("uses the person's name, not a label disambiguated for the picker", async () => {
    renderWithPerson(<McpSetup />, {
      people: [makePerson({ id: 3, name: "Sam Lee" })],
      overrides: { labelFor: (p) => `${p.name} #${p.id}` },
    });
    await screen.findByText(SETUP.mcp_command);
    expect(promptUnder("2. Ask your agent")).toContain("for Sam Lee (profile_id 3) from");
  });

  it("follows the picker when the person changes", async () => {
    const { switchTo } = renderWithPerson(<McpSetup />, {
      people: [makePerson({ id: 1, name: "Jordan Rivera" }), makePerson({ id: 2, name: "Sam Lee" })],
    });
    await screen.findByText(SETUP.mcp_command);
    expect(promptUnder("2. Ask your agent")).toContain("for Jordan Rivera (profile_id 1)");
    act(() => {
      switchTo(2);
    });
    expect(promptUnder("2. Ask your agent")).toContain("for Sam Lee (profile_id 2)");
    expect(promptUnder("Or hand it a whole list")).toContain("for Sam Lee (profile_id 2)");
    expect(screen.queryByText(/Jordan Rivera/)).not.toBeInTheDocument();
  });

  it("keeps the 'my profile' prompts when there are no people", async () => {
    renderWithPerson(<McpSetup />, { people: [], personId: null });
    await screen.findByText(SETUP.mcp_command);
    expect(promptUnder("2. Ask your agent")).toBe(`${GUIDE}tailor my profile for <job url>.`);
    expect(promptUnder("Or hand it a whole list")).toBe(
      `${GUIDE}queue these jobs for my profile and work through them one at a time:\n${URL_LIST}`
    );
  });

  it("shows no prompt while the person list is still loading", async () => {
    renderWithPerson(<McpSetup />, { people: [], personId: null, loading: true });
    // The register command does not depend on the person, so it still shows.
    expect(await screen.findByText(SETUP.mcp_command)).toBeInTheDocument();
    expect(screen.queryByText("2. Ask your agent")).not.toBeInTheDocument();
    expect(screen.queryByText("Or hand it a whole list")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy prompt" })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the McpSetup tests and confirm they fail**

Run: `cd frontend && npx vitest run src/components/McpSetup.test.tsx`

Expected: FAIL, `Tests  6 failed | 4 passed (10)`. The failures are "shows the batch queue prompt with a copy button", "names the current person and their profile_id in both prompts", "copies the prompt that names the person", "uses the person's name, not a label disambiguated for the picker" and "follows the picker when the person changes" (each receives `...tailor my profile for <job url>.` or `...for my profile...`), plus "shows no prompt while the person list is still loading" (the field `2. Ask your agent` is still rendered). The command, fallback, missing-server and no-people tests already pass.

- [ ] **Step 3: Make McpSetup name the current person**

Both edits are in `frontend/src/components/McpSetup.tsx`.

3a. Imports, prompt builders and the person read. Replace this code:

```tsx
import { useEffect, useState } from "react";
import { getSetup } from "../api";
import type { SetupShape } from "../types";
import CopyButton from "./CopyButton";

const AGENT_PROMPT =
  "Read Tailored's workflow guide (the get_workflow_guide tool), then tailor my profile for <job url>.";

const BATCH_PROMPT =
  "Read Tailored's workflow guide (the get_workflow_guide tool), then queue these jobs for my profile and work through them one at a time:\n<paste your job URLs, one per line>";

const MANUAL_COMMAND =
  'claude mcp add tailored -- "<path to your Python>" "<path to>/backend/mcp_server.py"';

export default function McpSetup() {
  const [setup, setSetup] = useState<SetupShape | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getSetup()
      .then(setSetup)
      .catch(() => setFailed(true));
  }, []);

  const command = setup?.mcp_command ?? MANUAL_COMMAND;
```

with:

```tsx
import { useEffect, useState } from "react";
import { getSetup } from "../api";
import { usePerson } from "../person";
import type { SetupShape } from "../types";
import CopyButton from "./CopyButton";

const GUIDE_STEP = "Read Tailored's workflow guide (the get_workflow_guide tool), then ";

const URL_LIST = "<paste your job URLs, one per line>";

const MANUAL_COMMAND =
  'claude mcp add tailored -- "<path to your Python>" "<path to>/backend/mcp_server.py"';

// With several people, get_master_profile() without an id errors, so the
// prompts carry the person's id. The name (not the picker label) is used:
// the id already tells two people with one name apart.
type PromptPerson = { id: number; name: string } | null;

function agentPrompt(p: PromptPerson): string {
  return p
    ? `${GUIDE_STEP}tailor a resume and cover letter for ${p.name} (profile_id ${p.id}) from <job url>.`
    : `${GUIDE_STEP}tailor my profile for <job url>.`;
}

function batchPrompt(p: PromptPerson): string {
  const whom = p ? `${p.name} (profile_id ${p.id})` : "my profile";
  return `${GUIDE_STEP}queue these jobs for ${whom} and work through them one at a time:\n${URL_LIST}`;
}

export default function McpSetup() {
  const { person, loading } = usePerson();
  const [setup, setSetup] = useState<SetupShape | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getSetup()
      .then(setSetup)
      .catch(() => setFailed(true));
  }, []);

  const command = setup?.mcp_command ?? MANUAL_COMMAND;
  const agent = agentPrompt(person);
  const batch = batchPrompt(person);
```

3b. The two prompt fields. Replace this code:

```tsx
      <div className="field">
        <label className="field-label">2. Ask your agent</label>
        <pre className="code-block mono">{AGENT_PROMPT}</pre>
        <CopyButton text={AGENT_PROMPT} label="Copy prompt" />
      </div>
      <div className="field">
        <label className="field-label">Or hand it a whole list</label>
        <pre className="code-block mono">{BATCH_PROMPT}</pre>
        <CopyButton text={BATCH_PROMPT} label="Copy batch prompt" />
        <p className="muted">
          Queueing is free and instant: every URL appears on your dashboard as a
          saved job right away, and the agent works through them one at a time. The
          queue lives in the database, so if the agent restarts it resumes where it
          stopped instead of starting over.
        </p>
      </div>
```

with:

```tsx
      {/* The prompts name the person, so they wait for the person list. */}
      {!loading && (
        <>
          <div className="field">
            <label className="field-label">2. Ask your agent</label>
            <pre className="code-block mono">{agent}</pre>
            <CopyButton text={agent} label="Copy prompt" />
          </div>
          <div className="field">
            <label className="field-label">Or hand it a whole list</label>
            <pre className="code-block mono">{batch}</pre>
            <CopyButton text={batch} label="Copy batch prompt" />
            <p className="muted">
              Queueing is free and instant: every URL appears on your dashboard as a
              saved job right away, and the agent works through them one at a time. The
              queue lives in the database, so if the agent restarts it resumes where it
              stopped instead of starting over.
            </p>
          </div>
        </>
      )}
```

Nothing else in the file changes: the register-command field, the fallback note and the missing-server alert stay as they are.

- [ ] **Step 4: Run the McpSetup tests and confirm they pass**

Run: `cd frontend && npx vitest run src/components/McpSetup.test.tsx`

Expected: PASS, `Tests  10 passed (10)`.

- [ ] **Step 5: Rewrite the Getting Started tests onto `renderWithPerson` and add the person tests**

Replace the entire contents of `frontend/src/screens/GettingStartedScreen.test.tsx` with the file below. What changes in the existing tests, and why:

- `render(<MemoryRouter><GettingStartedScreen /></MemoryRouter>)` becomes `renderWithPerson(<GettingStartedScreen />, opts)` inside `renderScreen(opts?)`; the helper supplies the `MemoryRouter`. The `MemoryRouter` and `ProfileSummary` imports and the `contact` constant go.
- Every `vi.mocked(api.listProfiles).mockResolvedValue([{ id: 1, name: "Me", contact, has_master_profile: true }]);` is removed: the helper's default person (`makePerson()`, `has_master_profile: true`) plays that part. Every `vi.mocked(api.listProfiles).mockResolvedValue([]);` becomes `renderScreen({ people: [], personId: null })`. The "in flight" test drops its never-resolving `listProfiles` mock; it stays in flight through the never-resolving `getSettings`.
- The five-field settings literals are built with a `settings(over)` helper; the values each test uses are unchanged.
- Every assertion in the seven existing tests is unchanged. `listProfiles` stays in the `../api` mock only so the new test can assert it is never called.
- `beforeEach(() => vi.clearAllMocks())` is added so call counts are per test.

```tsx
import { act, screen } from "@testing-library/react";
import GettingStartedScreen from "./GettingStartedScreen";
import * as api from "../api";
import type { SettingsShape } from "../types";
import { makePerson, renderWithPerson } from "../test-utils";
import type { PersonTestOptions } from "../test-utils";

vi.mock("../api", () => ({
  getSettings: vi.fn(),
  listProfiles: vi.fn(),
}));
vi.mock("../components/McpSetup", () => ({ default: () => <div>MCP setup block</div> }));

function settings(over: Partial<SettingsShape> = {}): SettingsShape {
  return {
    api_key_set: true,
    fake_mode: false,
    default_template: "slate",
    default_depth: "standard",
    page_size: "Letter",
    ...over,
  };
}

function renderScreen(opts?: PersonTestOptions) {
  return renderWithPerson(<GettingStartedScreen />, opts);
}

describe("GettingStartedScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the ready confirmation when a profile exists and the API key is set", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    renderScreen();
    expect(
      await screen.findByText("You're ready to tailor your first job")
    ).toBeInTheDocument();
  });

  it("prompts to create a profile and shows 'not set' when nothing is configured", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: false }));
    renderScreen({ people: [], personId: null });
    expect(await screen.findByText("Create your profile →")).toBeInTheDocument();
    expect(screen.getByText("not set")).toBeInTheDocument();
    expect(
      screen.queryByText("You're ready to tailor your first job")
    ).not.toBeInTheDocument();
  });

  it("treats demo mode with a profile as ready", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(
      settings({ api_key_set: false, fake_mode: true })
    );
    renderScreen();
    expect(
      await screen.findByText("You're ready to tailor your first job")
    ).toBeInTheDocument();
    expect(screen.getByText("Demo mode on")).toBeInTheDocument();
  });

  it("deep-links the walkthrough steps to the matching screens", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    renderScreen();
    await screen.findByText("You're ready to tailor your first job");
    expect(screen.getByRole("link", { name: "Master Profile" })).toHaveAttribute(
      "href",
      "/profiles"
    );
    expect(screen.getByRole("link", { name: "Add job URLs" })).toHaveAttribute("href", "/add");
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "templates" })).toHaveAttribute("href", "/templates");
  });

  it("points users without an Anthropic account at the console", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: false }));
    renderScreen({ people: [], personId: null });
    const link = await screen.findByRole("link", { name: /anthropic console/i });
    expect(link).toHaveAttribute("href", "https://console.anthropic.com/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("shows a neutral placeholder instead of a verdict while the requests are in flight", () => {
    vi.mocked(api.getSettings).mockReturnValue(new Promise<SettingsShape>(() => {}));
    renderScreen();
    expect(screen.getByText("Checking…")).toBeInTheDocument();
    expect(screen.queryByText("not set")).not.toBeInTheDocument();
    expect(screen.queryByText("empty")).not.toBeInTheDocument();
    expect(screen.queryByText("Create your profile →")).not.toBeInTheDocument();
    expect(
      screen.queryByText("You're ready to tailor your first job")
    ).not.toBeInTheDocument();
  });

  it("surfaces an error instead of a false verdict when a setup request fails", async () => {
    vi.mocked(api.getSettings).mockRejectedValue(new Error("network down"));
    renderScreen({ people: [], personId: null });
    expect(await screen.findByText(/Couldn't check your setup/)).toBeInTheDocument();
    expect(screen.queryByText("not set")).not.toBeInTheDocument();
    expect(screen.queryByText("empty")).not.toBeInTheDocument();
    expect(screen.queryByText("Create your profile →")).not.toBeInTheDocument();
    expect(
      screen.queryByText("You're ready to tailor your first job")
    ).not.toBeInTheDocument();
  });

  it("reads the person list from the picker, never from listProfiles", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen();
    await screen.findByText("You're ready to tailor your first job");
    expect(api.listProfiles).not.toHaveBeenCalled();
  });

  it("judges the current person's profile, not whether anyone has one", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    renderScreen({
      people: [
        makePerson({ id: 1, name: "Jordan Rivera", has_master_profile: true }),
        makePerson({ id: 2, name: "Sam Lee", has_master_profile: false }),
      ],
      personId: 2,
    });
    expect(await screen.findByText("Master Profile for Sam Lee:")).toBeInTheDocument();
    expect(screen.getByText("empty")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create your profile →" })).toHaveAttribute(
      "href",
      "/profiles"
    );
    expect(
      screen.queryByText("You're ready to tailor your first job")
    ).not.toBeInTheDocument();
  });

  it("changes its verdict when the picker switches person", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    const { switchTo } = renderScreen({
      people: [
        makePerson({ id: 1, name: "Jordan Rivera", has_master_profile: true }),
        makePerson({ id: 2, name: "Sam Lee", has_master_profile: false }),
      ],
      personId: 2,
    });
    await screen.findByText("empty");
    act(() => {
      switchTo(1);
    });
    expect(screen.getByText("Master Profile for Jordan Rivera:")).toBeInTheDocument();
    expect(screen.getByText("created")).toBeInTheDocument();
    expect(screen.getByText("You're ready to tailor your first job")).toBeInTheDocument();
    // The app-wide API key status does not depend on the person: one request only.
    expect(api.getSettings).toHaveBeenCalledTimes(1);
  });

  it("names the person with the picker's label", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({
      people: [makePerson({ id: 4, name: "Sam Lee" })],
      overrides: { labelFor: (p) => `${p.name} #${p.id}` },
    });
    expect(await screen.findByText("Master Profile for Sam Lee #4:")).toBeInTheDocument();
  });

  it("gives no verdict while the person list is still loading", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    renderScreen({ people: [], personId: null, loading: true });
    // Let the resolved settings request land; the verdict must still wait.
    await act(async () => {
      await Promise.resolve();
    });
    expect(api.getSettings).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Checking…")).toBeInTheDocument();
    expect(screen.queryByText("empty")).not.toBeInTheDocument();
    expect(screen.queryByText("Create your profile →")).not.toBeInTheDocument();
  });

  it("surfaces a failed person list instead of calling the profile empty", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    renderScreen({
      people: [],
      personId: null,
      overrides: { error: "API 500: Internal Server Error" },
    });
    expect(
      await screen.findByText(/Couldn't check your setup.*API 500: Internal Server Error/)
    ).toBeInTheDocument();
    expect(screen.queryByText("empty")).not.toBeInTheDocument();
    expect(screen.queryByText("Create your profile →")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run the Getting Started tests and confirm they fail**

Run: `cd frontend && npx vitest run src/screens/GettingStartedScreen.test.tsx`

Expected: FAIL, `Tests  9 failed | 4 passed (13)`. The old screen ignores the person context and still calls `listProfiles()`, which the mock now answers with `undefined`, so it always reports the profile as `empty`. Every test expecting "You're ready to tailor your first job" or "Master Profile for ...:" fails; "reads the person list from the picker, never from listProfiles" fails; "gives no verdict while the person list is still loading" and "surfaces a failed person list instead of calling the profile empty" fail because the old screen shows a verdict. The four tests whose expectations are the same with or without a person ("prompts to create a profile...", "points users without an Anthropic account...", "shows a neutral placeholder...", "surfaces an error ... when a setup request fails") already pass.

- [ ] **Step 7: Make Getting Started judge the current person**

Both edits are in `frontend/src/screens/GettingStartedScreen.tsx`.

7a. Imports, state, the settings effect and the derived flags. Replace this code:

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getSettings, listProfiles } from "../api";
import type { ProfileSummary, SettingsShape } from "../types";
import CopyButton from "../components/CopyButton";
import McpSetup from "../components/McpSetup";

const ENV_LINE = "ANTHROPIC_API_KEY=sk-ant-...";

export default function GettingStartedScreen() {
  const [settings, setSettings] = useState<SettingsShape | null>(null);
  const [profiles, setProfiles] = useState<ProfileSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getSettings(), listProfiles()])
      .then(([s, p]) => {
        if (!alive) return;
        setSettings(s);
        setProfiles(p);
      })
      .catch((e) => {
        if (alive) setError(String(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  // Until both requests land we know nothing — never report "empty"/"not set" from that.
  const loaded = settings !== null && profiles !== null;
  const hasProfile = (profiles ?? []).some((p) => p.has_master_profile);
  const canGenerateWebApp = Boolean(settings?.api_key_set || settings?.fake_mode);
```

with:

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getSettings } from "../api";
import { usePerson } from "../person";
import type { SettingsShape } from "../types";
import CopyButton from "../components/CopyButton";
import McpSetup from "../components/McpSetup";

const ENV_LINE = "ANTHROPIC_API_KEY=sk-ant-...";

export default function GettingStartedScreen() {
  const { person, loading: peopleLoading, error: peopleError, labelFor } = usePerson();
  const [settings, setSettings] = useState<SettingsShape | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Only the app-wide fields (api_key_set, fake_mode) are read here, so the
  // request carries no person and is not repeated on a switch.
  useEffect(() => {
    let alive = true;
    getSettings()
      .then((s) => {
        if (alive) setSettings(s);
      })
      .catch((e) => {
        if (alive) setError(String(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  // Until the settings and the person list have both landed we know nothing,
  // so never report "empty" or "not set" from that.
  const shownError = error ?? peopleError;
  const loaded = settings !== null && !peopleLoading;
  const hasProfile = Boolean(person?.has_master_profile);
  const canGenerateWebApp = Boolean(settings?.api_key_set || settings?.fake_mode);
```

7b. The error line and the Master Profile line in "Your setup at a glance". Replace this code:

```tsx
        {error ? (
          <div className="alert alert-error">Couldn't check your setup — {error}</div>
        ) : !loaded ? (
          <p className="muted">Checking…</p>
        ) : (
          <>
            <p>
              Master Profile:{" "}
```

with:

```tsx
        {shownError ? (
          <div className="alert alert-error">Couldn't check your setup: {shownError}</div>
        ) : !loaded ? (
          <p className="muted">Checking…</p>
        ) : (
          <>
            <p>
              Master Profile{person ? ` for ${labelFor(person)}` : ""}:{" "}
```

Nothing else in the file changes: the `created` / `empty` pills, the `Create your profile →` link to `/profiles`, the API key line, the ready pill and the rest of the page stay as they are, and `<McpSetup />` is still rendered with no props.

- [ ] **Step 8: Run the Getting Started tests, then the whole frontend suite**

Run: `cd frontend && npx vitest run src/screens/GettingStartedScreen.test.tsx`

Expected: PASS, `Tests  13 passed (13)`.

Run: `cd frontend && npm test`

Expected: PASS. `SettingsScreen.test.tsx` and `GettingStartedScreen.test.tsx` mock `../components/McpSetup`, and `App.test.tsx` renders `/` only, so no other test renders the real McpSetup.

- [ ] **Step 9: Rebuild the bundle and check it**

Run: `cd frontend && npm run build`

Expected: `tsc` reports no errors (it type-checks the test files too), Vite writes `frontend/dist`, and the last line is `stamp-build: recorded <N> build inputs`.

Run (from the repo root): `.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q`

Expected: PASS.

- [ ] **Step 10: Commit**

Run (from the repo root):

```bash
git add frontend/src/components/McpSetup.tsx frontend/src/components/McpSetup.test.tsx frontend/src/screens/GettingStartedScreen.tsx frontend/src/screens/GettingStartedScreen.test.tsx frontend/dist
git commit -m "$(cat <<'EOF'
feat: name the current person in Getting Started and the MCP prompts

Getting Started judges "Master Profile" by the current person's
has_master_profile instead of whether anyone has one, reads the person
from PersonContext rather than calling listProfiles, and waits for the
person list before giving a verdict. McpSetup reads the current person
itself, so on both Getting Started and Settings the copyable prompts say
"for {name} (profile_id {id})" and follow the picker. With no people
they keep "my profile"; while the list loads they are not shown.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
git status --short
```

Expected: `git status --short` prints nothing (a dirty `frontend/dist` means the rebuild was not added).


---

### Task 18: Settings and Templates edit the current person's settings

**Files:**
- Create: `frontend/src/personSettings.ts`
- Modify: `frontend/src/screens/SettingsScreen.tsx` (whole file replaced: the settings state moves into the new hook, and the page is regrouped into a person section and an app-wide section)
- Modify: `frontend/src/screens/TemplatesScreen.tsx` (imports; `TemplateCard` props and its button; the `TemplatesScreen` component)
- Modify: `frontend/src/screens/SettingsScreen.test.tsx` (whole file rewritten onto `renderWithPerson`; new describe block)
- Modify: `frontend/src/screens/TemplatesScreen.test.tsx` (whole file rewritten onto `renderWithPerson`; new describe block)
- Rebuild: `frontend/dist` (committed)
- Test: `frontend/src/screens/SettingsScreen.test.tsx`, `frontend/src/screens/TemplatesScreen.test.tsx`

**Interfaces:**
- Consumes: `usePerson()` from `frontend/src/person.tsx` (Task 11), reading `person`, `loading`, `error` and `labelFor(p)`. `getSettings(profileId?: number): Promise<SettingsShape>` and `updateSettings(patch, profileId?: number): Promise<SettingsShape>` from `frontend/src/api.ts` (Task 10; both add `?profile_id=N` when the id is given and behave as today when it is `undefined`). `makePerson`, `renderWithPerson` and the `PersonTestOptions` type from `frontend/src/test-utils.tsx` (Task 11). `McpSetup` (Task 17), which the Settings test keeps mocking. Existing `listTemplates()` and `templatePreviewUrl(name)`.
- Produces, in the new `frontend/src/personSettings.ts` (nothing later in the plan relies on it):
  ```ts
  export interface SettingsPatch { default_template?: TemplateName; default_depth?: Depth; page_size?: PageSize }
  export interface PersonSettings {
    settings: SettingsShape | null;  // the current person's effective values; null until they arrive, and again right after a switch
    error: string | null;            // the person-list error, or a failed read or write for the current person
    save(patch: SettingsPatch): Promise<void>;  // writes for whoever is current at the call; never throws
  }
  export function usePersonSettings(): PersonSettings;
  ```
- Choices made here (the contract leaves them open):
  - **One hook for both screens.** Settings and Templates need the same rules: fetch keyed on the person, drop a late response, write with the id captured at the call. `usePersonSettings()` holds them once. Add Jobs (Task 14) keeps its own fetch; it is not changed here.
  - Whose settings: with a person, `getSettings(person.id)` / `updateSettings(patch, person.id)`. With no people (`!loading && !error && person === null`), `getSettings(undefined)` / `updateSettings(patch, undefined)`: the app-wide defaults, as today. While `loading`, or when the person list failed (`error`), nothing is requested and the screen shows the loading line or that error. This follows spec §4.1: the app-wide settings must not flash while the list loads or when the API is down.
  - A result is kept together with the id it was fetched for, and shown only while that id is still the current person. On a switch the previous person's values disappear at once (Settings shows `Loading...`; Templates shows no Default badge), and a read or a save that settles after the switch is dropped.
  - Settings page layout: `<h1>Settings</h1>`, then, only with a person, `<section aria-labelledby>` headed `<h2>Settings for {labelFor(person)}</h2>` with a one-paragraph note and the Defaults card. Then `<section>` headed `<h2>App-wide</h2>` with the API key, How generation works (including `<McpSetup />`) and Appearance cards. With no people the Defaults card sits inside App-wide between How generation works and Appearance, which is today's order. The depth, page-size and theme selects get `id`/`htmlFor` (`default-depth`, `page-size`, `theme-pref`) like the existing `default-template`, so their labels name them.
  - Templates page: with a person, `<h2>Settings for {labelFor(person)}</h2>` plus one muted line between the intro and the grid. `TemplateCard` gains `disabled: boolean`, and "Set as default" is disabled until the current person's settings have loaded, the same rule Add Jobs uses for submit. With no people there is no heading and the button writes the app-wide default, as today.
  - All existing copy is kept as it is; the new strings are the two headings, the `App-wide` heading and three muted notes.
- Order and overlap: no earlier task edits these five files. `App.test.tsx` needs no change: the screens call no api export that its mock lacks, and it renders `/` only. The working tree uses CRLF line endings (`core.autocrlf=true`); make the edits with an editor or the Edit tool, which match the code below regardless.

- [ ] **Step 1: Rewrite the Settings tests onto `renderWithPerson` and add the per-person tests**

Replace the entire contents of `frontend/src/screens/SettingsScreen.test.tsx` with the file below. What changes in the existing tests, and why:

- `render(<MemoryRouter><SettingsScreen /></MemoryRouter>)` becomes `renderWithPerson(<SettingsScreen />, opts)` inside `renderScreen(opts?)`: the screen now reads `usePerson()`. The default person is `makePerson()`, Jordan Rivera, id 1. The `MemoryRouter` import goes.
- The first `beforeEach` gains `vi.clearAllMocks()`, so the new tests' call assertions see only their own calls.
- Every assertion in the eight existing tests is unchanged. "saves the selected template id, not its label" still checks only the patch (`calls[calls.length - 1]?.[0]`); the id is asserted by the new per-person tests.
- `switchTo` is wrapped in `act` so the re-render is flushed before the next assertion, whichever way Task 11 implements it.

```tsx
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import SettingsScreen from "./SettingsScreen";
import * as api from "../api";
import type { SettingsShape } from "../types";
import { makePerson, renderWithPerson } from "../test-utils";
import type { PersonTestOptions } from "../test-utils";

vi.mock("../api", () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  listTemplates: vi.fn(),
}));

vi.mock("../components/McpSetup", () => ({ default: () => <div>MCP setup block</div> }));

function renderScreen(opts?: PersonTestOptions) {
  return renderWithPerson(<SettingsScreen />, opts);
}

function settings(over: Partial<SettingsShape> = {}): SettingsShape {
  return {
    api_key_set: true,
    fake_mode: false,
    default_template: "slate",
    default_depth: "standard",
    page_size: "Letter",
    ...over,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const JORDAN = makePerson({ id: 1, name: "Jordan Rivera" });
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
});

describe("SettingsScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "slate", label: "Slate", description: "d", best_for: "b" },
    ]);
  });

  it("renders the 'not set' warning pill and note when no API key is configured", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: false,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    renderScreen();
    expect(await screen.findByText("API key: not set")).toBeInTheDocument();
    expect(
      screen.getByText(/Add ANTHROPIC_API_KEY to the .env file and restart/)
    ).toBeInTheDocument();
    expect(screen.queryByText("API key: set")).not.toBeInTheDocument();
  });

  it("renders the 'set' pill with no not-set warning when an API key is configured", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    renderScreen();
    expect(await screen.findByText("API key: set")).toBeInTheDocument();
    expect(screen.queryByText("API key: not set")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Add ANTHROPIC_API_KEY to the .env file and restart to generate/)
    ).not.toBeInTheDocument();
  });

  it("shows the 'How generation works' section with both web-app and MCP blocks", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    renderScreen();
    expect(await screen.findByText("How generation works")).toBeInTheDocument();
    expect(screen.getByText("Web app (this browser)")).toBeInTheDocument();
    expect(screen.getByText("Your own AI agent (MCP)")).toBeInTheDocument();
  });

  it("embeds the MCP setup block in the generation section", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    renderScreen();
    expect(await screen.findByText("MCP setup block")).toBeInTheDocument();
  });

  it("renders template options from the API, not a hardcoded list", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "meridian",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
      { name: "plainwork", label: "Plainwork", description: "d", best_for: "b" },
    ]);
    renderScreen();
    const select = await screen.findByLabelText(/default template/i);
    expect(within(select).getByRole("option", { name: "Ledger" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "Plainwork" })).toBeInTheDocument();
  });

  it("shows template labels rather than raw ids", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "meridian",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
    ]);
    renderScreen();
    const select = await screen.findByLabelText(/default template/i);
    expect(within(select).getByRole("option", { name: "Meridian" })).toBeInTheDocument();
    expect(within(select).queryByRole("option", { name: "meridian" })).toBeNull();
  });

  // The label is display, the name is the contract the backend validates against
  // (api/settings.py rejects anything not in the registry). Options that render the
  // label but carry the label as their value would look right and write garbage.
  it("carries the template id as the option value while showing the label", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "meridian",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
    ]);
    renderScreen();
    const select = (await screen.findByLabelText(/default template/i)) as HTMLSelectElement;
    const ledger = within(select).getByRole("option", { name: "Ledger" }) as HTMLOptionElement;
    expect(ledger.value).toBe("ledger");
    // the saved id must resolve to a real option, or the select shows the wrong entry
    expect(select.value).toBe("meridian");
  });

  it("saves the selected template id, not its label", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "meridian",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.updateSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "ledger",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
    ]);
    renderScreen();
    const select = await screen.findByLabelText(/default template/i);
    fireEvent.change(select, { target: { value: "ledger" } });

    await waitFor(() => {
      const calls = vi.mocked(api.updateSettings).mock.calls;
      expect(calls[calls.length - 1]?.[0]).toEqual({ default_template: "ledger" });
    });
  });
});

describe("SettingsScreen per person", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "slate", label: "Slate", description: "d", best_for: "b" },
    ]);
  });

  it("reads and writes the current person's settings under their name", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ page_size: "A4" }));
    vi.mocked(api.updateSettings).mockResolvedValue(settings({ page_size: "Letter" }));
    renderScreen({ people: [SAM] });

    expect(await screen.findByRole("heading", { name: "Settings for Sam Lee" })).toBeInTheDocument();
    expect(api.getSettings).toHaveBeenCalledWith(2);
    const pageSize = screen.getByLabelText("Page size") as HTMLSelectElement;
    expect(pageSize.value).toBe("A4");

    fireEvent.change(pageSize, { target: { value: "Letter" } });
    await waitFor(() =>
      expect(api.updateSettings).toHaveBeenCalledWith({ page_size: "Letter" }, 2)
    );
    await waitFor(() => expect(pageSize.value).toBe("Letter"));
  });

  it("heads the section with the picker's label", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({
      people: [SAM],
      overrides: { labelFor: (p) => `${p.name} (${p.contact.email})` },
    });
    expect(
      await screen.findByRole("heading", { name: "Settings for Sam Lee (sam@example.com)" })
    ).toBeInTheDocument();
  });

  it("keeps the API key status and theme in an app-wide section", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    renderScreen({ people: [JORDAN] });

    const mine = await screen.findByRole("region", { name: "Settings for Jordan Rivera" });
    const appWide = screen.getByRole("region", { name: "App-wide" });

    expect(within(mine).getByLabelText(/default template/i)).toBeInTheDocument();
    expect(within(mine).getByLabelText("Default research depth")).toBeInTheDocument();
    expect(within(mine).getByLabelText("Page size")).toBeInTheDocument();
    expect(within(mine).queryByText("API key set")).not.toBeInTheDocument();

    expect(within(appWide).getByText("API key set")).toBeInTheDocument();
    expect(within(appWide).getByLabelText("Theme")).toBeInTheDocument();
    expect(within(appWide).queryByLabelText(/default template/i)).not.toBeInTheDocument();
  });

  it("hides the previous person's values the moment the person changes", async () => {
    const forSam = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((id?: number) =>
      id === 1 ? Promise.resolve(settings({ page_size: "Letter" })) : forSam.promise
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });
    expect(await screen.findByRole("heading", { name: "Settings for Jordan Rivera" })).toBeInTheDocument();

    act(() => {

      switchTo(2);

    });
    expect(api.getSettings).toHaveBeenLastCalledWith(2);
    // Jordan's values must not sit under Sam's name while Sam's load.
    expect(screen.queryByLabelText("Page size")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Settings for Jordan Rivera" })).toBeNull();
    expect(screen.getByText("Loading...")).toBeInTheDocument();

    await act(async () => {
      forSam.resolve(settings({ page_size: "A4" }));
    });
    expect(screen.getByRole("heading", { name: "Settings for Sam Lee" })).toBeInTheDocument();
    expect((screen.getByLabelText("Page size") as HTMLSelectElement).value).toBe("A4");
  });

  it("ignores a late response for the previous person", async () => {
    const forJordan = deferred<SettingsShape>();
    const forSam = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((id?: number) =>
      id === 1 ? forJordan.promise : forSam.promise
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });

    act(() => {

      switchTo(2);

    });
    await act(async () => {
      forSam.resolve(settings({ page_size: "A4", default_depth: "deep" }));
    });
    expect(screen.getByRole("heading", { name: "Settings for Sam Lee" })).toBeInTheDocument();
    expect((screen.getByLabelText("Page size") as HTMLSelectElement).value).toBe("A4");

    // Jordan's request was still in flight; its answer must not land on Sam.
    await act(async () => {
      forJordan.resolve(settings({ page_size: "Letter", default_depth: "quick" }));
    });
    expect((screen.getByLabelText("Page size") as HTMLSelectElement).value).toBe("A4");
    expect((screen.getByLabelText("Default research depth") as HTMLSelectElement).value).toBe(
      "deep"
    );
    expect(screen.queryByRole("heading", { name: "Settings for Jordan Rivera" })).toBeNull();
  });

  it("does not show a save that returns after a switch on the new person", async () => {
    vi.mocked(api.getSettings).mockImplementation(async (id?: number) =>
      id === 1 ? settings({ page_size: "Letter" }) : settings({ page_size: "A4" })
    );
    const saving = deferred<SettingsShape>();
    vi.mocked(api.updateSettings).mockReturnValue(saving.promise);
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });

    const pageSize = await screen.findByLabelText("Page size");
    fireEvent.change(pageSize, { target: { value: "A4" } });
    expect(api.updateSettings).toHaveBeenCalledWith({ page_size: "A4" }, 1);

    act(() => {

      switchTo(2);

    });
    await screen.findByRole("heading", { name: "Settings for Sam Lee" });
    await act(async () => {
      saving.resolve(settings({ page_size: "A4", default_depth: "quick" }));
    });
    expect(screen.getByRole("heading", { name: "Settings for Sam Lee" })).toBeInTheDocument();
    expect((screen.getByLabelText("Default research depth") as HTMLSelectElement).value).toBe(
      "standard"
    );
  });

  it("edits the app-wide defaults when there are no people", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    vi.mocked(api.updateSettings).mockResolvedValue(settings({ default_depth: "deep" }));
    renderScreen({ people: [], personId: null });

    const depth = await screen.findByLabelText("Default research depth");
    expect(vi.mocked(api.getSettings).mock.calls[0][0]).toBeUndefined();
    expect(screen.queryByRole("heading", { name: /^Settings for/ })).not.toBeInTheDocument();
    // With no people the defaults are app-wide, so they sit in that section.
    expect(
      within(screen.getByRole("region", { name: "App-wide" })).getByLabelText(/default template/i)
    ).toBeInTheDocument();

    fireEvent.change(depth, { target: { value: "deep" } });
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1));
    const [patch, profileId] = vi.mocked(api.updateSettings).mock.calls[0];
    expect(patch).toEqual({ default_depth: "deep" });
    expect(profileId).toBeUndefined();
  });

  it("requests nothing while the person list is loading", () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({ people: [], personId: null, loading: true });
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(api.getSettings).not.toHaveBeenCalled();
  });

  it("shows a failed person list instead of the app-wide defaults", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({
      people: [],
      personId: null,
      overrides: { error: "API 500: Internal Server Error" },
    });
    expect(await screen.findByText("API 500: Internal Server Error")).toBeInTheDocument();
    expect(api.getSettings).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(/default template/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the Settings tests and confirm they fail**

Run: `cd frontend && npx vitest run src/screens/SettingsScreen.test.tsx`

Expected: FAIL, `Tests  9 failed | 8 passed (17)`. The eight existing tests pass. All nine in "SettingsScreen per person" fail: the old screen calls `getSettings()` with no id, has no `Settings for ...` or `App-wide` headings, cannot be found by the `Page size` / `Default research depth` / `Theme` labels (they are not linked to their selects), and requests settings even while the person list is loading or has failed.

- [ ] **Step 3: Create the shared hook**

Create `frontend/src/personSettings.ts`:

```ts
import { useEffect, useRef, useState } from "react";
import { getSettings, updateSettings } from "./api";
import { usePerson } from "./person";
import type { Depth, PageSize, SettingsShape, TemplateName } from "./types";

export interface SettingsPatch {
  default_template?: TemplateName;
  default_depth?: Depth;
  page_size?: PageSize;
}

// Whose settings are being edited: a person's id, null for the app-wide
// defaults (only when there are no people), or undefined while that is not
// known (the person list is loading or failed to load).
type Target = number | null | undefined;

interface Loaded {
  target: number | null;
  settings: SettingsShape | null;
  error: string | null;
}

export interface PersonSettings {
  /** The current person's effective settings; null until they arrive, and again right after a switch. */
  settings: SettingsShape | null;
  /** The person-list error, or a failed read or write for the current person. */
  error: string | null;
  /** Writes a change for whoever is current at the moment of the call. Never throws. */
  save(patch: SettingsPatch): Promise<void>;
}

/**
 * The settings the Settings and Templates screens edit: the current person's
 * own values when there is a person, the app-wide defaults when there are no
 * people. Nothing is requested while the person list is loading or failed.
 * A read or write that settles after the person changed is dropped, so one
 * person's values are never shown, or saved back, under another person's name.
 */
export function usePersonSettings(): PersonSettings {
  const { person, loading, error: peopleError } = usePerson();
  const target: Target = loading || peopleError ? undefined : person ? person.id : null;
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const targetRef = useRef<Target>(target);
  targetRef.current = target;

  useEffect(() => {
    if (target === undefined) return;
    let alive = true;
    getSettings(target ?? undefined)
      .then((s) => {
        if (alive) setLoaded({ target, settings: s, error: null });
      })
      .catch((e) => {
        if (alive) setLoaded({ target, settings: null, error: String(e) });
      });
    return () => {
      alive = false;
    };
  }, [target]);

  async function save(patch: SettingsPatch): Promise<void> {
    const at = targetRef.current;
    if (at === undefined) return;
    setLoaded((prev) => (prev && prev.target === at ? { ...prev, error: null } : prev));
    try {
      const s = await updateSettings(patch, at ?? undefined);
      if (targetRef.current !== at) return;
      setLoaded({ target: at, settings: s, error: null });
    } catch (err) {
      if (targetRef.current !== at) return;
      setLoaded((prev) =>
        prev && prev.target === at
          ? { ...prev, error: String(err) }
          : { target: at, settings: null, error: String(err) }
      );
    }
  }

  const mine = target !== undefined && loaded?.target === target ? loaded : null;
  return {
    settings: mine?.settings ?? null,
    error: peopleError ?? mine?.error ?? null,
    save,
  };
}
```

- [ ] **Step 4: Move the Settings screen onto the hook and regroup the page**

Replace the entire contents of `frontend/src/screens/SettingsScreen.tsx` with the file below. Compared with the current file: the `settings` / `error` state, the `getSettings()` effect and the body of `patch` are replaced by `usePersonSettings()`; the Defaults card moves into a `defaultsCard` constant, shown in the person section when there is a person and inside App-wide when there is not; the API key, How generation works and Appearance cards move, unchanged apart from the theme select's new `id`/`htmlFor`, into the App-wide section; the depth and page-size selects gain `id`/`htmlFor`. Every other string is as it is today.

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listTemplates } from "../api";
import McpSetup from "../components/McpSetup";
import { usePerson } from "../person";
import { usePersonSettings } from "../personSettings";
import type { SettingsPatch } from "../personSettings";
import { getThemePref, setThemePref, subscribeTheme } from "../theme";
import type { ThemePref } from "../theme";
import type { Depth, PageSize, TemplateInfo, TemplateName } from "../types";

const DEPTHS: Depth[] = ["quick", "standard", "deep"];
const PAGE_SIZES: PageSize[] = ["Letter", "A4"];
const THEME_PREFS: ThemePref[] = ["system", "light", "dark"];
const THEME_LABELS: Record<ThemePref, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

export default function SettingsScreen() {
  const { person, labelFor } = usePerson();
  const { settings, error, save } = usePersonSettings();
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [themePref, setThemePrefState] = useState<ThemePref>(() => getThemePref());

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => subscribeTheme((pref) => setThemePrefState(pref)), []);

  function patch(p: SettingsPatch) {
    void save(p);
  }

  function handleThemeChange(pref: ThemePref) {
    setThemePref(pref);
  }

  if (!settings) {
    return (
      <div>
        <h1>Settings</h1>
        {error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading...</p>}
      </div>
    );
  }

  const defaultsCard = (
    <div className="card">
      <div className="card-title">Defaults</div>
      <div className="field" style={{ maxWidth: "20rem" }}>
        <label className="field-label" htmlFor="default-template">
          Default template
        </label>
        <select
          id="default-template"
          className="select"
          value={settings.default_template}
          onChange={(e) => patch({ default_template: e.target.value as TemplateName })}
        >
          {templates.map((t) => (
            <option key={t.name} value={t.name}>
              {t.label || t.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field" style={{ maxWidth: "20rem" }}>
        <label className="field-label" htmlFor="default-depth">
          Default research depth
        </label>
        <select
          id="default-depth"
          className="select"
          value={settings.default_depth}
          onChange={(e) => patch({ default_depth: e.target.value as Depth })}
        >
          {DEPTHS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </div>
      <div className="field" style={{ maxWidth: "20rem" }}>
        <label className="field-label" htmlFor="page-size">
          Page size
        </label>
        <select
          id="page-size"
          className="select"
          value={settings.page_size}
          onChange={(e) => patch({ page_size: e.target.value as PageSize })}
        >
          {PAGE_SIZES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
    </div>
  );

  return (
    <div>
      <h1>Settings</h1>
      {error && <div className="alert alert-error">{error}</div>}

      {person && (
        <section aria-labelledby="person-settings-heading">
          <h2 id="person-settings-heading">Settings for {labelFor(person)}</h2>
          <p className="muted">
            The default template and research depth apply to jobs added for {labelFor(person)} on
            the Add Jobs page. The page size applies to every document rendered for{" "}
            {labelFor(person)}, including ones an agent makes over MCP.
          </p>
          {defaultsCard}
        </section>
      )}

      <section aria-labelledby="app-wide-heading">
        <h2 id="app-wide-heading">App-wide</h2>
        <p className="muted">
          The API key, demo mode and theme do not change with the selected person.
        </p>

        <div className="card">
          <div className="card-title">Anthropic API key</div>
          <p>
            {settings.api_key_set ? (
              <span className="pill pill-ok">API key set</span>
            ) : (
              <span className="pill pill-warn">API key not set</span>
            )}
          </p>
          <p className="muted">
            The key is read from the ANTHROPIC_API_KEY variable in the .env file next to run.py.
            Add or change it there and restart the app — it is never stored in the database.
          </p>
          {settings.fake_mode ? (
            <div className="callout">
              Demo mode is active (TAILORED_FAKE=1): all generation uses offline canned fixtures and
              no API calls are made.
            </div>
          ) : (
            <p className="muted">
              Demo mode is off. Set TAILORED_FAKE=1 in the .env file next to run.py and restart to
              explore the app fully offline with no API key.
            </p>
          )}
        </div>

        <div className="card">
          <div className="card-title">How generation works</div>
          <div className="field">
            <label className="field-label">Web app (this browser)</label>
            <p className="muted">
              Applications you create on the Add Jobs page are generated with the Anthropic API,
              billed to your API key.
            </p>
            <p>
              {settings.api_key_set ? (
                <span className="pill pill-ok">API key: set</span>
              ) : (
                <span className="pill pill-warn">API key: not set</span>
              )}
              {settings.fake_mode && <span className="pill" style={{ marginLeft: "0.4rem" }}>Demo mode</span>}
            </p>
            {!settings.api_key_set && (
              <p className="muted">
                Add ANTHROPIC_API_KEY to the .env file and restart to generate from the web app.
              </p>
            )}
            {settings.fake_mode && (
              <p className="muted">Sample data only — no API calls, no key needed.</p>
            )}
          </div>
          <div className="field">
            <label className="field-label">Your own AI agent (MCP)</label>
            <p className="muted">
              Connect Tailored to Claude Code (or any MCP-capable agent) and it does the work on your own
              subscription — no API key used. These applications show a depth of "external" on the
              dashboard, and the same truthfulness guard applies.
            </p>
            <McpSetup />
            <p className="muted">
              New here? The <Link to="/getting-started">Getting Started</Link> page walks through all three
              ways to power Tailored.
            </p>
          </div>
        </div>

        {!person && defaultsCard}

        <div className="card">
          <div className="card-title">Appearance</div>
          <div className="field" style={{ maxWidth: "20rem" }}>
            <label className="field-label" htmlFor="theme-pref">
              Theme
            </label>
            <select
              id="theme-pref"
              className="select"
              value={themePref}
              onChange={(e) => handleThemeChange(e.target.value as ThemePref)}
            >
              {THEME_PREFS.map((p) => (
                <option key={p} value={p}>
                  {THEME_LABELS[p]}
                </option>
              ))}
            </select>
          </div>
          <p className="muted">
            Stored on this device only — "System" follows your OS light/dark setting.
          </p>
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 5: Run the Settings tests and confirm they pass**

Run: `cd frontend && npx vitest run src/screens/SettingsScreen.test.tsx`

Expected: PASS, `Tests  17 passed (17)`.

- [ ] **Step 6: Rewrite the Templates tests onto `renderWithPerson` and add the per-person tests**

Replace the entire contents of `frontend/src/screens/TemplatesScreen.test.tsx` with the file below. What changes in the existing tests, and why:

- `render(<MemoryRouter><TemplatesScreen /></MemoryRouter>)` becomes `renderWithPerson(<TemplatesScreen />, opts)` inside `renderScreen(opts?)`. The default person is Jordan Rivera, id 1. The `MemoryRouter` import goes. The first `beforeEach` gains `vi.clearAllMocks()`.
- "renders four cards and exactly one Default pill". Old: `expect(screen.getAllByText("Default")).toHaveLength(1);` New: `await waitFor(() => expect(screen.getAllByText("Default")).toHaveLength(1));` The settings now arrive through the hook, a separate effect from the template list, so the badge can land a tick after the cards.
- "clicking Set as default on another card calls updateSettings with that name". Old: `await screen.findByText("Meridian");` then `expect(api.updateSettings).toHaveBeenCalledWith({ default_template: "meridian" });` New: `await screen.findByText("Default");` then `expect(api.updateSettings).toHaveBeenCalledWith({ default_template: "meridian" }, 1);` The buttons stay disabled until the person's settings have loaded, so the test waits for the badge; the write now carries the current person's id.
- The thumbnail test is unchanged.

```tsx
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import TemplatesScreen from "./TemplatesScreen";
import * as api from "../api";
import type { SettingsShape } from "../types";
import { makePerson, renderWithPerson } from "../test-utils";
import type { PersonTestOptions } from "../test-utils";

vi.mock("../api", () => ({
  listTemplates: vi.fn(),
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  templatePreviewUrl: (name: string) => `/api/templates/preview/${name}`,
}));

const TEMPLATES = [
  {
    name: "meridian",
    label: "Meridian",
    description: "Classic serif with small caps and hairline rules - understated and traditional.",
    best_for: "Corporate, finance, healthcare, government",
  },
  {
    name: "slate",
    label: "Slate",
    description: "Clean contemporary sans-serif with strong hierarchy - the default.",
    best_for: "General purpose - safe everywhere",
  },
  {
    name: "terminal",
    label: "Terminal",
    description: "Technical layout with monospace accents and projects placed forward.",
    best_for: "Engineering, data, technical roles",
  },
  {
    name: "signal",
    label: "Signal",
    description: "Bold headline treatment with a single warm accent color.",
    best_for: "Design, marketing, creative roles",
  },
] as const;

function settings(over: Partial<SettingsShape> = {}): SettingsShape {
  return {
    api_key_set: true,
    fake_mode: false,
    default_template: "slate",
    default_depth: "standard",
    page_size: "Letter",
    ...over,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

// The card whose title is this template's label.
function card(label: string): HTMLElement {
  return screen.getByText(label, { selector: ".card-title" }).closest(".template-card") as HTMLElement;
}

const JORDAN = makePerson({ id: 1, name: "Jordan Rivera" });
const SAM = makePerson({ id: 2, name: "Sam Lee" });

function renderScreen(opts?: PersonTestOptions) {
  return renderWithPerson(<TemplatesScreen />, opts);
}

describe("TemplatesScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listTemplates).mockResolvedValue([...TEMPLATES]);
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.updateSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "meridian",
      default_depth: "standard",
      page_size: "Letter",
    });
  });

  it("renders four cards and exactly one Default pill", async () => {
    renderScreen();
    expect(await screen.findByText("Meridian")).toBeInTheDocument();
    expect(screen.getByText("Slate")).toBeInTheDocument();
    expect(screen.getByText("Terminal")).toBeInTheDocument();
    expect(screen.getByText("Signal")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("Default")).toHaveLength(1));
  });

  it("clicking Set as default on another card calls updateSettings with that name", async () => {
    renderScreen();
    await screen.findByText("Default");
    fireEvent.click(screen.getAllByText("Set as default")[0]);
    expect(api.updateSettings).toHaveBeenCalledWith({ default_template: "meridian" }, 1);
  });

  it("renders each preview as a true-page-width thumbnail with an open-full-size link", async () => {
    const { container } = renderScreen();
    await screen.findByText("Meridian");

    const thumbs = container.querySelectorAll(".preview-thumb");
    expect(thumbs).toHaveLength(4);

    const links = screen.getAllByRole("link", { name: /open full size/i });
    expect(links).toHaveLength(4);

    TEMPLATES.forEach((t, i) => {
      const iframe = screen.getByTitle(t.label) as HTMLIFrameElement;
      expect(iframe.closest(".preview-thumb")).not.toBeNull();
      expect(iframe.getAttribute("sandbox")).toBe("");
      expect(iframe.style.width).toBe("816px");
      expect(iframe.style.height).toBe("1056px");
      expect(iframe.style.position).toBe("absolute");

      expect(links[i]).toHaveAttribute("href", `/api/templates/preview/${t.name}`);
      expect(links[i]).toHaveAttribute("target", "_blank");
      expect(links[i]).toHaveAttribute("rel", "noreferrer");
    });
  });
});

describe("TemplatesScreen per person", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listTemplates).mockResolvedValue([...TEMPLATES]);
  });

  it("marks the current person's default and names them", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ default_template: "terminal" }));
    renderScreen({ people: [SAM] });

    expect(await screen.findByRole("heading", { name: "Settings for Sam Lee" })).toBeInTheDocument();
    expect(api.getSettings).toHaveBeenCalledWith(2);
    await waitFor(() => expect(within(card("Terminal")).getByText("Default")).toBeInTheDocument());
    expect(within(card("Slate")).queryByText("Default")).not.toBeInTheDocument();
  });

  it("heads the page's person section with the picker's label", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({ people: [SAM], overrides: { labelFor: (p) => `${p.name} #${p.id}` } });
    expect(await screen.findByRole("heading", { name: "Settings for Sam Lee #2" })).toBeInTheDocument();
  });

  it("sets the default for the person who was current at the click", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ default_template: "slate" }));
    vi.mocked(api.updateSettings).mockResolvedValue(settings({ default_template: "signal" }));
    renderScreen({ people: [SAM] });
    await waitFor(() => expect(within(card("Slate")).getByText("Default")).toBeInTheDocument());

    fireEvent.click(within(card("Signal")).getByRole("button", { name: "Set as default" }));
    expect(api.updateSettings).toHaveBeenCalledWith({ default_template: "signal" }, 2);
    await waitFor(() => expect(within(card("Signal")).getByText("Default")).toBeInTheDocument());
    expect(within(card("Slate")).queryByText("Default")).not.toBeInTheDocument();
  });

  it("drops the previous person's Default the moment the person changes", async () => {
    const forSam = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((id?: number) =>
      id === 1 ? Promise.resolve(settings({ default_template: "meridian" })) : forSam.promise
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });
    await waitFor(() => expect(within(card("Meridian")).getByText("Default")).toBeInTheDocument());

    act(() => {

      switchTo(2);

    });
    expect(screen.queryByText("Default")).not.toBeInTheDocument();
    // Until Sam's settings arrive, nothing can be written on Sam's behalf.
    for (const button of screen.getAllByRole("button", { name: "Set as default" })) {
      expect(button).toBeDisabled();
    }

    await act(async () => {
      forSam.resolve(settings({ default_template: "signal" }));
    });
    expect(within(card("Signal")).getByText("Default")).toBeInTheDocument();
    expect(screen.getAllByText("Default")).toHaveLength(1);
  });

  it("ignores a late response for the previous person", async () => {
    const forJordan = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((id?: number) =>
      id === 1 ? forJordan.promise : Promise.resolve(settings({ default_template: "signal" }))
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });
    await screen.findByText("Meridian");
    expect(api.getSettings).toHaveBeenLastCalledWith(1);

    act(() => {

      switchTo(2);

    });
    expect(api.getSettings).toHaveBeenLastCalledWith(2);
    await waitFor(() => expect(within(card("Signal")).getByText("Default")).toBeInTheDocument());
    await act(async () => {
      forJordan.resolve(settings({ default_template: "meridian" }));
    });
    expect(within(card("Signal")).getByText("Default")).toBeInTheDocument();
    expect(within(card("Meridian")).queryByText("Default")).not.toBeInTheDocument();
  });

  it("keeps Set as default disabled until the person's settings load", async () => {
    vi.mocked(api.getSettings).mockReturnValue(new Promise<SettingsShape>(() => {}));
    renderScreen({ people: [SAM] });
    await screen.findByText("Meridian");
    const buttons = screen.getAllByRole("button", { name: "Set as default" });
    expect(buttons).toHaveLength(4);
    for (const button of buttons) expect(button).toBeDisabled();
  });

  it("sets the app-wide default when there are no people", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ default_template: "slate" }));
    vi.mocked(api.updateSettings).mockResolvedValue(settings({ default_template: "meridian" }));
    renderScreen({ people: [], personId: null });
    await waitFor(() => expect(within(card("Slate")).getByText("Default")).toBeInTheDocument());
    expect(vi.mocked(api.getSettings).mock.calls[0][0]).toBeUndefined();
    expect(screen.queryByRole("heading", { name: /^Settings for/ })).not.toBeInTheDocument();

    fireEvent.click(within(card("Meridian")).getByRole("button", { name: "Set as default" }));
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1));
    const [patch, profileId] = vi.mocked(api.updateSettings).mock.calls[0];
    expect(patch).toEqual({ default_template: "meridian" });
    expect(profileId).toBeUndefined();
  });

  it("requests no settings while the person list is loading", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({ people: [], personId: null, loading: true });
    await screen.findByText("Meridian");
    expect(api.getSettings).not.toHaveBeenCalled();
    for (const button of screen.getAllByRole("button", { name: "Set as default" })) {
      expect(button).toBeDisabled();
    }
  });
});
```

- [ ] **Step 7: Run the Templates tests and confirm they fail**

Run: `cd frontend && npx vitest run src/screens/TemplatesScreen.test.tsx`

Expected: FAIL, `Tests  8 failed | 3 passed (11)`. "clicking Set as default..." fails on the missing `1` argument; the per-person tests fail because the old screen calls `getSettings()` with no id and never again, has no `Settings for ...` heading, and leaves "Set as default" enabled before the settings load and while the person list is loading. "renders four cards...", the thumbnail test and "sets the app-wide default when there are no people" (today's behaviour) already pass.

- [ ] **Step 8: Move the Templates screen onto the hook**

All edits are in `frontend/src/screens/TemplatesScreen.tsx`.

8a. Imports. Replace this code:

```tsx
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { getSettings, listTemplates, templatePreviewUrl, updateSettings } from "../api";
import type { SettingsShape, TemplateInfo, TemplateName } from "../types";
```

with:

```tsx
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { listTemplates, templatePreviewUrl } from "../api";
import { usePerson } from "../person";
import { usePersonSettings } from "../personSettings";
import type { TemplateInfo, TemplateName } from "../types";
```

8b. `TemplateCard` takes a `disabled` flag. Replace this code:

```tsx
function TemplateCard({
  template,
  isDefault,
  busy,
  onMakeDefault,
}: {
  template: TemplateInfo;
  isDefault: boolean;
  busy: boolean;
  onMakeDefault: (name: TemplateName) => void;
}) {
```

with:

```tsx
function TemplateCard({
  template,
  isDefault,
  busy,
  disabled,
  onMakeDefault,
}: {
  template: TemplateInfo;
  isDefault: boolean;
  busy: boolean;
  disabled: boolean;
  onMakeDefault: (name: TemplateName) => void;
}) {
```

8c. The card's button honours it. Replace this code:

```tsx
            onClick={() => onMakeDefault(template.name)}
            disabled={busy}
```

with:

```tsx
            onClick={() => onMakeDefault(template.name)}
            disabled={busy || disabled}
```

8d. The screen component. Replace this code:

```tsx
export default function TemplatesScreen() {
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [settings, setSettings] = useState<SettingsShape | null>(null);
  const [busy, setBusy] = useState<TemplateName | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch((e) => setError(String(e)));
    getSettings()
      .then(setSettings)
      .catch((e) => setError(String(e)));
  }, []);

  async function makeDefault(name: TemplateName) {
    setBusy(name);
    setError(null);
    try {
      const s = await updateSettings({ default_template: name });
      setSettings(s);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <h1>Templates</h1>
      <p className="muted">
        Every template renders the same data - pick the voice that fits the field.
      </p>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="template-grid">
        {templates.map((t) => (
          <TemplateCard
            key={t.name}
            template={t}
            isDefault={settings?.default_template === t.name}
            busy={busy === t.name}
            onMakeDefault={makeDefault}
          />
        ))}
      </div>
    </div>
  );
}
```

with:

```tsx
export default function TemplatesScreen() {
  const { person, labelFor } = usePerson();
  const { settings, error: settingsError, save } = usePersonSettings();
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [busy, setBusy] = useState<TemplateName | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch((e) => setError(String(e)));
  }, []);

  async function makeDefault(name: TemplateName) {
    setBusy(name);
    try {
      await save({ default_template: name });
    } finally {
      setBusy(null);
    }
  }

  const shownError = error ?? settingsError;

  return (
    <div>
      <h1>Templates</h1>
      <p className="muted">
        Every template renders the same data - pick the voice that fits the field.
      </p>
      {shownError && <div className="alert alert-error">{shownError}</div>}

      {person && (
        <>
          <h2>Settings for {labelFor(person)}</h2>
          <p className="muted">
            The Default badge marks {labelFor(person)}'s default template for jobs added on the
            Add Jobs page. Changing it changes nobody else's.
          </p>
        </>
      )}

      <div className="template-grid">
        {templates.map((t) => (
          <TemplateCard
            key={t.name}
            template={t}
            isDefault={settings?.default_template === t.name}
            busy={busy === t.name}
            // Nothing is written until the current person's default is known.
            disabled={settings === null}
            onMakeDefault={makeDefault}
          />
        ))}
      </div>
    </div>
  );
}
```

Nothing else in the file changes (`PAGE_W`, `PAGE_H`, `useThumbScale` and the rest of `TemplateCard` stay as they are).

- [ ] **Step 9: Run the Templates tests, then the whole frontend suite**

Run: `cd frontend && npx vitest run src/screens/TemplatesScreen.test.tsx`

Expected: PASS, `Tests  11 passed (11)`.

Run: `cd frontend && npm test`

Expected: PASS. No other test renders `SettingsScreen` or `TemplatesScreen` (`App.test.tsx` renders `/` only).

- [ ] **Step 10: Rebuild the bundle and check it**

Run: `cd frontend && npm run build`

Expected: `tsc` reports no errors (it type-checks the test files too; the calls rely on Task 10's optional `profileId` parameters), Vite writes `frontend/dist`, and the last line is `stamp-build: recorded <N> build inputs` (one more input than before: `src/personSettings.ts`).

Run (from the repo root): `.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q`

Expected: PASS.

- [ ] **Step 11: Commit**

Run (from the repo root):

```bash
git add frontend/src/personSettings.ts frontend/src/screens/SettingsScreen.tsx frontend/src/screens/SettingsScreen.test.tsx frontend/src/screens/TemplatesScreen.tsx frontend/src/screens/TemplatesScreen.test.tsx frontend/dist
git commit -m "$(cat <<'EOF'
feat: settings and templates edit the current person's settings

A new usePersonSettings() hook reads and writes getSettings/
updateSettings for the current person (the app-wide defaults when there
are no people), keeps each result with the id it was fetched for, and
drops a read or save that settles after a switch. Settings shows the
defaults under "Settings for {label}" and groups the API key, generation
and theme cards under "App-wide". Templates marks the current person's
default under the same heading and keeps "Set as default" disabled until
that person's settings have loaded. Nothing is requested while the
person list is loading or has failed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
git status --short
```

Expected: `git status --short` prints nothing (a dirty `frontend/dist` means the rebuild was not added).


---

### Task 19: Application screen switches to the application's owner

**Files:**
- Modify: `frontend/src/screens/ApplicationScreen.tsx` (imports; person context and owner state after the `switching` state; owner-switch effect after the poll effect; switch-guard effect after the `beforeunload` effect; "no longer exists" message after the status line)
- Test: `frontend/src/screens/ApplicationScreen.test.tsx` (imports, the `../api` mock factory, the `renderAt` helper, one new `describe` block appended at the end of the file)
- Rebuilt and committed: `frontend/dist`

**Interfaces:**
- Consumes:
  - From Task 11 (`frontend/src/person.tsx`): `usePerson()` returning `PersonContextValue` with `people`, `person`, `loading`, `error`, `labelFor(p)`, `setPersonId(id, { remember: false })`, `setNotice(message)`, `refreshPeople(): Promise<void>`, `setSwitchGuard(message | null)`. Also `PersonProvider` and `PERSON_STORAGE_KEY` (one test mounts the real provider).
  - From Task 11 (`frontend/src/test-utils.tsx`): `makePerson(p?)`, `renderWithPerson(ui, opts)` and `PersonTestOptions` (`people`, `personId`, `loading`, `route`, `path`, `overrides`), and the returned `switchTo(id)`. The tests pass their own `vi.fn()` spies through `overrides` and rely on `switchTo` re-rendering with the same `overrides` and a different `person`.
  - From Task 12 (`frontend/src/components/PersonPicker.tsx`): the picker shows `notice`, shows the guard's "Switch anyway" / "Stay" prompt, and navigates to `/` after a manual numeric switch on `/applications/*`. This task relies on that and does not implement it. `setPersonId` does not go through the guard and does not navigate, so the owner switch leaves the user on this screen.
  - Existing: `ApplicationDetail.profile_id` and `ApplicationDetail.id` (`frontend/src/types.ts`).
- Produces: no new exports. Later tasks rely on nothing from this one except the behaviour and these user-visible strings:
  - `Switched to {label} to show this application.` (sent through `setNotice`; `{label}` is `labelFor(owner)`)
  - `This application's person no longer exists.` (rendered on this screen as `<div className="alert" role="status">`)
  - `{label}'s application has unsaved edits.` (sent through `setSwitchGuard`)
- Choices made here (the contract left them open):
  - The owner check waits until `loading` is false **and** `error` is null. A failed people load leaves `people` empty, and treating that as "loaded" would call every owner gone.
  - "No longer exists" is shown on the Application screen itself (not through `setNotice`), because it describes this page, and the notice line is already used for "{label} was removed.".
  - The owner check only uses a `detail` whose `id` equals the route's id, so a route change does not act on the application being left.
  - When the owner is not in `people` (the orphan case), the guard message is `This application has unsaved edits.`, since there is no label to use.
  - The guard follows the contract exactly: `dirty || coverDraft !== null` (the same condition as the existing `beforeunload` warning).
  - The switch notice is not cleared when leaving the screen. It has its own Dismiss button (Task 12).
  - `setSwitchGuard` is left out of the guard effect's dependencies on purpose, so a provider that creates a new function on every render cannot cause a set/clear loop.

- [ ] **Step 1: Write the failing tests**

All edits are in `frontend/src/screens/ApplicationScreen.test.tsx`. The screen will call `usePerson()`, which throws outside a provider, so every existing test moves onto `renderWithPerson` through the one `renderAt` helper. The default test person (id 1) owns the `base` fixture (`profile_id: 1`), so the 30 existing tests see no owner switch and need no other change.

(a) Replace the imports. Current code:

```tsx
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ApplicationScreen from "./ApplicationScreen";
import * as api from "../api";
import type { ApplicationDetail } from "../types";
```

Replacement:

```tsx
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ApplicationScreen from "./ApplicationScreen";
import * as api from "../api";
import { PERSON_STORAGE_KEY, PersonProvider, usePerson } from "../person";
import { makePerson, renderWithPerson, type PersonTestOptions } from "../test-utils";
import type { ApplicationDetail } from "../types";
```

(b) Add `listProfiles` to the `../api` mock. The real `PersonProvider` imports it from the same module, so this mock serves it too. Current code:

```tsx
vi.mock("../api", () => ({
  getApplication: vi.fn(),
```

Replacement:

```tsx
vi.mock("../api", () => ({
  // PersonProvider, mounted for real in one test below, loads people with this.
  listProfiles: vi.fn(),
  getApplication: vi.fn(),
```

(c) Replace the `renderAt` helper. Current code:

```tsx
function renderAt() {
  return render(
    <MemoryRouter initialEntries={["/applications/1"]}>
      <Routes>
        <Route path="/applications/:id" element={<ApplicationScreen />} />
      </Routes>
    </MemoryRouter>
  );
}
```

Replacement:

```tsx
// The screen reads the active person, so it renders inside the test person
// context. The default person (id 1) owns `base`, so a test that passes no
// options sees no owner switch.
function renderAt(opts: PersonTestOptions = {}) {
  return renderWithPerson(<ApplicationScreen />, {
    route: "/applications/1",
    path: "/applications/:id",
    ...opts,
  });
}
```

`renderScreen()` and every existing test call `renderAt()` with no arguments, so they are unchanged.

(d) Append this block at the very end of the file, after the closing `});` of `describe("ApplicationScreen inline editing", ...)`:

```tsx
const JORDAN = makePerson();
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
  created_at: "2026-02-01T00:00:00+00:00",
});

const ORPHAN_TEXT = "This application's person no longer exists.";
const GUARD_TEXT = "Jordan Rivera's application has unsaved edits.";

/** Fresh spies for the context functions this screen calls. */
function personSpies() {
  return {
    setPersonId: vi.fn(),
    setNotice: vi.fn(),
    refreshPeople: vi.fn(async () => undefined),
    setSwitchGuard: vi.fn(),
  };
}

/**
 * Lets pending effects and promise callbacks run, so a test that asserts
 * something did NOT happen is not just asserting too early.
 */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

/** Shows what the real provider holds, for the test that mounts it. */
function PersonProbe() {
  const { person, notice } = usePerson();
  return <p data-testid="person-probe">{`${person?.name ?? "nobody"} | ${notice ?? ""}`}</p>;
}

describe("ApplicationScreen and the active person", () => {
  beforeEach(() => {
    // resetAllMocks, not clearAllMocks: tests below queue
    // mockResolvedValueOnce values, and a leftover from an earlier test in
    // this file would be served first.
    vi.resetAllMocks();
    vi.mocked(api.listTemplates).mockResolvedValue([]);
    vi.mocked(api.fetchEditPreview).mockResolvedValue(EDIT_HTML);
    vi.mocked(api.getApplication).mockResolvedValue({
      ...base,
      status: "ready",
      resume: READY_RESUME,
      cover_letter_md: "Dear team,\n\nI build data systems.",
    });
    vi.mocked(api.updateContent).mockResolvedValue({
      ...base,
      status: "ready",
      resume: READY_RESUME,
      cover_letter_md: "Dear team,",
      style_violations: [],
    });
  });

  it("switches to the application's owner once, without remembering the choice", async () => {
    vi.mocked(api.getApplication).mockResolvedValue({ ...base, profile_id: 2, status: "ready" });
    const spies = personSpies();
    renderAt({
      people: [JORDAN, SAM],
      personId: 1,
      // A label that differs from the name proves the notice uses labelFor,
      // the same labelling rule the picker uses.
      overrides: { ...spies, labelFor: (p) => `${p.name} #${p.id}` },
    });

    await waitFor(() => expect(spies.setPersonId).toHaveBeenCalledWith(2, { remember: false }));
    await settle();
    expect(spies.setPersonId).toHaveBeenCalledTimes(1);
    expect(spies.setNotice).toHaveBeenCalledTimes(1);
    expect(spies.setNotice).toHaveBeenCalledWith(
      "Switched to Sam Lee #2 to show this application."
    );
    expect(spies.refreshPeople).not.toHaveBeenCalled();
    expect(screen.queryByText(ORPHAN_TEXT)).not.toBeInTheDocument();
  });

  it("stays put when the application belongs to the current person", async () => {
    const spies = personSpies();
    renderAt({ people: [JORDAN, SAM], personId: 1, overrides: spies });
    expect(await screen.findByText(/0\.4321/)).toBeInTheDocument();
    await settle();
    expect(spies.setPersonId).not.toHaveBeenCalled();
    expect(spies.setNotice).not.toHaveBeenCalled();
    expect(spies.refreshPeople).not.toHaveBeenCalled();
  });

  it("decides nothing while the people list is still loading", async () => {
    vi.mocked(api.getApplication).mockResolvedValue({ ...base, profile_id: 2, status: "ready" });
    const spies = personSpies();
    renderAt({ people: [], personId: null, loading: true, overrides: spies });
    expect(await screen.findByText(/0\.4321/)).toBeInTheDocument();
    await settle();
    // An empty list while loading would otherwise look like a missing owner.
    expect(spies.refreshPeople).not.toHaveBeenCalled();
    expect(spies.setPersonId).not.toHaveBeenCalled();
    expect(screen.queryByText(ORPHAN_TEXT)).not.toBeInTheDocument();
  });

  it("does not call the person gone when the people list failed to load", async () => {
    vi.mocked(api.getApplication).mockResolvedValue({ ...base, profile_id: 2, status: "ready" });
    const spies = personSpies();
    renderAt({
      people: [],
      personId: null,
      overrides: { ...spies, error: "API 500: Internal Server Error" },
    });
    expect(await screen.findByText(/0\.4321/)).toBeInTheDocument();
    await settle();
    expect(spies.refreshPeople).not.toHaveBeenCalled();
    expect(spies.setPersonId).not.toHaveBeenCalled();
    expect(screen.queryByText(ORPHAN_TEXT)).not.toBeInTheDocument();
  });

  it("does not switch back on a later poll after a manual switch", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(api.getApplication)
        .mockResolvedValueOnce({ ...base, profile_id: 2, status: "queued" })
        .mockResolvedValue({ ...base, profile_id: 2, status: "ready" });
      const spies = personSpies();
      const { switchTo } = renderAt({ people: [JORDAN, SAM], personId: 1, overrides: spies });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(spies.setPersonId).toHaveBeenCalledTimes(1);
      expect(spies.setPersonId).toHaveBeenCalledWith(2, { remember: false });

      switchTo(2); // the provider applies the owner switch
      switchTo(1); // then the person is changed while this screen is still open

      // The application is still queued, so the 2s poll fetches it again.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(api.getApplication).toHaveBeenCalledTimes(2);
      expect(spies.setPersonId).toHaveBeenCalledTimes(1);
      expect(spies.setNotice).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("refreshes the people list once when the owner is missing, then says the person no longer exists", async () => {
    vi.mocked(api.getApplication).mockResolvedValue({ ...base, profile_id: 7, status: "ready" });
    const spies = personSpies();
    renderAt({ people: [JORDAN], personId: 1, overrides: spies });

    expect(await screen.findByText(ORPHAN_TEXT)).toBeInTheDocument();
    await settle();
    expect(spies.refreshPeople).toHaveBeenCalledTimes(1);
    expect(spies.refreshPeople).toHaveBeenCalledWith();
    expect(spies.setPersonId).not.toHaveBeenCalled();
    expect(spies.setNotice).not.toHaveBeenCalled();
  });

  it("switches to an owner that only a refresh of the people list finds, without remembering it", async () => {
    localStorage.clear();
    try {
      // The provider's first load predates the owner; the refresh finds them.
      vi.mocked(api.listProfiles)
        .mockResolvedValueOnce([JORDAN])
        .mockResolvedValue([JORDAN, SAM]);
      vi.mocked(api.getApplication).mockResolvedValue({ ...base, profile_id: 2, status: "ready" });

      render(
        <MemoryRouter initialEntries={["/applications/1"]}>
          <PersonProvider>
            <Routes>
              <Route
                path="/applications/:id"
                element={
                  <>
                    <PersonProbe />
                    <ApplicationScreen />
                  </>
                }
              />
            </Routes>
          </PersonProvider>
        </MemoryRouter>
      );

      await waitFor(() =>
        expect(screen.getByTestId("person-probe")).toHaveTextContent(
          "Sam Lee | Switched to Sam Lee to show this application."
        )
      );
      expect(screen.queryByText(ORPHAN_TEXT)).not.toBeInTheDocument();
      // remember: false. Whatever the provider stored for this browser, it is
      // not the person a followed link switched to.
      const stored = localStorage.getItem(PERSON_STORAGE_KEY);
      expect(stored === null ? null : JSON.parse(stored).id).not.toBe(2);
    } finally {
      localStorage.clear();
    }
  });

  it("guards a picker switch while the resume has unsaved edits, until they are reverted", async () => {
    const spies = personSpies();
    renderAt({ overrides: spies });
    const doc = await editorFrame();
    expect(spies.setSwitchGuard).not.toHaveBeenCalledWith(expect.any(String));

    typeInto(doc, "summary", "Nine years of Python.");
    await waitFor(() => expect(spies.setSwitchGuard).toHaveBeenLastCalledWith(GUARD_TEXT));

    fireEvent.click(screen.getByRole("button", { name: "Revert" }));
    await waitFor(() => expect(spies.setSwitchGuard).toHaveBeenLastCalledWith(null));
  });

  it("guards while the cover letter has a draft, and clears the guard once it is saved", async () => {
    const spies = personSpies();
    renderAt({ overrides: spies });
    fireEvent.click(await screen.findByRole("button", { name: "Cover Letter" }));
    fireEvent.change(screen.getByLabelText("Cover letter"), {
      target: { value: "Dear team,\n\nI build data pipelines." },
    });
    await waitFor(() => expect(spies.setSwitchGuard).toHaveBeenLastCalledWith(GUARD_TEXT));

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.updateContent).toHaveBeenCalled());
    await waitFor(() => expect(spies.setSwitchGuard).toHaveBeenLastCalledWith(null));
  });

  it("clears the guard when the screen unmounts with edits still unsaved", async () => {
    const spies = personSpies();
    const { unmount } = renderAt({ overrides: spies });
    const doc = await editorFrame();
    typeInto(doc, "summary", "Nine years of Python.");
    await waitFor(() => expect(spies.setSwitchGuard).toHaveBeenLastCalledWith(GUARD_TEXT));

    unmount();
    expect(spies.setSwitchGuard).toHaveBeenLastCalledWith(null);
  });
});
```

Notes on the tests:
- The poll test uses the same `await act(async () => { await vi.advanceTimersByTimeAsync(n); })` pattern as `CopyButton.test.tsx`. It does not use `waitFor` or `findBy*`: they poll on real timers and stall under vitest's fake timers.
- The real-provider test is the only one that mounts `PersonProvider`. It puts `MemoryRouter` outside the provider, the same order `main.tsx` uses (`BrowserRouter > PersonProvider > App`).
- `editorFrame`, `typeInto`, `EDIT_HTML`, `READY_RESUME` and `base` are the helpers and fixtures already at the top of this file.

- [ ] **Step 2: Run the tests and confirm the new ones fail**

Run: `cd frontend && npx vitest run src/screens/ApplicationScreen.test.tsx`

Expected: 7 failed, 33 passed (40 total). The 30 existing tests pass on `renderWithPerson`, because the unchanged screen ignores the context. Three of the new tests pass already because they check that nothing happens, and they stay as regression guards: "stays put when the application belongs to the current person", "decides nothing while the people list is still loading", and "does not call the person gone when the people list failed to load". These 7 fail:
- "switches to the application's owner once, without remembering the choice": `expected "spy" to be called with arguments: [ 2, { remember: false } ]` (0 calls).
- "does not switch back on a later poll after a manual switch": `expected "spy" to be called 1 times, but got 0 times`.
- "refreshes the people list once when the owner is missing, ...": `Unable to find an element with the text: This application's person no longer exists.`
- "switches to an owner that only a refresh of the people list finds, ...": the probe reads `Jordan Rivera | ` rather than `Sam Lee | Switched to Sam Lee to show this application.`
- the three guard tests: `expected "spy" to be last called with arguments: [ "Jordan Rivera's application has unsaved edits." ]` (0 calls).

- [ ] **Step 3: Implement the owner switch and the switch guard**

All edits are in `frontend/src/screens/ApplicationScreen.tsx`. No earlier task touches this file.

(a) Import the hook. Current code:

```tsx
import { harvestResume, removalTarget } from "../inlineEdit";
```

Replacement:

```tsx
import { harvestResume, removalTarget } from "../inlineEdit";
import { usePerson } from "../person";
```

(b) Read the person context and add the owner state, directly after the `switching` state. Current code:

```tsx
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [switching, setSwitching] = useState(false);
```

Replacement:

```tsx
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [switching, setSwitching] = useState(false);

  const {
    people,
    person,
    loading: peopleLoading,
    error: peopleError,
    labelFor,
    setPersonId,
    setNotice,
    refreshPeople,
    setSwitchGuard,
  } = usePerson();
  // The application id whose owner has been dealt with. Opening someone else's
  // application switches to them once per id. After that, the screen does not
  // switch again, on a later poll or when the person changes while it is open.
  const ownerHandledFor = useRef<number | null>(null);
  // An owner missing from the list may have been created since the list
  // loaded, so the list is refreshed once before the person is called gone.
  const ownerRefreshStarted = useRef<number | null>(null);
  const [ownerRefreshedFor, setOwnerRefreshedFor] = useState<number | null>(null);
  const [ownerMissingFor, setOwnerMissingFor] = useState<number | null>(null);
```

(c) Add the owner-switch effect directly after the poll effect. Current code (the end of the poll effect):

```tsx
    tick();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [appId, pollNonce]);
```

Replacement:

```tsx
    tick();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [appId, pollNonce]);

  // The owner of the application on screen. A detail still showing the
  // previous id (the route changed, the new fetch has not landed) does not
  // count, or the switch would follow the application being left.
  const ownerId = detail !== null && detail.id === appId ? detail.profile_id : null;

  // Switch to the owner once the people list has loaded. A failed load does
  // not count as loaded: with no list, every owner would look missing.
  useEffect(() => {
    if (peopleLoading || peopleError !== null || ownerId === null) return;
    if (ownerHandledFor.current === appId) return;
    const owner = people.find((p) => p.id === ownerId);
    if (owner === undefined) {
      if (ownerRefreshedFor === appId) {
        ownerHandledFor.current = appId;
        setOwnerMissingFor(appId);
      } else if (ownerRefreshStarted.current !== appId) {
        ownerRefreshStarted.current = appId;
        // Settled either way: a failed refresh leaves the owner exactly as
        // missing as before.
        refreshPeople()
          .catch(() => undefined)
          .finally(() => setOwnerRefreshedFor(appId));
      }
      return;
    }
    ownerHandledFor.current = appId;
    if (person === null || person.id !== owner.id) {
      // remember: false, so following a link to someone else's application
      // does not change who this browser opens on next time.
      setPersonId(owner.id, { remember: false });
      setNotice(`Switched to ${labelFor(owner)} to show this application.`);
    }
  }, [
    appId,
    ownerId,
    people,
    person,
    peopleLoading,
    peopleError,
    ownerRefreshedFor,
    labelFor,
    setPersonId,
    setNotice,
    refreshPeople,
  ]);
```

(d) Add the switch-guard effect directly after the `beforeunload` effect. Current code (the end of that effect):

```tsx
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, coverDraft]);
```

Replacement:

```tsx
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, coverDraft]);

  // A picker switch from here navigates away, which would drop the frame's
  // edits and the cover-letter draft. So while there are unsaved edits, the
  // guard makes the picker ask "Switch anyway" first. The cleanup clears the
  // guard when the edits are saved or reverted and when the screen unmounts,
  // so no guard outlives this screen.
  const hasUnsavedEdits = dirty || coverDraft !== null;
  const guardOwner =
    detail === null ? undefined : people.find((p) => p.id === detail.profile_id);
  const guardMessage =
    guardOwner === undefined
      ? "This application has unsaved edits."
      : `${labelFor(guardOwner)}'s application has unsaved edits.`;
  useEffect(() => {
    if (!hasUnsavedEdits) return;
    setSwitchGuard(guardMessage);
    return () => setSwitchGuard(null);
    // setSwitchGuard is deliberately not a dependency: this runs when the edits
    // start or stop, not on every provider render. A provider that handed out a
    // new function per render would otherwise clear and set the guard in a loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasUnsavedEdits, guardMessage]);
```

(e) Show the orphan message under the status line. Current code:

```tsx
        {working && <span className="spinner" style={{ marginLeft: "0.5rem" }} />}
      </p>
```

Replacement:

```tsx
        {working && <span className="spinner" style={{ marginLeft: "0.5rem" }} />}
      </p>

      {ownerMissingFor === appId && (
        <div className="alert" role="status">
          This application's person no longer exists.
        </div>
      )}
```

All new hooks sit above the `if (!detail)` early return, so the hook order is the same on every render.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd frontend && npx vitest run src/screens/ApplicationScreen.test.tsx`
Expected: 40 passed, 0 failed.

Then the whole frontend suite: `cd frontend && npm test`
Expected: every test file passes. Nothing outside this screen imports `ApplicationScreen` except `App.tsx`. `App.test.tsx` renders `/` and does not reach it.

- [ ] **Step 5: Rebuild the bundle and check it**

Run: `cd frontend && npm run build`
Expected: `tsc` reports no errors. That includes the test file, since `tsconfig.json` includes all of `src`. Then `vite build` writes `dist/`, and `stamp-build.mjs` rewrites `dist/build-inputs.sha256`.

Then from the repo root: `.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q`
Expected: `3 passed`.

- [ ] **Step 6: Commit**

From the repo root:

```bash
git add frontend/src/screens/ApplicationScreen.tsx frontend/src/screens/ApplicationScreen.test.tsx frontend/dist
git commit -m "$(cat <<'EOF'
feat: switch to an application's owner when it is opened

Opening another person's application switches the picker to its owner for
this visit, without remembering it, and says so in the picker notice. An
owner missing from the people list triggers one refresh, then "This
application's person no longer exists." Later polls never switch again.
Unsaved resume or cover-letter edits set the switch guard, cleared on
save, revert and unmount.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

Then `git status` must show a clean tree. If `frontend/dist` is still dirty, it was not added.


---

### Task 20: Docs for several people on one install, final rebuild and full suites

**Files:**
- Modify: `README.md` (intro paragraph; MCP mode prompt; Research depth intro; Demo mode paragraph; Voice paragraph; new `## Several people, one install` section before `## Development`; Known limitations page-size line; Highlights test counts)
- Modify: `CLAUDE.md` (opening paragraph; MCP mode item under "Two intelligences"; `config.py`, `models.py`, `services/`, `api/` bullets under "Backend layout"; new paragraph under "Frontend")
- Modify: `docs/EXTENDING.md` (§1: verify Task 9's `get_master_profile` row; reword the profile-writes paragraph; new "Several people on one install" paragraph after it)
- Out of repo, read only (spec §10, fourth bullet): the operator instructions that `CLAUDE.local.md` imports on this machine, `personal/Eldon_Dahlin_Resume/CLAUDE.md` under the workspace root. Step 16 proposes a change to them in the final report; nothing outside the repo is edited or committed unless the user approves it.
- Test: no new test file (the contract names none for this task). A docs check run from the shell (Step 1) fails before the edits and passes after; `tests/test_e2e.py::test_readme_quickstart` and `tests/test_frontend_bundle.py` are the committed guards; the full backend and frontend suites close the feature.

**Interfaces:**
- Consumes (names the docs describe; every one must already exist from Tasks 1-19):
  - Task 1: `backend/app/services/inbox.py::inbox_url(email)`, `profiles.py::profile_summary` (keys `created_at`, `inbox_url`), profile detail `application_count`, blank-name 422.
  - Task 2: `profiles.py::_merge_contact` (Build keeps filled contact fields).
  - Task 3: `DELETE /api/profiles/{profile_id}/documents/{doc_id}`.
  - Tasks 4-5: `backend/app/services/removal.py` (`delete_application_rows`, `ACTIVE_STATUSES`, `STALE_AFTER`, `RemovalBlocked`, `blocking_applications`, `remove_person`), `DELETE /api/profiles/{profile_id}?confirm_name=`.
  - Task 6: `models.PROFILE_SETTING_KEYS`, `Profile.settings_json`, `get_profile_settings`/`set_profile_settings`, `services/person_settings.py::settings_for(data_dir, profile)`.
  - Task 7: `GET/PUT /api/settings?profile_id=N`.
  - Task 9: the `CANDIDATE'S INBOX` guide section in `backend/mcp_ops.py`, `inbox_url` in `get_master_profile`, and the `docs/EXTENDING.md` §1 `get_master_profile` row mentioning `inbox_url`.
  - Task 11: `frontend/src/person.tsx` (`PersonProvider`, `usePerson()`, `PERSON_STORAGE_KEY = "tailored-person"`, `requestSwitch`, `setPersonId(id, { remember })`, `refreshPeople`, `setSwitchGuard`, `labelFor`), `frontend/src/test-utils.tsx::renderWithPerson`.
  - Task 12: `frontend/src/components/PersonPicker.tsx` strings `Add a person`, `Inbox`, `Switch anyway`, `Stay`.
  - Task 16: `Remove this person` in `ProfileScreen.tsx`. Task 18: `Settings for` heading in `SettingsScreen.tsx`.
- Produces: documentation only. No code names. Choices made here: the docs check is a shell heredoc, not a committed test file, because the contract names no test file for Task 20; the README test counts are refreshed from the suites run in this task, as earlier docs commits did; spec §10's out-of-repo bullet is handled as a proposal in the final report (Step 16), because the operator's instructions are the user's private file and the spec says it does not reproduce them.

- [ ] **Step 1: Write the docs check and run it (expected to fail)**

From the repo root in Git Bash, run this heredoc. It is not saved anywhere; later steps run the same heredoc again, unchanged. It checks that every sentence this task adds is present, that the UI and agent strings the docs name actually exist in the code, and that the new prose blocks carry no em dash, en dash, curly quote, ellipsis character, non-breaking space or zero-width space.

```bash
.venv/Scripts/python.exe - <<'EOF'
import pathlib, sys

BAD = "—–‘’“”… ​"

NEEDLES = {
    "README.md": [
        "## Several people, one install",
        "[Several people, one install](#several-people-one-install)",
        "**The choice is kept per browser.**",
        "**Settings are per person.**",
        "install-wide defaults in `data/settings.json`",
        "**The Inbox link.**",
        "**Remove this person**",
        "**Agents and profile ids.**",
        "on the selected person's default depth from Settings.",
        "removing the last person in demo mode brings the sample person and",
        "The register comes from the newest document on",
        "page-size setting of the person the application belongs to",
    ],
    "CLAUDE.md": [
        "one Master Profile per person",
        "**The active person**",
        "`usePerson()`",
        '`localStorage["tailored-person"]`',
        "`renderWithPerson`",
        "`services/person_settings.settings_for(data_dir, profile)`",
        "`Profile.settings_json`",
        "`get_profile_settings/set_profile_settings`",
        "`inbox.py`",
        "CANDIDATE'S INBOX",
        "`removal.py`",
        "`_merge_contact`",
        "?confirm_name=",
    ],
    "docs/EXTENDING.md": [
        "inbox_url",
        "**Several people on one install.**",
        "CANDIDATE'S INBOX",
        "this is a local app with no locking",
    ],
    # The docs name these; they must exist in the code the earlier tasks wrote.
    "frontend/src/components/PersonPicker.tsx": ["Add a person", "Inbox", "Switch anyway", "Stay"],
    "frontend/src/screens/ProfileScreen.tsx": ["Remove this person"],
    "frontend/src/screens/SettingsScreen.tsx": ["Settings for"],
    "backend/mcp_ops.py": ["CANDIDATE'S INBOX", "inbox_url"],
}

# New prose blocks that must carry no machine-tell characters: (file, start, end).
BLOCKS = [
    ("README.md", "## Several people, one install", "\n## Development"),
    ("CLAUDE.md", "**The active person**", "\n### Tests"),
    ("docs/EXTENDING.md", "**Several people on one install.**", "\n### Why Tailored"),
]

problems = []
for name, needles in NEEDLES.items():
    text = pathlib.Path(name).read_text(encoding="utf-8")
    problems += [f"{name}: missing {n!r}" for n in needles if n not in text]
for name, start, end in BLOCKS:
    text = pathlib.Path(name).read_text(encoding="utf-8")
    i = text.find(start)
    if i < 0:
        continue  # already reported above as a missing needle
    j = text.find(end, i)
    block = text[i:] if j < 0 else text[i:j]
    problems += [f"{name}: block {start!r} contains U+{ord(c):04X}" for c in BAD if c in block]

print("\n".join(problems) if problems else "docs check: ok")
sys.exit(1 if problems else 0)
EOF
```

Expected: exit code 1, and every listed problem is a `README.md:`, `CLAUDE.md:` or `docs/EXTENDING.md:` "missing" line (the EXTENDING `inbox_url` and `CANDIDATE'S INBOX` needles already pass, from Task 9's table row). There must be **no** missing line for `frontend/src/...` or `backend/mcp_ops.py`. If there is, an earlier task shipped a different string than the contract says; stop and reconcile that task before documenting it.

- [ ] **Step 2: Verify Task 9's EXTENDING.md row**

```bash
grep -n '^| `get_master_profile' docs/EXTENDING.md
```

Expected: exactly one table row, the one Task 9 wrote:

```text
| `get_master_profile(profile_id?)` | Contact + master profile: the only facts an agent may use. Omitting `profile_id` resolves the sole profile; ambiguity returns an error listing the profiles. Also returns `inbox_url`, the candidate's webmail link when the contact email is on Gmail, iCloud or Outlook, else null; the guide's CANDIDATE'S INBOX section says how an agent may use it. |
```

The row must contain `inbox_url` and `CANDIDATE'S INBOX`; Task 9's `tests/test_mcp_inbox.py::test_extending_md_documents_inbox_url` also asserts the first, so Step 13 would fail without it. If the row still reads "Contact + master profile — the only facts an agent may use. Omitting ..." with no `inbox_url`, Task 9's docs step was skipped: replace that row with the one above, verbatim. Do not edit the row otherwise; the paragraph added in Step 10 summarises the guide section's rules, and the row keeps pointing at it.

**Line endings.** The working tree is CRLF (`core.autocrlf=true`; `git ls-files --eol` shows `w/crlf` for all three docs). Make every edit in Steps 3-10 and 14 with an editor or the Edit tool, which keep the file's endings; do not rewrite these files from a script that emits LF. The Step 1 check reads with universal newlines, so it works either way.

- [ ] **Step 3: README intro and MCP mode**

In `README.md`, replace (end of the first paragraph):

```markdown
and emphasizes* from it per job. It never invents anything
(see [Truthfulness](#truthfulness)).
```

with:

```markdown
and emphasizes* from it per job. It never invents anything
(see [Truthfulness](#truthfulness)). Several people can share one install,
each with their own profile, applications and settings; see
[Several people, one install](#several-people-one-install).
```

In the "Use your own AI agent instead of the API (MCP mode)" section, replace:

```markdown
> tailor my profile for &lt;job url&gt;

The agent reads your master profile, fetches and analyzes the posting,
```

with:

```markdown
> tailor my profile for &lt;job url&gt;

When several people share the install, say whose profile to use. The
copyable prompts on the Getting Started page name the person selected in the
nav for you, and an agent never follows the picker by itself (see
[Several people, one install](#several-people-one-install)).

The agent reads your master profile, fetches and analyzes the posting,
```

- [ ] **Step 4: README demo mode, research depth, known limitations**

In "Demo mode (no API key, fully offline)", replace:

```markdown
Demo mode seeds a sample profile plus one finished application and answers every AI
call from offline fixtures. Every screen is clickable end to end.
```

with:

```markdown
Demo mode seeds a sample profile plus one finished application and answers every AI
call from offline fixtures. Every screen is clickable end to end. To try the
person picker, add a second person with **Add a person** in the nav's person
list. The sample is seeded whenever the database has no people at all, so
removing the last person in demo mode brings the sample person and
application back on the next start.
```

In "Research depth = cost dial", replace:

```markdown
Research depth is chosen per job when you add it. Approximate cost per application
```

with:

```markdown
Research depth is chosen per job when you add it, and the Add Jobs form starts
on the selected person's default depth from Settings. Approximate cost per application
```

In "Known limitations", replace:

```markdown
- Browser-printing an exported resume.html always uses Letter (PDF exports honor the page-size setting).
```

with:

```markdown
- Browser-printing an exported resume.html always uses Letter (PDF exports honor the page-size setting of the person the application belongs to).
```

- [ ] **Step 5: README Voice paragraph**

In "Voice", replace:

```markdown
reads the register of the documents you uploaded during intake, as style only:
every fact still has to come from your Master Profile, and the truthfulness
check is what guarantees it.
```

with:

```markdown
reads the register of the documents you uploaded during intake, as style only:
every fact still has to come from your Master Profile, and the truthfulness
check is what guarantees it. The register comes from the newest document on
the person's profile, so removing a document on the Profiles screen changes it
from the next generation on: to the newest one left, or to none.
```

- [ ] **Step 6: README "Several people, one install" section**

Insert the new section between "Voice" and "Development". Replace:

```markdown
## Development

### Frontend (Node required for development only)
```

with:

```markdown
## Several people, one install

One install can serve several people, such as a household sharing a computer.
Each person has their own Master Profile, applications and settings. The person
picker in the nav bar, beside the theme toggle, chooses whose you are looking
at, and every screen follows it: the dashboard lists that person's
applications, Add Jobs adds jobs for them, Getting Started checks their
profile, and Profiles, Settings and Templates show theirs. Switching is one
click at any time, with no sign-in. To add someone, pick **Add a person** at
the bottom of the list.

**The choice is kept per browser.** Tailored remembers the last person picked
in the browser's own storage, and each Chrome profile has its own storage. If
everyone in the household uses their own Chrome profile, Tailored opens on the
right person for each of them, and anyone can still switch. A web page cannot
see which Chrome profile or Google account is signed in, so Tailored does not
guess. The choice is never sent to the server and is not part of `data/`, and
switching in one tab leaves other open tabs as they were.

**Opening another person's application.** A link to someone else's
application switches to its owner for that visit and says so. It does not
change which person this browser opens on next time.

**Unsaved work.** Switching while the Profiles screen has unsaved changes or a
save, upload or Build still running, or while an application's editor has
unsaved edits, asks first, with **Switch anyway** and **Stay**.

**Settings are per person.** Default template, default research depth and page
size belong to the person selected when you change them, and the Settings
screen names that person in its heading. A new person starts from the
install-wide defaults in `data/settings.json`. The API key and the theme are
the same for everyone. An application always renders with the page size of
the person it belongs to, whoever is selected in any browser, and that holds
for renders an MCP agent triggers too. Jobs an agent registers over MCP do not
pick up a person's default template or depth: they start on the Slate template
unless the agent picks another, and a saved job an agent queued uses standard
depth if you later generate it from the dashboard.

**Name, email and documents.** The Profiles screen edits the selected person's
name and email. Build fills in only the contact details that are still empty,
so building over an old resume does not change a name, email or phone number
already there. Each uploaded document has a **Remove** button, which is how to
undo a resume uploaded to the wrong person. Removing a document leaves the
built Master Profile as it is; the next Build reads only what is left.

**The Inbox link.** When a person's email is at Gmail (`gmail.com`,
`googlemail.com`), iCloud (`icloud.com`, `me.com`, `mac.com`) or Outlook.com
(`outlook.com`, `hotmail.com`, `live.com`, `msn.com`), an **Inbox** link beside
the picker opens their mailbox in a new tab. The Gmail link asks for that exact
account; the other two open whichever account is signed in on that site. A
custom domain, including Google Workspace, gets no link, because the domain
does not say who hosts the mail. A connected agent gets the same link as
`inbox_url` from `get_master_profile`, and the workflow guide tells it to
confirm the mailbox on screen is the person's before reading anything and
never to sign in for you.

**Removing a person.** **Remove this person**, at the bottom of the Profiles
screen, states what will be deleted: the person's profile, documents and
applications (archived ones included), plus their exported files. The button
stays disabled until you type the person's name exactly. Removal is permanent
and leaves everyone else's rows and files alone. It is refused while any of the
person's applications is being generated, or is parked for an agent, and has
changed in the last 15 minutes; the refusal links to those applications. Rows
stuck in those states for longer count as abandoned and go with the rest. It
is also refused, with nothing deleted, while another program has one of the
person's exported files open, since Windows will not move an open file; close
it and try again. Saved jobs are removed too, including any an agent is
working through, so stop an agent working for that person first. There is no
MCP tool for removing a person.

**Agents and profile ids.** An agent never follows the picker. Every MCP tool
that works on a person takes an explicit `profile_id`, so name the person when
you ask an agent for work; the copyable prompts on the Getting Started and
Settings pages name the person selected in the nav. After a removal, the next
person created can be given the removed person's `profile_id`. The picker
guards against that by checking each person's creation time as well as the
id, but an agent that kept an old id would act on the new person, so start
each agent session from the person's name rather than a remembered id.

## Development

### Frontend (Node required for development only)
```

No wrapped line in this section starts with `-`, `+`, `*`, `#`, `>` or a digit followed by `.`, so CommonMark keeps every paragraph a paragraph (the concern behind commit "docs: rewrap the voice paragraph so CommonMark keeps it a paragraph"). Keep it that way if you rewrap.

- [ ] **Step 7: CLAUDE.md opening paragraph and MCP mode item**

In `CLAUDE.md`, replace (line 5, mid-sentence):

```markdown
cover letters from one Master Profile. `README.md` is the user-facing reference
```

with:

```markdown
cover letters from one Master Profile per person (several people can share an install; see "The active person" under Frontend). `README.md` is the user-facing reference
```

In item 2 ("**MCP mode**") under "Two intelligences, one gated write path", replace the end of the item:

```markdown
but the prose and `_WORKED_EXAMPLE` are hand-written, so update them when schemas or tool order change.
```

with:

```markdown
but the prose and `_WORKED_EXAMPLE` are hand-written, so update them when schemas or tool order change. MCP never follows the web app's person picker: every tool that works on a person takes an explicit `profile_id`, and `get_master_profile()` without one still errors when several people exist. `get_master_profile` also returns `inbox_url` (`services/inbox.py`), and the guide's CANDIDATE'S INBOX section, after WRITING VOICE, tells the agent to open that URL in the user's browser, confirm the mailbox address on the page is the candidate's contact email before reading anything, stop at a sign-in page, and never pick an account by position or sign in on the user's behalf.
```

- [ ] **Step 8: CLAUDE.md backend layout bullets**

In the `config.py` bullet, replace:

```markdown
per-user prefs (`default_template`, `default_depth`, `page_size`) live in `data/settings.json` via `load_user_settings/save_user_settings`.
```

with:

```markdown
the install-wide defaults for the three prefs (`default_template`, `default_depth`, `page_size`) live in `data/settings.json` via `load_user_settings/save_user_settings`, and each person's own values override them from `Profile.settings_json`. Every render path and batch create resolves them with `services/person_settings.settings_for(data_dir, profile)`, passing the application's owner (or `body.profile_id` for batch create), never whoever is selected in a browser. `GET/PUT /api/settings?profile_id=N` reads and writes one person's values; without `profile_id` they act on the install-wide file exactly as before. Per-person template and depth defaults reach web-app jobs only: rows from MCP `create_application`/`queue_jobs` keep `slate` and the `Job` default depth.
```

In the `models.py` bullet, replace:

```markdown
(`get_resume/set_resume`, `get_master_profile/set_master_profile`, `get_parsed/set_parsed`, `get_contact`, `get_findings`).
```

with:

```markdown
(`get_resume/set_resume`, `get_master_profile/set_master_profile`, `get_parsed/set_parsed`, `get_contact`, `get_findings`, `get_profile_settings/set_profile_settings`). `Profile.settings_json` holds one person's overrides of the three prefs; its helpers keep only `PROFILE_SETTING_KEYS` with string values, and `{}` means inherit the install-wide values. The `profile` table has no `AUTOINCREMENT`, so SQLite reissues the highest id after a delete; the frontend pairs a remembered id with `created_at`, and tombstoning removed profiles was deliberately left out.
```

At the end of the `services/` bullet, replace:

```markdown
`render_resume_html(..., edit_mode=True)` for the inline editor).
```

with:

```markdown
`render_resume_html(..., edit_mode=True)` for the inline editor), `inbox.py` (`inbox_url(email)`: a Gmail `?authuser=` URL, the iCloud or Outlook.com mail URL, or None for any other domain), `person_settings.py` (`settings_for`), `removal.py` (`delete_application_rows`, shared by single-application delete and person removal; `remove_person`, which refuses with `RemovalBlocked` (409) while `blocking_applications` finds work in `ACTIVE_STATUSES` newer than `STALE_AFTER`, stages the person's export dirs by rename into `exports/.removing-<profile_id>/` and moves them back if any rename fails, deletes the rows in one transaction, then removes the staging dir).
```

In the `api/` bullet, replace:

```markdown
events, archive/delete), `profiles.py` (CRUD, document upload, `build`), `settings.py`, `setup.py`
```

with:

```markdown
events, archive/delete; delete also removes the job and research briefs via `removal.delete_application_rows`), `profiles.py` (CRUD through `profile_summary`, ordered by id and carrying `created_at`/`inbox_url`; detail adds `application_count`, archived included; a blank name is 422; document upload and `DELETE /profiles/{id}/documents/{doc_id}`; `build`, which keeps filled contact fields via `_merge_contact`; `DELETE /profiles/{id}?confirm_name=` removes a person), `settings.py` (optional `?profile_id=N` for one person's values), `setup.py`
```

- [ ] **Step 9: CLAUDE.md frontend paragraph**

Under "### Frontend (`frontend/src/`)", replace:

```markdown
shared `types.ts`/`statuses.ts`/`theme.ts`. Screens poll the API until a status in `TERMINAL_STATUSES`.
```

with:

```markdown
shared `types.ts`/`statuses.ts`/`theme.ts`. Screens poll the API until a status in `TERMINAL_STATUSES`.

**The active person** (`person.tsx`). `PersonProvider` wraps `<App/>` in `main.tsx` and is the only frontend code that lists profiles: screens read `usePerson()` (`person`, `people`, `loading`, `labelFor`) and never call `listProfiles` or keep a profile id of their own. The choice is browser-only, stored as `localStorage["tailored-person"]` (`PERSON_STORAGE_KEY`) = `{id, created_at}` and used on load only when a person with that id and that `created_at` exists, because SQLite reissues a deleted profile's id; every storage access is in try/catch, and the fallback is the first person. It is never sent to the server, and no backend or MCP behaviour may depend on it. Every per-person fetch is keyed on `person.id` and drops a response that lands after a switch. `components/PersonPicker.tsx` is the nav control. A screen with work a switch would lose calls `setSwitchGuard(message)`, and clears it when the condition ends and in the cleanup of the effect that set it. Picker switches go through `requestSwitch`, which honors the guard; `setPersonId` (the Application screen's switch to an application's owner, with `remember: false`) and `refreshPeople()` bypass it. Call `refreshPeople()` after every profile write. Screen tests render through `renderWithPerson` in `test-utils.tsx`, a static context of `vi.fn()`s inside a `MemoryRouter`; that file name has no `.test.`, so it is a hashed bundle input and editing it needs `npm run build`.
```

- [ ] **Step 10: EXTENDING.md §1 paragraph**

In `docs/EXTENDING.md` §1, replace:

```markdown
`add_profile_evidence` and other profile writes have no such guard: they
use last-writer-wins on the whole profile record, so don't hand-edit a
profile in the web UI while an agent is writing to it (and vice-versa) -
this is a single-user local app and simultaneous edits to the same profile
are unsupported.
```

with:

```markdown
`add_profile_evidence` and other profile writes have no such guard: they
use last-writer-wins on the whole profile record, so don't hand-edit a
profile in the web UI while an agent is writing to it (and vice-versa) -
this is a local app with no locking, and simultaneous edits to the same
profile are unsupported.

**Several people on one install.** The web app has a person picker, but it
lives only in the user's browser and nothing on the server reads it, so no
tool depends on who is selected there. Every tool that works on a person takes
an explicit `profile_id`, and `get_master_profile()` without one still errors
when several people exist. Renders use the settings of the person who owns the
application (`settings_for` in `backend/app/services/person_settings.py`), so
an agent's exports get the owner's page size. Rows made by `create_application`
or `queue_jobs` do not take the person's default template or depth: the
template is `slate` unless `create_application` is passed one. People can be
removed in the web app, with no MCP tool for it, and SQLite can give a removed
person's id to the next person created, so an agent should resolve the person
with `list_profiles` or `get_master_profile` at the start of each session
instead of reusing a remembered `profile_id`. When the user asks the agent to
work in their mail, the guide's CANDIDATE'S INBOX section applies: open the
`inbox_url` that `get_master_profile` returns, confirm the mailbox on the page
is the candidate's contact email before reading anything, stop at a sign-in
page, and never sign in on the user's behalf.
```

- [ ] **Step 11: Run the docs check (expected to pass) and scan the diff**

Run the Step 1 heredoc again, unchanged.

Expected: `docs check: ok`, exit code 0.

Then scan every word this task added, across all three files, for machine-tell characters:

```bash
git diff --word-diff=porcelain -- README.md CLAUDE.md docs/EXTENDING.md | .venv/Scripts/python.exe -c "import sys; bad=set('—–‘’“”… ​'); lines=sys.stdin.buffer.read().decode('utf-8').splitlines(); hits=[l for l in lines if l.startswith('+') and not l.startswith('+++') and bad & set(l)]; print('\n'.join(ascii(h) for h in hits) if hits else 'no machine-tell characters added')"
```

Expected: `no machine-tell characters added`. The em dashes and arrows already in `README.md` and `CLAUDE.md` (for example "`config.py` — `Settings`") are untouched context and do not appear as `+` lines. If a hit appears, it is in text this task added: rewrite it with a comma, colon, semicolon or period.

Also run the README guard:

```bash
.venv/Scripts/python.exe -m pytest tests/test_e2e.py::test_readme_quickstart -q
```

Expected: `1 passed`.

- [ ] **Step 12: Final frontend rebuild and bundle check**

```bash
cd frontend && npm run build && cd ..
.venv/Scripts/python.exe -m pytest tests/test_frontend_bundle.py -q
git status --short frontend/dist
```

Expected: `npm run build` finishes with no `tsc` errors and the stamp script writes `dist/build-inputs.sha256`; the bundle test passes; `git status --short frontend/dist` prints nothing, because every frontend task committed its own rebuild. If it lists files, an earlier task committed a stale bundle: add `frontend/dist` to this task's `git add` in Step 15 and say so in the commit body.

- [ ] **Step 13: Full backend suite, including the `pdf` marker**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: the final line reads `N passed` with no `failed` or `error`, where N is above 731 (the count collected on this branch before Task 1; Tasks 1-9 add nine new test files). The `pdf` tests need Chromium; if they fail with `Executable doesn't exist`, run `.venv/Scripts/python.exe -m playwright install chromium` and re-run.

Record the backend count for Step 14:

```bash
.venv/Scripts/python.exe -m pytest --collect-only -q | tail -1
```

Expected: `B tests collected in ...s`. B is the backend number.

- [ ] **Step 14: Full frontend suite, then refresh the README test counts**

```bash
cd frontend && npm test && cd ..
```

Expected: `Test Files  15 passed (15)` (the 12 files before this feature plus `api.test.ts`, `person.test.tsx` and `components/PersonPicker.test.tsx`) and `Tests  F passed (F)` with F above 110. F is the frontend number.

In `README.md` Highlights ("**Engineered, not vibe-coded.**"), replace:

```markdown
667 automated tests (593 backend including real headless-Chromium PDF rendering and text extraction, 74 frontend)
```

with the measured numbers, where T = B + F:

```markdown
T automated tests (B backend including real headless-Chromium PDF rendering and text extraction, F frontend)
```

For example, with B = 812 and F = 131 the line reads `943 automated tests (812 backend including real headless-Chromium PDF rendering and text extraction, 131 frontend)`. Use the real B and F from Steps 13 and 14, not these example values. Change nothing else on that line.

Re-run the Step 1 heredoc (expected `docs check: ok`) and:

```bash
.venv/Scripts/python.exe -m pytest tests/test_e2e.py::test_readme_quickstart -q
```

Expected: `1 passed`.

- [ ] **Step 15: Commit**

```bash
git add README.md CLAUDE.md docs/EXTENDING.md
git status --short
```

Expected: only `M  README.md`, `M  CLAUDE.md`, `M  docs/EXTENDING.md` are staged and nothing else is modified or untracked (plus `frontend/dist` if Step 12 found a stale bundle and you added it).

```bash
git commit -F - <<'EOF'
docs: several people on one install

README gains a "Several people, one install" section: the person
picker, why the choice is kept per browser, per-person settings and
whose settings a render uses, editing name and email, removing a
document or a person, the Inbox link, and why agents take an explicit
profile_id. The intro, MCP mode, research depth, demo mode, voice and
known limitations wording follow it, and the test counts are refreshed.

CLAUDE.md documents the person context, per-person settings, the
inbox_url key and the guide's inbox section, and the removal services.
EXTENDING.md section 1 gains a note on several people for agent
authors.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git status --short
git log --oneline -1
```

Expected: `git status --short` prints nothing; `git log --oneline -1` shows `docs: several people on one install`.

- [ ] **Step 16: Out-of-repo hand-off (no edit, no commit)**

Spec §10's last bullet: an operator whose local agent instructions pick a mailbox by position should switch them to the `inbox_url` returned by `get_master_profile(profile_id)`. On this machine they do, and after Task 9 the guide's CANDIDATE'S INBOX section says "Never pick an account by position (such as /mail/u/1/)", so the two now contradict each other. This step reads those instructions and proposes the change. It edits no file and commits nothing. The operator file is the user's private, uncommitted instructions; like the spec, this plan does not copy its contents, so take the addresses below from the file itself when you write the proposal.

Find the file and the positional wording:

```bash
main=$(git worktree list --porcelain | sed -n '1s/^worktree //p')
op=$(sed -n 's/^@//p' "$main/CLAUDE.local.md" | head -1 | tr -d '\r')
echo "$op"
grep -n 'mail/u/\|`u/[0-9]' "$op"
```

`CLAUDE.local.md` is gitignored, so a worktree does not carry it; the first line resolves the main checkout, which does (from the main checkout itself, `$main` is that same directory). If your shell refuses the compound `git` line, run `git worktree list --porcelain` alone and use the path on its first `worktree` line as `$main`.

Expected: `echo` prints the absolute path of `personal/Eldon_Dahlin_Resume/CLAUDE.md` under the workspace root. `grep` prints one line, the "Inbox triage" bullet, which gives the campaign mailbox as a `https://mail.google.com/mail/u/<n>/` URL and the operator's other Gmail account as `u/<n>`. If `CLAUDE.local.md` does not exist, has no `@` line, or the grep prints nothing, there is nothing to propose: say that in one line of the final report and stop here.

Check that profile 1's contact email is the campaign address that bullet names, because `inbox_url` is built from the profile's email, not from the bullet (the running app may predate this branch, so the URL is computed with the new module):

```bash
.venv/Scripts/python.exe - <<'EOF'
import json, urllib.request
from backend.app.services.inbox import inbox_url
with urllib.request.urlopen("http://127.0.0.1:8547/api/profiles/1") as r:
    p = json.load(r)
email = (p.get("contact") or {}).get("email")
print("profile 1:", p["name"], "| email:", email, "| inbox_url:", inbox_url(email))
EOF
```

Expected: the email is the campaign address from the bullet and `inbox_url` is `https://mail.google.com/mail/?authuser=<that address>`. If the email is a different address, or `inbox_url` is `None`, the proposal must say so first: the Inbox link and an agent would open the wrong mailbox, or none, until the email is corrected on the Profiles screen. If the request fails with a connection error, the app is not running; say the email could not be confirmed.

In the final report to the user, name the file (`personal/Eldon_Dahlin_Resume/CLAUDE.md`, the Inbox triage bullet) and propose these two sentence changes, showing the current sentence and the proposed one for each. Keep every other sentence of the bullet as it is.

1. The sentence that gives the campaign address "signed in at `https://mail.google.com/mail/u/<n>/` in his Chrome" becomes: "Campaign mail goes to `<campaign address>`: open the `inbox_url` returned by `get_master_profile(1)` and confirm the mailbox address shown on the page before reading anything."
2. The sentence that gives the other account as "`u/<n>`" becomes: "His personal `<other account>` account is never used for the campaign." It keeps the rule and drops the position.

`<campaign address>` and `<other account>` are copied from that same bullet as it reads today. Apply the change only if the user approves it, and then only to that bullet. The file is not in any repo, so there is nothing to commit.


---

