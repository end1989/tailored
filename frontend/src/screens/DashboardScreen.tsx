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
import { TERMINAL_STATUSES } from "../statuses";
import type { ApplicationSummary, ProfileSummary, Stage } from "../types";

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
        active = list.some((a) => !TERMINAL_STATUSES.includes(a.status));
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
                      <option
                        key={s}
                        value={s}
                        disabled={s === "saved" && a.status === "ready"}
                      >
                        {STAGE_LABELS[s]}
                      </option>
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
