"""Migration tests: SQLModel.create_all creates missing TABLES but never
missing COLUMNS, so existing databases need an additive ALTER TABLE pass."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from backend.app.db import get_engine, init_db

# The `application` table exactly as it existed before the tracker columns.
OLD_APPLICATION_DDL = """
CREATE TABLE application (
    id INTEGER NOT NULL PRIMARY KEY,
    profile_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    template VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    error_message VARCHAR,
    version INTEGER NOT NULL,
    resume_json VARCHAR,
    cover_letter_md VARCHAR,
    tailoring_notes VARCHAR,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd FLOAT NOT NULL,
    export_dir VARCHAR,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""

OLD_ROWS = """
INSERT INTO application
    (id, profile_id, job_id, template, status, version,
     input_tokens, output_tokens, cost_usd, created_at, updated_at)
VALUES
    (1, 1, 1, 'slate', 'ready', 1, 0, 0, 0.0, '2026-01-01', '2026-01-01'),
    (2, 1, 2, 'slate', 'error', 1, 0, 0, 0.0, '2026-01-01', '2026-01-01')
"""


def _old_database(tmp_path):
    engine = get_engine(tmp_path / "old.db")
    with engine.begin() as conn:
        conn.execute(text(OLD_APPLICATION_DDL))
        conn.execute(text(OLD_ROWS))
    return engine


# The `profile` table exactly as it existed before voice_notes.
OLD_PROFILE_DDL = """
CREATE TABLE profile (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    contact_json VARCHAR NOT NULL,
    master_profile_json VARCHAR NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""

OLD_PROFILE_ROWS = """
INSERT INTO profile VALUES
    (1, 'Ada', '{}', '{}', '2026-01-01', '2026-01-01')
"""


def _old_profile_database(tmp_path):
    engine = get_engine(tmp_path / "old_profile.db")
    with engine.begin() as conn:
        conn.execute(text(OLD_PROFILE_DDL))
        conn.execute(text(OLD_PROFILE_ROWS))
    return engine


def _columns(engine, table: str) -> set[str]:
    with engine.begin() as conn:
        return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}


def _stages(engine) -> dict[int, str]:
    with engine.begin() as conn:
        return dict(conn.execute(text("SELECT id, stage FROM application")).all())


def test_migration_adds_tracker_columns_to_existing_database(tmp_path):
    engine = _old_database(tmp_path)
    assert "stage" not in _columns(engine, "application")

    init_db(engine)

    assert {"stage", "applied_at", "archived_at"} <= _columns(engine, "application")


def test_migration_backfills_stage_from_status(tmp_path):
    engine = _old_database(tmp_path)
    init_db(engine)

    stages = _stages(engine)
    assert stages[1] == "drafted"  # status was 'ready'
    assert stages[2] == "saved"    # status was 'error'


def test_migration_is_idempotent(tmp_path):
    engine = _old_database(tmp_path)
    init_db(engine)
    first = _stages(engine)

    init_db(engine)  # must not raise, must not change anything

    assert _stages(engine) == first


def test_migration_creates_new_tables_normally(tmp_path):
    """A brand-new database needs no migration and gets every table."""
    engine = get_engine(tmp_path / "fresh.db")
    init_db(engine)

    assert {"stage", "applied_at", "archived_at"} <= _columns(engine, "application")
    assert _columns(engine, "applicationevent")


def test_voice_notes_is_added_to_a_pre_existing_profile_table(tmp_path):
    """A database created before voice_notes existed must gain the column."""
    engine = _old_profile_database(tmp_path)
    assert "voice_notes" not in _columns(engine, "profile")

    init_db(engine)

    assert "voice_notes" in _columns(engine, "profile")
    with engine.begin() as conn:
        value = conn.execute(text("SELECT voice_notes FROM profile WHERE id=1")).scalar()
    assert value == "", "the existing row must get the default, not NULL"
