from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi import Request
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
