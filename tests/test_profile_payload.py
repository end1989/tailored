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
