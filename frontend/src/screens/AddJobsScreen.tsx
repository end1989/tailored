import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createApplications, getSettings, listProfiles } from "../api";
import type { Depth, JobRequest, ProfileSummary, TemplateName } from "../types";

const DEPTHS: Depth[] = ["quick", "standard", "deep"];
const TEMPLATES: TemplateName[] = ["meridian", "slate", "terminal", "signal"];

interface RowOverride {
  depth?: Depth;
  template?: TemplateName;
}

export default function AddJobsScreen() {
  const navigate = useNavigate();
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [profileId, setProfileId] = useState<number | undefined>(undefined);
  const [defaultDepth, setDefaultDepth] = useState<Depth>("standard");
  const [defaultTemplate, setDefaultTemplate] = useState<TemplateName>("slate");
  const [text, setText] = useState("");
  const [overrides, setOverrides] = useState<Record<number, RowOverride>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listProfiles()
      .then((list) => {
        setProfiles(list);
        if (list.length > 0) {
          setProfileId((cur) => cur ?? list[0].id);
        }
      })
      .catch((e) => setError(String(e)));
    getSettings()
      .then((s) => {
        setDefaultDepth(s.default_depth);
        setDefaultTemplate(s.default_template);
      })
      .catch(() => undefined);
  }, []);

  const urls = useMemo(
    () =>
      text
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0),
    [text]
  );

  function setOverride(idx: number, patch: RowOverride) {
    setOverrides((o) => ({ ...o, [idx]: { ...o[idx], ...patch } }));
  }

  async function handleSubmit() {
    if (profileId === undefined || urls.length === 0) return;
    setSubmitting(true);
    setError(null);
    const jobs: JobRequest[] = urls.map((url, i) => ({
      url,
      depth: overrides[i]?.depth ?? defaultDepth,
      template: overrides[i]?.template ?? defaultTemplate,
    }));
    try {
      await createApplications(profileId, jobs, defaultDepth, defaultTemplate);
      navigate("/");
    } catch (err) {
      setError(String(err));
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h1>Add Jobs</h1>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        <div className="row">
          <div className="field">
            <label className="field-label">Profile</label>
            <select
              className="select"
              value={profileId ?? ""}
              onChange={(e) => setProfileId(Number(e.target.value))}
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label">Default depth</label>
            <select
              className="select"
              value={defaultDepth}
              onChange={(e) => setDefaultDepth(e.target.value as Depth)}
            >
              {DEPTHS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label">Default template</label>
            <select
              className="select"
              value={defaultTemplate}
              onChange={(e) => setDefaultTemplate(e.target.value as TemplateName)}
            >
              {TEMPLATES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="field">
          <label className="field-label">Job posting URLs — one per line</label>
          <textarea
            className="textarea"
            placeholder="https://..."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
      </div>

      {urls.length > 0 && (
        <div className="card">
          <div className="card-title">
            {urls.length} job{urls.length === 1 ? "" : "s"} to queue
          </div>
          {urls.map((url, i) => (
            <div className="row" data-testid="job-row" key={i}>
              <span className="mono" style={{ flex: "2 1 16rem", overflowWrap: "anywhere" }}>
                {url}
              </span>
              <select
                className="select"
                aria-label={`Depth for row ${i + 1}`}
                value={overrides[i]?.depth ?? defaultDepth}
                onChange={(e) => setOverride(i, { depth: e.target.value as Depth })}
              >
                {DEPTHS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
              <select
                className="select"
                aria-label={`Template for row ${i + 1}`}
                value={overrides[i]?.template ?? defaultTemplate}
                onChange={(e) => setOverride(i, { template: e.target.value as TemplateName })}
              >
                {TEMPLATES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
          ))}
          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={submitting || profileId === undefined}
          >
            {submitting ? "Queueing..." : "Queue applications"}
          </button>
        </div>
      )}
    </div>
  );
}
