import { useEffect, useState } from "react";
import { getSettings, listTemplates, templatePreviewUrl, updateSettings } from "../api";
import type { SettingsShape, TemplateInfo, TemplateName } from "../types";

export default function TemplatesScreen() {
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [settings, setSettings] = useState<SettingsShape | null>(null);
  const [busy, setBusy] = useState<TemplateName | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch((e) => setError(String(e)));
    getSettings()
      .then(setSettings)
      .catch((e) => setError(String(e)));
  }, []);

  async function makeDefault(name: TemplateName) {
    setBusy(name);
    setError(null);
    try {
      const s = await updateSettings({ default_template: name });
      setSettings(s);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <h1>Templates</h1>
      <p className="muted">
        Every template renders the same data - pick the voice that fits the field.
      </p>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="template-grid">
        {templates.map((t) => {
          const isDefault = settings?.default_template === t.name;
          return (
            <div className="card template-card" key={t.name}>
              <div className="card-title">{t.label}</div>
              <p className="muted">{t.best_for}</p>
              <p>{t.description}</p>
              <iframe
                sandbox=""
                title={t.label}
                src={templatePreviewUrl(t.name)}
                className="template-preview-frame"
              />
              <div className="row template-card-footer">
                {isDefault ? (
                  <span className="pill pill-ok">Default</span>
                ) : (
                  <button
                    className="btn"
                    onClick={() => makeDefault(t.name)}
                    disabled={busy === t.name}
                  >
                    {busy === t.name ? "Setting..." : "Set as default"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
