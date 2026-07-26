# Tailored — MCP Multi-URL Queue and Browser Escalation — Design Spec

Date: 2026-07-26
Status: approved
Depends on: spec 3 (dashboard job tracker) — reuses its `saved` stage and
`not_started` status as the queue's state

## 1. What this is

Two related gaps in agent-driven (MCP) mode:

**You cannot hand an agent a list of jobs.** `create_application` takes one URL
and one blob of posting text. Working through twenty postings means the agent
holds the whole list in its own context and loops. There is no server-side
record of what is left, so an agent that compacts, loses context, or dies at
URL eleven either restarts from the beginning or silently skips the rest — and
nothing on the dashboard reveals which happened.

**The fetch instruction is too vague to act on.** The workflow guide's step 2
says only *"Fetch the job posting yourself (browse the URL with your own
abilities - you can read login-walled postings the app cannot fetch)"*
(`backend/mcp_ops.py:82`). An agent that hits a 403 or a bot check has no
guidance, so it gives up and asks the user to paste. Many large job boards
refuse automated requests outright.

## 2. Architectural constraint, stated up front

The Tailored MCP server is a local Python process. **It cannot drive Chrome.**
The browser tools live in the *client agent* — Claude Code with the Claude in
Chrome extension, or any MCP client with equivalent browser access.

So "use the Chrome extension for blocked listings" is not a tool Tailored
implements. It is an instruction Tailored gives, in the guide the agent already
reads, at the point where the agent needs it. The design work is making that
instruction specific enough to act on, and giving the agent somewhere to record
what happened.

This also happens to be the approach that works. Blocked postings are read by
opening them in the user's own Chrome, with the user's own session and cookies,
on a posting the user is entitled to read. That is a person's browser loading a
page, which is what the site's defences are designed to permit. No fingerprint
spoofing, no anti-detection, no defeating access controls — none of which
Tailored will implement.

## 3. Decisions

| Decision | Choice |
|---|---|
| Queue state | Reuses spec 3's `stage="saved"` + `status="not_started"` |
| New MCP tools | `queue_jobs`, `next_pending_job` |
| Blocked postings | Documented escalation ladder ending in the user's real browser |
| Recording blockage | Reuses `Job.fetch_status`, plus a timeline event |

### 3.1 Why the queue is not a new table

Twenty parked URLs and twenty saved applications are the same thing. Spec 3
already introduces a job that exists, has a URL, has no documents yet, and has
cost nothing — that *is* a queue entry.

Building a separate `McpQueue` table would give the project two mechanisms for
one idea, and a dashboard that cannot see what the agent is working through.
Reusing the tracker model means queued work appears on the dashboard as it
arrives, the user can watch twenty rows advance from Saved to Drafted, and they
can delete one mid-run and have the agent simply not receive it.

This is why spec 3 lands first.

## 4. New MCP tools

### 4.1 `queue_jobs(profile_id, urls) -> list[dict]`

Registers many URLs at once, cheaply.

- Creates one `Application` per URL with `status="not_started"`,
  `stage="saved"`, no `Job.raw_text`, and no pipeline run.
- Validates the profile exists and the list is non-empty; rejects the whole
  batch if any URL is malformed, matching the all-or-nothing behaviour of the
  existing web `POST /applications/batch` (`backend/app/api/applications.py:152`).
- **Deduplicates against existing non-archived applications for the profile by
  URL**, and reports which were skipped. Pasting a list twice is normal user
  behaviour and must not silently create twenty duplicates.
- Returns `[{application_id, url, status}]` for every input URL, including
  skipped ones with a reason.

### 4.2 `next_pending_job(profile_id) -> dict | None`

Returns the oldest application for the profile with `status="not_started"`,
as `{application_id, url}`, or `null` when the queue is empty.

Returning `null` rather than raising is deliberate: it makes the agent's loop
terminate on a plain condition rather than on an error, which is far more
reliable across models.

The tool does not lock or reserve the row. Tailored is a local, single-user,
single-agent application; a claim protocol would be machinery guarding against
a scenario that does not exist. Worst case with two agents running is duplicate
work on one posting, which the truthfulness and style checks will not corrupt.

### 4.3 Progress is visible without a new tool

`get_application` already reports status. The dashboard from spec 3 shows the
whole queue draining in real time. No progress-reporting tool is needed.

## 5. The fetch ladder

Workflow guide step 2 is replaced with an explicit escalation, ordered
cheapest-first:

```
1. DIRECT FETCH
   Fetch the URL with your normal tooling. If you get the posting text, done.

2. BROWSER ESCALATION  — when step 1 is refused
   Triggers: HTTP 401/403/429, a bot or CAPTCHA interstitial, a login wall,
   a consent gate, or a page whose body is too short to be a real posting
   (< ~400 characters of extracted text).

   Open the URL in the user's own browser (Claude in Chrome, or your client's
   equivalent), let it render, and read the page text. This uses the user's
   existing session, so postings behind a login they already hold are readable.

   Do not attempt to disguise automated traffic, defeat a CAPTCHA, or access
   anything the user could not open themselves in their own browser. If the
   user is not logged in and the posting requires it, that is step 3.

3. ASK FOR A PASTE  — only when both above fail
   Record the failure (§6) and tell the user which URL needs pasting and why.
   Continue with the rest of the queue; do not stall the batch on one posting.
```

The short-body heuristic in step 2 matters: many sites return HTTP 200 with a
JavaScript shell or a "please enable cookies" page. Keying escalation solely on
status codes would miss the most common case.

The same ladder is added to `create_application`'s and `queue_jobs`' tool
docstrings in `backend/mcp_server.py`, because agents read tool descriptions
far more reliably than they re-read a guide fetched at the start of a long run.

## 6. Recording a blocked posting

`Job.fetch_status` already carries `"pending" | "fetched" | "needs_paste" |
"pasted"` (`backend/app/models.py:39`). It gains `"blocked"` — fetched
directly, refused, browser escalation also unsuccessful.

A new op, `report_fetch_blocked(application_id, reason)`, sets it and writes an
`ApplicationEvent` of kind `note` with the reason. The user then sees on the
dashboard *why* a posting stalled rather than finding a row that never moved.

This is what makes an abandoned URL visible instead of silent, which is the
actual failure this spec exists to prevent.

## 7. Workflow guide changes

`get_workflow_guide` (`backend/mcp_ops.py:67`) gains:

- The fetch ladder above, replacing step 2.
- A **batch workflow** section: call `queue_jobs` once with all the URLs, then
  loop `next_pending_job` → fetch → `create_application`-equivalent → parse →
  research → tailor → save, until it returns null. Explicitly: process one job
  to completion before starting the next, so a context loss costs one job
  rather than twenty.
- A note that the queue survives context loss, and that re-calling
  `next_pending_job` after a restart resumes correctly. Agents behave better
  when told the recovery path exists.

`create_application` keeps working unchanged for the single-URL case. Queueing
is additive; nothing existing breaks.

## 8. Testing

- **`queue_jobs`**: creates N applications with `not_started` / `saved`, queues
  no background task, invokes no Claude client, and returns one entry per input
  URL.
- **Deduplication**: queueing the same URL twice for a profile creates one
  application and reports the second as skipped. Archived applications do not
  block re-queueing.
- **All-or-nothing**: one malformed URL in twenty creates zero applications.
- **`next_pending_job`**: returns oldest-first, returns null on an empty queue,
  ignores applications already generated, ignores other profiles, and ignores
  archived applications.
- **Resumption**: queue five, generate two, and assert `next_pending_job`
  returns the third — the property the whole design exists for.
- **`report_fetch_blocked`**: sets `fetch_status` and writes the timeline event.
- **Guide content**: `get_workflow_guide` names the escalation ladder and the
  batch loop. A thin test, but the guide *is* the deliverable for the browser
  half of this spec, and it silently rotting is the realistic failure.

## 9. Out of scope

- Tailored driving a browser itself — Playwright is present for PDF rendering
  and will not be repurposed to fetch postings. That would put a headless
  browser with no user session in exactly the position that gets refused.
- Any form of bot-detection evasion, CAPTCHA solving, proxying, or user-agent
  spoofing.
- Parallel or concurrent queue processing.
- Scheduled or unattended re-runs.
- Automatic retry of blocked URLs.

## 10. Risks

**The browser half is instructions, not code.** Its effectiveness depends on
the client agent having browser tools and following the guide. Mitigated by
putting the ladder in tool docstrings as well as the guide, and by making the
give-up path (§6) record itself visibly rather than failing quietly. Stated
plainly because a guide change is easy to over-claim as a feature.

**Queue and dashboard share one model.** A user deleting a saved application
mid-run means the agent's next `next_pending_job` simply will not return it.
That is correct behaviour, and the tests assert it rather than treating it as
an error.
