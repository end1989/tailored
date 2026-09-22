import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listTemplates } from "../api";
import McpSetup from "../components/McpSetup";
import { usePerson } from "../person";
import { usePersonSettings } from "../personSettings";
import type { SettingsPatch } from "../personSettings";
import { getThemePref, setThemePref, subscribeTheme } from "../theme";
import type { ThemePref } from "../theme";
import type { Depth, PageSize, TemplateInfo, TemplateName } from "../types";

const DEPTHS: Depth[] = ["quick", "standard", "deep"];
const PAGE_SIZES: PageSize[] = ["Letter", "A4"];
const THEME_PREFS: ThemePref[] = ["system", "light", "dark"];
const THEME_LABELS: Record<ThemePref, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

export default function SettingsScreen() {
  const { person, labelFor } = usePerson();
  const { settings, error, save } = usePersonSettings();
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [themePref, setThemePrefState] = useState<ThemePref>(() => getThemePref());

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => subscribeTheme((pref) => setThemePrefState(pref)), []);

  function patch(p: SettingsPatch) {
    void save(p);
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

  const defaultsCard = (
    <div className="card">
      <div className="card-title">Defaults</div>
      <div className="field" style={{ maxWidth: "20rem" }}>
        <label className="field-label" htmlFor="default-template">
          Default template
        </label>
        <select
          id="default-template"
          className="select"
          value={settings.default_template}
          onChange={(e) => patch({ default_template: e.target.value as TemplateName })}
        >
          {templates.map((t) => (
            <option key={t.name} value={t.name}>
              {t.label || t.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field" style={{ maxWidth: "20rem" }}>
        <label className="field-label" htmlFor="default-depth">
          Default research depth
        </label>
        <select
          id="default-depth"
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
        <label className="field-label" htmlFor="page-size">
          Page size
        </label>
        <select
          id="page-size"
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
  );

  return (
    <div>
      <h1>Settings</h1>
      {error && <div className="alert alert-error">{error}</div>}

      {person && (
        <section aria-labelledby="person-settings-heading">
          <h2 id="person-settings-heading">Settings for {labelFor(person)}</h2>
          <p className="muted">
            The default template and research depth apply to jobs added for {labelFor(person)} on
            the Add Jobs page. The page size applies to every document rendered for{" "}
            {labelFor(person)}, including ones an agent makes over MCP.
          </p>
          {defaultsCard}
        </section>
      )}

      <section aria-labelledby="app-wide-heading">
        <h2 id="app-wide-heading">App-wide</h2>
        <p className="muted">
          The API key, demo mode and theme do not change with the selected person.
        </p>

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
              Connect Tailored to Claude Code (or any MCP-capable agent) and it does the work on your own
              subscription — no API key used. These applications show a depth of "external" on the
              dashboard, and the same truthfulness guard applies.
            </p>
            <McpSetup />
            <p className="muted">
              New here? The <Link to="/getting-started">Getting Started</Link> page walks through all three
              ways to power Tailored.
            </p>
          </div>
        </div>

        {!person && defaultsCard}

        <div className="card">
          <div className="card-title">Appearance</div>
          <div className="field" style={{ maxWidth: "20rem" }}>
            <label className="field-label" htmlFor="theme-pref">
              Theme
            </label>
            <select
              id="theme-pref"
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
      </section>
    </div>
  );
}
