// Client-side theme handling. Entirely local — never sent to the backend.
export type ThemePref = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "tailored-theme";

export function getThemePref(): ThemePref {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") {
    return stored;
  }
  return "system";
}

export function resolveTheme(pref: ThemePref): ResolvedTheme {
  if (pref === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return pref;
}

export interface ThemeChangeDetail {
  pref: ThemePref;
  resolved: ResolvedTheme;
}

export function applyTheme(pref: ThemePref): void {
  const resolved = resolveTheme(pref);
  document.documentElement.dataset.theme = resolved;
  window.dispatchEvent(
    new CustomEvent<ThemeChangeDetail>("tailored-theme-changed", { detail: { pref, resolved } })
  );
}

export function setThemePref(pref: ThemePref): void {
  localStorage.setItem(STORAGE_KEY, pref);
  applyTheme(pref);
}

export function initTheme(): void {
  const pref = getThemePref();
  applyTheme(pref);
  const mql = window.matchMedia("(prefers-color-scheme: dark)");
  mql.addEventListener("change", () => applyTheme(getThemePref()));
}

export function subscribeTheme(cb: (pref: ThemePref, resolved: ResolvedTheme) => void): () => void {
  const listener = (event: Event) => {
    const { pref, resolved } = (event as CustomEvent<ThemeChangeDetail>).detail;
    cb(pref, resolved);
  };
  window.addEventListener("tailored-theme-changed", listener);
  return () => window.removeEventListener("tailored-theme-changed", listener);
}
