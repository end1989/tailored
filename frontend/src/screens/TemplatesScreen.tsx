import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { getSettings, listTemplates, templatePreviewUrl, updateSettings } from "../api";
import type { SettingsShape, TemplateInfo, TemplateName } from "../types";

// Letter page at 96dpi — the iframe renders at this real page size and gets
// scaled down to fit the card, so the resume reflows exactly as it would on
// a full page instead of cramming into a narrow container.
const PAGE_W = 816;
const PAGE_H = 1056;

function useThumbScale() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    function measure() {
      if (!el) return;
      const width = el.getBoundingClientRect().width;
      if (width > 0) {
        setScale(width / PAGE_W);
      }
    }

    measure();

    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(measure);
      observer.observe(el);
      return () => observer.disconnect();
    }

    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  return { ref, scale };
}

function TemplateCard({
  template,
  isDefault,
  busy,
  onMakeDefault,
}: {
  template: TemplateInfo;
  isDefault: boolean;
  busy: boolean;
  onMakeDefault: (name: TemplateName) => void;
}) {
  const { ref, scale } = useThumbScale();
  const previewUrl = templatePreviewUrl(template.name);

  return (
    <div className="card template-card">
      <div className="card-title">{template.label}</div>
      <p className="muted">{template.best_for}</p>
      <p>{template.description}</p>
      <div className="preview-thumb" ref={ref}>
        <iframe
          sandbox=""
          title={template.label}
          src={previewUrl}
          style={{
            width: `${PAGE_W}px`,
            height: `${PAGE_H}px`,
            border: 0,
            position: "absolute",
            top: 0,
            left: 0,
            transformOrigin: "top left",
            pointerEvents: "none",
            transform: `scale(${scale})`,
          }}
        />
      </div>
      <a className="muted-link" href={previewUrl} target="_blank" rel="noreferrer">
        Open full size &rarr;
      </a>
      <div className="row template-card-footer">
        {isDefault ? (
          <span className="pill pill-ok">Default</span>
        ) : (
          <button
            className="btn"
            onClick={() => onMakeDefault(template.name)}
            disabled={busy}
          >
            {busy ? "Setting..." : "Set as default"}
          </button>
        )}
      </div>
    </div>
  );
}

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
        {templates.map((t) => (
          <TemplateCard
            key={t.name}
            template={t}
            isDefault={settings?.default_template === t.name}
            busy={busy === t.name}
            onMakeDefault={makeDefault}
          />
        ))}
      </div>
    </div>
  );
}
