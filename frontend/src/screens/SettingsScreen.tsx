import { useEffect, useState } from "react";
import { getSettings, updateSettings } from "../api";
import { getThemePref, setThemePref, subscribeTheme } from "../theme";
import type { ThemePref } from "../theme";
import type { Depth, PageSize, SettingsShape, TemplateName } from "../types";

const DEPTHS: Depth[] = ["quick", "standard", "deep"];
const TEMPLATES: TemplateName[] = ["meridian", "slate", "terminal", "signal"];
const PAGE_SIZES: PageSize[] = ["Letter", "A4"];
const THEME_PREFS: ThemePref[] = ["system", "light", "dark"];
const THEME_LABELS: Record<ThemePref, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

export default function SettingsScreen() {
  const [settings, setSettings] = useState<SettingsShape | null>(null);
  const [themePref, setThemePrefState] = useState<ThemePref>(() => getThemePref());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSettings()
      .then(setSettings)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => subscribeTheme((pref) => setThemePrefState(pref)), []);

  async function patch(p: {
    default_template?: TemplateName;
    default_depth?: Depth;
    page_size?: PageSize;
  }) {
    setError(null);
    try {
      const s = await updateSettings(p);
      setSettings(s);
    } catch (err) {
      setError(String(err));
    }
  }

  function handleThemeChange(pref: ThemePref) {
    setThemePref(pref);
  }

  if (!settings) {
    return (
      <div>
        <h1>Settings</h1>
        {error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading...</p>}
      </div>
    );
  }

  return (
    <div>
      <h1>Settings</h1>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        <div className="card-title">Anthropic API key</div>
        <p>
          {settings.api_key_set ? (
            <span className="pill pill-ok">API key set</span>
          ) : (
            <span className="pill pill-warn">API key not set</span>
          )}
        </p>
        <p className="muted">
          The key is read from the ANTHROPIC_API_KEY variable in the .env file next to run.py.
          Add or change it there and restart the app — it is never stored in the database.
        </p>
        {settings.fake_mode ? (
          <div className="callout">
            Demo mode is active (TAILORED_FAKE=1): all generation uses offline canned fixtures and
            no API calls are made.
          </div>
        ) : (
          <p className="muted">
            Demo mode is off. Set TAILORED_FAKE=1 in the .env file next to run.py and restart to
            explore the app fully offline with no API key.
          </p>
        )}
      </div>

      <div className="card">
        <div className="card-title">How generation works</div>
        <div className="field">
          <label className="field-label">Web app (this browser)</label>
          <p className="muted">
            Applications you create on the Add Jobs page are generated with the Anthropic API,
            billed to your API key.
          </p>
          <p>
            {settings.api_key_set ? (
              <span className="pill pill-ok">API key: set</span>
            ) : (
              <span className="pill pill-warn">API key: not set</span>
            )}
            {settings.fake_mode && <span className="pill" style={{ marginLeft: "0.4rem" }}>Demo mode</span>}
          </p>
          {!settings.api_key_set && (
            <p className="muted">
              Add ANTHROPIC_API_KEY to the .env file and restart to generate from the web app.
            </p>
          )}
          {settings.fake_mode && (
            <p className="muted">Sample data only — no API calls, no key needed.</p>
          )}
        </div>
        <div className="field">
          <label className="field-label">Your own AI agent (MCP)</label>
          <p className="muted">
            Connect Tailored to Claude Code (or any MCP-capable agent) and it does the work on
            your own subscription — no API key used. Ask your agent to read Tailored's workflow
            guide, then say "tailor my profile for &lt;job url&gt;".
          </p>
          <p className="muted">
            These applications show a depth of "external" on the dashboard, and the same
            truthfulness guard applies. See the setup steps in the README, or
            docs/EXTENDING.md for the full tool contract.
          </p>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Defaults</div>
        <div className="field" style={{ maxWidth: "20rem" }}>
          <label className="field-label">Default template</label>
          <select
            className="select"
            value={settings.default_template}
            onChange={(e) => patch({ default_template: e.target.value as TemplateName })}
          >
            {TEMPLATES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ maxWidth: "20rem" }}>
          <label className="field-label">Default research depth</label>
          <select
            className="select"
            value={settings.default_depth}
            onChange={(e) => patch({ default_depth: e.target.value as Depth })}
          >
            {DEPTHS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ maxWidth: "20rem" }}>
          <label className="field-label">Page size</label>
          <select
            className="select"
            value={settings.page_size}
            onChange={(e) => patch({ page_size: e.target.value as PageSize })}
          >
            {PAGE_SIZES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Appearance</div>
        <div className="field" style={{ maxWidth: "20rem" }}>
          <label className="field-label">Theme</label>
          <select
            className="select"
            value={themePref}
            onChange={(e) => handleThemeChange(e.target.value as ThemePref)}
          >
            {THEME_PREFS.map((p) => (
              <option key={p} value={p}>
                {THEME_LABELS[p]}
              </option>
            ))}
          </select>
        </div>
        <p className="muted">
          Stored on this device only — "System" follows your OS light/dark setting.
        </p>
      </div>
    </div>
  );
}
