import "@testing-library/jest-dom/vitest";

// jsdom does not implement matchMedia; theme.ts relies on it for the
// "system" preference. Only install a mock if one isn't already present so
// this stays harmless if a future setup provides its own.
if (typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string): MediaQueryList => {
    const listeners = new Set<(event: MediaQueryListEvent) => void>();
    return {
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined, // deprecated API, kept for compatibility
      removeListener: () => undefined,
      addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.add(listener);
      },
      removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.delete(listener);
      },
      dispatchEvent: () => false,
    } as MediaQueryList;
  };
}

// jsdom does not implement ResizeObserver; TemplatesScreen's thumbnail scaling
// hook uses it (with a window-resize fallback guarded by a typeof check) to
// measure the preview card width. Only install a mock if one isn't already
// present so this stays harmless if a future setup provides its own.
if (typeof window.ResizeObserver !== "function") {
  class ResizeObserverMock {
    observe(): void {
      // jsdom performs no layout, so there is nothing to measure here; the
      // hook's initial synchronous measure() call covers the render-time
      // assertions this mock exists to support.
    }
    unobserve(): void {}
    disconnect(): void {}
  }
  window.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;
}
