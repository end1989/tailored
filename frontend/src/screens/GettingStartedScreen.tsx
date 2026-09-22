import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getSettings } from "../api";
import { usePerson } from "../person";
import type { SettingsShape } from "../types";
import CopyButton from "../components/CopyButton";
import McpSetup from "../components/McpSetup";

const ENV_LINE = "ANTHROPIC_API_KEY=sk-ant-...";

export default function GettingStartedScreen() {
  const { person, loading: peopleLoading, error: peopleError, labelFor } = usePerson();
  const [settings, setSettings] = useState<SettingsShape | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Only the app-wide fields (api_key_set, fake_mode) are read here, so the
  // request carries no person and is not repeated on a switch.
  useEffect(() => {
    let alive = true;
    getSettings()
      .then((s) => {
        if (alive) setSettings(s);
      })
      .catch((e) => {
        if (alive) setError(String(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  // Until the settings and the person list have both landed we know nothing,
  // so never report "empty" or "not set" from that.
  const shownError = error ?? peopleError;
  const loaded = settings !== null && !peopleLoading;
  const hasProfile = Boolean(person?.has_master_profile);
  const canGenerateWebApp = Boolean(settings?.api_key_set || settings?.fake_mode);
  const ready = hasProfile && canGenerateWebApp;

  return (
    <div>
      <h1>Getting Started</h1>
      <p className="muted">
        Tailored turns job-posting URLs into truthful, tailored resumes and cover letters from one
        Master Profile you maintain.
      </p>

      <div className="card">
        <div className="card-title">Your setup at a glance</div>
        {shownError ? (
          <div className="alert alert-error">Couldn't check your setup: {shownError}</div>
        ) : !loaded ? (
          <p className="muted">Checking…</p>
        ) : (
          <>
            <p>
              Master Profile{person ? ` for ${labelFor(person)}` : ""}:{" "}
              {hasProfile ? (
                <span className="pill pill-ok">created</span>
              ) : (
                <span className="pill pill-warn">empty</span>
              )}{" "}
              {!hasProfile && <Link to="/profiles">Create your profile →</Link>}
            </p>
            <p>
              Anthropic API key:{" "}
              {settings?.api_key_set ? (
                <span className="pill pill-ok">set</span>
              ) : (
                <span className="pill pill-warn">not set</span>
              )}
              {settings?.fake_mode && (
                <span className="pill" style={{ marginLeft: "0.4rem" }}>
                  Demo mode on
                </span>
              )}
            </p>
            {ready && <p className="pill pill-ok">You're ready to tailor your first job</p>}
          </>
        )}
      </div>

      <div className="card">
        <div className="card-title">Choose how to power Tailored</div>

        <div className="field">
          <label className="field-label">Use your Anthropic API key</label>
          <p className="muted">
            Paste job URLs and walk away. ~$0.15–$3 per job by research depth.
          </p>
          <p className="muted">
            No key yet? Create one in the{" "}
            <a href="https://console.anthropic.com/" target="_blank" rel="noreferrer">
              Anthropic Console →
            </a>{" "}
            (sign in, then API keys → Create key).
          </p>
          <pre className="code-block mono">{ENV_LINE}</pre>
          <CopyButton text={ENV_LINE} label="Copy .env line" />
          <p className="muted">
            Put that line in the <span className="mono">.env</span> file next to{" "}
            <span className="mono">run.py</span> (with your real key) and restart.
          </p>
        </div>

        <div className="field">
          <label className="field-label">Use your own Claude agent (MCP)</label>
          <p className="muted">
            No API key — uses your Claude Code/Codex subscription, and can read login-walled
            postings.
          </p>
          <McpSetup />
        </div>

        <div className="field">
          <label className="field-label">Just explore (Demo mode)</label>
          <p className="muted">
            Offline sample data, no key, no network. Set{" "}
            <span className="mono">TAILORED_FAKE=1</span> and restart, or let the launcher offer it.
          </p>
        </div>
      </div>

      <div className="card">
        <div className="card-title">How Tailored works</div>
        <ol>
          <li>
            Build your <Link to="/profiles">Master Profile</Link> — everything you've done.
          </li>
          <li>
            <Link to="/add">Add job URLs</Link>, pick research depth and template.
          </li>
          <li>
            Watch generation and the truthfulness check on the <Link to="/">Dashboard</Link>.
          </li>
          <li>
            Compare <Link to="/templates">templates</Link> and export PDF / HTML / ATS text.
          </li>
        </ol>
      </div>
    </div>
  );
}
