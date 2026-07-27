# MCP Queue and Browser Escalation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an agent be handed twenty job URLs at once, work through them one at a time with the queue surviving context loss, and know exactly what to do when a job board refuses to be fetched.

**Architecture:** The queue is not a new table. Twenty parked URLs and twenty saved applications are the same thing, so `queue_jobs` creates ordinary applications in `status="not_started"` / `stage="saved"` — the states the dashboard already understands — and `next_pending_job` returns the oldest one. Queued work therefore appears on the dashboard as it arrives and drains in real time. The browser half is not code: the Tailored MCP server is a local Python process and cannot drive Chrome. It is an instruction, made specific enough to act on, placed in both the workflow guide and the tool docstrings, with a recorded give-up path so an abandoned URL is visible rather than silent.

**Tech Stack:** Python 3.14 / FastAPI / SQLModel / MCP (FastMCP).

## Global Constraints

- **Python is `./.venv/Scripts/python.exe`.** The ambient `python` is a conda install missing this project's dependencies. Run tests as `./.venv/Scripts/python.exe -m pytest tests/ -q` from the repo root.
- **Tailored will never drive a browser to fetch a posting.** Playwright is present for PDF rendering and is not to be repurposed for fetching: a headless browser with no user session is exactly what gets refused. Browser escalation happens in the *client agent*, in the user's own Chrome, with the user's own session, on a posting the user is entitled to read.
- **No bot-detection evasion, CAPTCHA solving, proxying, user-agent spoofing, or fingerprint manipulation.** Not in code, and not in the instructions given to agents. The escalation ladder says so explicitly, and that wording is part of the deliverable.
- **The queue does not lock or reserve rows.** Tailored is a local, single-user, single-agent application; a claim protocol would be machinery guarding a scenario that does not exist.
- **`get_workflow_guide` returns an f-string.** Every literal `{` or `}` added to it must be doubled or the module will not import.
- **No em dashes and no emoji** in any copy this plan adds, including guide text and tool docstrings.
- **`_run` in `mcp_server.py` passes positional arguments only**, in declaration order. The convention is `engine` first, then `data_dir` if the op needs it, then the tool's own arguments.

## Verified starting conditions

Checked against the repo before this plan was written:

- **There is no URL validator anywhere in this codebase.** `POST /applications/batch` validates only `depth` and `template`; `BatchJobIn.url` is a bare `str` and passes through untouched. `fetcher.fetch_posting` never raises. So "malformed URL" is currently undefined here and Task 1 has to define it. Nothing exists to reuse.
- **There is no dedup-by-URL anywhere either.** `mcp_ops.create_application` creates a Job and an Application unconditionally on every call.
- **`"not_started"` already works end to end.** `POST /applications/batch` sets it when `generate=false`, `POST /applications/{id}/generate` transitions it to `queued`, the dashboard renders a `.badge-not_started`, and `TERMINAL_STATUSES` in `frontend/src/statuses.ts` includes it so polling stops. The queue is reusing a finished mechanism, not building one.
- **`"not_started"` is not in `_PIPELINE_ACTIVE_STATUSES`**, so `_reject_if_pipeline_active` will not block an agent from working on a queued application. Note the signature is `_reject_if_pipeline_active(app, application_id)` — two arguments.
- **`mcp_ops.py` does not import `ApplicationEvent`.** Task 3 adds it.
- **`EVENT_KINDS` has no "blocked" kind and does not need one.** The spec calls for an event of kind `note`, which already exists. Do not extend `EVENT_KINDS`: the API route validates user-posted events against that tuple, so a new kind would also become user-postable, which is not intended.
- **`Job.fetch_status` has no enum.** Its four values live only in a trailing comment at `models.py:63`. Adding `"blocked"` means writing the string and updating that comment.
- **`test_workflow_guide_contents` (`tests/test_mcp_ops.py:87`) asserts on guide substrings**, including `"projects-forward"`. Rewriting guide text without checking that test will break it.

## File Structure

**Modified**

| Path | Change |
|---|---|
| `backend/mcp_ops.py` | `_valid_url`, `queue_jobs`, `next_pending_job`, `report_fetch_blocked`; the rewritten fetch ladder and batch section in `get_workflow_guide`. |
| `backend/mcp_server.py` | Three new tool registrations; the ladder in `create_application`'s docstring. |
| `backend/app/models.py:63` | `fetch_status` comment gains `"blocked"`. |
| `tests/test_mcp_ops.py` | Queue, resumption, dedup, all-or-nothing, blocked-reporting and guide tests. |
| `README.md`, `docs/EXTENDING.md` | The batch workflow. |

**Created** — nothing. Every new operation lives in `mcp_ops.py` beside its siblings.

**Dependency order.** Task 1, then 2, then 3 (each adds an operation the next task's guide text describes), then 4 (the guide), then 5 (docs). Only one task at a time may run `git add`/`git commit`.

---

### Task 1: `queue_jobs`

**Files:**
- Modify: `backend/mcp_ops.py` (add `_valid_url` and `queue_jobs` after `create_application`)
- Modify: `backend/mcp_server.py` (register the tool)
- Modify: `tests/test_mcp_ops.py` (append)

**Interfaces:**
- Produces `mcp_ops.queue_jobs(engine, profile_id: int, urls: list[str]) -> list[dict]`.
- Returns one entry per **input** URL, in input order. Created entries are `{"application_id": int, "url": str, "status": "not_started"}`. Skipped entries are `{"application_id": <the existing id>, "url": str, "status": "skipped", "reason": "already queued for this profile"}`.
- Registered as an MCP tool `queue_jobs(profile_id, urls)`.

**Why one entry per input URL, including skips.** An agent that pasted twenty URLs and got back seventeen entries has to diff two lists to work out what happened. Returning twenty entries with three marked skipped is unambiguous, and gives the agent the existing `application_id` so it can still act on it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_ops.py`:

```python
QUEUE_URLS = [
    "https://jobs.example.com/one",
    "https://jobs.example.com/two",
    "https://jobs.example.com/three",
]


def test_queue_jobs_creates_one_parked_application_per_url(engine, profile_id):
    result = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    assert len(result) == 3
    assert [r["url"] for r in result] == QUEUE_URLS
    with Session(engine) as session:
        apps = session.exec(select(Application)).all()
        assert len(apps) == 3
        for app in apps:
            assert app.status == "not_started"
            assert app.stage == "saved"
            assert app.cost_usd == 0.0
            assert app.resume_json is None


def test_queue_jobs_stores_no_posting_text(engine, profile_id):
    """The agent fetches each posting later, one at a time."""
    mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    with Session(engine) as session:
        for job in session.exec(select(Job)).all():
            assert job.raw_text is None
            assert job.fetch_status == "pending"


def test_queue_jobs_returns_the_ids_and_urls(engine, profile_id):
    result = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    for entry in result:
        assert entry["status"] == "not_started"
        assert isinstance(entry["application_id"], int)


def test_queue_jobs_never_calls_claude(engine, profile_id, monkeypatch):
    """Queueing twenty URLs must cost nothing."""
    from backend.app.services import claude as claude_module

    def explode(*args, **kwargs):
        raise AssertionError("queue_jobs must not call Claude")

    monkeypatch.setattr(claude_module.ClaudeService, "structured", explode)
    assert len(mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)) == 3


def test_queue_jobs_rejects_an_empty_list(engine, profile_id):
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.queue_jobs(engine, profile_id, [])
    assert "empty" in str(exc.value).lower()


def test_queue_jobs_rejects_an_unknown_profile(engine):
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.queue_jobs(engine, 9999, QUEUE_URLS)
    assert "9999" in str(exc.value)


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "not-a-url", "example.com/job", "ftp://example.com/job", "javascript:alert(1)"],
)
def test_queue_jobs_rejects_a_malformed_url(engine, profile_id, bad):
    with pytest.raises(mcp_ops.McpOpsError):
        mcp_ops.queue_jobs(engine, profile_id, [bad])


def test_one_bad_url_in_twenty_creates_nothing(engine, profile_id):
    """All-or-nothing, matching the web batch route. A partial queue is worse
    than a rejected one: the agent cannot tell which half landed."""
    urls = [f"https://jobs.example.com/{i}" for i in range(19)] + ["not-a-url"]
    with pytest.raises(mcp_ops.McpOpsError):
        mcp_ops.queue_jobs(engine, profile_id, urls)
    with Session(engine) as session:
        assert session.exec(select(Application)).all() == []
        assert session.exec(select(Job)).all() == []


def test_queueing_the_same_url_twice_skips_the_second(engine, profile_id):
    """Pasting a list twice is normal user behaviour and must not create
    twenty duplicates."""
    first = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    second = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)

    assert [r["status"] for r in second] == ["skipped"] * 3
    assert [r["application_id"] for r in second] == [r["application_id"] for r in first]
    assert all("reason" in r for r in second)
    with Session(engine) as session:
        assert len(session.exec(select(Application)).all()) == 3


def test_a_duplicate_within_one_call_is_skipped(engine, profile_id):
    result = mcp_ops.queue_jobs(
        engine, profile_id, ["https://jobs.example.com/a", "https://jobs.example.com/a"]
    )
    assert [r["status"] for r in result] == ["not_started", "skipped"]
    with Session(engine) as session:
        assert len(session.exec(select(Application)).all()) == 1


def test_dedup_is_scoped_to_the_profile(engine, profile_id, claude_fake):
    """Two people may legitimately apply to the same job."""
    with Session(engine) as session:
        other = Profile(name="Someone Else")
        session.add(other)
        session.commit()
        session.refresh(other)
        other_id = other.id

    mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    result = mcp_ops.queue_jobs(engine, other_id, ["https://jobs.example.com/a"])
    assert result[0]["status"] == "not_started"


def test_an_archived_application_does_not_block_requeueing(engine, profile_id):
    """Archiving is how a user says 'done with this'. Re-queueing must work."""
    first = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    with Session(engine) as session:
        app = session.get(Application, first[0]["application_id"])
        app.archived_at = datetime.utcnow()
        session.add(app)
        session.commit()

    second = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    assert second[0]["status"] == "not_started"
    assert second[0]["application_id"] != first[0]["application_id"]
```

Add to that file's imports whatever is missing: `from datetime import datetime`, `from sqlmodel import select`, and `Job` alongside the existing `Application` model import.

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp_ops.py -q -k "queue or dedup or requeue or bad_url or profile_scoped"`
Expected: `AttributeError: module 'backend.mcp_ops' has no attribute 'queue_jobs'`.

- [ ] **Step 3: Implement**

Add to `backend/mcp_ops.py`, after `create_application`:

```python
_ALLOWED_URL_SCHEMES = ("http", "https")


def _valid_url(url: str) -> bool:
    """A URL an agent could plausibly open. Deliberately permissive.

    There is no URL validation anywhere else in this project: the web batch
    route accepts any string. This exists only so that a typo or a stray line
    from a pasted list fails the whole batch loudly instead of creating a queue
    entry that can never be fetched. It is not a security boundary.
    """
    if not url or not url.strip():
        return False
    parsed = urlparse(url.strip())
    return parsed.scheme in _ALLOWED_URL_SCHEMES and bool(parsed.netloc)


def queue_jobs(engine, profile_id: int, urls: list[str]) -> list[dict]:
    """Register many job URLs at once, cheaply, for working through one by one.

    Creates one parked application per URL: status "not_started", stage
    "saved", no posting text, no pipeline run, no model call, no cost. They
    appear on the dashboard immediately and the user can watch them drain.

    All-or-nothing: if any URL is malformed the whole batch is rejected and
    nothing is created, matching the web batch route. A partial queue is worse
    than a rejected one, because the agent cannot tell which half landed.

    Returns one entry per INPUT url, in input order, so the caller never has to
    diff two lists. Entries already queued for this profile come back with
    status "skipped" and the existing application_id.
    """
    if not urls:
        raise McpOpsError("urls must not be empty - pass at least one job URL.")
    bad = [u for u in urls if not _valid_url(u)]
    if bad:
        raise McpOpsError(
            f"{len(bad)} malformed URL(s), so nothing was queued: {bad[:5]}. "
            "Every URL must be an absolute http or https address."
        )

    with Session(engine) as session:
        profile = session.get(Profile, profile_id)
        if profile is None:
            raise McpOpsError(
                f"Profile {profile_id} not found. Call list_profiles to see "
                "what exists."
            )

        # Existing, non-archived applications for this profile, by URL.
        # Archiving is how a user says "done with this", so an archived row
        # must not block re-queueing.
        existing: dict[str, int] = {}
        rows = session.exec(
            select(Application, Job)
            .where(Application.job_id == Job.id)
            .where(Application.profile_id == profile_id)
            .where(Application.archived_at.is_(None))
        ).all()
        for app_row, job_row in rows:
            existing.setdefault(job_row.url, app_row.id)

        results: list[dict] = []
        for url in urls:
            url = url.strip()
            if url in existing:
                results.append(
                    {
                        "application_id": existing[url],
                        "url": url,
                        "status": "skipped",
                        "reason": "already queued for this profile",
                    }
                )
                continue
            job = Job(url=url, depth="external")
            session.add(job)
            session.commit()
            session.refresh(job)
            app_row = Application(
                profile_id=profile_id,
                job_id=job.id,
                status="not_started",
            )
            session.add(app_row)
            session.commit()
            session.refresh(app_row)
            # A duplicate later in the same list is a skip, not a second row.
            existing[url] = app_row.id
            results.append(
                {
                    "application_id": app_row.id,
                    "url": url,
                    "status": "not_started",
                }
            )
        return results
```

Add `from urllib.parse import urlparse` to the imports at the top of `mcp_ops.py`.

`Application.stage` defaults to `"saved"` and `Job.fetch_status` defaults to `"pending"`, so neither is set explicitly; the tests assert both, which keeps the defaults honest.

- [ ] **Step 4: Register the tool**

In `backend/mcp_server.py`, beside `create_application`:

```python
@mcp.tool()
async def queue_jobs(profile_id: int, urls: list[str]) -> list[dict]:
    """Register many job URLs at once so you can work through them one at a
    time. Free and instant: no fetching, no model call, no cost. Each becomes a
    saved job on the user's dashboard, and the queue survives you losing
    context - call next_pending_job to pick up where you left off.
    Rejects the whole batch if any URL is malformed. URLs already queued for
    this profile come back marked "skipped" with their existing id.
    Then loop: next_pending_job, fetch the posting (see get_workflow_guide for
    what to do when a site refuses), save_parsed_posting, save_tailored_resume."""
    return await _run(mcp_ops.queue_jobs, _engine, profile_id, urls)
```

- [ ] **Step 5: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp_ops.py -q`
Expected: all pass.

- [ ] **Step 6: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures.

- [ ] **Step 7: Commit**

```bash
git add backend/mcp_ops.py backend/mcp_server.py tests/test_mcp_ops.py
git commit -m "feat: queue many job URLs at once through MCP"
```

---

### Task 2: `next_pending_job`

**Files:**
- Modify: `backend/mcp_ops.py` (add after `queue_jobs`)
- Modify: `backend/mcp_server.py` (register)
- Modify: `tests/test_mcp_ops.py` (append)

**Interfaces:**
- Produces `mcp_ops.next_pending_job(engine, profile_id: int) -> dict | None`, returning `{"application_id": int, "url": str}` or `None`.

**Returning `None` rather than raising is deliberate.** It makes the agent's loop terminate on a plain condition rather than on an error, which is far more reliable across models.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_ops.py`:

```python
def test_next_pending_job_returns_the_oldest_first(engine, profile_id):
    queued = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    nxt = mcp_ops.next_pending_job(engine, profile_id)
    assert nxt["application_id"] == queued[0]["application_id"]
    assert nxt["url"] == QUEUE_URLS[0]


def test_next_pending_job_returns_none_on_an_empty_queue(engine, profile_id):
    assert mcp_ops.next_pending_job(engine, profile_id) is None


def test_next_pending_job_ignores_applications_already_started(engine, profile_id):
    queued = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    with Session(engine) as session:
        app = session.get(Application, queued[0]["application_id"])
        app.status = "ready"
        session.add(app)
        session.commit()

    assert mcp_ops.next_pending_job(engine, profile_id)["application_id"] == (
        queued[1]["application_id"]
    )


def test_next_pending_job_ignores_other_profiles(engine, profile_id):
    with Session(engine) as session:
        other = Profile(name="Someone Else")
        session.add(other)
        session.commit()
        session.refresh(other)
        other_id = other.id

    mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    assert mcp_ops.next_pending_job(engine, other_id) is None


def test_next_pending_job_ignores_archived_applications(engine, profile_id):
    queued = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    with Session(engine) as session:
        app = session.get(Application, queued[0]["application_id"])
        app.archived_at = datetime.utcnow()
        session.add(app)
        session.commit()

    assert mcp_ops.next_pending_job(engine, profile_id)["application_id"] == (
        queued[1]["application_id"]
    )


def test_the_queue_resumes_after_a_context_loss(engine, profile_id, tmp_path, pdf_faked):
    """The property this whole design exists for.

    Queue five, complete two, and the third is what comes back - with no
    memory of the run carried anywhere but the database.
    """
    urls = [f"https://jobs.example.com/{i}" for i in range(5)]
    queued = mcp_ops.queue_jobs(engine, profile_id, urls)

    for entry in queued[:2]:
        with Session(engine) as session:
            app = session.get(Application, entry["application_id"])
            app.status = "ready"
            session.add(app)
            session.commit()

    nxt = mcp_ops.next_pending_job(engine, profile_id)
    assert nxt["application_id"] == queued[2]["application_id"]
    assert nxt["url"] == urls[2]


def test_a_user_deleting_a_saved_job_mid_run_simply_removes_it(engine, profile_id):
    """Correct behaviour, not an error: the agent just never receives it."""
    queued = mcp_ops.queue_jobs(engine, profile_id, QUEUE_URLS)
    with Session(engine) as session:
        session.delete(session.get(Application, queued[0]["application_id"]))
        session.commit()

    assert mcp_ops.next_pending_job(engine, profile_id)["application_id"] == (
        queued[1]["application_id"]
    )
```

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp_ops.py -q -k next_pending`
Expected: `AttributeError: module 'backend.mcp_ops' has no attribute 'next_pending_job'`.

- [ ] **Step 3: Implement**

Add to `backend/mcp_ops.py`, after `queue_jobs`:

```python
def next_pending_job(engine, profile_id: int) -> dict | None:
    """The oldest queued job for this profile, or None when the queue is empty.

    Returns None rather than raising on an empty queue: it makes your loop
    terminate on a plain condition rather than on an error.

    Does not lock or reserve the row. Tailored is a local, single-user
    application, so a claim protocol would guard a scenario that does not
    exist. If the user deletes a saved job mid-run, it simply stops being
    returned, which is correct.
    """
    with Session(engine) as session:
        row = session.exec(
            select(Application, Job)
            .where(Application.job_id == Job.id)
            .where(Application.profile_id == profile_id)
            .where(Application.status == "not_started")
            .where(Application.archived_at.is_(None))
            .order_by(Application.id)
        ).first()
        if row is None:
            return None
        app_row, job_row = row
        return {"application_id": app_row.id, "url": job_row.url}
```

- [ ] **Step 4: Register the tool**

```python
@mcp.tool()
async def next_pending_job(profile_id: int) -> dict | None:
    """The next queued job to work on, as {application_id, url}, or null when
    the queue is empty. Loop on this after queue_jobs: process one job all the
    way to save_tailored_resume before asking for the next, so losing context
    costs one job rather than twenty. Safe to call after a restart - the queue
    lives in the database, so you resume exactly where you stopped."""
    return await _run(mcp_ops.next_pending_job, _engine, profile_id)
```

- [ ] **Step 5: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp_ops.py -q`
Expected: all pass.

- [ ] **Step 6: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures.

- [ ] **Step 7: Commit**

```bash
git add backend/ tests/test_mcp_ops.py
git commit -m "feat: next_pending_job drains the MCP queue oldest first"
```

---

### Task 3: `report_fetch_blocked`

**Files:**
- Modify: `backend/app/models.py:63` (the `fetch_status` comment)
- Modify: `backend/mcp_ops.py` (import `ApplicationEvent`; add the op)
- Modify: `backend/mcp_server.py` (register)
- Modify: `tests/test_mcp_ops.py` (append)

**Interfaces:**
- Produces `mcp_ops.report_fetch_blocked(engine, application_id: int, reason: str) -> dict` returning `{"application_id", "fetch_status", "event_id"}`.

**Why this is the point of the whole browser half.** The browser escalation is instructions, not code, so its realistic failure is an agent quietly giving up and a row that never moves. This operation makes giving up *visible*: the user sees on the dashboard why a posting stalled instead of finding a row that sat there. Without it, the ladder is unfalsifiable advice.

**Use `kind="note"`.** It already exists in `EVENT_KINDS`. Do not add a `"blocked"` kind: the API route validates user-posted events against that same tuple, so a new kind would silently become something a user can post from the timeline UI, which is not intended.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_ops.py`:

```python
def test_report_fetch_blocked_sets_the_fetch_status(engine, profile_id):
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]

    result = mcp_ops.report_fetch_blocked(engine, app_id, "403 and a bot check")
    assert result["fetch_status"] == "blocked"

    with Session(engine) as session:
        app = session.get(Application, app_id)
        assert session.get(Job, app.job_id).fetch_status == "blocked"


def test_report_fetch_blocked_writes_a_timeline_note(engine, profile_id):
    """The user must see WHY a posting stalled, not just that it did."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]

    mcp_ops.report_fetch_blocked(engine, app_id, "403 and a bot check")

    with Session(engine) as session:
        events = session.exec(
            select(ApplicationEvent).where(ApplicationEvent.application_id == app_id)
        ).all()
        assert len(events) == 1
        assert events[0].kind == "note"
        assert "403 and a bot check" in events[0].body


def test_report_fetch_blocked_is_visible_on_the_application(client, engine, profile_id):
    """It has to reach the dashboard, or it is not a report."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]
    mcp_ops.report_fetch_blocked(engine, app_id, "login wall")

    detail = client.get(f"/api/applications/{app_id}").json()
    assert any("login wall" in e["body"] for e in detail["events"])


def test_report_fetch_blocked_leaves_the_job_queueable_for_a_paste(engine, profile_id):
    """Blocked is a record, not a deletion. The user can still paste the text."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    app_id = queued[0]["application_id"]
    mcp_ops.report_fetch_blocked(engine, app_id, "login wall")

    with Session(engine) as session:
        assert session.get(Application, app_id) is not None


def test_report_fetch_blocked_rejects_an_unknown_application(engine):
    with pytest.raises(mcp_ops.McpOpsError) as exc:
        mcp_ops.report_fetch_blocked(engine, 9999, "nope")
    assert "9999" in str(exc.value)


def test_report_fetch_blocked_requires_a_reason(engine, profile_id):
    """A blocked row with no reason is exactly the silent failure this prevents."""
    queued = mcp_ops.queue_jobs(engine, profile_id, ["https://jobs.example.com/a"])
    with pytest.raises(mcp_ops.McpOpsError):
        mcp_ops.report_fetch_blocked(engine, queued[0]["application_id"], "   ")
```

Add `ApplicationEvent` to that test file's model imports.

- [ ] **Step 2: Run and confirm they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp_ops.py -q -k blocked`
Expected: `AttributeError: module 'backend.mcp_ops' has no attribute 'report_fetch_blocked'`.

- [ ] **Step 3: Update the `fetch_status` comment**

In `backend/app/models.py`, line 63, change the trailing comment on `fetch_status` to:

```python
    fetch_status: str = "pending"  # "pending"|"fetched"|"needs_paste"|"pasted"|"blocked"
```

`"blocked"` means: fetched directly, refused, and browser escalation also unsuccessful. There is no enum constant to update; these values live only in this comment.

- [ ] **Step 4: Implement**

Add `ApplicationEvent` to the `from .app.models import (...)` list at the top of `backend/mcp_ops.py`, then add the op after `next_pending_job`:

```python
def report_fetch_blocked(engine, application_id: int, reason: str) -> dict:
    """Record that a posting could not be read, and why.

    Call this when a direct fetch was refused AND opening the URL in the user's
    own browser also did not work. It marks the job blocked and writes a note
    on the application's timeline, so the user sees on the dashboard why this
    posting stalled instead of finding a row that never moved.

    Then move on to the next job. Do not stall the batch on one posting.
    """
    if not reason or not reason.strip():
        raise McpOpsError(
            "reason must not be empty - say what refused the fetch (a 403, a "
            "bot check, a login wall) so the user knows what to do."
        )
    with Session(engine) as session:
        app, job = _get_app_and_job(session, application_id)
        job.fetch_status = "blocked"
        session.add(job)
        event = ApplicationEvent(
            application_id=app.id,
            kind="note",
            body=f"Could not read the posting: {reason.strip()}",
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        return {
            "application_id": app.id,
            "fetch_status": job.fetch_status,
            "event_id": event.id,
        }
```

- [ ] **Step 5: Register the tool**

```python
@mcp.tool()
async def report_fetch_blocked(application_id: int, reason: str) -> dict:
    """Record that you could not read a posting, and why, so the user sees it
    on the dashboard instead of finding a job that never moved. Call this only
    after BOTH a direct fetch and opening the URL in the user's own browser
    failed. Say what refused you: a 403, a bot check, a login wall. Then move
    on to the next job - do not stall the batch on one posting."""
    return await _run(mcp_ops.report_fetch_blocked, _engine, application_id, reason)
```

- [ ] **Step 6: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp_ops.py -q`
Expected: all pass.

- [ ] **Step 7: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures.

- [ ] **Step 8: Commit**

```bash
git add backend/ tests/test_mcp_ops.py
git commit -m "feat: record a blocked posting visibly instead of failing quietly"
```

---

### Task 4: The workflow guide

**Files:**
- Modify: `backend/mcp_ops.py:67-152` (`get_workflow_guide`)
- Modify: `backend/mcp_server.py:141` (`create_application`'s docstring)
- Modify: `tests/test_mcp_ops.py:87` (`test_workflow_guide_contents`)

**This task is the deliverable for the browser half of the spec.** The Tailored MCP server cannot drive Chrome; the browser tools live in the client agent. So "use the Chrome extension for blocked listings" is not a tool Tailored implements, it is an instruction Tailored gives, at the point where the agent needs it. The work is making that instruction specific enough to act on.

The ladder goes in the tool docstrings as well as the guide, because agents read tool descriptions far more reliably than they re-read a guide fetched at the start of a long run.

- [ ] **Step 1: Extend the guide test first**

In `tests/test_mcp_ops.py`, extend `test_workflow_guide_contents` (line 87) with:

```python
    # The fetch ladder. This guide IS the deliverable for the browser half of
    # the design, and it silently rotting is the realistic failure mode.
    assert "DIRECT FETCH" in guide
    assert "BROWSER ESCALATION" in guide
    assert "ASK FOR A PASTE" in guide
    assert "403" in guide
    assert "400 characters" in guide, "the short-body heuristic must survive"
    assert "user's own browser" in guide
    assert "report_fetch_blocked" in guide

    # The explicit refusal to help with evasion is part of the deliverable.
    lowered = guide.lower()
    assert "do not attempt to disguise automated traffic" in lowered

    # The batch loop.
    assert "queue_jobs" in guide
    assert "next_pending_job" in guide
    assert "one job to completion before starting the next" in lowered
```

- [ ] **Step 2: Run and confirm it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp_ops.py::test_workflow_guide_contents -q`
Expected: FAIL on the first missing assertion.

- [ ] **Step 3: Replace step 2 of the guide with the ladder**

In `backend/mcp_ops.py`, replace the current step 2 (lines 82-83, `2. Fetch the job posting yourself ...`) with:

```
2. Fetch the job posting. Escalate in this order, cheapest first:

   2a. DIRECT FETCH
       Fetch the URL with your normal tooling. If you get the posting text,
       you are done - go to step 3.

   2b. BROWSER ESCALATION - when the direct fetch is refused.
       Triggers: HTTP 401, 403 or 429; a bot check or CAPTCHA interstitial; a
       login wall; a consent gate; or a page whose extracted body is under
       about 400 characters, which usually means you received a JavaScript
       shell or a "please enable cookies" page rather than a posting. Many
       sites return HTTP 200 for those, so do not key this on status alone.

       Open the URL in the user's own browser (Claude in Chrome, or your
       client's equivalent), let it render, and read the page text. This uses
       the user's existing session, so postings behind a login they already
       hold are readable.

       Do not attempt to disguise automated traffic, defeat a CAPTCHA, or
       reach anything the user could not open themselves in their own browser.
       If the user is not logged in and the posting requires it, that is 2c.

   2c. ASK FOR A PASTE - only when both of the above failed.
       Call report_fetch_blocked(application_id, reason) so the user sees on
       their dashboard why this posting stalled, then tell them which URL needs
       pasting and why. Move on to the next job. Do not stall the batch on one
       posting.
```

Reminder: this function returns an f-string. Any literal `{` or `}` must be doubled. The text above contains none, so it can be pasted as is.

- [ ] **Step 4: Add the batch workflow section**

Add this to the guide, immediately after the numbered workflow and before the `TRUTHFULNESS CONTRACT` block:

```
WORKING THROUGH A LIST OF JOBS:
Call queue_jobs(profile_id, urls) once with every URL. It is free and instant -
no fetching, no model call, no cost - and each URL becomes a saved job on the
user's dashboard right away, so they can watch the list drain.

Then loop:
  job = next_pending_job(profile_id)   -> {{"application_id", "url"}} or null
  if null: the queue is empty, you are finished.
  otherwise: fetch it (step 2 above), then save_parsed_posting, optionally
  save_research, then save_tailored_resume. Then ask for the next one.

Process one job all the way to completion before starting the next. If you lose
context partway through a batch, that costs one job rather than twenty.

The queue lives in the database, not in your context. After a restart, or after
compacting, just call next_pending_job again: it returns the oldest job you have
not finished, so you resume exactly where you stopped. Do not start over.

If the user deletes a saved job while you are working, next_pending_job simply
stops returning it. That is correct - it is the user changing their mind, not an
error.
```

Note the doubled braces in `{{"application_id", "url"}}`. That line is inside an f-string and single braces would raise at import.

- [ ] **Step 5: Put the ladder in the tool docstrings too**

In `backend/mcp_server.py`, replace `create_application`'s docstring (line 145-148) with:

```python
    """Create a job application from a posting YOU gathered: fetch the URL
    yourself and pass the full posting text. If the site refuses you (403, a
    bot check, a login wall, or a body under about 400 characters), open the
    URL in the user's own browser and read it there - that uses their session,
    so postings behind a login they already hold are readable. Never try to
    disguise automated traffic or defeat a CAPTCHA. If both fail, call
    report_fetch_blocked and ask the user to paste.
    For more than one job, call queue_jobs instead. Returns the application_id
    used by every later call. Next: save_parsed_posting, save_tailored_resume."""
```

- [ ] **Step 6: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp_ops.py -q`
Expected: all pass, including the extended guide test.

- [ ] **Step 7: Confirm the module still imports**

The single most likely failure in this task is an unbalanced brace in the f-string.

Run: `./.venv/Scripts/python.exe -c "from backend import mcp_ops; g = mcp_ops.get_workflow_guide(); print(len(g), 'chars'); print('OK')"`
Expected: a character count and `OK`.

Run: `./.venv/Scripts/python.exe -c "import backend.mcp_server" 2>&1 | tail -3`
Expected: no traceback.

- [ ] **Step 8: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures.

- [ ] **Step 9: Commit**

```bash
git add backend/ tests/test_mcp_ops.py
git commit -m "feat: an actionable fetch ladder and batch loop in the agent guide"
```

---

### Task 5: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/EXTENDING.md`

- [ ] **Step 1: Document the batch workflow in the README**

In the section describing MCP / agent mode, add:

```markdown
### Working through a list of jobs

Paste a list of URLs at your agent and let it work:

> Queue these twenty jobs for my profile and work through them one at a time.

The agent calls `queue_jobs` once, and all twenty appear on your dashboard as
saved jobs immediately, before anything has been fetched or generated. Nothing
has cost anything yet. It then loops on `next_pending_job`, taking one job all
the way to a finished resume before starting the next, and you watch the list
drain in real time.

The queue lives in the database, not in the agent's context. If the agent
restarts or runs out of context at job eleven, it picks up at job eleven. If you
delete a saved job partway through, the agent simply never receives it.

When a job board refuses to be read, the agent opens the posting in your own
Chrome using your own session, which is what works for postings behind a login
you already hold. Tailored never tries to disguise automated traffic or defeat a
bot check. If that still does not work, the job is marked blocked with the
reason on its timeline, so you can see which posting needs pasting instead of
finding a row that never moved.
```

- [ ] **Step 2: List the new tools wherever the README enumerates MCP tools**

Search the README for the existing tool list and add:

```markdown
| `queue_jobs` | Register many job URLs at once. Free; creates saved jobs. |
| `next_pending_job` | The next queued job, or null when the queue is empty. |
| `report_fetch_blocked` | Record that a posting could not be read, and why. |
```

Match the surrounding table's exact column layout; if the README uses a bulleted list rather than a table, follow that instead.

- [ ] **Step 3: Note the constraint in `docs/EXTENDING.md`**

Add a short section:

```markdown
### Why Tailored does not fetch blocked postings itself

Playwright is in this project to render PDFs and will not be repurposed to
fetch job postings. A headless browser with no user session is exactly what a
job board's defences are built to refuse, so it would fail at the one job it
was added for while adding a whole category of maintenance.

Blocked postings are read by the client agent, in the user's own browser, with
the user's own session, on a posting the user is entitled to read. That is a
person's browser loading a page, which is what those defences are designed to
permit. Tailored's part is the instruction and the record: the escalation ladder
in `get_workflow_guide`, and `report_fetch_blocked` so giving up is visible
rather than silent.

Bot-detection evasion, CAPTCHA solving, proxying and user-agent spoofing are out
of scope and will not be added.
```

- [ ] **Step 4: Verify everything**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 0 failures.

- [ ] **Step 5: Manual end-to-end check**

With the MCP server configured in a client that has browser tools:

1. Ask the agent to queue three real job URLs. Confirm three rows appear on the dashboard as Saved, with no cost.
2. Ask it to work through them. Confirm they advance one at a time, and that the dashboard updates as each finishes.
3. Delete one saved row mid-run. Confirm the agent does not process it and does not error.
4. Give it a URL from a site that blocks automated fetches. Confirm it escalates to the browser, and if that fails, that a blocked note appears on the application's timeline with a reason.

Report anything that does not match.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/EXTENDING.md
git commit -m "docs: the MCP batch workflow and the fetch ladder"
```

---

## Self-Review

**Spec coverage.**

| Spec section | Task |
|---|---|
| §4.1 `queue_jobs`, not_started + saved, no pipeline run | 1 |
| §4.1 all-or-nothing on a malformed URL | 1 |
| §4.1 dedup against non-archived applications, reporting skips | 1 |
| §4.1 one entry per input URL | 1 |
| §4.2 `next_pending_job`, oldest first, null on empty | 2 |
| §4.2 no locking or reservation | 2 (stated in the docstring; the delete test pins the consequence) |
| §4.3 no progress tool needed | covered by not adding one |
| §5 the three-step fetch ladder with every trigger | 4 |
| §5 the short-body heuristic | 4 (asserted on "400 characters") |
| §5 the refusal to help with evasion | 4 (asserted) |
| §5 ladder in tool docstrings as well as the guide | 1, 3, 4 |
| §6 `Job.fetch_status` gains "blocked" | 3 |
| §6 `report_fetch_blocked` writes a note event | 3 |
| §7 guide gains the ladder, the batch section, the recovery note | 4 |
| §7 `create_application` unchanged for the single-URL case | 1 (additive; no signature change) |
| §8 every listed test | 1, 2, 3, 4 |

No gaps.

**Placeholder scan.** Clean. Three steps tell the implementer to match a local convention rather than trust the snippet — the README tool-list layout in Task 5 Step 2, and the test-file imports in Tasks 1 and 3 — and each names exactly what to check.

**Type consistency.** `queue_jobs` returns `list[dict]` with the entry shapes fixed in Task 1's Interfaces block and asserted by its tests. `next_pending_job` returns `dict | None` with keys `application_id` and `url`, and the guide text in Task 4 quotes that exact shape. `report_fetch_blocked` returns three keys, all asserted. All three ops take `engine` first and no `data_dir`, because none of them writes exports; `_run` threads arguments positionally in declaration order, and the registrations match.

**Verified before planning, not assumed.** There is no URL validator and no dedup-by-URL anywhere in this repo, so Task 1 writes both rather than reusing something. `EVENT_KINDS` deliberately gains nothing, because the API route validates user-posted events against the same tuple and a new kind would become user-postable as a side effect. `"not_started"` is already handled end to end by the dashboard, the generate route and the frontend polling set, so the queue reuses a finished mechanism. `get_workflow_guide` is an f-string, which is why Task 4 doubles the braces in the one line that needs it and includes an explicit import check as its own step.

**The honest limitation, stated because it is easy to over-claim.** The browser half of this spec is instructions, not code. Its effectiveness depends on the client agent having browser tools and following the guide. What makes it more than hopeful advice is Task 3: the give-up path records itself visibly, so a posting the agent abandoned shows up on the dashboard with a reason. That is the difference between a feature and a suggestion, and it is the reason `report_fetch_blocked` is a required task rather than a nice-to-have.
