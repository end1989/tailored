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
