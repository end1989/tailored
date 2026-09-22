import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  archiveApplication,
  deleteApplication,
  generateApplication,
  listApplications,
  patchApplication,
  restoreApplication,
} from "../api";
import { usePerson } from "../person";
import { STATUS_LABELS, TERMINAL_STATUSES } from "../statuses";
import type { ApplicationSummary, Stage } from "../types";

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

const NO_APPS: ApplicationSummary[] = [];

/**
 * Polls listApplications(profileId) every 2000ms while any application status
 * is outside TERMINAL. Makes no request at all while profileId is undefined
 * (no person yet, or none exist). Cleans up on unmount, on person change, and
 * on tab change; a response that lands after any of those is dropped.
 *
 * Rows are kept together with the person they were fetched for, and only the
 * current person's rows are returned. On the very render where the person
 * changes the list is already empty, before any effect has run, so the
 * previous person's rows are never painted with live controls under the new
 * person.
 */
export function usePolling(
  profileId: number | undefined,
  archived: boolean,
  reloadKey: number
): ApplicationSummary[] {
  const [fetched, setFetched] = useState<{ profileId: number; list: ApplicationSummary[] } | null>(
    null
  );

  useEffect(() => {
    if (profileId === undefined) return;
    const id = profileId;
    let stopped = false;
    let timer: number | undefined;

    async function tick() {
      let active = false;
      try {
        const list = await listApplications(id, archived ? { archived: true } : undefined);
        if (stopped) return;
        setFetched({ profileId: id, list });
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

  return fetched !== null && fetched.profileId === profileId ? fetched.list : NO_APPS;
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
  const { person, loading: peopleLoading, error: peopleError } = usePerson();
  const personId = person?.id;
  const [tab, setTab] = useState<Tab>("to_apply");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirming, setConfirming] = useState<ApplicationSummary[] | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const apps = usePolling(personId, tab === "archived", reloadKey);
  const rows = visible(apps, tab);
  const counts = tabCounts(apps, tab);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  // The person shown now. An action compares it with the person it started
  // for: one that settles after a switch reports on someone else's rows.
  const personRef = useRef(personId);
  useEffect(() => {
    personRef.current = personId;
  }, [personId]);

  useEffect(() => setSelected(new Set()), [tab, personId]);

  // An open delete confirmation lists the previous person's rows and its
  // button would still delete them; an error describes the previous person's
  // action. Neither survives a switch.
  useEffect(() => {
    setConfirming(null);
    setError(null);
  }, [personId]);

  async function run(action: () => Promise<unknown>) {
    const startedFor = personRef.current;
    setError(null);
    try {
      await action();
    } catch (e) {
      if (personRef.current === startedFor) setError(String(e));
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
    const startedFor = personRef.current;
    setError(null);
    const results = await Promise.allSettled(ids.map(op));
    const failures = results.filter((r) => r.status === "rejected");
    if (failures.length > 0 && personRef.current === startedFor) {
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
                  {/* Until the people list has loaded, neither the first steps
                      nor a tab's "Nothing ..." line is true yet. */}
                  {peopleLoading ? (
                    "Loading..."
                  ) : peopleError ? (
                    peopleError
                  ) : apps.length === 0 && tab !== "archived" ? (
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
