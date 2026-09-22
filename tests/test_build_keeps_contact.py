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
