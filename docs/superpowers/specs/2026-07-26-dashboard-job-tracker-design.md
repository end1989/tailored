# Tailored — Dashboard as a Job Tracker — Design Spec

Date: 2026-07-26
Status: approved
Depends on: nothing
Depended on by: spec 2 (MCP queue reuses the saved/not_started model),
spec 4 (voice_notes column reuses the migration helper)

## 1. What this is

The dashboard is currently a read-only render of the generation pipeline. It
lists applications, shows how far Claude got, and links to each one. Nothing
can be removed, no progress can be recorded, and there is nowhere to write down
that a recruiter called.

This spec turns it into a job application tracker: stages, a dated timeline,
notes, archive and delete, and the ability to park a job you are considering
without paying to tailor it.

## 2. Two findings that shape the design

### 2.1 `Application.status` is not a tracker status

`status` is the generation pipeline: `queued → fetching → researching →
tailoring → rendering → ready`, plus `error` and `needs_paste`. It answers
"did the AI finish writing the documents," not "where do I stand with this
employer."

Overloading it would break the first time you regenerate a resume for a job you
have already interviewed for — the regeneration would reset your funnel
position to `queued`.

The tracker therefore gets a second, orthogonal axis, `stage`, which moves
independently. An application can be `ready` (documents done) and `interview`
(funnel position) simultaneously. These two fields are never derived from each
other, with exactly one exception documented in §4.3.

### 2.2 There is no migration system

`init_db` calls `SQLModel.metadata.create_all(engine)` and nothing else
(`backend/app/db.py:35`). There is no Alembic, no `ALTER TABLE` anywhere in the
codebase.

`create_all` creates *missing tables*. It does **not** add *columns to existing
tables*. So a new `ApplicationEvent` table would appear correctly, while new
columns on `Application` would be silently absent from any existing
`data/tailored.db`, and the first dashboard query would fail with
`OperationalError: no such column: application.stage`.

This spec must therefore carry a migration step, or it breaks live user data on
first run. That helper becomes shared infrastructure — spec 4 depends on it too.

## 3. Decisions

| Decision | Choice |
|---|---|
| Funnel | Full, starting before you apply — includes a `saved` stage |
| Saved jobs | Cost nothing: no pipeline run, no Claude call |
| Removal | Archive by default (reversible); permanent delete as a separate confirmed action |
| Notes vs events | One timeline table; a note is an event with `kind="note"` |
| Stage transitions | Free-form, user-driven; no enforced order |
| Layout | Table with filter tabs, not a kanban board |

## 4. Data model

### 4.1 New columns on `Application`

| Column | Type | Default | Meaning |
|---|---|---|---|
| `stage` | `str` | `"saved"` | Funnel position |
| `applied_at` | `Optional[datetime]` | `None` | Stamped when stage first becomes `applied` |
| `archived_at` | `Optional[datetime]` | `None` | Non-null means hidden from the default view |

Stage vocabulary, in `STAGES`:

```
saved       parked; no documents generated, nothing spent
drafted     resume and cover letter generated, not sent
applied     submitted
screening   recruiter contact, phone screen
interview   any round
offer
rejected    terminal
withdrawn   terminal
```

Validated server-side against `STAGES` exactly as `template` and `depth`
already are.

### 4.2 New table `ApplicationEvent`

```python
class ApplicationEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="application.id")
    kind: str                                   # see EVENT_KINDS
    occurred_at: datetime                       # user-supplied; defaults to now
    body: str = ""                              # freeform text
    created_at: datetime = Field(default_factory=_utcnow)
```

`EVENT_KINDS`: `applied`, `callback`, `interview`, `offer`, `rejection`,
`followup`, `note`.

Notes and events are one table because they are the same shape — a dated entry
with text. "Add a note" and "log a callback" become one code path, one API
endpoint, one UI component, and one ordered timeline instead of two parallel
lists the user has to mentally merge.

`occurred_at` is separate from `created_at` because you record the call on
Thursday that happened on Tuesday.

### 4.3 Stage automation — deliberately minimal

Two rules, and no others:

1. Setting `stage` to `applied` stamps `applied_at` if it is currently null.
   Moving away and back does not re-stamp.
2. Successful generation advances `saved → drafted`. It does not touch any
   other stage, so regenerating an application you are interviewing for leaves
   the funnel alone.

Logging an event never changes the stage. Recording a callback puts it on the
timeline; you move the stage when you decide the stage has moved. Silent
auto-advancement is the behaviour that makes trackers untrustworthy.

### 4.4 Migration helper

A new function in `backend/app/db.py`, called from `init_db` after
`create_all`:

```python
def _add_missing_columns(engine) -> None:
    """Add columns present on the models but missing from existing SQLite
    tables. SQLModel.create_all only creates missing TABLES, never columns."""
```

Implementation: for each table, read `PRAGMA table_info(<table>)`, diff against
the model's columns, and issue `ALTER TABLE <table> ADD COLUMN <name> <type>`
for anything missing. SQLite supports `ADD COLUMN` with a constant default,
which covers every column this spec and spec 4 add.

Then backfill, once, for rows where `stage` is null: `'drafted'` if `status` is
`'ready'`, otherwise `'saved'`.

Properties this must have:
- **Idempotent.** Runs on every startup; costs one `PRAGMA` per table when
  there is nothing to do.
- **Additive only.** It never drops or retypes a column. A column that exists
  with the wrong type is reported, not "fixed" — silent data loss is worse than
  a loud failure.

This is deliberately not Alembic. The project's constraint is that cloning and
running requires only Python, and a migration framework plus its version
directory is a large amount of machinery for a local single-user SQLite file.

## 5. Saved jobs cost nothing

`BatchRequest` gains `generate: bool = True`.

When `generate` is false, applications are created with a new generation status
`not_started` and `stage="saved"`, and **no background task is queued**. No
fetch, no research, no Claude call, nothing spent.

A **Generate** action on the dashboard (`POST /applications/{id}/generate`)
starts the pipeline for such a job later. On success the `saved → drafted`
advance in §4.3 fires.

### 5.1 The polling consequence

`DashboardScreen` treats anything outside `ready | error | needs_paste` as
in-flight and re-polls every 2000ms (`frontend/src/screens/DashboardScreen.tsx:6`).

`not_started` **must** join that terminal list. Otherwise a single saved job
makes the dashboard poll the backend forever, at 2-second intervals, for as
long as the tab is open. This is a one-line change and a guaranteed bug if
missed, so it gets its own test.

`AppStatus` in `frontend/src/types.ts` also gains `not_started`, and
`styles.css` gains a `.badge-not_started` rule — the badge class is
interpolated from the status string (`DashboardScreen.tsx`), so a new status
without a matching rule renders unstyled.

## 6. API

| Method | Path | Purpose |
|---|---|---|
| `PATCH` | `/applications/{id}` | Set `stage`; validated against `STAGES` |
| `POST` | `/applications/{id}/archive` | Set `archived_at` |
| `POST` | `/applications/{id}/restore` | Clear `archived_at` |
| `DELETE` | `/applications/{id}` | Permanent delete (see §6.1) |
| `POST` | `/applications/{id}/generate` | Start the pipeline for a `not_started` job |
| `GET` | `/applications/{id}/events` | Timeline, newest `occurred_at` first |
| `POST` | `/applications/{id}/events` | Add a timeline entry |
| `DELETE` | `/applications/{id}/events/{event_id}` | Remove a timeline entry |

`GET /applications` gains `stage` and `archived` query filters. It excludes
archived rows by default — archived means archived.

`application_summary` gains `stage`, `applied_at`, `archived_at`, and
`last_activity_at` (the most recent `occurred_at` for the application, or
`created_at` when there are no events).

`application_detail` additionally embeds the full event list, so the
Application screen needs one request rather than two.

### 6.1 Permanent delete

`DELETE /applications/{id}` removes, in order:

1. The `data/exports/<id>/` directory, recursively
2. `ApplicationEvent` rows for the application
3. `ApplicationVersion` rows for the application
4. The `Application` row

**Files first, not rows first.** This spec originally mandated rows-first
(delete the DB rows, commit, then best-effort remove the directory,
swallowing removal failures since the rows were already gone). That order was
reversed during implementation, with the user's approval, after review found
a real corruption path: `Application.id` is a bare SQLite rowid with no
`AUTOINCREMENT`, so ids get recycled once a row is deleted. Combined with a
tolerated `rmtree` failure (e.g. a PDF held open in a viewer on Windows) and
`download_export`'s fallback to `data_dir/exports/<id>` whenever
`export_dir` is NULL, a rows-first delete could leave a locked export
directory on disk under an id that a subsequently created application would
inherit — silently serving that new application's Exports tab the deleted
application's resume. Files-first makes that state unreachable: removal now
runs, and must fully succeed, before any row is touched, and a removal
failure raises so the whole delete aborts with nothing committed. Do not
revert this order back to rows-first.

The `Job` row is left alone — it is shared state and may be referenced
elsewhere; orphan cleanup is out of scope.

Directory removal is the only destructive filesystem operation in the codebase
and gets the corresponding care: the path is rebuilt from
`settings.data_dir / "exports" / str(application_id)`, never from
`Application.export_dir` (a stored, potentially stale, potentially
attacker-influenced string), and is verified to sit inside `data_dir` before
`shutil.rmtree`. A missing directory is not an error. A removal failure
(e.g. `OSError` from a locked file) raises a 409 so the caller can close the
file and retry — nothing is committed on that path.

Returns 409 if the application is mid-pipeline; deleting rows out from under a
running background task would leave it writing to a deleted row. A locked
export directory now also returns 409, for the same "retry me" reason.

There is no bulk endpoint. The frontend loops over selected ids. For a local
single-user app, twenty sequential requests is not a problem worth new API
surface.

## 7. UI

### 7.1 Dashboard

- **Filter tabs with counts**: All · Saved · Active · Archived. "Active" means
  not archived and not in a terminal stage (`rejected`, `withdrawn`).
- **Stage as an inline dropdown** in each row, so you can advance a job without
  opening it. This is the single highest-frequency action in a job hunt and it
  should cost one click.
- **Checkbox selection** with bulk Archive and bulk Delete.
- **Columns**: Company · Role · Stage · Status · Applied · Last activity ·
  Actions. `Depth`, `Template`, `Version` and `Cost` are dropped from this
  view; they are generation trivia and this is now a job-hunt view. All four
  remain on the Application screen, where spec 1 also places the template
  switcher — so template stays visible and changeable, just not in the tracker
  table.
- Saved rows show a **Generate** action in place of the cost column.
- Permanent delete opens a confirmation dialog naming the company and role, and
  stating that the exported files will be deleted. Archive does not confirm —
  it is reversible.

### 7.2 Application screen

A timeline panel: an add-entry form (date, kind, text), the entries in reverse
chronological order, and per-entry delete. Stage selector and applied date in
the header area alongside the existing metadata line.

## 8. Testing

- **Migration**: given a database created from the *old* schema, `init_db` adds
  the three columns and backfills `stage` correctly from `status`; running it
  twice is a no-op. This is the test that protects existing user data and it is
  written first.
- **Orthogonality**: regenerating an application in stage `interview` leaves
  the stage at `interview` while `status` cycles back through the pipeline.
- **Stage validation**: an unknown stage returns 422 with the valid list.
- **`applied_at`**: stamped on first transition to `applied`, not re-stamped on
  a second transition.
- **Saved jobs**: `generate: false` creates rows with no background task queued
  and no Claude client invocation; `POST /generate` starts it.
- **Polling**: `not_started` is in the frontend's terminal set — asserted
  directly, so the infinite-poll bug cannot regress.
- **Archive**: archived rows are absent from the default list, present under
  the archived filter, and restorable.
- **Permanent delete**: rows and the export directory are gone; a path outside
  `data_dir` is refused; a missing directory does not raise; 409 mid-pipeline.
- **Events**: create, list ordering by `occurred_at`, delete; unknown `kind`
  returns 422.
- **Frontend**: filter tabs, inline stage change, bulk selection, and that the
  delete confirmation names the role.

## 9. Out of scope

- **Follow-up reminders and due dates.** The natural next feature, deliberately
  excluded: it pulls in date arithmetic, an overdue concept, and notification
  surface. Called out to the user, who left it out.
- Kanban board view. The table filters better at fifty rows and matches the
  rest of the app.
- Interview scheduling, calendar integration, email integration.
- Analytics: response rates, funnel conversion, time-to-offer.
- Per-application contacts and salary fields.
- Orphaned `Job` row cleanup.
- Undo for permanent delete.

## 10. Risks

**The migration is the dangerous part.** It runs against the user's real
database on startup, before anything else. It is additive-only, idempotent, and
tested against a genuine old-schema database rather than a mock. Its failure
mode must be a clear startup error, never a partially migrated database.

**`shutil.rmtree` is the only destructive filesystem call in the project.** The
containment check in §6.1 is not optional.
