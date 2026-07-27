# Dashboard Job Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the read-only dashboard into a job application tracker with funnel stages, a dated timeline, archive/delete, and saved jobs that cost nothing to park.

**Architecture:** A `stage` column on `Application` runs orthogonally to the existing `status` pipeline column — an application can be `ready` (documents generated) and `interview` (funnel position) at once. A single `ApplicationEvent` table carries both notes and dated events. Because the project has no migration system, a dependency-free additive column migration runs from `init_db` before anything touches the new columns.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy over SQLite, Pydantic v2, React 18 + TypeScript, Vitest + Testing Library, pytest.

**Spec:** `docs/superpowers/specs/2026-07-26-dashboard-job-tracker-design.md`

## Global Constraints

- **No new dependencies.** Everything here uses what is already in `requirements.txt`.
- **The migration is additive only.** It never drops, renames, or retypes a column.
- **`status` and `stage` are never derived from each other**, with exactly one exception: successful generation advances `saved → drafted` (spec §4.3).
- **Validate before mutating.** Batch creation stays all-or-nothing (`backend/app/api/applications.py:152`).
- **Naive UTC datetimes everywhere.** The codebase stores naive UTC via `models._utcnow()`; any client-supplied timestamp is converted before storage.
- **No bulk endpoints.** The frontend loops over selected ids.
- **Archived rows are excluded from `GET /applications` by default.**
- **Run backend tests with** `./.venv/Scripts/python.exe -m pytest tests/ -q` from the
  repo root. The project has a `.venv`; the ambient `python` on this machine is a
  conda interpreter that lacks `trafilatura` and every other project dependency, so
  a bare `python -m pytest` fails at conftest import. Verified baseline: 154 passed.
- **Run frontend tests with** `npm test -- --run` from `frontend/`, and type-check
  with `npx tsc --noEmit`. Verified baseline: 37 passed, tsc clean.
- **Commit after every task.** Work on branch `feature/dashboard-job-tracker`.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `backend/app/models.py` | `Application` tracker columns, `ApplicationEvent`, `STAGES`, `EVENT_KINDS` | Modify |
| `backend/app/db.py` | Additive column migration + stage backfill | Modify |
| `backend/app/api/applications.py` | Stage, events, archive, delete, generate routes | Modify |
| `backend/app/services/pipeline.py` | `saved → drafted` advance on success | Modify |
| `backend/mcp_ops.py` | Same advance for the MCP write path | Modify |
| `frontend/src/types.ts` | `Stage`, `ApplicationEvent`, new status and summary fields | Modify |
| `frontend/src/api.ts` | Client functions for the new endpoints | Modify |
| `frontend/src/screens/DashboardScreen.tsx` | Tracker table, filters, bulk actions | Modify |
| `frontend/src/screens/ApplicationScreen.tsx` | Timeline panel, stage selector | Modify |
| `frontend/src/styles.css` | `not_started` badge, stage pills, filter tabs | Modify |
| `tests/test_migration.py` | Migration against a genuine old-schema database | Create |
| `tests/test_tracker.py` | Stage, events, archive, delete, saved jobs | Create |

---

### Task 1: Schema migration helper and `Application` tracker columns

The foundation. Everything else assumes these columns exist on databases that predate them.

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/db.py`
- Test: `tests/test_migration.py` (create)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `models.STAGES: tuple[str, ...]` — `("saved", "drafted", "applied", "screening", "interview", "offer", "rejected", "withdrawn")`
  - `models.TERMINAL_STAGES: tuple[str, ...]` — `("rejected", "withdrawn")`
  - `Application.stage: str`, `Application.applied_at: Optional[datetime]`, `Application.archived_at: Optional[datetime]`
  - `db._add_missing_columns(engine) -> list[str]` — returns `"table.column"` names added
  - `db._backfill_stage(engine) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_migration.py -q`
Expected: FAIL — `no such column: stage` on the backfill query, and `applicationevent` does not exist.

- [ ] **Step 3: Add the model columns and constants**

In `backend/app/models.py`, add near the top after `_utcnow`:

```python
STAGES = (
    "saved",      # parked; no documents generated, nothing spent
    "drafted",    # resume and cover letter generated, not sent
    "applied",    # submitted
    "screening",  # recruiter contact, phone screen
    "interview",  # any round
    "offer",
    "rejected",   # terminal
    "withdrawn",  # terminal
)

TERMINAL_STAGES = ("rejected", "withdrawn")

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

Add three fields to `Application`, after `status`:

```python
    stage: str = "saved"
    applied_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
```

Add the new table after `ApplicationVersion`:

```python
class ApplicationEvent(SQLModel, table=True):
    """One dated entry on an application's timeline. A note is an event with
    kind='note' -- same shape, so notes and events share one code path."""
    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="application.id")
    kind: str                                   # one of EVENT_KINDS
    occurred_at: datetime = Field(default_factory=_utcnow)
    body: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
```

- [ ] **Step 4: Add the migration to `db.py`**

In `backend/app/db.py`, add these imports alongside the existing ones:

```python
from sqlalchemy import text
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
```

then add these three functions above `init_db`:

```python
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
```

Then change `init_db` so its final lines read:

```python
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)
    _backfill_stage(engine)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_migration.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 6: Run the full backend suite for regressions**

Run: `python -m pytest tests/ -q`
Expected: PASS. `init_db` now runs two extra statements on every fixture engine; nothing should break.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/db.py tests/test_migration.py
git commit -m "feat: add tracker columns with an additive SQLite migration"
```

---

### Task 2: Timeline API

**Files:**
- Modify: `backend/app/api/applications.py`
- Test: `tests/test_tracker.py` (create)

**Interfaces:**
- Consumes: `models.ApplicationEvent`, `models.EVENT_KINDS` (Task 1)
- Produces:
  - `GET /api/applications/{id}/events -> list[dict]`
  - `POST /api/applications/{id}/events -> dict`
  - `DELETE /api/applications/{id}/events/{event_id} -> {"deleted": int}`
  - `applications.event_payload(ev) -> dict[str, Any]`
  - `applications._naive_utc(dt) -> datetime`
  - `application_summary` gains a third parameter `last_activity_at: datetime | None = None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tracker.py`. This file is extended by Tasks 3–6, so it carries the shared fixture:

```python
"""Job tracker tests: stages, timeline, archive, delete, saved jobs."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db import get_engine
from backend.app.main import create_app
from backend.app.services import pipeline

CONTACT = {
    "name": "Avery Kim",
    "email": "avery.kim@example.com",
    "phone": None,
    "location": "Seattle, WA",
    "links": [],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILORED_FAKE", "1")
    monkeypatch.setenv("TAILORED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings()
    engine = get_engine(tmp_path / "test.db")
    app = create_app(settings=settings, engine=engine)

    calls = {"process": []}
    monkeypatch.setattr(
        pipeline, "process_application",
        lambda app_id, engine=None: calls["process"].append(app_id))

    test_client = TestClient(app)
    test_client.calls = calls
    test_client.data_dir = tmp_path / "data"
    return test_client


def make_profile(client) -> int:
    resp = client.post("/api/profiles", json={"name": "Avery Kim", "contact": CONTACT})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def make_application(client, profile_id: int, **batch) -> int:
    body = {"profile_id": profile_id, "jobs": [{"url": "https://example.com/job"}]}
    body.update(batch)
    resp = client.post("/api/applications/batch", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()[0]["id"]


# --- timeline --------------------------------------------------------------


def test_add_and_list_events(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    created = client.post(
        f"/api/applications/{aid}/events",
        json={"kind": "callback", "body": "Recruiter called, 20 minutes."},
    )
    assert created.status_code == 200, created.text
    assert created.json()["kind"] == "callback"
    assert created.json()["body"] == "Recruiter called, 20 minutes."

    listing = client.get(f"/api/applications/{aid}/events").json()
    assert len(listing) == 1
    assert listing[0]["id"] == created.json()["id"]


def test_events_are_ordered_by_occurrence_not_insertion(client):
    """Post in the OPPOSITE order to the expected result, so a regression that
    ordered by id alone would fail. Posting oldest-first would let id-only
    ordering produce the same answer and pass a broken implementation."""
    pid = make_profile(client)
    aid = make_application(client, pid)

    client.post(f"/api/applications/{aid}/events",
                json={"kind": "note", "body": "newer", "occurred_at": "2026-06-01T00:00:00"})
    client.post(f"/api/applications/{aid}/events",
                json={"kind": "note", "body": "older", "occurred_at": "2026-01-01T00:00:00"})

    bodies = [e["body"] for e in client.get(f"/api/applications/{aid}/events").json()]
    assert bodies == ["newer", "older"]


def test_events_with_equal_occurrence_tiebreak_on_id_desc(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    same = "2026-03-01T00:00:00"

    client.post(f"/api/applications/{aid}/events",
                json={"kind": "note", "body": "first", "occurred_at": same})
    client.post(f"/api/applications/{aid}/events",
                json={"kind": "note", "body": "second", "occurred_at": same})

    bodies = [e["body"] for e in client.get(f"/api/applications/{aid}/events").json()]
    assert bodies == ["second", "first"]


def test_event_kind_is_validated(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    resp = client.post(f"/api/applications/{aid}/events", json={"kind": "lunch"})
    assert resp.status_code == 422
    assert "lunch" in resp.json()["detail"]


def test_delete_event(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    eid = client.post(f"/api/applications/{aid}/events",
                      json={"kind": "note", "body": "x"}).json()["id"]

    assert client.delete(f"/api/applications/{aid}/events/{eid}").status_code == 200
    assert client.get(f"/api/applications/{aid}/events").json() == []


def test_delete_event_belonging_to_another_application_is_404(client):
    pid = make_profile(client)
    a1 = make_application(client, pid)
    a2 = make_application(client, pid)
    eid = client.post(f"/api/applications/{a1}/events",
                      json={"kind": "note", "body": "x"}).json()["id"]

    assert client.delete(f"/api/applications/{a2}/events/{eid}").status_code == 404


def test_summary_reports_last_activity(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    client.post(f"/api/applications/{aid}/events",
                json={"kind": "callback", "occurred_at": "2026-06-01T00:00:00"})

    row = next(a for a in client.get("/api/applications").json() if a["id"] == aid)
    assert row["last_activity_at"].startswith("2026-06-01")


def test_detail_embeds_events(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    client.post(f"/api/applications/{aid}/events", json={"kind": "note", "body": "hello"})

    detail = client.get(f"/api/applications/{aid}").json()
    assert [e["body"] for e in detail["events"]] == ["hello"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracker.py -q`
Expected: FAIL — 404 on the events routes.

- [ ] **Step 3: Implement the timeline routes**

In `backend/app/api/applications.py`:

Add to the imports from `..models`: `ApplicationEvent`, `ApplicationVersion`, `EVENT_KINDS`, `STAGES`. Add `from datetime import datetime, timezone` (the module currently imports only `timezone`) and `from sqlalchemy import func`.

Add the helpers after `_get_app_and_job`:

```python
def _naive_utc(dt: datetime) -> datetime:
    """Project convention: datetimes are stored naive, in UTC."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def event_payload(ev: ApplicationEvent) -> dict[str, Any]:
    return {
        "id": ev.id,
        "application_id": ev.application_id,
        "kind": ev.kind,
        "body": ev.body,
        "occurred_at": ev.occurred_at.replace(tzinfo=timezone.utc).isoformat(),
        "created_at": ev.created_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def _events_for(session: Session, application_id: int) -> list[ApplicationEvent]:
    return list(session.exec(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .order_by(ApplicationEvent.occurred_at.desc(), ApplicationEvent.id.desc())
    ).all())
```

Change `application_summary` to accept the activity timestamp and emit it:

```python
def application_summary(
    app_row: Application, job: Job, last_activity_at: datetime | None = None
) -> dict[str, Any]:
```

and add to its returned dict, after `"created_at"`:

```python
        "last_activity_at": (last_activity_at or app_row.created_at)
            .replace(tzinfo=timezone.utc).isoformat(),
```

In `application_detail`, replace the existing first line

```python
    detail = application_summary(app_row, job)
```

with a single fetch of the timeline that feeds both the activity timestamp and
the embedded list (query once, use twice):

```python
    events = _events_for(session, app_row.id)
    detail = application_summary(
        app_row, job, events[0].occurred_at if events else None
    )
```

and add one entry to the existing `detail.update({...})` call, after
`"raw_text_present"`:

```python
            "events": [event_payload(e) for e in events],
```

Add the request body next to the other `BaseModel`s:

```python
class EventIn(BaseModel):
    kind: str
    body: str = ""
    occurred_at: Optional[datetime] = None
```

Add the three routes at the end of the file:

```python
@router.get("/applications/{application_id}/events")
def list_events(
    application_id: int, session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    _get_app_and_job(session, application_id)
    return [event_payload(e) for e in _events_for(session, application_id)]


@router.post("/applications/{application_id}/events")
def add_event(
    application_id: int, body: EventIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    _get_app_and_job(session, application_id)
    if body.kind not in EVENT_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"invalid kind {body.kind!r}; must be one of {list(EVENT_KINDS)}",
        )
    event = ApplicationEvent(
        application_id=application_id,
        kind=body.kind,
        body=body.body,
        occurred_at=_naive_utc(body.occurred_at) if body.occurred_at else _utcnow(),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event_payload(event)


@router.delete("/applications/{application_id}/events/{event_id}")
def delete_event(
    application_id: int, event_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    event = session.get(ApplicationEvent, event_id)
    if event is None or event.application_id != application_id:
        raise HTTPException(status_code=404, detail="event not found")
    session.delete(event)
    session.commit()
    return {"deleted": event_id}
```

Finally, make `list_applications` fetch the newest occurrence for every row in one query rather than one query per row:

```python
    latest = dict(session.exec(
        select(ApplicationEvent.application_id,
               func.max(ApplicationEvent.occurred_at))
        .group_by(ApplicationEvent.application_id)
    ).all())
    ...
            out.append(application_summary(app_row, job, latest.get(app_row.id)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tracker.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 5: Run the full backend suite**

Run: `python -m pytest tests/ -q`
Expected: PASS. `application_summary` gained an optional third parameter, so existing two-argument callers (including `backend/mcp_ops.py`) still work.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/applications.py tests/test_tracker.py
git commit -m "feat: add application timeline events API"
```

---

### Task 3: Stage transitions

**Files:**
- Modify: `backend/app/api/applications.py`
- Test: `tests/test_tracker.py` (append)

**Interfaces:**
- Consumes: `models.STAGES` (Task 1)
- Produces: `PATCH /api/applications/{id}` accepting `{"stage": str}`, returning `application_detail`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracker.py`:

```python
# --- stages ----------------------------------------------------------------


def test_new_application_starts_saved(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    assert client.get(f"/api/applications/{aid}").json()["stage"] == "saved"


def test_set_stage(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    resp = client.patch(f"/api/applications/{aid}", json={"stage": "interview"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage"] == "interview"


def test_invalid_stage_is_rejected(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    resp = client.patch(f"/api/applications/{aid}", json={"stage": "ghosted"})
    assert resp.status_code == 422
    assert "ghosted" in resp.json()["detail"]


def test_applied_at_is_stamped_once(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    first = client.patch(f"/api/applications/{aid}", json={"stage": "applied"}).json()
    assert first["applied_at"] is not None

    client.patch(f"/api/applications/{aid}", json={"stage": "screening"})
    again = client.patch(f"/api/applications/{aid}", json={"stage": "applied"}).json()
    assert again["applied_at"] == first["applied_at"]


def test_stage_is_independent_of_status(client):
    """Regenerating a job you are interviewing for must not reset the funnel."""
    pid = make_profile(client)
    aid = make_application(client, pid)
    client.patch(f"/api/applications/{aid}", json={"stage": "interview"})

    resp = client.post(f"/api/applications/{aid}/retry")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert resp.json()["stage"] == "interview"


def set_status(client, application_id: int, status: str) -> None:
    """Force a generation status the pipeline would normally set. The pipeline
    is monkeypatched in these tests, so status is driven directly."""
    from sqlmodel import Session

    from backend.app.models import Application

    with Session(client.app.state.engine) as s:
        row = s.get(Application, application_id)
        row.status = status
        s.add(row)
        s.commit()


def test_cannot_move_a_generated_application_back_to_saved(client):
    """'saved' means no documents exist. Allowing it on a ready application
    would also break the migration backfill's idempotence, which identifies
    pre-migration rows precisely by ready + saved being impossible."""
    pid = make_profile(client)
    aid = make_application(client, pid)
    set_status(client, aid, "ready")

    resp = client.patch(f"/api/applications/{aid}", json={"stage": "saved"})
    assert resp.status_code == 422
    assert "saved" in resp.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracker.py -q -k stage or applied`
Expected: FAIL — 405 Method Not Allowed on PATCH.

- [ ] **Step 3: Implement the stage route**

In `backend/app/api/applications.py`, add the request body next to the others:

```python
class ApplicationPatch(BaseModel):
    stage: Optional[str] = None
```

Add the route after `get_application`:

```python
@router.patch("/applications/{application_id}")
def patch_application(
    application_id: int,
    body: ApplicationPatch,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Update tracker fields. `stage` is the job-hunt funnel and is deliberately
    independent of `status`, which is the generation pipeline."""
    app_row, job = _get_app_and_job(session, application_id)
    if body.stage is not None:
        if body.stage not in STAGES:
            raise HTTPException(
                status_code=422,
                detail=f"invalid stage {body.stage!r}; must be one of {list(STAGES)}",
            )
        if body.stage == "saved" and app_row.status == "ready":
            raise HTTPException(
                status_code=422,
                detail="cannot move a generated application back to 'saved'; "
                       "its documents already exist",
            )
        app_row.stage = body.stage
        if body.stage == "applied" and app_row.applied_at is None:
            app_row.applied_at = _utcnow()
        app_row.updated_at = _utcnow()
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
    return application_detail(session, app_row, job)
```

Add `stage`, `applied_at` and `archived_at` to the dict returned by `application_summary`, after `"status"`:

```python
        "stage": app_row.stage,
        "applied_at": app_row.applied_at.replace(tzinfo=timezone.utc).isoformat()
            if app_row.applied_at else None,
        "archived_at": app_row.archived_at.replace(tzinfo=timezone.utc).isoformat()
            if app_row.archived_at else None,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tracker.py -q`
Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/applications.py tests/test_tracker.py
git commit -m "feat: add application stage transitions with applied_at stamping"
```

---

### Task 4: Archive, restore, and list filtering

**Files:**
- Modify: `backend/app/api/applications.py`
- Test: `tests/test_tracker.py` (append)

**Interfaces:**
- Consumes: `Application.archived_at` (Task 1), `models.STAGES`
- Produces:
  - `POST /api/applications/{id}/archive -> application_detail`
  - `POST /api/applications/{id}/restore -> application_detail`
  - `GET /api/applications` gains query params `stage: Optional[str]`, `archived: bool = False`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracker.py`:

```python
# --- archive ---------------------------------------------------------------


def test_archive_hides_from_default_listing(client):
    pid = make_profile(client)
    aid = make_application(client, pid)

    assert client.post(f"/api/applications/{aid}/archive").status_code == 200
    assert [a["id"] for a in client.get("/api/applications").json()] == []


def test_archived_filter_shows_only_archived(client):
    pid = make_profile(client)
    kept = make_application(client, pid)
    gone = make_application(client, pid)
    client.post(f"/api/applications/{gone}/archive")

    archived = client.get("/api/applications?archived=true").json()
    assert [a["id"] for a in archived] == [gone]
    assert [a["id"] for a in client.get("/api/applications").json()] == [kept]


def test_restore_returns_it_to_the_default_listing(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    client.post(f"/api/applications/{aid}/archive")

    assert client.post(f"/api/applications/{aid}/restore").status_code == 200
    assert [a["id"] for a in client.get("/api/applications").json()] == [aid]


def test_stage_filter(client):
    pid = make_profile(client)
    a1 = make_application(client, pid)
    a2 = make_application(client, pid)
    client.patch(f"/api/applications/{a2}", json={"stage": "offer"})

    rows = client.get("/api/applications?stage=offer").json()
    assert [a["id"] for a in rows] == [a2]


def test_invalid_stage_filter_is_rejected(client):
    assert client.get("/api/applications?stage=nope").status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracker.py -q -k "archive or restore or filter"`
Expected: FAIL — 404 on the archive route.

- [ ] **Step 3: Implement archive, restore, and filtering**

Add the two routes after `patch_application`:

```python
@router.post("/applications/{application_id}/archive")
def archive_application(
    application_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Reversible removal: drops off the dashboard, keeps rows and exports."""
    app_row, job = _get_app_and_job(session, application_id)
    app_row.archived_at = _utcnow()
    app_row.updated_at = _utcnow()
    session.add(app_row)
    session.commit()
    session.refresh(app_row)
    return application_detail(session, app_row, job)


@router.post("/applications/{application_id}/restore")
def restore_application(
    application_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    app_row, job = _get_app_and_job(session, application_id)
    app_row.archived_at = None
    app_row.updated_at = _utcnow()
    session.add(app_row)
    session.commit()
    session.refresh(app_row)
    return application_detail(session, app_row, job)
```

Replace the signature and filter block of `list_applications`:

```python
@router.get("/applications")
def list_applications(
    profile_id: Optional[int] = None,
    stage: Optional[str] = None,
    archived: bool = False,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    if stage is not None and stage not in STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid stage {stage!r}; must be one of {list(STAGES)}",
        )
    stmt = select(Application)
    if profile_id is not None:
        stmt = stmt.where(Application.profile_id == profile_id)
    if stage is not None:
        stmt = stmt.where(Application.stage == stage)
    if archived:
        stmt = stmt.where(Application.archived_at.is_not(None))
    else:
        stmt = stmt.where(Application.archived_at.is_(None))
    rows = session.exec(stmt.order_by(Application.id.desc())).all()
```

The rest of the function body is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tracker.py -q`
Expected: PASS, 18 tests.

- [ ] **Step 5: Run the full backend suite**

Run: `python -m pytest tests/ -q`
Expected: PASS. Existing `GET /api/applications` tests still pass because unarchived rows are the default.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/applications.py tests/test_tracker.py
git commit -m "feat: add archive/restore and stage filtering for applications"
```

---

### Task 5: Permanent delete

The only destructive filesystem operation in the codebase. Handle it accordingly.

**Files:**
- Modify: `backend/app/api/applications.py`
- Test: `tests/test_tracker.py` (append)

**Interfaces:**
- Consumes: `models.ApplicationEvent`, `models.ApplicationVersion`
- Produces:
  - `DELETE /api/applications/{id} -> {"deleted": int}`
  - `applications._remove_export_dir(data_dir: Path, application_id: int) -> None`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracker.py`:

```python
# --- permanent delete ------------------------------------------------------


def test_delete_removes_rows_and_exports(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    client.post(f"/api/applications/{aid}/events", json={"kind": "note", "body": "x"})

    export_dir = client.data_dir / "exports" / str(aid)
    export_dir.mkdir(parents=True)
    (export_dir / "resume.pdf").write_bytes(b"%PDF-1.4")

    resp = client.delete(f"/api/applications/{aid}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": aid}

    assert client.get(f"/api/applications/{aid}").status_code == 404
    assert not export_dir.exists()


def test_delete_leaves_other_export_directories_alone(client):
    pid = make_profile(client)
    doomed = make_application(client, pid)
    kept = make_application(client, pid)

    for aid in (doomed, kept):
        d = client.data_dir / "exports" / str(aid)
        d.mkdir(parents=True)
        (d / "resume.pdf").write_bytes(b"%PDF-1.4")

    client.delete(f"/api/applications/{doomed}")

    assert not (client.data_dir / "exports" / str(doomed)).exists()
    assert (client.data_dir / "exports" / str(kept) / "resume.pdf").is_file()


def test_delete_with_no_export_directory_succeeds(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    assert client.delete(f"/api/applications/{aid}").status_code == 200


def test_delete_is_refused_mid_pipeline(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    set_status(client, aid, "tailoring")  # helper defined in the stage section

    resp = client.delete(f"/api/applications/{aid}")
    assert resp.status_code == 409
    assert "tailoring" in resp.json()["detail"]


def test_delete_removes_timeline_rows(client):
    from sqlmodel import Session, select
    from backend.app.models import ApplicationEvent

    pid = make_profile(client)
    aid = make_application(client, pid)
    client.post(f"/api/applications/{aid}/events", json={"kind": "note", "body": "x"})

    client.delete(f"/api/applications/{aid}")

    with Session(client.app.state.engine) as s:
        remaining = s.exec(
            select(ApplicationEvent).where(ApplicationEvent.application_id == aid)
        ).all()
    assert remaining == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracker.py -q -k delete`
Expected: FAIL — 405 Method Not Allowed on DELETE.

- [ ] **Step 3: Implement permanent delete**

Add `import shutil` to the imports at the top of `backend/app/api/applications.py`.

Add the helper next to `_get_app_and_job`:

```python
def _remove_export_dir(data_dir: Path, application_id: int) -> None:
    """Delete data/exports/<application_id>/ recursively.

    The path is rebuilt from data_dir and the integer id -- never from the
    stored Application.export_dir string, which is user-visible state that
    could be stale or wrong. The containment check is defence in depth: it is
    unreachable through the route because application_id is typed int, but it
    protects any future caller.

    A missing directory is not an error.
    """
    data_dir = Path(data_dir).resolve()
    target = (data_dir / "exports" / str(application_id)).resolve()
    if not target.is_dir():
        return
    if data_dir not in target.parents:
        raise HTTPException(
            status_code=500, detail="refusing to delete outside the data directory"
        )
    shutil.rmtree(target)
```

Add the route at the end of the file:

```python
@router.delete("/applications/{application_id}")
def delete_application(
    application_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Permanent, unrecoverable delete: rows, versions, timeline, and the
    exported files on disk. The reversible path is /archive."""
    app_row, _job = _get_app_and_job(session, application_id)
    if app_row.status in PROCESSING_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"application is currently {app_row.status}; wait for it to finish",
        )

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

    _remove_export_dir(request.app.state.settings.data_dir, application_id)
    return {"deleted": application_id}
```

The `Job` row is intentionally left in place — it is shared state, and orphan cleanup is out of scope per spec §9.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tracker.py -q`
Expected: PASS, 23 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/applications.py tests/test_tracker.py
git commit -m "feat: add permanent application delete with export cleanup"
```

---

### Task 6: Saved jobs that cost nothing

**Files:**
- Modify: `backend/app/api/applications.py`
- Modify: `backend/app/services/pipeline.py`
- Modify: `backend/mcp_ops.py`
- Test: `tests/test_tracker.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1–5
- Produces:
  - `BatchRequest.generate: bool = True`
  - New generation status `"not_started"`
  - `POST /api/applications/{id}/generate -> application_detail`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracker.py`:

```python
# --- saved jobs ------------------------------------------------------------


def test_generate_false_creates_saved_job_without_running_anything(client):
    pid = make_profile(client)
    resp = client.post("/api/applications/batch", json={
        "profile_id": pid,
        "jobs": [{"url": "https://example.com/a"}, {"url": "https://example.com/b"}],
        "generate": False,
    })
    assert resp.status_code == 200, resp.text

    rows = resp.json()
    assert [r["status"] for r in rows] == ["not_started", "not_started"]
    assert [r["stage"] for r in rows] == ["saved", "saved"]
    assert client.calls["process"] == []  # nothing queued, nothing spent


def test_generate_defaults_to_true(client):
    pid = make_profile(client)
    aid = make_application(client, pid)
    assert client.calls["process"] == [aid]


def test_generate_endpoint_starts_a_saved_job(client):
    pid = make_profile(client)
    aid = client.post("/api/applications/batch", json={
        "profile_id": pid,
        "jobs": [{"url": "https://example.com/a"}],
        "generate": False,
    }).json()[0]["id"]

    resp = client.post(f"/api/applications/{aid}/generate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"
    assert client.calls["process"] == [aid]


def test_generate_endpoint_refuses_an_already_started_job(client):
    pid = make_profile(client)
    aid = make_application(client, pid)  # status 'queued'

    resp = client.post(f"/api/applications/{aid}/generate")
    assert resp.status_code == 409
    assert "not_started" in resp.json()["detail"]


def test_not_started_jobs_are_deletable_and_archivable(client):
    pid = make_profile(client)
    aid = client.post("/api/applications/batch", json={
        "profile_id": pid,
        "jobs": [{"url": "https://example.com/a"}],
        "generate": False,
    }).json()[0]["id"]

    assert client.post(f"/api/applications/{aid}/archive").status_code == 200
    assert client.delete(f"/api/applications/{aid}").status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracker.py -q -k "saved or generate"`
Expected: FAIL — `generate` is ignored, status comes back `"queued"`.

- [ ] **Step 3: Implement saved jobs**

In `backend/app/api/applications.py`, add the field to `BatchRequest`:

```python
class BatchRequest(BaseModel):
    profile_id: int
    jobs: list[BatchJobIn]
    default_depth: Optional[str] = None
    default_template: Optional[str] = None
    generate: bool = True
```

In `create_batch`, replace the creation loop body:

```python
    results: list[dict[str, Any]] = []
    for url, depth, template in resolved:
        job = Job(url=url, depth=depth)
        session.add(job)
        session.commit()
        session.refresh(job)
        app_row = Application(
            profile_id=body.profile_id,
            job_id=job.id,
            template=template,
            status="queued" if body.generate else "not_started",
        )
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
        if body.generate:
            # Schedule through the module attribute so tests can monkeypatch pipeline.
            background_tasks.add_task(pipeline.process_application, app_row.id)
        results.append(application_detail(session, app_row, job))
    return results
```

Add the route after `retry`:

```python
@router.post("/applications/{application_id}/generate")
def generate(
    application_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Start the pipeline for a saved job. /retry covers every other state."""
    app_row, job = _get_app_and_job(session, application_id)
    if app_row.status != "not_started":
        raise HTTPException(
            status_code=409,
            detail=f"application is {app_row.status!r}, not 'not_started'; "
                   "use /retry to re-run it",
        )
    app_row.status = "queued"
    app_row.error_message = None
    app_row.updated_at = _utcnow()
    session.add(app_row)
    session.commit()
    session.refresh(app_row)
    background_tasks.add_task(pipeline.process_application, app_row.id)
    return application_detail(session, app_row, job)
```

In `backend/app/services/pipeline.py`, find the final `_set_status(session, app, "ready")` at the end of the render step and insert the stage advance immediately above it:

```python
    # The one place status drives stage: finishing generation moves a parked
    # job to drafted. Any other stage is the user's and is left alone.
    if app.stage == "saved":
        app.stage = "drafted"
        session.add(app)
        session.commit()

    _set_status(session, app, "ready")
```

In `backend/mcp_ops.py`, apply the same advance in `save_tailored_resume`, immediately before the call that sets the application's status to `"ready"`. Without it, every MCP-generated application stays in `saved` forever:

```python
        if app.stage == "saved":
            app.stage = "drafted"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tracker.py -q`
Expected: PASS, 28 tests.

- [ ] **Step 5: Run the full backend suite**

Run: `python -m pytest tests/ -q`
Expected: PASS. `generate` defaults to `True`, so every existing batch test is unaffected.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/applications.py backend/app/services/pipeline.py backend/mcp_ops.py tests/test_tracker.py
git commit -m "feat: add saved jobs that cost nothing until generated"
```

---

### Task 7: Frontend types, API client, and the polling fix

Small but load-bearing: `not_started` must terminate polling or the dashboard hammers the backend forever.

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/screens/DashboardScreen.tsx:6`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/screens/DashboardScreen.test.tsx` (append)

**Interfaces:**
- Consumes: the endpoints from Tasks 2–6
- Produces:
  - `types.Stage`, `types.EventKind`, `types.ApplicationEvent`
  - `types.AppStatus` gains `"not_started"`
  - `api.patchApplication`, `api.archiveApplication`, `api.restoreApplication`, `api.deleteApplication`, `api.generateApplication`, `api.listEvents`, `api.addEvent`, `api.deleteEvent`

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/screens/DashboardScreen.test.tsx`:

```tsx
it("stops polling when every application is in a terminal state", async () => {
  vi.useFakeTimers();
  vi.mocked(api.listApplications).mockResolvedValue([
    { ...BASE_APP, id: 1, status: "not_started", stage: "saved" },
  ]);

  render(<MemoryRouter><DashboardScreen /></MemoryRouter>);
  await vi.advanceTimersByTimeAsync(0);
  const callsAfterFirstTick = vi.mocked(api.listApplications).mock.calls.length;

  await vi.advanceTimersByTimeAsync(10_000);

  expect(vi.mocked(api.listApplications).mock.calls.length).toBe(callsAfterFirstTick);
  vi.useRealTimers();
});
```

If `BASE_APP` does not already exist in that file, define it from the existing inline fixture object at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm test -- --run DashboardScreen`
Expected: FAIL — the poll count keeps rising because `not_started` is not terminal.

- [ ] **Step 3: Update types**

In `frontend/src/types.ts`, add `"not_started"` to `AppStatus`:

```ts
export type AppStatus =
  | "not_started"
  | "queued"
  | "fetching"
  | "researching"
  | "tailoring"
  | "rendering"
  | "ready"
  | "needs_paste"
  | "error";

export type Stage =
  | "saved"
  | "drafted"
  | "applied"
  | "screening"
  | "interview"
  | "offer"
  | "rejected"
  | "withdrawn";

export type EventKind =
  | "applied"
  | "callback"
  | "interview"
  | "offer"
  | "rejection"
  | "followup"
  | "note";

export interface ApplicationEvent {
  id: number;
  application_id: number;
  kind: EventKind;
  body: string;
  occurred_at: string;
  created_at: string;
}
```

Add to `ApplicationSummary`:

```ts
  stage: Stage;
  applied_at: string | null;
  archived_at: string | null;
  last_activity_at: string;
```

Add to `ApplicationDetail`:

```ts
  events: ApplicationEvent[];
```

Add to `JobRequest`'s containing batch call — no change needed there; `generate` is passed separately in Task 8.

- [ ] **Step 4: Add the API client functions**

In `frontend/src/api.ts`, import `ApplicationEvent`, `EventKind` and `Stage` from `./types`, then add after `createApplications`:

```ts
export function patchApplication(id: number, patch: { stage?: Stage }): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}`, jsonInit("PATCH", patch));
}

export function archiveApplication(id: number): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/archive`, { method: "POST" });
}

export function restoreApplication(id: number): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/restore`, { method: "POST" });
}

export function deleteApplication(id: number): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/applications/${id}`, { method: "DELETE" });
}

export function generateApplication(id: number): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/generate`, { method: "POST" });
}

export function listEvents(id: number): Promise<ApplicationEvent[]> {
  return request<ApplicationEvent[]>(`/applications/${id}/events`);
}

export function addEvent(
  id: number,
  event: { kind: EventKind; body: string; occurred_at?: string }
): Promise<ApplicationEvent> {
  return request<ApplicationEvent>(`/applications/${id}/events`, jsonInit("POST", event));
}

export function deleteEvent(id: number, eventId: number): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/applications/${id}/events/${eventId}`, {
    method: "DELETE",
  });
}
```

Change `listApplications` to carry the filters:

```ts
export function listApplications(
  profileId?: number,
  opts?: { stage?: Stage; archived?: boolean }
): Promise<ApplicationSummary[]> {
  const params = new URLSearchParams();
  if (profileId !== undefined) params.set("profile_id", String(profileId));
  if (opts?.stage) params.set("stage", opts.stage);
  if (opts?.archived) params.set("archived", "true");
  const qs = params.toString();
  return request<ApplicationSummary[]>(`/applications${qs ? `?${qs}` : ""}`);
}
```

- [ ] **Step 5: Fix the polling terminal set and add the badge style**

In `frontend/src/screens/DashboardScreen.tsx` line 6:

```tsx
const TERMINAL: AppStatus[] = ["not_started", "ready", "error", "needs_paste"];
```

In `frontend/src/styles.css`, add beside the other badge rules (after `.badge-queued`):

```css
.badge-not_started { background: #F5F5F4; color: #78716C; }  /* stone, dimmer than queued */
```

and in the dark block, after `.badge-queued`:

```css
:root[data-theme="dark"] .badge-not_started { background: rgba(168, 162, 158, 0.14); color: #A8A29E; }
```

- [ ] **Step 6: Run tests to verify they pass**

Run (from `frontend/`): `npm test -- --run`
Expected: PASS.

- [ ] **Step 7: Type-check**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no errors. Existing test fixtures that build `ApplicationSummary` objects will need the four new fields — add them.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/screens/DashboardScreen.tsx frontend/src/screens/DashboardScreen.test.tsx frontend/src/styles.css
git commit -m "feat: add tracker types and API client, stop polling on not_started"
```

---

### Task 8: Dashboard tracker table

**Files:**
- Modify: `frontend/src/screens/DashboardScreen.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/screens/DashboardScreen.test.tsx` (append)

**Interfaces:**
- Consumes: everything from Task 7
- Produces: no exported API beyond the default component and the existing `usePolling`

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/screens/DashboardScreen.test.tsx`:

```tsx
it("filters to archived applications when the tab is selected", async () => {
  vi.mocked(api.listApplications).mockResolvedValue([{ ...BASE_APP, id: 1 }]);
  render(<MemoryRouter><DashboardScreen /></MemoryRouter>);

  await userEvent.click(await screen.findByRole("button", { name: /archived/i }));

  await waitFor(() =>
    expect(api.listApplications).toHaveBeenCalledWith(undefined, { archived: true })
  );
});

it("changes stage from the row without opening the application", async () => {
  vi.mocked(api.listApplications).mockResolvedValue([
    { ...BASE_APP, id: 7, stage: "applied" },
  ]);
  vi.mocked(api.patchApplication).mockResolvedValue({ ...BASE_APP, id: 7, stage: "interview" } as never);
  render(<MemoryRouter><DashboardScreen /></MemoryRouter>);

  const select = await screen.findByLabelText(/stage for row 1/i);
  await userEvent.selectOptions(select, "interview");

  expect(api.patchApplication).toHaveBeenCalledWith(7, { stage: "interview" });
});

it("asks for confirmation naming the role before deleting", async () => {
  vi.mocked(api.listApplications).mockResolvedValue([
    { ...BASE_APP, id: 3, company: "Initech", title: "Staff Engineer" },
  ]);
  render(<MemoryRouter><DashboardScreen /></MemoryRouter>);

  await userEvent.click(await screen.findByLabelText(/select row 1/i));
  await userEvent.click(screen.getByRole("button", { name: /delete permanently/i }));

  expect(screen.getByRole("dialog")).toHaveTextContent("Initech");
  expect(screen.getByRole("dialog")).toHaveTextContent("Staff Engineer");
  expect(api.deleteApplication).not.toHaveBeenCalled();
});
```

Add `api.patchApplication`, `api.archiveApplication`, `api.deleteApplication` and `api.generateApplication` to the `vi.mock("../api", ...)` factory at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm test -- --run DashboardScreen`
Expected: FAIL — no Archived tab, no stage select, no confirmation dialog.

- [ ] **Step 3: Rewrite `DashboardScreen.tsx`**

Replace the file with:

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
import type { ApplicationSummary, AppStatus, ProfileSummary, Stage } from "../types";

const TERMINAL: AppStatus[] = ["not_started", "ready", "error", "needs_paste"];

const STAGES: Stage[] = [
  "saved", "drafted", "applied", "screening",
  "interview", "offer", "rejected", "withdrawn",
];

const STAGE_LABELS: Record<Stage, string> = {
  saved: "Saved",
  drafted: "Drafted",
  applied: "Applied",
  screening: "Screening",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

const TERMINAL_STAGES: Stage[] = ["rejected", "withdrawn"];

type Tab = "all" | "saved" | "active" | "archived";

const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "saved", label: "Saved" },
  { key: "active", label: "Active" },
  { key: "archived", label: "Archived" },
];

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
        active = list.some((a) => !TERMINAL.includes(a.status));
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

function StatusBadge({ app }: { app: ApplicationSummary }) {
  if (app.status === "needs_paste") {
    return (
      <Link to={`/applications/${app.id}`} className="badge badge-needs_paste">
        Paste required
      </Link>
    );
  }
  return <span className={`badge badge-${app.status}`}>{app.status.replace("_", " ")}</span>;
}

function visible(apps: ApplicationSummary[], tab: Tab): ApplicationSummary[] {
  if (tab === "saved") return apps.filter((a) => a.stage === "saved");
  if (tab === "active") {
    return apps.filter((a) => !TERMINAL_STAGES.includes(a.stage));
  }
  return apps;
}

export default function DashboardScreen() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [profileId, setProfileId] = useState<number | undefined>(undefined);
  const [tab, setTab] = useState<Tab>("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirming, setConfirming] = useState<ApplicationSummary[] | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const apps = usePolling(profileId, tab === "archived", reloadKey);
  const rows = visible(apps, tab);
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
      reload();
    } catch (e) {
      setError(String(e));
    }
  }

  function toggle(id: number) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const chosen = rows.filter((a) => selected.has(a.id));

  return (
    <div>
      <h1>Dashboard</h1>
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
        {TABS.map((t) => (
          <button
            key={t.key}
            className={t.key === tab ? "tab active" : "tab"}
            onClick={() => setTab(t.key)}
          >
            {t.label}
            {t.key === tab && <span className="tab-count"> {rows.length}</span>}
          </button>
        ))}
      </div>

      {chosen.length > 0 && (
        <div className="row bulk-bar">
          <span className="muted">{chosen.length} selected</span>
          {tab === "archived" ? (
            <button
              className="btn"
              onClick={() => run(() => Promise.all(chosen.map((a) => restoreApplication(a.id))))}
            >
              Restore
            </button>
          ) : (
            <button
              className="btn"
              onClick={() => run(() => Promise.all(chosen.map((a) => archiveApplication(a.id))))}
            >
              Archive
            </button>
          )}
          <button className="btn btn-danger" onClick={() => setConfirming(chosen)}>
            Delete permanently
          </button>
        </div>
      )}

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th />
              <th>Company</th>
              <th>Role</th>
              <th>Stage</th>
              <th>Status</th>
              <th>Applied</th>
              <th>Last activity</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a, i) => (
              <tr key={a.id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Select row ${i + 1}`}
                    checked={selected.has(a.id)}
                    onChange={() => toggle(a.id)}
                  />
                </td>
                <td>{a.company ? a.company : a.url}</td>
                <td>{a.title ?? ""}</td>
                <td>
                  <select
                    className="select select-inline"
                    aria-label={`Stage for row ${i + 1}`}
                    value={a.stage}
                    onChange={(e) =>
                      run(() => patchApplication(a.id, { stage: e.target.value as Stage }))
                    }
                  >
                    {STAGES.map((s) => (
                      <option key={s} value={s}>{STAGE_LABELS[s]}</option>
                    ))}
                  </select>
                </td>
                <td><StatusBadge app={a} /></td>
                <td>{a.applied_at ? new Date(a.applied_at).toLocaleDateString() : ""}</td>
                <td>{new Date(a.last_activity_at).toLocaleDateString()}</td>
                <td>
                  {a.status === "not_started" && (
                    <button
                      className="btn btn-small"
                      onClick={() => run(() => generateApplication(a.id))}
                    >
                      Generate
                    </button>
                  )}{" "}
                  <Link to={`/applications/${a.id}`}>Open</Link>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  {tab === "archived" ? (
                    "Nothing archived."
                  ) : (
                    <>
                      No applications yet. New here? Start with{" "}
                      <Link to="/getting-started">Getting Started</Link>, or{" "}
                      <Link to="/profiles">create your Master Profile</Link> and then{" "}
                      <Link to="/add">add job URLs</Link>.
                    </>
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {confirming && (
        <div className="modal-backdrop">
          <div className="card modal" role="dialog" aria-label="Confirm permanent delete">
            <div className="card-title">Delete permanently?</div>
            <p>
              This deletes {confirming.length === 1 ? "this application" : "these applications"},
              {" "}their timeline, and the exported PDF and HTML files on disk. It cannot be undone.
            </p>
            <ul>
              {confirming.map((a) => (
                <li key={a.id}>
                  {a.company ?? a.url}
                  {a.title ? ` — ${a.title}` : ""}
                </li>
              ))}
            </ul>
            <div className="row">
              <button className="btn" onClick={() => setConfirming(null)}>Cancel</button>
              <button
                className="btn btn-danger"
                onClick={() => {
                  const targets = confirming;
                  setConfirming(null);
                  setSelected(new Set());
                  run(() => Promise.all(targets.map((a) => deleteApplication(a.id))));
                }}
              >
                Delete permanently
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

Note the em dash in the confirmation list is UI copy, not generated resume text — spec 4's voice contract applies only to model output.

- [ ] **Step 4: Add the supporting styles**

Append to `frontend/src/styles.css`:

```css
/* ---- tracker: tab counts, bulk bar, inline controls, confirm modal ---- */
.tab-count { opacity: 0.6; }
.bulk-bar { align-items: center; gap: 0.75rem; margin-bottom: 0.75rem; }
.select-inline { padding: 0.15rem 0.4rem; font-size: var(--fs-xs); width: auto; }
.btn-small { padding: 0.15rem 0.5rem; font-size: var(--fs-xs); }
.modal-backdrop {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal { max-width: 32rem; margin: 0; }
```

**Do not redefine `.tabs`, `.tab`, `.tab.active` or `.btn-danger`** — all four already
exist in `styles.css` (lines 114 and 169–176) and the component above reuses them.
That is why the tab buttons use `className="tab active"` rather than a new modifier
class. The verified custom properties in this file are `--bg`, `--surface`, `--ink`,
`--muted`, `--accent`, `--danger`, `--border`, `--radius`, `--shadow` and the
`--fs-*` scale; there is no `--fg`, `--fg-muted` or `--surface-2`.

- [ ] **Step 5: Run tests to verify they pass**

Run (from `frontend/`): `npm test -- --run`
Expected: PASS.

- [ ] **Step 6: Type-check**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/screens/DashboardScreen.tsx frontend/src/screens/DashboardScreen.test.tsx frontend/src/styles.css
git commit -m "feat: rebuild the dashboard as a job tracker table"
```

---

### Task 9: Application screen timeline panel

**Files:**
- Modify: `frontend/src/screens/ApplicationScreen.tsx`
- Test: `frontend/src/screens/ApplicationScreen.test.tsx` (append)

**Interfaces:**
- Consumes: `api.listEvents`, `api.addEvent`, `api.deleteEvent`, `api.patchApplication` (Task 7); `ApplicationDetail.events` (Task 2)
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/screens/ApplicationScreen.test.tsx`:

```tsx
it("logs a timeline entry", async () => {
  vi.mocked(api.addEvent).mockResolvedValue({
    id: 1, application_id: 1, kind: "callback",
    body: "Recruiter called", occurred_at: "2026-07-01T00:00:00+00:00",
    created_at: "2026-07-01T00:00:00+00:00",
  });
  renderScreen();

  await userEvent.selectOptions(await screen.findByLabelText(/entry type/i), "callback");
  await userEvent.type(screen.getByLabelText(/entry note/i), "Recruiter called");
  await userEvent.click(screen.getByRole("button", { name: /add to timeline/i }));

  expect(api.addEvent).toHaveBeenCalledWith(
    1,
    expect.objectContaining({ kind: "callback", body: "Recruiter called" })
  );
});

it("changes stage from the application screen", async () => {
  renderScreen();
  await userEvent.selectOptions(await screen.findByLabelText(/stage/i), "offer");
  expect(api.patchApplication).toHaveBeenCalledWith(1, { stage: "offer" });
});
```

Extend the existing `ApplicationScreen.test.tsx` detail fixture with `stage: "applied"`, `applied_at: null`, `archived_at: null`, `last_activity_at: "2026-07-01T00:00:00+00:00"`, and `events: []`. Add `addEvent`, `deleteEvent`, `listEvents` and `patchApplication` to the `vi.mock("../api", ...)` factory.

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm test -- --run ApplicationScreen`
Expected: FAIL — no timeline controls exist.

- [ ] **Step 3: Add the timeline panel**

In `frontend/src/screens/ApplicationScreen.tsx`, import `addEvent`, `deleteEvent`, `patchApplication` from `../api` and `EventKind`, `Stage`, `ApplicationEvent` from `../types`.

Add these module-level constants near the top:

```tsx
const EVENT_KINDS: EventKind[] = [
  "note", "applied", "callback", "interview", "offer", "rejection", "followup",
];

const STAGES: Stage[] = [
  "saved", "drafted", "applied", "screening",
  "interview", "offer", "rejected", "withdrawn",
];
```

Add this component in the same file, above the default export:

```tsx
function Timeline({
  applicationId,
  events,
  onChanged,
}: {
  applicationId: number;
  events: ApplicationEvent[];
  onChanged: () => void;
}) {
  const [kind, setKind] = useState<EventKind>("note");
  const [body, setBody] = useState("");
  const [when, setWhen] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      await addEvent(applicationId, {
        kind,
        body,
        occurred_at: when ? new Date(when).toISOString() : undefined,
      });
      setBody("");
      setWhen("");
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title">Timeline</div>
      <div className="row">
        <div className="field">
          <label className="field-label" htmlFor="event-kind">Entry type</label>
          <select
            id="event-kind"
            className="select"
            value={kind}
            onChange={(e) => setKind(e.target.value as EventKind)}
          >
            {EVENT_KINDS.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="event-date">Date</label>
          <input
            id="event-date"
            className="input"
            type="date"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
          />
        </div>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="event-body">Entry note</label>
        <textarea
          id="event-body"
          className="textarea"
          rows={2}
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
      </div>
      <button className="btn btn-primary" disabled={busy} onClick={submit}>
        Add to timeline
      </button>

      <ul className="timeline">
        {events.map((e) => (
          <li key={e.id}>
            <span className={`badge badge-${e.kind}`}>{e.kind}</span>{" "}
            <span className="muted">{new Date(e.occurred_at).toLocaleDateString()}</span>{" "}
            {e.body}{" "}
            <button
              className="btn btn-small"
              aria-label={`Delete timeline entry ${e.id}`}
              onClick={async () => {
                await deleteEvent(applicationId, e.id);
                onChanged();
              }}
            >
              Remove
            </button>
          </li>
        ))}
        {events.length === 0 && <li className="muted">Nothing logged yet.</li>}
      </ul>
    </div>
  );
}
```

Render `<Timeline applicationId={detail.id} events={detail.events} onChanged={reload} />` below the existing content, where `reload` is the screen's existing detail-refetch function. Add a stage selector to the metadata area:

```tsx
<div className="field" style={{ maxWidth: "14rem" }}>
  <label className="field-label" htmlFor="app-stage">Stage</label>
  <select
    id="app-stage"
    className="select"
    value={detail.stage}
    onChange={async (e) => {
      await patchApplication(detail.id, { stage: e.target.value as Stage });
      reload();
    }}
  >
    {STAGES.map((s) => (
      <option key={s} value={s}>{s}</option>
    ))}
  </select>
</div>
```

- [ ] **Step 4: Add timeline styles**

Append to `frontend/src/styles.css`:

```css
.timeline { list-style: none; margin-top: 1rem; padding: 0; }
.timeline li { padding: 0.4rem 0; border-top: 1px solid var(--border); }
.badge-note, .badge-followup { background: #F5F5F4; color: #57534E; }
.badge-callback, .badge-interview { background: #DBEAFE; color: #1D4ED8; }
.badge-applied { background: #EDE9FE; color: #6D28D9; }
.badge-offer { background: #D1FAE5; color: #047857; }
.badge-rejection { background: #FEE2E2; color: #B91C1C; }
```

- [ ] **Step 5: Run tests to verify they pass**

Run (from `frontend/`): `npm test -- --run`
Expected: PASS.

- [ ] **Step 6: Type-check**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/screens/ApplicationScreen.tsx frontend/src/screens/ApplicationScreen.test.tsx frontend/src/styles.css
git commit -m "feat: add timeline panel and stage selector to the application screen"
```

---

### Task 10: Rebuild the bundle and update the docs

The repo commits `frontend/dist` so that cloning needs only Python. An un-rebuilt bundle means none of Tasks 7–9 reach the running app.

**Files:**
- Modify: `frontend/dist/**` (generated)
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1–9
- Produces: nothing

- [ ] **Step 1: Run the whole test suite, both sides**

Run: `python -m pytest tests/ -q`
Run (from `frontend/`): `npm test -- --run && npx tsc --noEmit`
Expected: PASS on all three. Do not proceed past a failure.

- [ ] **Step 2: Rebuild the frontend bundle**

Run (from `frontend/`): `npm run build`
Expected: writes `frontend/dist/`.

- [ ] **Step 3: Verify the built app serves and the tracker works end to end**

Run: `python run.py`

Then in the browser: add two URLs with the "Save without generating" path, confirm they appear as Saved with a Generate button, change one stage to Applied, log a callback on it, archive the other, check the Archived tab, and restore it. Confirm the dashboard is not issuing a request every two seconds while only saved jobs are present — check the network tab.

- [ ] **Step 4: Update the README**

In `README.md`, the Highlights and pipeline sections describe the dashboard as a status list. Add a bullet to Highlights:

```markdown
- **It tracks the job hunt, not just the generation.** Stages from Saved through Offer, a dated timeline for callbacks, interviews and notes, archive and permanent delete, and saved jobs you can park for free and generate later.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/dist README.md
git commit -m "chore: rebuild frontend bundle and document the job tracker"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §2.1 status/stage orthogonality | 1, 3 (`test_stage_is_independent_of_status`) |
| §2.2 / §4.4 migration | 1 |
| §4.1 columns and `STAGES` | 1 |
| §4.2 `ApplicationEvent` | 1 (model), 2 (API) |
| §4.3 `applied_at` stamping, `saved → drafted` | 3, 6 |
| §5 saved jobs, `generate` flag | 6 |
| §5.1 polling terminal set, `AppStatus`, badge CSS | 7 |
| §6 API surface | 2, 3, 4, 5, 6 |
| §6.1 permanent delete, path containment | 5 |
| §7.1 dashboard | 8 |
| §7.2 application screen | 9 |
| §8 testing | every task |

**Deviations from the spec, deliberate:**

1. Spec §4.4 says a wrong-typed existing column is "reported, not fixed". Task 1 implements *never modified* and does not report, because SQLite's type affinity (`VARCHAR` vs `TEXT` vs no type) makes comparison a false-positive generator. The safety property the spec wanted — never silently alter existing data — holds.
2. Task 3 adds a rule the spec does not state: `PATCH` refuses `stage="saved"` on a `ready` application. This is required for the §4.4 backfill to be idempotent, since the backfill identifies pre-migration rows precisely by the `ready` + `saved` combination being otherwise impossible.
3. Task 6 also advances `saved → drafted` in `backend/mcp_ops.py`. The spec only names the pipeline; without this, MCP-generated applications would sit in `saved` forever.

**Type consistency:** `Stage`, `EventKind` and `ApplicationEvent` are defined once in Task 7 and used unchanged in Tasks 8 and 9. `STAGES` exists as `models.STAGES` (backend, Task 1) and as a `Stage[]` literal in both frontend screens — duplicated deliberately rather than fetched, matching how the codebase already handles `DEPTHS`. `application_summary`'s third parameter is optional so the call in
`application_detail` stays two-argument. (An earlier draft of this line claimed
`backend/mcp_ops.py` calls it — it does not; `mcp_ops` builds its own response
dicts. The function's only callers are both inside `api/applications.py`.)

**Placeholder scan:** none. Every step carries the code it needs.

**Style-collision check (run against `frontend/src/styles.css` after drafting):**
the first draft of Task 8 invented `.tab-row`, `.tab-active` and a `.btn-danger`
override. All three collided with existing rules — the file already defines
`.tabs` / `.tab` / `.tab.active` (lines 169–176) and `.btn-danger` (line 114) —
and the draft also used three custom properties (`--fg`, `--fg-muted`,
`--surface-2`) that do not exist. Task 8 now reuses the existing classes, Task 9
uses the existing `.textarea` class rather than `.input`, and only genuinely new
rules are added. Verified: `--bg`, `--surface`, `--ink`, `--muted`, `--accent`,
`--danger`, `--border`, `--radius`, `--shadow`, `--fs-xs..--fs-2xl`.
