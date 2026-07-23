from __future__ import annotations

from typing import Optional

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlmodel import Field, Session, SQLModel, select

from backend.app.db import get_engine, get_session, init_db, session_scope


class ScaffoldProbe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    label: str = ""


def test_init_db_creates_tables_and_parent_dirs(tmp_path):
    engine = get_engine(tmp_path / "nested" / "dir" / "probe.db")
    init_db(engine)
    tables = inspect(engine).get_table_names()
    assert len(tables) > 0
    assert "scaffoldprobe" in tables
    assert (tmp_path / "nested" / "dir" / "probe.db").exists()


def test_session_scope_commits(tmp_path):
    engine = get_engine(tmp_path / "probe.db")
    init_db(engine)
    with session_scope(engine) as s:
        s.add(ScaffoldProbe(label="hello"))
    with Session(engine) as s:
        rows = s.exec(select(ScaffoldProbe)).all()
    assert len(rows) == 1
    assert rows[0].label == "hello"


def test_session_scope_rolls_back_on_error(tmp_path):
    engine = get_engine(tmp_path / "probe.db")
    init_db(engine)
    with pytest.raises(RuntimeError):
        with session_scope(engine) as s:
            s.add(ScaffoldProbe(label="doomed"))
            raise RuntimeError("boom")
    with Session(engine) as s:
        rows = s.exec(select(ScaffoldProbe)).all()
    assert rows == []


def test_get_session_dependency_uses_app_state_engine(tmp_path):
    engine = get_engine(tmp_path / "dep.db")
    init_db(engine)
    probe_app = FastAPI()
    probe_app.state.engine = engine

    @probe_app.get("/probe-count")
    def probe_count(session: Session = Depends(get_session)) -> dict:
        count = len(session.exec(select(ScaffoldProbe)).all())
        return {"count": count}

    client = TestClient(probe_app)
    resp = client.get("/probe-count")
    assert resp.status_code == 200
    assert resp.json() == {"count": 0}
