from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings


def get_engine(db_path: Path | None = None):
    """SQLite engine for the given file (default data/tailored.db).
    Creates parent directories as needed."""
    if db_path is None:
        db_path = get_settings().data_dir / "tailored.db"
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )


def _column_ddl(column) -> str:
    """`<name> <TYPE>[ NOT NULL DEFAULT <literal>]` for ALTER TABLE ADD COLUMN.

    SQLite requires a constant default when adding a NOT NULL column, which
    every column added by this project supplies via its SQLModel default.
    """
    type_sql = column.type.compile(dialect=sqlite_dialect())
    default = getattr(column, "default", None)
    if default is not None and getattr(default, "is_scalar", False):
        value = default.arg
        literal = f"'{value}'" if isinstance(value, str) else repr(value)
        return f"{column.name} {type_sql} NOT NULL DEFAULT {literal}"
    return f"{column.name} {type_sql}"


def _add_missing_columns(engine) -> list[str]:
    """Add columns present on the models but missing from existing tables.

    SQLModel.metadata.create_all() creates missing TABLES; it never adds
    COLUMNS to a table that already exists. Without this, a database created
    before a new column was declared keeps working until the first query that
    references the column, which then fails with `no such column`.

    Additive only. Existing columns are never dropped, renamed or retyped --
    SQLite's loose type affinity (VARCHAR vs TEXT) makes type comparison
    unreliable, so this deliberately does not attempt it.

    Returns the "table.column" names it added.
    """
    added: list[str] = []
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            info = conn.execute(text(f"PRAGMA table_info({table.name})")).all()
            if not info:
                continue  # table absent entirely; create_all handles it
            existing = {row[1] for row in info}
            for column in table.columns:
                if column.name in existing:
                    continue
                conn.execute(
                    text(f"ALTER TABLE {table.name} ADD COLUMN {_column_ddl(column)}")
                )
                added.append(f"{table.name}.{column.name}")
    return added


def _backfill_stage(engine) -> None:
    """Give pre-migration applications a sensible funnel stage.

    ALTER TABLE gave every existing row the 'saved' default. A generated
    application is never 'saved' -- the pipeline advances saved -> drafted on
    success -- so any row that is status='ready' and still stage='saved' must
    predate the column. That makes this idempotent: after one pass no such
    rows remain.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE application SET stage = 'drafted' "
                "WHERE status = 'ready' AND stage = 'saved'"
            )
        )


def init_db(engine) -> None:
    """Create all tables registered on SQLModel.metadata. Imports the models
    module (when it exists) so entity tables register before create_all."""
    try:
        from . import models  # noqa: F401  (registers SQLModel table classes)
    except ImportError:
        # Task 1/2: models.py not written yet; tables come from whatever is
        # already registered on the shared metadata.
        pass
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)
    _backfill_stage(engine)


@contextmanager
def session_scope(engine) -> Iterator[Session]:
    """Commit on success, rollback on exception, always close."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency: yields a Session bound to the app-level engine
    (request.app.state.engine)."""
    with session_scope(request.app.state.engine) as session:
        yield session
