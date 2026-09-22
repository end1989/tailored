import { useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  buildProfile,
  createProfile,
  deleteDocument,
  deleteProfile,
  getProfile,
  listApplications,
  updateProfile,
  uploadDocument,
} from "../api";
import { usePerson } from "../person";
import { STATUS_LABELS } from "../statuses";
import type {
  AppStatus,
  Contact,
  MasterProfile,
  MPCertification,
  MPEducation,
  MPExperience,
  MPProject,
  ProfileDetail,
  ProfileSummary,
  SkillGroup,
  TaggedBullet,
  UsageInfo,
} from "../types";

const emptyMP: MasterProfile = {
  summary_notes: "",
  experiences: [],
  projects: [],
  skills: [],
  education: [],
  certifications: [],
  extras: [],
};

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/**
 * Structural equality for the editor's JSON-shaped state, so an edit typed
 * and then reverted reads as clean. A key missing on one side and undefined
 * on the other counts as equal.
 */
function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((item, i) => deepEqual(item, b[i]));
  }
  const ao = a as Record<string, unknown>;
  const bo = b as Record<string, unknown>;
  for (const key of new Set([...Object.keys(ao), ...Object.keys(bo)])) {
    if (!deepEqual(ao[key], bo[key])) return false;
  }
  return true;
}

/** Every request the editor makes that a person switch would cut short. */
type Action =
  | "build"
  | "save-profile"
  | "save-identity"
  | "upload"
  | "remove-document"
  | "remove-person";

/** How the switch guard words each one: "{label}'s profile is building." */
const BUSY_WORD: Record<Action, string> = {
  build: "building",
  "save-profile": "saving",
  "save-identity": "saving",
  upload: "uploading",
  "remove-document": "removing",
  "remove-person": "removing",
};

/** "1 document", "4 applications". */
function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** The Dashboard's words for a status; a locked export file reads "locked". */
function statusLabel(status: string): string {
  return Object.prototype.hasOwnProperty.call(STATUS_LABELS, status)
    ? STATUS_LABELS[status as AppStatus]
    : status;
}

/** One application, or one locked export file, standing in the way of a removal. */
interface RemovalBlocking {
  id: number;
  label: string;
  status: string;
}

interface RemovalProblem {
  message: string;
  blocking: RemovalBlocking[];
}

/**
 * Reads a failed DELETE /profiles/{id}. A 409's detail is an object
 * ({message, blocking}), and api.ts's request() puts a non-string detail into
 * the Error message as the whole JSON body ("API 409: {"detail": {...}}"), so
 * the blocking list is recovered from there. Anything else is shown as is.
 */
function removalProblem(err: unknown): RemovalProblem {
  const text = err instanceof Error ? err.message : String(err);
  const match = /^API 409: ([\s\S]*)$/.exec(text);
  if (match) {
    try {
      const detail = JSON.parse(match[1])?.detail;
      if (detail && typeof detail.message === "string" && Array.isArray(detail.blocking)) {
        return { message: detail.message, blocking: detail.blocking as RemovalBlocking[] };
      }
    } catch {
      // Not the structured body; fall through to the raw message.
    }
  }
  return { message: String(err), blocking: [] };
}

/** Editor fields that take the server's value when a write comes back. */
type Part = "mp" | "voice" | "identity";

export default function ProfileScreen() {
  const { people, person, loading, error: peopleError } = usePerson();
  const [searchParams, setSearchParams] = useSearchParams();
  const listed = !loading && peopleError === null;
  const showCreate = listed && (people.length === 0 || searchParams.get("new") === "1");
  // created_at is part of the key because SQLite reissues a removed person's id.
  const personKey = person ? `${person.id}@${person.created_at}` : null;

  // Choosing a person in the nav while the create form is open means "show me
  // this person", so the form gives way to their editor. The first load
  // (nobody, then someone) is not a choice.
  const prevKey = useRef(personKey);
  useEffect(() => {
    const was = prevKey.current;
    prevKey.current = personKey;
    if (was !== null && was !== personKey && searchParams.get("new") === "1") {
      setSearchParams({}, { replace: true });
    }
    // Only a change of person matters here, not a change of the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personKey]);

  return (
    <div>
      <h1>Profiles</h1>
      {peopleError !== null && <div className="alert alert-error">{peopleError}</div>}
      {showCreate ? (
        <CreatePersonForm onCancel={people.length > 0 ? () => setSearchParams({}) : null} />
      ) : (
        // Keyed on the person: a switch mounts a fresh editor, so nothing typed
        // for one person, and no late response to their requests, can land in
        // another person's fields.
        person !== null &&
        personKey !== null && <PersonEditor key={personKey} person={person} />
      )}
    </div>
  );
}

function CreatePersonForm({ onCancel }: { onCancel: (() => void) | null }) {
  const { refreshPeople, setSwitchGuard } = usePerson();
  const [searchParams, setSearchParams] = useSearchParams();
  const [newName, setNewName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // False once this form is gone (the user left the screen, or the new person
  // was selected and the form gave way to their editor).
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  async function handleCreate() {
    const name = newName.trim();
    if (name === "") return;
    const fromPicker = searchParams.get("new") === "1";
    setCreating(true);
    setError(null);
    try {
      const d = await createProfile(name, { name, email: newEmail.trim(), links: [] });
      // Nothing may hold back the switch refreshPeople makes to the new person.
      // A form that is gone owns no guard, and the screen now showing may hold
      // one, so only a mounted form clears it.
      if (alive.current) setSwitchGuard(null);
      await refreshPeople(d.id);
      // Gone means the user left or the editor took over: no navigation back
      // to /profiles.
      if (!alive.current) return;
      setNewName("");
      setNewEmail("");
      if (fromPicker) setSearchParams({}, { replace: true });
    } catch (err) {
      if (alive.current) setError(String(err));
    } finally {
      if (alive.current) setCreating(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title">Add a person</div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="field">
        <label className="field-label" htmlFor="new-person-name">Name</label>
        <input
          id="new-person-name"
          className="input"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="new-person-email">Email</label>
        <input
          id="new-person-email"
          className="input"
          type="email"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
        />
      </div>
      <div className="row">
        <button
          className="btn btn-primary"
          onClick={handleCreate}
          disabled={creating || newName.trim() === ""}
        >
          {creating ? "Creating..." : "Create person"}
        </button>
        {onCancel && (
          <button className="btn" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * The editor for one person. ProfileScreen mounts a new one per person, so
 * `person.id` is fixed for the life of this component.
 */
function PersonEditor({ person }: { person: ProfileSummary }) {
  const { refreshPeople, setSwitchGuard, labelFor } = usePerson();
  const label = labelFor(person);
  const [detail, setDetail] = useState<ProfileDetail | null>(null);
  const [mp, setMp] = useState<MasterProfile>(emptyMP);
  const [voiceNotes, setVoiceNotes] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [pasteName, setPasteName] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [buildUsage, setBuildUsage] = useState<UsageInfo | null>(null);
  const [busy, setBusy] = useState<Action | null>(null);
  const [confirmDocId, setConfirmDocId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [savedJobs, setSavedJobs] = useState<number | null>(null);
  const [removeProblem, setRemoveProblem] = useState<RemovalProblem | null>(null);
  const building = busy === "build";
  const saving = busy === "save-profile";

  // False once this editor is gone. A request that finishes after that still
  // refreshes the people list, but applies nothing to the screen.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  /** The first load: every field starts from the server. */
  function loadDetail(d: ProfileDetail) {
    setDetail(d);
    setMp({ ...emptyMP, ...d.master_profile });
    setVoiceNotes(d.voice_notes);
    setName(d.name);
    setEmail(d.contact.email);
  }

  /**
   * A write came back: `d` becomes the baseline the dirty check compares
   * against. Fields named in `take` show the server's value. Every other field
   * keeps an unsaved edit and follows the server only when it had none, so a
   * Build that fills an empty email shows it instead of leaving a blank box
   * that the next save would write back.
   */
  function applyResponse(d: ProfileDetail, prev: ProfileDetail, take: Part[]) {
    const prevMp = { ...emptyMP, ...prev.master_profile };
    const nextMp = { ...emptyMP, ...d.master_profile };
    setDetail(d);
    setMp((m) => (take.includes("mp") || deepEqual(m, prevMp) ? nextMp : m));
    setVoiceNotes((v) => (take.includes("voice") || v === prev.voice_notes ? d.voice_notes : v));
    setName((n) => (take.includes("identity") || n === prev.name ? d.name : n));
    setEmail((e) => (take.includes("identity") || e === prev.contact.email ? d.contact.email : e));
  }

  useEffect(() => {
    getProfile(person.id)
      .then((d) => {
        if (alive.current) loadDetail(d);
      })
      .catch((e) => {
        if (alive.current) setError(String(e));
      });
    // Runs once: this editor never changes person (see ProfileScreen).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty =
    detail !== null &&
    (!deepEqual(mp, { ...emptyMP, ...detail.master_profile }) ||
      voiceNotes !== detail.voice_notes ||
      name !== detail.name ||
      email !== detail.contact.email);
  const guard =
    busy !== null
      ? `${label}'s profile is ${BUSY_WORD[busy]}.`
      : dirty
        ? `${label} has unsaved profile changes.`
        : null;

  // Set while a switch would lose something; cleared when that ends and when
  // this editor unmounts. The setter is read through a ref so the effect
  // depends on the message alone, not on the setter's identity.
  const setGuard = useRef(setSwitchGuard);
  setGuard.current = setSwitchGuard;
  useEffect(() => {
    if (guard === null) return;
    setGuard.current(guard);
    return () => setGuard.current(null);
  }, [guard]);

  // ---- typed master-profile editor helpers ----

  function updateExperience(idx: number, patch: Partial<MPExperience>) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) => (i === idx ? { ...e, ...patch } : e)),
    }));
  }

  function addExperience() {
    setMp((m) => ({
      ...m,
      experiences: [
        ...m.experiences,
        { company: "", title: "", start: "", end: null, location: null, bullets: [] },
      ],
    }));
  }

  function removeExperience(idx: number) {
    setMp((m) => ({ ...m, experiences: m.experiences.filter((_, i) => i !== idx) }));
  }

  function updateBullet(expIdx: number, bulletIdx: number, patch: Partial<TaggedBullet>) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) =>
        i === expIdx
          ? {
              ...e,
              bullets: e.bullets.map((b, j) => (j === bulletIdx ? { ...b, ...patch } : b)),
            }
          : e
      ),
    }));
  }

  function addBullet(expIdx: number) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) =>
        i === expIdx ? { ...e, bullets: [...e.bullets, { text: "", tags: [] }] } : e
      ),
    }));
  }

  function removeBullet(expIdx: number, bulletIdx: number) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) =>
        i === expIdx ? { ...e, bullets: e.bullets.filter((_, j) => j !== bulletIdx) } : e
      ),
    }));
  }

  function updateSkillGroup(idx: number, patch: Partial<SkillGroup>) {
    setMp((m) => ({
      ...m,
      skills: m.skills.map((g, i) => (i === idx ? { ...g, ...patch } : g)),
    }));
  }

  function addSkillGroup() {
    setMp((m) => ({ ...m, skills: [...m.skills, { label: "", items: [] }] }));
  }

  function removeSkillGroup(idx: number) {
    setMp((m) => ({ ...m, skills: m.skills.filter((_, i) => i !== idx) }));
  }

  function updateEducation(idx: number, patch: Partial<MPEducation>) {
    setMp((m) => ({
      ...m,
      education: m.education.map((ed, i) => (i === idx ? { ...ed, ...patch } : ed)),
    }));
  }

  function addEducation() {
    setMp((m) => ({
      ...m,
      education: [...m.education, { institution: "", credential: "", year: null, detail: null }],
    }));
  }

  function removeEducation(idx: number) {
    setMp((m) => ({ ...m, education: m.education.filter((_, i) => i !== idx) }));
  }

  function updateCertification(idx: number, patch: Partial<MPCertification>) {
    setMp((m) => ({
      ...m,
      certifications: m.certifications.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
    }));
  }

  function addCertification() {
    setMp((m) => ({
      ...m,
      certifications: [...m.certifications, { name: "", issuer: null, year: null }],
    }));
  }

  function removeCertification(idx: number) {
    setMp((m) => ({ ...m, certifications: m.certifications.filter((_, i) => i !== idx) }));
  }

  function updateProject(idx: number, patch: Partial<MPProject>) {
    setMp((m) => ({
      ...m,
      projects: m.projects.map((p, i) => (i === idx ? { ...p, ...patch } : p)),
    }));
  }

  function addProject() {
    setMp((m) => ({
      ...m,
      projects: [...m.projects, { name: "", description: "", url: null, bullets: [] }],
    }));
  }

  function removeProject(idx: number) {
    setMp((m) => ({ ...m, projects: m.projects.filter((_, i) => i !== idx) }));
  }

  function updateExtra(idx: number, value: string) {
    setMp((m) => ({ ...m, extras: m.extras.map((x, i) => (i === idx ? value : x)) }));
  }

  function addExtra() {
    setMp((m) => ({ ...m, extras: [...m.extras, ""] }));
  }

  function removeExtra(idx: number) {
    setMp((m) => ({ ...m, extras: m.extras.filter((_, i) => i !== idx) }));
  }

  // ---- actions ----
  //
  // Each write captures person.id when it starts (in run). The editor is
  // remounted per person, so a response that lands after a switch reaches an
  // unmounted editor and is dropped there: a Build that returns late can never
  // load one person's master profile into another's editor, where the next
  // Save would write it.

  async function run<T>(
    action: Action,
    call: (id: number) => Promise<T>,
    apply: (result: T) => void
  ): Promise<boolean> {
    const id = person.id;
    setBusy(action);
    setError(null);
    try {
      const result = await call(id);
      const applied = alive.current;
      if (applied) apply(result);
      // The list carries names, emails, inbox links and has_master_profile, so
      // it is refreshed after every write, including one whose editor is gone.
      await refreshPeople();
      return applied;
    } catch (err) {
      if (alive.current) setError(String(err));
      return false;
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  async function handleFile(e: ChangeEvent<HTMLInputElement>) {
    const input = e.target;
    if (detail === null || !input.files || input.files.length === 0) return;
    const file = input.files[0];
    const prev = detail;
    await run(
      "upload",
      async (id) => {
        await uploadDocument(id, file);
        return getProfile(id);
      },
      (d) => applyResponse(d, prev, [])
    );
    input.value = "";
  }

  async function handlePasteDoc() {
    if (detail === null || pasteText.trim() === "") return;
    const prev = detail;
    const source = {
      filename: pasteName.trim() !== "" ? pasteName.trim() : "pasted.txt",
      text: pasteText,
    };
    const applied = await run(
      "upload",
      async (id) => {
        await uploadDocument(id, source);
        return getProfile(id);
      },
      (d) => applyResponse(d, prev, [])
    );
    if (applied) {
      setPasteName("");
      setPasteText("");
    }
  }

  async function handleRemoveDocument(docId: number) {
    if (detail === null) return;
    const prev = detail;
    setConfirmDocId(null);
    await run(
      "remove-document",
      async (id) => {
        await deleteDocument(id, docId);
        return getProfile(id);
      },
      (d) => applyResponse(d, prev, [])
    );
  }

  async function handleBuild() {
    if (detail === null) return;
    const prev = detail;
    await run(
      "build",
      (id) => buildProfile(id),
      (d) => {
        // Build replaces the structured profile. Voice notes are deliberately
        // not taken from its response: build runs intake, which never touches
        // them, so taking them would discard unsaved edits. Name and email
        // keep an unsaved edit the same way.
        applyResponse(d, prev, ["mp"]);
        setBuildUsage(d.usage ?? null);
      }
    );
  }

  async function handleSave() {
    if (detail === null) return;
    const prev = detail;
    const patch = { master_profile: mp, voice_notes: voiceNotes };
    await run(
      "save-profile",
      (id) => updateProfile(id, patch),
      (d) => applyResponse(d, prev, ["mp", "voice"])
    );
  }

  async function handleSaveIdentity() {
    if (detail === null) return;
    const trimmed = name.trim();
    if (trimmed === "") return;
    const prev = detail;
    const contact: Contact = {
      ...prev.contact,
      email: email.trim(),
      // Renaming the person renames them on their resume too. An email-only
      // edit leaves a contact name that Build took from a resume alone.
      ...(trimmed !== prev.name ? { name: trimmed } : {}),
    };
    await run(
      "save-identity",
      (id) => updateProfile(id, { name: trimmed, contact }),
      (d) => applyResponse(d, prev, ["identity"])
    );
  }

  function openRemovePanel() {
    const id = person.id;
    setRemoveOpen(true);
    setConfirmName("");
    setRemoveProblem(null);
    setSavedJobs(null);
    // An agent working a queued job leaves no status trace, so the panel says
    // how many not-yet-built jobs go with this person, archived ones included.
    Promise.all([listApplications(id), listApplications(id, { archived: true })])
      .then(([active, archived]) => {
        if (!alive.current) return;
        setSavedJobs([...active, ...archived].filter((a) => a.status === "not_started").length);
      })
      .catch(() => {
        // The count is a warning, not a precondition: without it the panel
        // still states everything the server will delete.
      });
  }

  async function handleRemovePerson() {
    if (confirmName !== person.name) return;
    const id = person.id;
    setBusy("remove-person");
    setRemoveProblem(null);
    try {
      await deleteProfile(id, confirmName);
      // This person is gone. Clear the guard before refreshPeople(), which
      // falls back to the first remaining person, or to the create form.
      if (alive.current) setSwitchGuard(null);
      await refreshPeople();
    } catch (err) {
      if (alive.current) setRemoveProblem(removalProblem(err));
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  const removalSummary =
    detail === null
      ? ""
      : `This permanently deletes ${label}'s profile, ${count(detail.documents.length, "document")} ` +
        `and ${count(detail.application_count, "application")} (archived included), ` +
        "plus their exported files. It cannot be undone.";

  return (
    <div>
      {error && <div className="alert alert-error">{error}</div>}

      {detail && (
        <>
          <h2>{label}</h2>

          <div className="card">
            <div className="card-title">Name and email</div>
            <div className="field">
              <label className="field-label" htmlFor="person-name">Name</label>
              <input
                id="person-name"
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              {name.trim() === "" && <p className="muted">A person needs a name.</p>}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="person-email">Email</label>
              <input
                id="person-email"
                className="input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <button
              className="btn"
              onClick={handleSaveIdentity}
              disabled={
                busy !== null ||
                name.trim() === "" ||
                (name === detail.name && email === detail.contact.email)
              }
            >
              {busy === "save-identity" ? "Saving..." : "Save name and email"}
            </button>
          </div>

          <div className="card">
            <div className="card-title">Documents</div>
            <ul>
              {detail.documents.map((d) => (
                <li key={d.id}>
                  {confirmDocId === d.id ? (
                    <>
                      <span>Remove {d.filename}?</span>{" "}
                      <button
                        className="btn btn-danger btn-small"
                        onClick={() => handleRemoveDocument(d.id)}
                        disabled={busy !== null}
                      >
                        Yes
                      </button>{" "}
                      <button className="btn btn-small" onClick={() => setConfirmDocId(null)}>
                        No
                      </button>
                    </>
                  ) : (
                    <>
                      {d.filename} <span className="muted">({d.kind})</span>{" "}
                      <button
                        className="btn btn-ghost btn-small"
                        aria-label={`Remove ${d.filename}`}
                        onClick={() => setConfirmDocId(d.id)}
                        disabled={busy !== null}
                      >
                        Remove
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
            {detail.documents.length === 0 && (
              <p className="muted">Upload your existing resumes and notes to build a master profile.</p>
            )}
            <div className="field">
              <label className="field-label">Upload file (.pdf, .docx, .txt)</label>
              <input
                type="file"
                accept=".pdf,.docx,.txt"
                onChange={handleFile}
                disabled={busy !== null}
              />
            </div>
            <div className="field">
              <label className="field-label">Or paste text</label>
              <input
                className="input"
                placeholder="Document name"
                value={pasteName}
                onChange={(e) => setPasteName(e.target.value)}
              />
              <textarea
                className="textarea"
                placeholder="Paste resume or notes text"
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
              />
              <button className="btn" onClick={handlePasteDoc} disabled={busy !== null}>
                Add pasted text
              </button>
            </div>
          </div>

          <div className="card">
            <div className="card-title">Build</div>
            <p className="muted">
              Structures every document above into the master profile with one Claude call.
              Re-running replaces the current structured profile.
            </p>
            <button className="btn btn-primary" onClick={handleBuild} disabled={busy !== null}>
              {building && <span className="spinner" />}
              {building ? " Building..." : "Build master profile"}
            </button>
            {buildUsage && (
              <p className="muted">
                Done — {buildUsage.input_tokens} tokens in, {buildUsage.output_tokens} out, cost $
                {buildUsage.cost_usd.toFixed(4)}
              </p>
            )}
          </div>

          <div className="card">
            <div className="card-title">Master profile</div>

            <div className="field">
              <label className="field-label">Summary notes</label>
              <textarea
                className="textarea"
                value={mp.summary_notes}
                onChange={(e) => setMp({ ...mp, summary_notes: e.target.value })}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="voice-notes">Voice notes</label>
              <textarea
                id="voice-notes"
                className="textarea"
                value={voiceNotes}
                placeholder="Plain and direct. No salesmanship. Short sentences. Never call myself passionate about anything."
                onChange={(e) => setVoiceNotes(e.target.value)}
              />
              <p className="muted">
                How you want your resume and cover letters to sound. This shapes the writing
                only; every fact still comes from your master profile.
              </p>
            </div>

            <h3>Experiences</h3>
            {mp.experiences.map((exp, i) => (
              <div className="card" key={i}>
                <div className="row">
                  <input
                    className="input"
                    placeholder="Company"
                    value={exp.company}
                    onChange={(e) => updateExperience(i, { company: e.target.value })}
                  />
                  <input
                    className="input"
                    placeholder="Title"
                    value={exp.title}
                    onChange={(e) => updateExperience(i, { title: e.target.value })}
                  />
                </div>
                <div className="row">
                  <input
                    className="input"
                    placeholder="Start (YYYY-MM)"
                    value={exp.start}
                    onChange={(e) => updateExperience(i, { start: e.target.value })}
                  />
                  <input
                    className="input"
                    placeholder="End (blank = present)"
                    value={exp.end ?? ""}
                    onChange={(e) =>
                      updateExperience(i, { end: e.target.value === "" ? null : e.target.value })
                    }
                  />
                  <input
                    className="input"
                    placeholder="Location"
                    value={exp.location ?? ""}
                    onChange={(e) =>
                      updateExperience(i, {
                        location: e.target.value === "" ? null : e.target.value,
                      })
                    }
                  />
                </div>
                {exp.bullets.map((b, j) => (
                  <div className="row" key={j}>
                    <input
                      className="input"
                      placeholder="Bullet text"
                      value={b.text}
                      onChange={(e) => updateBullet(i, j, { text: e.target.value })}
                    />
                    <input
                      className="input"
                      placeholder="tags, comma, separated"
                      value={b.tags.join(", ")}
                      onChange={(e) => updateBullet(i, j, { tags: splitCsv(e.target.value) })}
                    />
                    <button className="btn btn-danger" onClick={() => removeBullet(i, j)}>
                      Remove
                    </button>
                  </div>
                ))}
                <div className="row">
                  <button className="btn btn-ghost" onClick={() => addBullet(i)}>
                    Add bullet
                  </button>
                  <button className="btn btn-danger" onClick={() => removeExperience(i)}>
                    Remove experience
                  </button>
                </div>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addExperience}>
              Add experience
            </button>

            <h3>Skills</h3>
            {mp.skills.map((g, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Group label"
                  value={g.label}
                  onChange={(e) => updateSkillGroup(i, { label: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="items, comma, separated"
                  value={g.items.join(", ")}
                  onChange={(e) => updateSkillGroup(i, { items: splitCsv(e.target.value) })}
                />
                <button className="btn btn-danger" onClick={() => removeSkillGroup(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addSkillGroup}>
              Add skill group
            </button>

            <h3>Education</h3>
            {mp.education.map((ed, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Institution"
                  value={ed.institution}
                  onChange={(e) => updateEducation(i, { institution: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Credential"
                  value={ed.credential}
                  onChange={(e) => updateEducation(i, { credential: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Year"
                  value={ed.year ?? ""}
                  onChange={(e) =>
                    updateEducation(i, { year: e.target.value === "" ? null : e.target.value })
                  }
                />
                <input
                  className="input"
                  placeholder="Detail"
                  value={ed.detail ?? ""}
                  onChange={(e) =>
                    updateEducation(i, { detail: e.target.value === "" ? null : e.target.value })
                  }
                />
                <button className="btn btn-danger" onClick={() => removeEducation(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addEducation}>
              Add education
            </button>

            <h3>Certifications</h3>
            {mp.certifications.map((c, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Certification name"
                  value={c.name}
                  onChange={(e) => updateCertification(i, { name: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Issuer"
                  value={c.issuer ?? ""}
                  onChange={(e) =>
                    updateCertification(i, { issuer: e.target.value === "" ? null : e.target.value })
                  }
                />
                <input
                  className="input"
                  placeholder="Year"
                  value={c.year ?? ""}
                  onChange={(e) =>
                    updateCertification(i, { year: e.target.value === "" ? null : e.target.value })
                  }
                />
                <button className="btn btn-danger" onClick={() => removeCertification(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addCertification}>
              Add certification
            </button>

            <h3>Projects</h3>
            {mp.projects.map((p, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Project name"
                  value={p.name}
                  onChange={(e) => updateProject(i, { name: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Description"
                  value={p.description}
                  onChange={(e) => updateProject(i, { description: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="URL"
                  value={p.url ?? ""}
                  onChange={(e) =>
                    updateProject(i, { url: e.target.value === "" ? null : e.target.value })
                  }
                />
                <button className="btn btn-danger" onClick={() => removeProject(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addProject}>
              Add project
            </button>

            <h3>Additional</h3>
            {mp.extras.map((x, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Extra item"
                  value={x}
                  onChange={(e) => updateExtra(i, e.target.value)}
                />
                <button className="btn btn-danger" onClick={() => removeExtra(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addExtra}>
              Add extra
            </button>

            <div className="row" style={{ marginTop: "1.25rem" }}>
              <button className="btn btn-primary" onClick={handleSave} disabled={busy !== null}>
                {saving ? "Saving..." : "Save master profile"}
              </button>
            </div>
          </div>

          <div className="card">
            <div className="card-title">Remove this person</div>
            {!removeOpen ? (
              <button className="btn btn-danger" onClick={openRemovePanel} disabled={busy !== null}>
                Remove this person
              </button>
            ) : (
              <>
                <p>{removalSummary}</p>
                {savedJobs !== null && savedJobs > 0 && (
                  <p>
                    {`${count(savedJobs, "saved job")}, including any an agent is working on, will be removed.`}
                  </p>
                )}
                <div className="field">
                  <label className="field-label" htmlFor="confirm-remove-name">
                    Type {person.name} to confirm
                  </label>
                  <input
                    id="confirm-remove-name"
                    className="input"
                    autoComplete="off"
                    value={confirmName}
                    onChange={(e) => setConfirmName(e.target.value)}
                  />
                </div>
                {removeProblem && (
                  <div className="alert alert-error" role="alert">
                    <p>{removeProblem.message}</p>
                    {removeProblem.blocking.length > 0 && (
                      <ul>
                        {removeProblem.blocking.map((b) => (
                          <li key={`${b.id}-${b.label}`}>
                            <Link to={`/applications/${b.id}`}>{b.label}</Link>{" "}
                            <span className="muted">({statusLabel(b.status)})</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
                <div className="row">
                  <button
                    className="btn btn-danger"
                    onClick={handleRemovePerson}
                    disabled={busy !== null || confirmName !== person.name}
                  >
                    {busy === "remove-person" ? "Removing..." : `Remove ${label}`}
                  </button>
                  <button
                    className="btn"
                    onClick={() => setRemoveOpen(false)}
                    disabled={busy === "remove-person"}
                  >
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
