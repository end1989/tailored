# Extending Tailored

Tailored has two deliberate extension seams: the MCP tool contract (plug in
any agent as the intelligence) and the internal pipeline's provider seam
(run the built-in pipeline on any model/provider).

## 1. The MCP tool contract (any agent)

`backend/mcp_server.py` exposes Tailored over stdio MCP; the business logic
lives in `backend/mcp_ops.py` as plain functions. Any MCP-capable agent that
registers the server (see the README's MCP mode section) can drive the full
workflow. The truthfulness guard runs server-side inside
`save_tailored_resume`, so no connected agent can save fabricated history.

| Tool | What it does |
|------|--------------|
| `get_workflow_guide()` | Call first: returns the workflow order, the truthfulness contract, and the exact JSON schemas with a worked example. |
| `list_profiles()` | List stored profiles (id, name, has_master_profile). |
| `get_master_profile(profile_id?)` | Contact + master profile — the only facts an agent may use. Omitting `profile_id` resolves the sole profile; ambiguity returns an error listing the profiles. |
| `add_profile_evidence(profile_id, projects?, skill_groups?, summary_note?)` | Import portfolio-scan findings into the master profile (`MPProject` + `SkillGroup` shapes). Additive and verified-evidence-only: never overwrites — new projects are appended (duplicate names skipped), same-label skill groups are merged, `summary_note` is appended; safe to call repeatedly. |
| `list_templates()` | The four templates with label/description/best_for metadata. |
| `create_application(profile_id, url, posting_text, template?)` | Register a job with agent-gathered posting text; creates the Job + Application (status `tailoring`, depth `external`) and returns `application_id`. |
| `save_parsed_posting(application_id, parsed)` | Store the agent's `ParsedPosting` analysis (dashboard shows company/title from it). |
| `save_research(application_id, findings)` | Optionally store agent-performed research as a `ResearchFindings` brief (tokens/cost 0). |
| `save_tailored_resume(application_id, resume, cover_letter_md, tailoring_notes?)` | The gated write: validates `ResumeDoc`, verifies truthfulness against the master profile (violations are returned verbatim for correction), snapshots a version, renders and exports; returns `ready` with the export files. |
| `get_application(application_id)` | Status / version / error_message / export files. |

**Concurrency with the built-in pipeline.** An application is owned by
whichever side is actively working it, in one direction only at a time.
MCP-driven applications park in status `tailoring` between
`create_application` and `save_tailored_resume`; while parked, the web UI's
paste/regenerate/edit actions on that row are blocked, so an abandoned agent
run leaves the row stuck there until someone either deletes it from the
dashboard/DB or an agent saves to it to release it. Conversely,
`save_parsed_posting`, `save_research`, and `save_tailored_resume` reject
with an error naming the status whenever the built-in pipeline is actively
processing that application (`queued`, `fetching`, `researching`, or
`rendering`) - retry once it finishes or create a separate application for
the agent run.

`add_profile_evidence` and other profile writes have no such guard: they
use last-writer-wins on the whole profile record, so don't hand-edit a
profile in the web UI while an agent is writing to it (and vice-versa) -
this is a single-user local app and simultaneous edits to the same profile
are unsupported.

## 2. The pipeline's provider seam (any model)

Every AI call in the built-in pipeline goes through one method:

```
ClaudeService.structured(
    task, system, user_content, schema_model, tools, max_tokens
) -> (BaseModel, UsageInfo)
```

(`backend/app/services/claude.py`). To run the pipeline on a different model
or provider, implement an object with that method — it must return an
instance of `schema_model` plus a `UsageInfo` — and swap it in `make_claude`
(same file). The fixture-backed fake mode (`ClaudeService` with
`fake_mode=True`) is the reference implementation of the contract: it shows
exactly what the pipeline passes in and expects back, and the whole test
suite runs against it.
