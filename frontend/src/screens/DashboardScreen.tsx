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
import { STATUS_LABELS, TERMINAL_STATUSES } from "../statuses";
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

// The dashboard's primary question is "what still needs sending, and what is
// already out?" -- so the buckets split on that line rather than on status.
// NOT_YET_SENT and IN_FLIGHT together with TERMINAL_STAGES partition every
// stage exactly once; a new Stage must be added to one of the three.
const NOT_YET_SENT: Stage[] = ["saved", "drafted"];
const IN_FLIGHT: Stage[] = ["applied", "screening", "interview", "offer"];

type Tab = "to_apply" | "applied" | "closed" | "all" | "archived";

const TABS: { key: Tab; label: string }[] = [
  { key: "to_apply", label: "To apply" },
  { key: "applied", label: "Applied" },
  { key: "closed", label: "Closed" },
  { key: "all", label: "All" },
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
        {STATUS_LABELS.needs_paste}
      </Link>
    );
  }
  return <span className={`badge badge-${app.status}`}>{STATUS_LABELS[app.status]}</span>;
}

function visible(apps: ApplicationSummary[], tab: Tab): ApplicationSummary[] {
  if (tab === "to_apply") return apps.filter((a) => NOT_YET_SENT.includes(a.stage));
  if (tab === "applied") return apps.filter((a) => IN_FLIGHT.includes(a.stage));
  if (tab === "closed") return apps.filter((a) => TERMINAL_STAGES.includes(a.stage));
  return apps;
}

/**
 * Counts for every tab, from the one list already in hand. Returns null while
 * viewing Archived: that fetch returns ONLY archived rows, so counting the
 * other buckets from it would show numbers that are quietly wrong.
 */
function tabCounts(apps: ApplicationSummary[], tab: Tab): Record<Tab, number> | null {
  if (tab === "archived") return null;
  return {
    to_apply: visible(apps, "to_apply").length,
    applied: visible(apps, "applied").length,
    closed: visible(apps, "closed").length,
    all: apps.length,
    archived: 0,
  };
}

const EMPTY_MESSAGE: Record<Tab, string> = {
  to_apply: "Nothing waiting to be sent. Everything generated has gone out.",
  applied: "Nothing sent yet.",
  closed: "Nothing closed out yet — no rejections or withdrawals logged.",
  all: "",
  archived: "Nothing archived.",
};

export default function DashboardScreen() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [profileId, setProfileId] = useState<number | undefined>(undefined);
  const [tab, setTab] = useState<Tab>("to_apply");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirming, setConfirming] = useState<ApplicationSummary[] | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const apps = usePolling(profileId, tab === "archived", reloadKey);
  const rows = visible(apps, tab);
  const counts = tabCounts(apps, tab);
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
    } catch (e) {
      setError(String(e));
    } finally {
      // Always reload, including on failure. Showing rows the server has
      // already changed is worse than showing an error beside fresh data.
      reload();
    }
  }

  /**
   * Bulk actions: one request per id. There is no bulk endpoint by design, so
   * `Promise.allSettled` rather than `Promise.all` -- the latter surfaces only
   * the FIRST rejection, which for a 5-row delete where 2 fail reports one
   * error and silently drops the other. Reports the count instead.
   */
  async function runBulk(
    ids: number[],
    op: (id: number) => Promise<unknown>,
    pastTense: string
  ) {
    setError(null);
    const results = await Promise.allSettled(ids.map(op));
    const failures = results.filter((r) => r.status === "rejected");
    if (failures.length > 0) {
      const first = failures[0] as PromiseRejectedResult;
      setError(
        `${failures.length} of ${ids.length} could not be ${pastTense}. First error: ${String(first.reason)}`
      );
    }
    reload();
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
            {t.key === tab ? (
              <span className="tab-count"> {rows.length}</span>
            ) : (
              counts && t.key !== "archived" && (
                <span className="tab-count"> {counts[t.key]}</span>
              )
            )}
          </button>
        ))}
      </div>

      {chosen.length > 0 && (
        <div className="row bulk-bar">
          <span className="muted">{chosen.length} selected</span>
          {tab === "archived" ? (
            <button
              className="btn"
              onClick={() =>
                runBulk(chosen.map((a) => a.id), restoreApplication, "restored")
              }
            >
              Restore
            </button>
          ) : (
            <button
              className="btn"
              onClick={() =>
                runBulk(chosen.map((a) => a.id), archiveApplication, "archived")
              }
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
              <th>Documents</th>
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
                  {apps.length === 0 && tab !== "archived" ? (
                    <>
                      No applications yet. New here? Start with{" "}
                      <Link to="/getting-started">Getting Started</Link>, or{" "}
                      <Link to="/profiles">create your Master Profile</Link> and then{" "}
                      <Link to="/add">add job URLs</Link>.
                    </>
                  ) : (
                    EMPTY_MESSAGE[tab]
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
                  runBulk(targets.map((a) => a.id), deleteApplication, "deleted");
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
