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

export function applyTheme(pref: ThemePref): void {
  document.documentElement.dataset.theme = resolveTheme(pref);
}

export function setThemePref(pref: ThemePref): void {
  localStorage.setItem(STORAGE_KEY, pref);
  applyTheme(pref);
}

export function initTheme(): void {
  const pref = getThemePref();
  applyTheme(pref);
  if (pref === "system") {
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    mql.addEventListener("change", () => applyTheme("system"));
  }
}
