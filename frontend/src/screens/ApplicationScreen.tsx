import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  addEvent,
  deleteEvent,
  exportUrl,
  fetchEditPreview,
  generateApplication,
  getApplication,
  listTemplates,
  pasteJobText,
  patchApplication,
  previewUrl,
  regenerate,
  retryApplication,
  setApplicationTemplate,
  updateContent,
} from "../api";
import { harvestResume, removalTarget } from "../inlineEdit";
import { STATUS_LABELS, TERMINAL_STATUSES } from "../statuses";
import type {
  ApplicationDetail,
  ApplicationEvent,
  EventKind,
  ExportKind,
  ResumeDoc,
  Stage,
  StyleViolation,
  TemplateInfo,
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

function StyleReport({
  violations,
  onClean,
  busy,
}: {
  violations: StyleViolation[];
  onClean: () => void;
  busy: boolean;
}) {
  if (violations.length === 0) return null;
  const mechanical = violations.filter((v) => v.mechanical).length;
  return (
    <div className="style-report">
      <div className="style-report-head">
        <strong>
          {violations.length} style {violations.length === 1 ? "hit" : "hits"}
        </strong>
        {mechanical > 0 && (
          <button className="btn btn-ghost" onClick={onClean} disabled={busy}>
            {busy ? "Cleaning..." : `Clean the ${mechanical} mechanical`}
          </button>
        )}
      </div>
      <ul className="style-report-list">
        {violations.map((v, i) => (
          <li key={i}>
            <span className="style-rule">{v.rule}</span>
            <span className="style-field">{v.field}</span>
            <span className="style-excerpt">{v.excerpt}</span>
            {!v.mechanical && <span className="style-yours">your call</span>}
          </li>
        ))}
      </ul>
    </div>
  );
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
      // `when` is a plain "YYYY-MM-DD" string from <input type="date">. Parsing
      // it directly (`new Date(when)`) treats it as UTC midnight, which is the
      // wrong calendar day once rendered back in local time for any negative
      // UTC offset. Build the instant from LOCAL midnight of that day instead
      // -- `new Date(year, month - 1, day)` interprets its components in the
      // browser's local zone -- so it round-trips through local display
      // correctly. `occurred_at` values created without a picked date (the
      // default path, and API/MCP-created events) are already real wall-clock
      // instants; both kinds are read back with plain local
      // `toLocaleDateString()` below -- one convention for every value.
      let occurredAt: string | undefined;
      if (when) {
        const [year, month, day] = when.split("-").map(Number);
        occurredAt = new Date(year, month - 1, day).toISOString();
      }
      await addEvent(applicationId, {
        kind,
        body,
        occurred_at: occurredAt,
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
              {new Date(e.occurred_at).toLocaleDateString()}
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
  // The editable preview: the rendered template HTML, written into the iframe
  // document so the parent can read the edits back out of it.
  const [editHtml, setEditHtml] = useState<string | null>(null);
  const [frameReady, setFrameReady] = useState(false);
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  // Removed before each re-attach, so one written document means one set of
  // listeners in every environment. See attachFrame.
  const frameListeners = useRef<{
    doc: Document;
    onInput: () => void;
    onClick: (event: Event) => void;
  } | null>(null);
  // Edits live in the frame's DOM, not in React state, so dirtiness is tracked
  // rather than derived. The ref is what the fetch effect reads: putting dirty
  // in its dependencies would refetch (and discard the frame) on every save.
  const [dirty, setDirtyState] = useState(false);
  const dirtyRef = useRef(false);
  const [violations, setViolations] = useState<StyleViolation[]>([]);
  const [saveNote, setSaveNote] = useState<string | null>(null);
  // null means "not touched": show, and keep showing, whatever the server has.
  const [coverDraft, setCoverDraft] = useState<string | null>(null);
  const coverRef = useRef<HTMLTextAreaElement | null>(null);
  const [iframeKey, setIframeKey] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollNonce, setPollNonce] = useState(0);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [switching, setSwitching] = useState(false);

  // Editing is offered once there is a resume and the pipeline has settled.
  // Mid-regeneration the preview stays read-only: anything typed into it would
  // be overwritten by the run in flight.
  const editable =
    detail !== null && detail.resume !== null && TERMINAL_STATUSES.includes(detail.status);

  // The registry is static for the life of the process, so this is a mount-only
  // fetch rather than part of the poll effect below, which re-runs on every
  // reload() and would refetch an unchanging list each time.
  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, []);

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

  // Fetch the editable preview. Skipped while there are unsaved edits in the
  // frame: a refetch replaces the document, and silently discarding someone's
  // typing is worse than a preview that lags a template switch by one save.
  useEffect(() => {
    if (!editable) {
      setEditHtml(null);
      return;
    }
    if (dirtyRef.current) return;
    let stopped = false;
    fetchEditPreview(appId)
      .then((html) => {
        if (!stopped) setEditHtml(html);
      })
      .catch((err) => {
        if (!stopped) setError(String(err));
      });
    return () => {
      stopped = true;
    };
  }, [appId, iframeKey, editable]);

  // Render the preview into the frame. srcdoc would be the obvious way, but
  // jsdom does not parse srcdoc content, which would leave the editing path
  // testable only in a real browser. Writing the document works in both, and
  // the frame stays same-origin either way.
  useEffect(() => {
    const doc = frameRef.current?.contentDocument;
    if (!doc || editHtml === null) return;
    doc.open();
    doc.write(editHtml);
    doc.close();
    attachFrame(doc);
    setFrameReady(true);
    // attachFrame is redefined every render and intentionally not a dependency:
    // this must run once per document, not once per keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editHtml, iframeKey]);

  // Mark the fields the style gate flagged, in place, where they sit.
  useEffect(() => {
    const doc = frameRef.current?.contentDocument;
    if (!doc || !frameReady) return;
    doc.querySelectorAll(".edit-violation").forEach((el) => {
      el.classList.remove("edit-violation");
    });
    for (const violation of violations) {
      if (violation.path === "") continue;
      doc
        .querySelector(`[data-edit-path="${violation.path}"]`)
        ?.classList.add("edit-violation");
    }
    // editHtml and iframeKey are dependencies because a rewritten document is
    // a blank one: after Clean, the refetched preview lands a tick later and
    // replaces every node, so the violations that survived have to be marked
    // again. (Verified in a browser: jsdom's instant fetch batches the two
    // updates into one commit, where effect order alone hides the gap.)
  }, [violations, frameReady, editHtml, iframeKey]);

  // A regeneration replaces the documents wholesale, so anything typed before it
  // started is void. Clearing here is what stops a Save from posting the old
  // text back over the new version once the run finishes.
  useEffect(() => {
    if (editable) return;
    dirtyRef.current = false;
    setDirtyState(false);
    setViolations([]);
    setSaveNote(null);
  }, [editable]);

  // Closing the tab with unsaved edits should cost a confirmation, not the work.
  useEffect(() => {
    if (!dirty && coverDraft === null) return;
    function warn(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, coverDraft]);

  // The cover letter is edited in a borderless textarea, so it has to grow to
  // fit its text the way the rendered letter would.
  useEffect(() => {
    const el = coverRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [coverDraft, detail?.cover_letter_md, tab]);

  function setDirty(value: boolean) {
    dirtyRef.current = value;
    setDirtyState(value);
  }

  /**
   * Wire up the preview document.
   *
   * Nothing runs inside the frame -- it is sandboxed without allow-scripts --
   * but it is same-origin, so listeners attached from here see everything that
   * happens in it. Typing bubbles as `input`; the delete markers are handled by
   * removing their node, which is all harvest needs to drop the item.
   *
   * Listeners are removed before each re-attach rather than left to the
   * browser to clean up. `document.open()` does unregister every listener on
   * the document, so in Chrome leaving them would be harmless even though the
   * Document object is reused across open/write/close (measured: three writes,
   * three attachments, one handler call per event). jsdom does not implement
   * that clearing (same measurement: three calls), so relying on it would mean
   * the tests exercise a different listener graph than the browser does.
   * Removing them by hand costs a few lines and holds everywhere.
   */
  function attachFrame(doc: Document) {
    const previous = frameListeners.current;
    if (previous !== null) {
      previous.doc.removeEventListener("input", previous.onInput);
      previous.doc.removeEventListener("click", previous.onClick);
    }

    const onInput = () => {
      setDirty(true);
      setSaveNote(null);
    };
    const onClick = (event: Event) => {
      const target = event.target as Element | null;
      if (target === null) return;
      const node = removalTarget(target);
      if (node === null) return;
      node.remove();
      setDirty(true);
      setSaveNote(null);
    };

    doc.addEventListener("input", onInput);
    doc.addEventListener("click", onClick);
    frameListeners.current = { doc, onInput, onClick };
    setFrameReady(true);
  }

  function currentEdits(): { resume?: ResumeDoc; cover_letter_md?: string } {
    const patch: { resume?: ResumeDoc; cover_letter_md?: string } = {};
    const doc = frameRef.current?.contentDocument;
    // Only when the frame is loaded AND has been typed into. Saving the cover
    // letter must not send a resume harvested from a frame that has not
    // rendered yet -- that would post an empty document over a good one.
    if (dirty && frameReady && doc && detail?.resume) {
      patch.resume = harvestResume(doc, detail.resume);
    }
    if (coverDraft !== null) patch.cover_letter_md = coverDraft;
    return patch;
  }

  async function saveEdits(extra: { clean?: boolean } = {}) {
    const patch = { ...currentEdits(), ...extra };
    if (patch.resume === undefined && patch.cover_letter_md === undefined && !extra.clean) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const d = await updateContent(appId, patch);
      setDetail(d);
      setViolations(d.style_violations);
      setDirty(false);
      setCoverDraft(null);
      setSaveNote("Saved. Every export file rewritten.");
      if (extra.clean) {
        // The server rewrote the text, so the frame is now stale.
        setIframeKey((k) => k + 1);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function revertEdits() {
    setDirty(false);
    setCoverDraft(null);
    setViolations([]);
    setSaveNote(null);
    setIframeKey((k) => k + 1);
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
  const coverValue = coverDraft ?? detail.cover_letter_md ?? "";
  const coverDirty = coverDraft !== null && coverDraft !== (detail.cover_letter_md ?? "");

  return (
    <div>
      <h1>
        {detail.company ? detail.company : detail.url} — {detail.title ?? ""}
      </h1>
      <p>
        <span className={`badge badge-${detail.status}`}>{STATUS_LABELS[detail.status]}</span>{" "}
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

      <label className="field-inline">
        <span>Template</span>
        <select
          className="select-inline"
          value={detail.template}
          disabled={switching || dirty}
          title={dirty ? "Save or revert your edits first" : undefined}
          onChange={async (e) => {
            const next = e.target.value;
            setSwitching(true);
            setError(null);
            try {
              // The PATCH response is the full re-rendered detail, so apply it
              // directly: no version bump, no cost, and no second GET.
              const d = await setApplicationTemplate(detail.id, next);
              setDetail(d);
              setIframeKey((k) => k + 1); // the preview is now a different template
            } catch (err) {
              setError(err instanceof Error ? err.message : String(err));
            } finally {
              setSwitching(false);
            }
          }}
        >
          {templates.map((t) => (
            <option key={t.name} value={t.name}>
              {t.label || t.name}
            </option>
          ))}
        </select>
      </label>

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

          {/* Kept mounted while other tabs are open: the edits live in the
              frame's DOM, and unmounting would throw them away. */}
          <div style={{ display: tab === "resume" ? undefined : "none" }}>
            {editable ? (
              <>
                <div className="editor-bar">
                  {dirty ? (
                    <>
                      <button
                        className="btn btn-primary"
                        onClick={() => saveEdits()}
                        disabled={busy}
                      >
                        {busy ? "Saving..." : "Save"}
                      </button>
                      <button className="btn btn-ghost" onClick={revertEdits} disabled={busy}>
                        Revert
                      </button>
                      <span className="editor-status">Unsaved edits</span>
                    </>
                  ) : (
                    <span className="editor-hint">
                      Click any text to edit it. Facts from your Master Profile are locked.
                    </span>
                  )}
                  {saveNote && !dirty && <span className="editor-status">{saveNote}</span>}
                </div>
                <StyleReport
                  violations={violations}
                  onClean={() => saveEdits({ clean: true })}
                  busy={busy}
                />
                <div className="preview-frame-wrap">
                  <iframe
                    key={iframeKey}
                    ref={frameRef}
                    title="Resume preview"
                    className="preview-frame"
                    /* allow-same-origin, and deliberately not allow-scripts:
                       the parent needs to read this document, nothing in it
                       needs to run. */
                    sandbox="allow-same-origin"
                  />
                </div>
              </>
            ) : (
              <div className="preview-frame-wrap">
                <iframe
                  key={iframeKey}
                  src={previewUrl(appId)}
                  title="Resume preview"
                  className="preview-frame"
                  sandbox=""
                />
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
                disabled={busy || working || dirty}
                title={dirty ? "Save or revert your edits first" : undefined}
              >
                {busy ? "Submitting..." : "Regenerate"}
              </button>
            </div>
          </div>

          {tab === "cover" && (
            <div>
              <div className="editor-bar">
                {coverDirty ? (
                  <>
                    <button
                      className="btn btn-primary"
                      onClick={() => saveEdits()}
                      disabled={busy}
                    >
                      {busy ? "Saving..." : "Save"}
                    </button>
                    <button
                      className="btn btn-ghost"
                      onClick={() => setCoverDraft(null)}
                      disabled={busy}
                    >
                      Revert
                    </button>
                    <span className="editor-status">Unsaved edits</span>
                  </>
                ) : (
                  <span className="editor-hint">Click the text to edit it.</span>
                )}
                {saveNote && !coverDirty && <span className="editor-status">{saveNote}</span>}
              </div>
              <StyleReport
                violations={violations}
                onClean={() => saveEdits({ clean: true })}
                busy={busy}
              />
              {detail.cover_letter_md === null ? (
                <pre className="cover-md">No cover letter yet.</pre>
              ) : (
                <textarea
                  ref={coverRef}
                  className="cover-editor"
                  aria-label="Cover letter"
                  value={coverValue}
                  onChange={(e) => {
                    setCoverDraft(e.target.value);
                    setSaveNote(null);
                  }}
                />
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
