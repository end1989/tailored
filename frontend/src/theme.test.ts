import { getThemePref, setThemePref, subscribeTheme } from "./theme";

describe("theme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("setThemePref('dark') sets the document theme and persists it", () => {
    setThemePref("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("tailored-theme")).toBe("dark");
    expect(getThemePref()).toBe("dark");
  });

  it("setThemePref('system') resolves to dark when the OS prefers dark", () => {
    const original = window.matchMedia;
    try {
      window.matchMedia = vi.fn().mockImplementation((query: string) => ({
        matches: true,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })) as unknown as typeof window.matchMedia;

      setThemePref("system");
      expect(document.documentElement.dataset.theme).toBe("dark");
      expect(localStorage.getItem("tailored-theme")).toBe("system");
    } finally {
      window.matchMedia = original;
    }
  });

  it("subscribeTheme receives the change event, then stops after unsubscribing", () => {
    const calls: Array<{ pref: string; resolved: string }> = [];
    const unsubscribe = subscribeTheme((pref, resolved) => {
      calls.push({ pref, resolved });
    });

    setThemePref("dark");
    expect(calls).toEqual([{ pref: "dark", resolved: "dark" }]);
    expect(document.documentElement.dataset.theme).toBe("dark");

    unsubscribe();
    setThemePref("light");
    expect(calls).toEqual([{ pref: "dark", resolved: "dark" }]);
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
