import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  addEvent,
  deleteEvent,
  exportUrl,
  generateApplication,
  getApplication,
  pasteJobText,
  patchApplication,
  previewUrl,
  regenerate,
  retryApplication,
  updateContent,
} from "../api";
import { TERMINAL_STATUSES } from "../statuses";
import type {
  ApplicationDetail,
  ApplicationEvent,
  EventKind,
  ExportKind,
  ResumeDoc,
  SkillGroup,
  Stage,
} from "../types";

const EXPORT_KINDS: ExportKind[] = [
  "resume.pdf",
  "resume.html",
  "resume.txt",
  "cover_letter.pdf",
  "cover_letter.txt",
];

const EVENT_KINDS: EventKind[] = [
  "note", "applied", "callback", "interview", "offer", "rejection", "followup",
];

const STAGES: Stage[] = [
  "saved", "drafted", "applied", "screening",
  "interview", "offer", "rejected", "withdrawn",
];

type Tab = "resume" | "cover" | "research" | "exports";

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function Timeline({
  applicationId,
  events,
  onChanged,
  onError,
}: {
  applicationId: number;
  events: ApplicationEvent[];
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [kind, setKind] = useState<EventKind>("note");
  const [body, setBody] = useState("");
  const [when, setWhen] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      // `when` is a plain "YYYY-MM-DD" string from <input type="date">. Date-only
      // strings parse as UTC midnight (ECMA-262 Date Time String Format), so this
      // stores the user's chosen calendar day as a fixed instant. The timeline
      // below reads it back with `timeZone: "UTC"` so the same calendar day
      // survives regardless of the viewer's local offset.
      await addEvent(applicationId, {
        kind,
        body,
        occurred_at: when ? new Date(when).toISOString() : undefined,
      });
      setBody("");
      setWhen("");
      onChanged();
    } catch (err) {
      onError(String(err));
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
            <span className="muted">
              {new Date(e.occurred_at).toLocaleDateString(undefined, { timeZone: "UTC" })}
            </span>{" "}
            {e.body}{" "}
            <button
              className="btn btn-small"
              aria-label={`Delete timeline entry ${e.id}`}
              onClick={async () => {
                try {
                  await deleteEvent(applicationId, e.id);
                  onChanged();
                } catch (err) {
                  onError(String(err));
                }
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

export default function ApplicationScreen() {
  const params = useParams<{ id: string }>();
  const appId = Number(params.id);

  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [tab, setTab] = useState<Tab>("resume");
  const [editingResume, setEditingResume] = useState(false);
  const [draft, setDraft] = useState<ResumeDoc | null>(null);
  const [editingCover, setEditingCover] = useState(false);
  const [coverDraft, setCoverDraft] = useState("");
  const [iframeKey, setIframeKey] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollNonce, setPollNonce] = useState(0);

  // Load + poll getApplication every 2000ms while status is non-terminal.
  // pollNonce restarts polling after regenerate / paste.
  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;

    async function tick() {
      try {
        const d = await getApplication(appId);
        if (stopped) return;
        setDetail(d);
        if (!TERMINAL_STATUSES.includes(d.status)) {
          timer = window.setTimeout(tick, 2000);
        } else {
          setIframeKey((k) => k + 1); // reload preview once the pipeline settles
        }
      } catch (err) {
        if (!stopped) setError(String(err));
      }
    }

    tick();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [appId, pollNonce]);

  // ---- resume draft editing helpers ----

  function startEditResume() {
    if (detail && detail.resume) {
      setDraft(JSON.parse(JSON.stringify(detail.resume)) as ResumeDoc);
      setEditingResume(true);
    }
  }

  function cancelEditResume() {
    setEditingResume(false);
    setDraft(null);
  }

  function setSectionTitle(idx: number, title: string) {
    setDraft((d) =>
      d ? { ...d, sections: d.sections.map((s, i) => (i === idx ? { ...s, title } : s)) } : d
    );
  }

  function removeSection(idx: number) {
    setDraft((d) => (d ? { ...d, sections: d.sections.filter((_, i) => i !== idx) } : d));
  }

  function setExperienceBullet(secIdx: number, itemIdx: number, bulletIdx: number, text: string) {
    setDraft((d) => {
      if (!d) return d;
      return {
        ...d,
        sections: d.sections.map((s, i) => {
          if (i !== secIdx || s.type !== "experience") return s;
          return {
            ...s,
            items: s.items.map((item, j) =>
              j === itemIdx
                ? { ...item, bullets: item.bullets.map((b, k) => (k === bulletIdx ? text : b)) }
                : item
            ),
          };
        }),
      };
    });
  }

  function removeExperienceBullet(secIdx: number, itemIdx: number, bulletIdx: number) {
    setDraft((d) => {
      if (!d) return d;
      return {
        ...d,
        sections: d.sections.map((s, i) => {
          if (i !== secIdx || s.type !== "experience") return s;
          return {
            ...s,
            items: s.items.map((item, j) =>
              j === itemIdx
                ? { ...item, bullets: item.bullets.filter((_, k) => k !== bulletIdx) }
                : item
            ),
          };
        }),
      };
    });
  }

  function removeExperienceItem(secIdx: number, itemIdx: number) {
    setDraft((d) => {
      if (!d) return d;
      return {
        ...d,
        sections: d.sections.map((s, i) => {
          if (i !== secIdx || s.type !== "experience") return s;
          return { ...s, items: s.items.filter((_, j) => j !== itemIdx) };
        }),
      };
    });
  }

  function setSkillGroupField(secIdx: number, groupIdx: number, patch: Partial<SkillGroup>) {
    setDraft((d) => {
      if (!d) return d;
      return {
        ...d,
        sections: d.sections.map((s, i) => {
          if (i !== secIdx || s.type !== "skills") return s;
          return {
            ...s,
            groups: s.groups.map((g, j) => (j === groupIdx ? { ...g, ...patch } : g)),
          };
        }),
      };
    });
  }

  // ---- actions ----

  async function saveResume() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      const d = await updateContent(appId, { resume: draft });
      setDetail(d);
      setEditingResume(false);
      setDraft(null);
      setIframeKey((k) => k + 1);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function startEditCover() {
    if (detail) {
      setCoverDraft(detail.cover_letter_md ?? "");
      setEditingCover(true);
    }
  }

  async function saveCover() {
    setBusy(true);
    setError(null);
    try {
      const d = await updateContent(appId, { cover_letter_md: coverDraft });
      setDetail(d);
      setEditingCover(false);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRegenerate() {
    if (feedback.trim() === "") return;
    setBusy(true);
    setError(null);
    try {
      await regenerate(appId, feedback);
      setFeedback("");
      setPollNonce((n) => n + 1);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRetry() {
    setBusy(true);
    setError(null);
    try {
      await retryApplication(appId);
      setPollNonce((n) => n + 1);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleGenerate() {
    setBusy(true);
    setError(null);
    try {
      await generateApplication(appId);
      setPollNonce((n) => n + 1);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handlePaste() {
    if (pasteText.trim() === "") return;
    setBusy(true);
    setError(null);
    try {
      await pasteJobText(appId, pasteText);
      setPasteText("");
      setPollNonce((n) => n + 1);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function reload() {
    setPollNonce((n) => n + 1);
  }

  if (!detail) {
    return (
      <div>
        {error && <div className="alert alert-error">{error}</div>}
        <p className="muted">Loading application...</p>
      </div>
    );
  }

  const working = !TERMINAL_STATUSES.includes(detail.status);

  return (
    <div>
      <h1>
        {detail.company ? detail.company : detail.url} — {detail.title ?? ""}
      </h1>
      <p>
        <span className={`badge badge-${detail.status}`}>{detail.status}</span>{" "}
        <span className="muted">
          v{detail.version} · ${detail.cost_usd.toFixed(4)} · {detail.depth} · {detail.template}
        </span>
        {working && <span className="spinner" style={{ marginLeft: "0.5rem" }} />}
      </p>

      <div className="field" style={{ maxWidth: "14rem" }}>
        <label className="field-label" htmlFor="app-stage">Stage</label>
        <select
          id="app-stage"
          className="select"
          value={detail.stage}
          onChange={async (e) => {
            const stage = e.target.value as Stage;
            setError(null);
            try {
              const d = await patchApplication(detail.id, { stage });
              setDetail(d);
            } catch (err) {
              setError(String(err));
            }
          }}
        >
          {STAGES.map((s) => (
            <option key={s} value={s} disabled={s === "saved" && detail.status === "ready"}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {detail.status === "error" && (
        <div className="alert alert-error">
          <strong>Generation failed:</strong> {detail.error_message ?? "Unknown error"}
          <div className="muted" style={{ marginTop: "0.25rem" }}>
            Fix the issue (API key, network) and click Retry to try again.
          </div>
          <div className="row" style={{ marginTop: "0.5rem" }}>
            <button className="btn btn-primary" onClick={handleRetry} disabled={busy}>
              {busy ? "Retrying..." : "Retry"}
            </button>
          </div>
        </div>
      )}

      {detail.status === "not_started" ? (
        <div className="card">
          <h2>Generate this application</h2>
          <p className="muted">
            This job hasn't been generated yet. Click Generate to run the tailoring pipeline.
          </p>
          <button className="btn btn-primary" onClick={handleGenerate} disabled={busy}>
            {busy ? "Starting..." : "Generate"}
          </button>
        </div>
      ) : detail.status === "needs_paste" ? (
        <div className="card">
          <h2>Paste the job posting</h2>
          <p className="muted">
            The posting URL could not be fetched automatically (login wall, bot protection, or a
            JavaScript-only page). Paste the full posting text below and the pipeline will resume.
          </p>
          <textarea
            className="textarea"
            style={{ minHeight: "12rem" }}
            placeholder="Paste the full job posting text here"
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
          />
          <button className="btn btn-primary" onClick={handlePaste} disabled={busy}>
            {busy ? "Submitting..." : "Submit pasted text"}
          </button>
        </div>
      ) : (
        <>
          <div className="tabs">
            <button
              className={tab === "resume" ? "tab active" : "tab"}
              onClick={() => setTab("resume")}
            >
              Resume
            </button>
            <button
              className={tab === "cover" ? "tab active" : "tab"}
              onClick={() => setTab("cover")}
            >
              Cover Letter
            </button>
            <button
              className={tab === "research" ? "tab active" : "tab"}
              onClick={() => setTab("research")}
            >
              Research
            </button>
            <button
              className={tab === "exports" ? "tab active" : "tab"}
              onClick={() => setTab("exports")}
            >
              Exports
            </button>
          </div>

          {tab === "resume" && (
            <div>
              {!editingResume && (
                <>
                  <div className="row">
                    <button
                      className="btn"
                      onClick={startEditResume}
                      disabled={!detail.resume || working}
                    >
                      Edit
                    </button>
                  </div>
                  <div className="preview-frame-wrap">
                    <iframe
                      key={iframeKey}
                      src={previewUrl(appId)}
                      title="Resume preview"
                      className="preview-frame"
                      sandbox=""
                    />
                  </div>
                </>
              )}

              {editingResume && draft && (
                <div className="card">
                  <div className="card-title">Edit resume</div>
                  <div className="field">
                    <label className="field-label">Headline</label>
                    <input
                      className="input"
                      value={draft.headline}
                      onChange={(e) => setDraft({ ...draft, headline: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label className="field-label">Summary</label>
                    <textarea
                      className="textarea"
                      value={draft.summary}
                      onChange={(e) => setDraft({ ...draft, summary: e.target.value })}
                    />
                  </div>

                  {draft.sections.map((section, si) => (
                    <div className="card" key={si}>
                      <div className="row">
                        <input
                          className="input"
                          aria-label={`Section ${si + 1} title`}
                          value={section.title}
                          onChange={(e) => setSectionTitle(si, e.target.value)}
                        />
                        <button className="btn btn-danger" onClick={() => removeSection(si)}>
                          Remove section
                        </button>
                      </div>

                      {section.type === "experience" &&
                        section.items.map((item, ii) => (
                          <div className="card" key={ii}>
                            <div className="row">
                              <strong>
                                {item.company} — {item.role}
                              </strong>
                              <span className="muted">
                                {item.start} – {item.end ?? "present"}
                              </span>
                              <button
                                className="btn btn-danger"
                                onClick={() => removeExperienceItem(si, ii)}
                              >
                                Remove item
                              </button>
                            </div>
                            {item.bullets.map((b, bi) => (
                              <div className="row" key={bi}>
                                <textarea
                                  className="textarea"
                                  style={{ minHeight: "3rem" }}
                                  value={b}
                                  onChange={(e) =>
                                    setExperienceBullet(si, ii, bi, e.target.value)
                                  }
                                />
                                <button
                                  className="btn btn-danger"
                                  onClick={() => removeExperienceBullet(si, ii, bi)}
                                >
                                  Remove bullet
                                </button>
                              </div>
                            ))}
                          </div>
                        ))}

                      {section.type === "skills" &&
                        section.groups.map((g, gi) => (
                          <div className="row" key={gi}>
                            <input
                              className="input"
                              placeholder="Group label"
                              value={g.label}
                              onChange={(e) =>
                                setSkillGroupField(si, gi, { label: e.target.value })
                              }
                            />
                            <input
                              className="input"
                              placeholder="items, comma, separated"
                              value={g.items.join(", ")}
                              onChange={(e) =>
                                setSkillGroupField(si, gi, { items: splitCsv(e.target.value) })
                              }
                            />
                          </div>
                        ))}
                    </div>
                  ))}

                  <div className="row">
                    <button className="btn btn-primary" onClick={saveResume} disabled={busy}>
                      {busy ? "Saving..." : "Save"}
                    </button>
                    <button className="btn btn-ghost" onClick={cancelEditResume}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              <div className="card" style={{ marginTop: "1.25rem" }}>
                <div className="card-title">Regenerate with feedback</div>
                <textarea
                  className="textarea"
                  placeholder="e.g. Emphasize the data pipeline work more; shorter summary."
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                />
                <button
                  className="btn btn-primary"
                  onClick={handleRegenerate}
                  disabled={busy || working}
                >
                  {busy ? "Submitting..." : "Regenerate"}
                </button>
              </div>
            </div>
          )}

          {tab === "cover" && (
            <div>
              {!editingCover && (
                <>
                  <div className="row">
                    <button
                      className="btn"
                      onClick={startEditCover}
                      disabled={detail.cover_letter_md === null || working}
                    >
                      Edit
                    </button>
                  </div>
                  <pre className="cover-md">{detail.cover_letter_md ?? "No cover letter yet."}</pre>
                </>
              )}
              {editingCover && (
                <div className="card">
                  <textarea
                    className="textarea"
                    style={{ minHeight: "20rem" }}
                    value={coverDraft}
                    onChange={(e) => setCoverDraft(e.target.value)}
                  />
                  <div className="row">
                    <button className="btn btn-primary" onClick={saveCover} disabled={busy}>
                      {busy ? "Saving..." : "Save"}
                    </button>
                    <button className="btn btn-ghost" onClick={() => setEditingCover(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === "research" && (
            <div>
              {detail.tailoring_notes && (
                <div className="callout">
                  <strong>Tailoring notes:</strong> {detail.tailoring_notes}
                </div>
              )}

              {detail.parsed && (
                <div className="card">
                  <div className="card-title">Parsed posting</div>
                  <h3>Must-haves</h3>
                  <div>
                    {detail.parsed.must_haves.map((m, i) => (
                      <span className="chip" key={i}>
                        {m}
                      </span>
                    ))}
                  </div>
                  <h3>Nice-to-haves</h3>
                  <div>
                    {detail.parsed.nice_to_haves.map((m, i) => (
                      <span className="chip" key={i}>
                        {m}
                      </span>
                    ))}
                  </div>
                  <h3>Keywords</h3>
                  <div>
                    {detail.parsed.keywords.map((m, i) => (
                      <span className="chip" key={i}>
                        {m}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {detail.research ? (
                <div className="card">
                  <div className="card-title">Research findings</div>
                  <dl>
                    <dt>
                      <strong>Mission</strong>
                    </dt>
                    <dd>{detail.research.mission}</dd>
                    <dt>
                      <strong>Products</strong>
                    </dt>
                    <dd>{detail.research.products.join("; ")}</dd>
                    <dt>
                      <strong>News</strong>
                    </dt>
                    <dd>{detail.research.news.join("; ")}</dd>
                    <dt>
                      <strong>Tech stack signals</strong>
                    </dt>
                    <dd>{detail.research.tech_stack_signals.join("; ")}</dd>
                    <dt>
                      <strong>Culture language</strong>
                    </dt>
                    <dd>{detail.research.culture_language.join("; ")}</dd>
                    <dt>
                      <strong>Sources</strong>
                    </dt>
                    <dd>
                      {detail.research.sources.map((s, i) => (
                        <div key={i} className="mono">
                          {s}
                        </div>
                      ))}
                    </dd>
                  </dl>
                </div>
              ) : (
                <p className="muted">
                  No research brief — this application ran at "quick" depth (parse only).
                </p>
              )}
            </div>
          )}

          {tab === "exports" && (
            <div className="card">
              <div className="card-title">Downloads</div>
              <ul>
                {EXPORT_KINDS.map((kind) => (
                  <li key={kind}>
                    <a href={exportUrl(appId, kind)} download>
                      {kind}
                    </a>
                  </li>
                ))}
              </ul>
              {detail.status !== "ready" && (
                <p className="muted">Exports are written when the application reaches "ready".</p>
              )}
            </div>
          )}
        </>
      )}

      <Timeline
        applicationId={detail.id}
        events={detail.events}
        onChanged={reload}
        onError={setError}
      />
    </div>
  );
}
