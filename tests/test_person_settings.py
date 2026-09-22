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
