# Tailored — Person Picker — Design Spec

Date: 2026-09-21
Status: draft, awaiting review
Followed by: the voice-samples spec (writing samples per person), which builds
on the active person defined here

## 1. What this is

Tailored supports several people on one install (v1 spec §4: "one per person;
multiple profiles per install supported"), but the web app has no notion of
who is using it. This spec adds one app-wide person picker. Choose a person and
every screen shows that person's profile, applications, and settings. Switching
is one click, at any time, with no sign-in, so a household can share one
install and move back and forth freely.

## 2. What exists today

### 2.1 Every screen picks its own person

Dashboard, Add Jobs and Profiles each call `listProfiles()`, hold their own id
in component state, default to `list[0]`, and forget the choice on unmount
(`DashboardScreen.tsx:133-153`, `AddJobsScreen.tsx:21-42`,
`ProfileScreen.tsx:42-76`). There is no React context anywhere in
`frontend/src`. Consequences seen in real use:

- Queueing jobs for a second person on Add Jobs navigates to `/`, which
  remounts the Dashboard on `list[0]`: the user lands on someone else's
  applications.
- The Profiles screen opens on `list[0]`. A resume meant for a second person
  was uploaded to the first person's profile. Because `_voice_for` takes the
  newest `SourceDocument` (`pipeline.py:110-123`), that resume became the first
  person's register reference, and a Build on that profile would have merged
  the second person's jobs into it. No route can remove a document.
- The Dashboard's first poll fires before `listProfiles` resolves, with no
  profile filter, and briefly fetches every person's applications.
- `GET /api/profiles` has no `ORDER BY` (`profiles.py:69`), so `list[0]` is
  whatever order SQLite returns.
- The copyable agent prompts in `McpSetup.tsx:6-10` say "my profile". With
  several people, `get_master_profile()` without an id errors
  (`mcp_ops.py:268-273`), so the agent has to guess or ask.

### 2.2 Settings are app-wide

`data/settings.json` holds `default_template`, `default_depth`, `page_size` for
the whole install (`config.py:11-15`). They are read by batch create
(`applications.py:261-265`) and by every render path: the pipeline
(`pipeline.py:190-194`), template switch (`applications.py:496-506`), content
save (`applications.py:609-617`), and both MCP render paths
(`mcp_ops.py:661-672`, `mcp_ops.py:843-847`). The Settings, Templates, Add Jobs
and Getting Started screens read them through `getSettings()`.

### 2.3 Nothing can be removed, and a person's email cannot be edited

There is no delete route for a profile or a source document
(`api/profiles.py:67-184`); only applications can be deleted
(`applications.py:713-747`), and that route leaves the application's `Job` and
`ResearchBrief` rows behind. `PUT /api/profiles/{id}` accepts `name` and
`contact` (`profiles.py:102-119`), but no screen edits them after creation, and
Build replaces the whole contact with whatever intake finds in the documents
(`profiles.py:176-177`).

## 3. Decisions

| Decision | Choice |
|---|---|
| Where the choice lives | This browser only: `localStorage`, per Chrome profile |
| Reach | Web app only. MCP tools keep taking an explicit `profile_id` |
| Switching | One control in the nav, on every screen, no sign-in |
| Settings | Per person: template, research depth, page size |
| Which person's settings a render uses | The application's owner, never the picker |
| Another person's application opened | Switch to its owner for this visit, with a notice |
| Removing a document | Per-document Remove with an inline confirm |
| Removing a person | Typed-name confirm; deletes that person's rows and export files |
| Inbox | A derived `inbox_url` per person, shown in the app and given to MCP |
| Account detection | None. Browsers do not expose Chrome or Google identity to pages |

Per-document Remove (§6.1) and editable name and email (§4.3) were proposed in
the design discussion to repair the wrong-profile upload in §2.1 and to keep
the Inbox link correct; they are included here for review.

### 3.1 Why the browser, and why not the Google account

A web page cannot read which Chrome profile or Google account is signed in;
browsers withhold both on purpose. The only way to learn a Google identity is
"Sign in with Google", which needs a registered OAuth client and makes the app
unusable without a login. That contradicts the requirement that switching work
freely whether or not anyone is signed into Gmail.

Storing the choice in `localStorage` gets the useful half of Chrome profiles
for free: each Chrome profile has its own storage, so a household where each
person uses their own Chrome profile opens Tailored on the right person, and
anyone can still switch. A household sharing one Chrome profile loses nothing.

The choice is deliberately not stored on the server. A server-side "active
person" would be shared state an MCP agent could come to depend on, and what an
agent writes must not depend on what happens to be selected in a browser.

## 4. The active person (frontend)

### 4.1 `PersonProvider`

New module `frontend/src/person.tsx`, mounted around `<App/>`'s nav and routes:

```ts
type PersonContext = {
  people: ProfileSummary[];      // ordered by id
  person: ProfileSummary | null; // null while loading, on a load error, or with no people
  loading: boolean;              // true until the first listProfiles() settles
  error: string | null;          // the listProfiles() failure, if any
  setPersonId(id: number, opts?: { remember?: boolean }): void;
  refreshPeople(selectId?: number): Promise<boolean>; // true: applied a fresh list
  setSwitchGuard(message: string | null): void;  // see 4.4
};
export function usePerson(): PersonContext;
```

"No people" means `!loading && !error && people.length === 0`. Screens render
nothing person-dependent until `loading` is false, so neither the create form
nor the app-wide settings flash while the list loads or when the API is down.

**Remembering.** The key `tailored-person` holds JSON `{id, created_at}`.
`ProfileSummary` and `GET /api/profiles` gain `created_at`. On load, the stored
entry is used only if a person with that id exists and has that `created_at`;
otherwise the provider falls back to the first person and overwrites the entry.
The `created_at` check matters because SQLite reuses the highest id after a
delete (the `profile` table has no `AUTOINCREMENT`, and adding it would mean
recreating the table, which the never-retype rule forbids): without it, a
browser that remembered a removed person would silently open on whoever was
created next. A stored value that is missing, unparseable or not an object
falls back the same way. Every storage read and write is wrapped in
`try/catch`; when storage throws, the provider works in memory.

Only a choice made in the picker is remembered (`remember` defaults to true).
The Application screen's owner switch (§4.3) passes `remember: false`, so
opening one of another person's links does not change which person that Chrome
profile opens on next time.

**Refreshing.** `refreshPeople()` is called after any profile write: create,
save, Build, name or email edit, document upload or remove, and person removal.
The provider also refreshes when the tab becomes visible again
(`visibilitychange`). If the current person has disappeared, or their
`created_at` changed, it falls back to the first person and shows
"{label} was removed." under the picker. Switching in one tab does not switch
other open tabs.

`GET /api/profiles` gains `ORDER BY id`, so "the first person" is stable.

### 4.2 The picker

In the nav, right-aligned beside the theme toggle.

- With people: a controlled native `<select aria-label="Person">` whose value is
  always `person.id`. It lists every person, plus a final "Add a person…"
  option that navigates to the Profiles screen's create form; after any pick
  the control snaps back to `person.id`, so "Add a person…" can be chosen again
  and a refused guarded switch (§4.4) shows the unchanged person.
- With no people: an "Add a person" link to the create form instead of the
  select (a select whose only option is already selected fires no change).
- Labels: the person's name. When two people share a name, their labels become
  "{name} ({email})", or "{name} #{id}" without an email. The same label is used
  in every notice and heading in this spec.
- When the current person has an `inbox_url` (§7), an "Inbox" link sits beside
  the select and opens it in a new tab (`rel="noopener noreferrer"`).
- At phone width it wraps with the rest of the nav (`styles.css:300`).

### 4.3 Screens

Every per-person fetch is keyed on `person.id` and ignores a response that
arrives after the person has changed.

| Screen | Change |
|---|---|
| Dashboard | Lists `listApplications(person.id)`. Its own dropdown is removed. It makes no request while `person` is null, and clears its list the moment the person changes, so another person's rows are never shown with live controls. |
| Add Jobs | Queues for `person.id`, with "Adding jobs for {label}". Its own select is removed. Defaults come from the person's settings (§5). Submit is disabled until that person's settings have loaded, and with no people shows "Add a person first". The submit uses the id captured at click; afterwards it navigates to `/`, which shows the same person. |
| Profiles | Edits `person` only. The "Your profiles" button row is removed. Name and email become editable fields, saved through the existing `PUT /api/profiles/{id}` (`name`, `contact`); a blank name is rejected (§6.2). The create form (name, email) appears when there are no people or when opened from "Add a person…"; creating calls `refreshPeople(newId)`, which switches to the new person. Documents get Remove (§6.1); the page ends with "Remove this person" (§6.2). |
| Getting Started | "Profile ready" reflects the current person's `has_master_profile`, not whether any person has one. |
| McpSetup (Getting Started, Settings) | Both copyable prompts name the current person, e.g. "for {name} (profile_id {id})". With no people they keep "my profile". |
| Application | Once per application id, after the provider has loaded: if `detail.profile_id !== person.id`, switch with `remember: false` and show "Switched to {label} to show this application." If the owner is not in `people`, call `refreshPeople()` first; if still absent, do not switch and show "This application's person no longer exists." If that refresh failed (it resolves false), do not switch and show "Couldn't check who this application belongs to." instead. Later polls never switch again. A manual picker switch while on this screen navigates to `/` for the chosen person. While the inline editor or the cover letter has unsaved edits (the screen's existing `dirty`/`coverDraft` state), the screen sets the switch guard. |
| Settings, Templates | Read and write the current person's settings (§5), headed "Settings for {label}". API key status and theme stay in an app-wide section. With no people, they edit the app-wide defaults as today. |

### 4.4 The switch guard

A screen with work that a switch would lose calls `setSwitchGuard(message)`.
A switch attempted from the picker while a guard is set shows an inline prompt
under the picker ("Switch anyway" / "Stay") instead of switching. No
`window.confirm`.

- **Profiles** sets "{label} has unsaved profile changes." while the master
  profile, voice notes, name or email differ (deep compare) from the last
  loaded or saved detail, and "{label}'s profile is building." (or saving,
  uploading, removing) while one of those requests is in flight.
- **Application** sets "{label}'s application has unsaved edits." as in §4.3.
- **Lifecycle.** A screen clears its guard when the condition ends (after a
  save, a reload, or reverting edits) and in the cleanup of the effect that set
  it, so leaving a screen never leaves a guard behind.
- **What it intercepts.** Only picker switches, including "Add a person…". The
  Application owner switch and `refreshPeople()` do not go through it; the
  Profiles screen clears its own guard before calling `refreshPeople()` after a
  create or a removal.
- **Late responses.** Every async handler on Profiles captures `person.id` when
  it starts and drops its response if the person has changed. Without this, a
  Build that returns after a switch would load one person's master profile
  into the other's editor, and the next Save would write it there: the
  contamination in §2.1, which the truthfulness guard would then accept.

## 5. Per-person settings (backend)

### 5.1 Storage

New column `Profile.settings_json: str = "{}"`, following the JSON-TEXT
convention (`models.py:127-170`). The scalar default makes `_add_missing_columns`
emit `NOT NULL DEFAULT '{}'`, so existing rows need no backfill. Typed helpers
`get_profile_settings(profile) -> dict` and `set_profile_settings(profile, dict)`
accept only the three known keys with valid values.

An empty object means "use the app-wide values", so a new person starts from
the current app-wide defaults. The Settings screen always writes a person's
own values, so with people present the app-wide file changes only through the
API.

### 5.2 One resolver

```python
def settings_for(data_dir: Path, profile: Profile | None) -> dict:
    """DEFAULT_USER_SETTINGS, overlaid with data/settings.json, overlaid with
    the profile's own values."""
```

Every backend consumer in §2.2 switches from `load_user_settings(data_dir)` to
`settings_for(data_dir, <the application's profile>)`, looked up from the
application row (or `body.profile_id` for batch create). This is the rule that
keeps MCP independent of the picker: a render always uses its owner's page
size, whoever is selected in any browser.

### 5.3 API

- `GET /api/settings?profile_id=N` returns the existing shape
  (`default_template`, `default_depth`, `page_size`, `api_key_set`,
  `fake_mode`) with that person's effective values. Unknown person: 404.
- `PUT /api/settings?profile_id=N` validates exactly as today
  (`settings.py:43-57`) and writes that person's values.
- Without `profile_id`, both behave exactly as today, so existing callers and
  `test_settings_round_trip` are unaffected.

### 5.4 Where per-person defaults do not reach

Per-person default template and depth apply to jobs added in the web app. Rows
created by MCP `create_application` or `queue_jobs` keep today's defaults
(template `slate`, depth `standard`), including when such a row is generated
later from the Dashboard. Page size always follows the owner (§5.2).

## 6. Removing things

### 6.1 A document

`DELETE /api/profiles/{id}/documents/{doc_id}`: 404 when the document does not
exist or belongs to another profile; otherwise deletes the row and returns
`{"deleted": doc_id}`. The built master profile is not changed; the next Build
reads only what remains. Removing a document also changes the voice sample at
once: the next generation uses the newest remaining document, or none
(`_voice_for`, `pipeline.py:110-123`). UI: a Remove button per document, then
an inline "Remove {filename}? Yes / No".

### 6.2 A person

`DELETE /api/profiles/{id}?confirm_name=<exact name, URL-encoded>`.

- **Confirmation.** 422 when `confirm_name` is missing, blank after `strip()`,
  or not exactly the profile's name. The check is server-side so a stray call
  cannot delete a person. Create and update now reject a blank name with 422,
  so every person has a name to type.
- **Active work.** 409 when any of the person's applications is `queued`,
  `fetching`, `researching`, `tailoring` or `rendering` and its `updated_at` is
  within the last 15 minutes (the pipeline stamps `updated_at` on every
  transition, `pipeline.py:35-43`; MCP `create_application` parks a fresh row
  in `tailoring`). The 409 body lists each blocking application (id, company or
  URL, status) and the panel shows them as links. Older rows in those statuses
  are treated as abandoned (a server restart kills background tasks, and an
  agent can abandon a parked row) and are deleted with the rest; without this,
  one stuck row would make a person impossible to remove.
- **Queue-driven MCP work is not detected.** An agent working a `not_started`
  row from `queue_jobs` leaves no status trace, so the panel says
  "{k} saved jobs, including any an agent is working on, will be removed."
- **Files.** Every `exports/<id>` of the person is first renamed into
  `exports/.removing-<profile_id>/<id>`. If any rename fails (Windows refuses
  while a file inside is open), the renamed directories are moved back and the
  route returns 409 naming the application and file; nothing is deleted. After
  the database commit the staging directory is removed; a failure there is
  logged, not raised.
- **Rows.** One transaction, set-based on `profile_id`: for each application,
  its events, versions, research briefs, job and the application itself, then
  the person's documents, then the profile. A shared helper
  `_delete_application_rows(session, app_row)` does the per-application part;
  `delete_application` uses it too, so a single-application delete now also
  removes its job and research briefs. Job rows orphaned by earlier deletes are
  unreachable and are left alone.
- **Response.** `{"deleted": id, "applications": n, "documents": m}`.

UI: at the bottom of the Profiles screen, "Remove this person" opens an inline
panel stating what will be deleted: "{label}'s profile, {m} documents and {n}
applications (archived included), plus their exported files." The counts come
from the server: profile detail gains `application_count` (every application
of the person, archived included); `m` is `documents.length`. A text field
enables the button only when it equals the name exactly. After deletion the
Profiles screen clears its guard and calls `refreshPeople()`, which falls back
to the first remaining person.

In demo mode (`TAILORED_FAKE=1`), removing the last person means the demo
person and application are seeded again on the next start (`demo.py:30-31`
seeds whenever no profile exists).

No MCP tool is added for removal.

## 7. Inbox link

One function, `inbox_url(email: str) -> str | None`, matching the contact
email's domain after `strip()` and `lower()`:

| Domain | URL |
|---|---|
| `gmail.com`, `googlemail.com` | `https://mail.google.com/mail/?authuser=<url-encoded email>` |
| `icloud.com`, `me.com`, `mac.com` | `https://www.icloud.com/mail` |
| `outlook.com`, `hotmail.com`, `live.com`, `msn.com` | `https://outlook.live.com/mail/` |
| anything else, or no email | `None` |

Only the Gmail form selects an account; the others open whichever account is
signed in on that site. Custom domains (including Google Workspace) get no link
because the provider cannot be known from the domain.

The email is the one shown and editable on the Profiles screen (§4.3). Build
keeps a non-empty existing name and email and fills only empty contact fields
from the documents, so a Build over an old resume cannot move the Inbox link to
another address.

- `GET /api/profiles` and profile detail include `inbox_url`.
- MCP `get_master_profile` includes `inbox_url` (an additive output key).
- `get_workflow_guide` gains one short section on inbox work in the user's
  browser: open the candidate's `inbox_url`, never an account chosen by
  position; before reading anything, confirm the mailbox address on the page
  equals the candidate's contact email, and if it differs, stop and say which
  account is open; a sign-in page means that account is not signed in in this
  browser, so say so and stop; if `inbox_url` is null, open no inbox and ask the
  user which one to use; never sign in on the user's behalf.

## 8. What does not change

- Every MCP tool and its arguments. `profile_id` stays explicit;
  `get_master_profile()` without an id still errors when several people exist.
  The only MCP changes are §7's additive `inbox_url` key and guide section.
- `GET /api/applications` without `profile_id` still returns everyone's rows,
  for external callers.
- Per-application routes are keyed by application id, as today.
- Template previews render from the fixture, not from a person.

## 9. Testing

Backend:

- `GET /api/profiles` is ordered by id and carries `created_at` and
  `inbox_url`; profile detail carries `application_count` including archived
  rows.
- Profiles: create and update reject a blank name; Build keeps a non-empty name
  and email and fills empty ones.
- Settings: per-person GET/PUT round trip; an empty override set inherits the
  app-wide values; invalid values 422; unknown person 404; the no-`profile_id`
  shape is unchanged.
- Each consumer in §2.2 uses the owner's settings. Two people with different
  page sizes, one application each: pipeline render, template switch, content
  save, and both MCP render paths each pass the owner's page size to
  `export_application`. Batch create uses the person's default template and
  depth.
- Document delete: success; unknown document 404; another profile's document
  404; master profile unchanged; `_voice_for` falls back to the next-newest
  document.
- Person delete: missing, blank or wrong `confirm_name` 422; a recent
  `fetching` row 409 with the row listed; a stale `fetching` row and a stale
  MCP-parked `tailoring` row do not block; success removes rows and export
  directories for that person only, and leaves a second person's rows and
  files intact; a locked export directory (simulated rename failure on the
  second directory) removes nothing, restores the first directory, and returns
  409.
- `delete_application` now removes the application's job and research briefs.
- Migration: `settings_json` is added to an existing database with `'{}'`
  (`test_migration.py` pattern).
- `inbox_url` table cases including case and whitespace; `get_master_profile`
  returns it; the guide contains the new section's sentences.

Frontend (vitest, a `renderWithPerson` test helper wrapping the provider and a
`MemoryRouter`):

- The provider restores a stored `{id, created_at}`; falls back when the stored
  person is gone, when the id was reused (same id, different `created_at`), and
  when the stored value is malformed; works when `localStorage` throws; shows
  "{label} was removed." after a refresh finds the current person gone.
- Switching the picker changes what Dashboard, Add Jobs, Profiles, Settings,
  Templates, Getting Started and the McpSetup prompts use; the Dashboard shows
  no rows from the previous person after a switch; a late response for the
  previous person is ignored.
- No people: the nav shows the "Add a person" link; Add Jobs says
  "Add a person first".
- "Add a person…" opens the create form and the select snaps back; creating
  switches to the new person.
- Duplicate names get distinguishing labels.
- Application screen: switches to the owner once, does not remember it, is not
  reverted by a later poll after a manual switch, and shows the "no longer
  exists" message for an orphan.
- Switch guard: shows the inline prompt instead of switching; a Build that
  resolves after a switch does not load into the new person's editor; leaving
  Profiles with unsaved edits clears the guard.
- Document Remove and person Remove, including the disabled button until the
  typed name matches and the counts from `application_count`.
- Editing a person's email updates the nav Inbox link.
- Existing screen tests move onto `renderWithPerson`. `App.test.tsx`'s api mock
  gains any newly called exports.

`frontend/dist` is rebuilt and committed with the source change
(`tests/test_frontend_bundle.py`).

## 10. Docs

- README: a "Several people, one install" section (the picker, Chrome
  profiles, per-person settings, removing a person, the Inbox link); update the
  Profiles, Settings and demo-mode wording.
- `docs/EXTENDING.md` §1: `get_master_profile` returns `inbox_url`; the guide's
  inbox section.
- `CLAUDE.md`: frontend (the person context replaces per-screen profile
  state), `config.py`/`models.py` (per-person settings), the `inbox_url` guide
  section.
- Outside the repo, not committed: an operator whose local agent instructions
  pick a mailbox by position should switch them to the `inbox_url` returned by
  `get_master_profile(profile_id)`. This spec does not reproduce those
  instructions.

## 11. Out of scope

- Writing samples and voice analysis (next spec).
- Per-person API keys or billing, and a per-person cost ledger.
- The person in the URL, and Google sign-in.
- Syncing the choice across open tabs.
- MCP following the picker.
- Tombstoning removed profiles so their ids are never reissued. Considered:
  it would protect an MCP agent holding a stale `profile_id`, but it makes
  every profile lookup in the API and MCP filter deleted rows. The browser is
  protected by the `created_at` check in §4.1.

## 12. Risks

- Test churn: every screen test that mounted a screen bare now needs the
  provider. Mitigated by one shared helper.
- A removed person's id can be reissued to the next person created. Browsers
  are protected by §4.1. An MCP agent that kept a `profile_id` across a removal
  and a new creation would act on the new person; agents are told to resolve
  the profile with `get_master_profile` at the start of a session.
- Removing a person while an agent is actively writing for them is
  unsupported, like other simultaneous edits (EXTENDING.md §1). The 409 covers
  recent pipeline and parked-MCP activity but not queue-driven agent work.
- Regenerate and paste schedule their background run without first marking the
  row `queued`, so a removal in the instant between the response and the run
  is not caught by the 409; that run then fails against missing rows. The
  window is the gap between an HTTP response and its background task.
- Deleting a person is irreversible. Mitigated by the server-side typed-name
  check, the active-work refusal, and the panel stating exactly what goes.
