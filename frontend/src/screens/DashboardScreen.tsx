import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listApplications, listProfiles } from "../api";
import type { ApplicationSummary, AppStatus, ProfileSummary } from "../types";

const TERMINAL: AppStatus[] = ["ready", "error", "needs_paste"];

/**
 * Polls listApplications every 2000ms while any application status is outside
 * ready/error/needs_paste. Cleans up on unmount and on profile change.
 */
export function usePolling(profileId: number | undefined): ApplicationSummary[] {
  const [apps, setApps] = useState<ApplicationSummary[]>([]);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;

    async function tick() {
      let active = false;
      try {
        const list = await listApplications(profileId);
        if (stopped) return;
        setApps(list);
        active = list.some((a) => !TERMINAL.includes(a.status));
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
  }, [profileId]);

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
  return <span className={`badge badge-${app.status}`}>{app.status}</span>;
}

export default function DashboardScreen() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [profileId, setProfileId] = useState<number | undefined>(undefined);
  const apps = usePolling(profileId);

  useEffect(() => {
    listProfiles()
      .then((list) => {
        setProfiles(list);
        if (list.length > 0) {
          setProfileId((cur) => cur ?? list[0].id);
        }
      })
      .catch(() => setProfiles([]));
  }, []);

  return (
    <div>
      <h1>Dashboard</h1>

      {profiles.length > 1 && (
        <div className="field" style={{ maxWidth: "20rem" }}>
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
      )}

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Role</th>
              <th>Depth</th>
              <th>Template</th>
              <th>Status</th>
              <th>Version</th>
              <th>Cost</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {apps.map((a) => (
              <tr key={a.id}>
                <td>{a.company ? a.company : a.url}</td>
                <td>{a.title ?? ""}</td>
                <td>{a.depth}</td>
                <td>{a.template}</td>
                <td>
                  <StatusBadge app={a} />
                </td>
                <td>v{a.version}</td>
                <td className="mono">${a.cost_usd.toFixed(4)}</td>
                <td>{new Date(a.created_at).toLocaleDateString()}</td>
                <td>
                  <Link to={`/applications/${a.id}`}>Open</Link>
                </td>
              </tr>
            ))}
            {apps.length === 0 && (
              <tr>
                <td colSpan={9} className="muted">
                  No applications yet — queue job URLs from the Add Jobs screen.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
