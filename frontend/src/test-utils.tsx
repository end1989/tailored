// Test helper: render a screen inside a fixed person context and a router.
//
// Nothing in the app imports this file, so Vite never bundles it; tsc still
// type-checks it with the rest of src. Its name has no ".test.", so
// scripts/stamp-build.mjs hashes it as a build input: after editing it, run
// `npm run build` like after any other src change.
import { render } from "@testing-library/react";
import type { RenderResult } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { PersonContext } from "./person";
import type { PersonContextValue } from "./person";
import type { ProfileSummary } from "./types";

export function makePerson(p: Partial<ProfileSummary> = {}): ProfileSummary {
  return {
    id: 1,
    name: "Jordan Rivera",
    contact: { name: "Jordan Rivera", email: "jordan@example.com", links: [] },
    has_master_profile: true,
    created_at: "2026-01-01T00:00:00+00:00",
    inbox_url: null,
    ...p,
  };
}

export interface PersonTestOptions {
  people?: ProfileSummary[];
  personId?: number | null;
  loading?: boolean;
  route?: string;
  path?: string;
  overrides?: Partial<PersonContextValue>;
}

export type PersonRenderResult = RenderResult & {
  ctx: PersonContextValue;
  switchTo(id: number | null): void;
};

/**
 * Renders `ui` with a static PersonContext value, inside a MemoryRouter at
 * `route`. Every context function is a vi.fn() (labelFor returns the name,
 * requestSwitch returns true, confirmSwitch returns null, refreshPeople
 * resolves), shared across switchTo so a test can assert calls made before
 * and after a switch. `ctx` always holds the value currently rendered.
 */
export function renderWithPerson(ui: ReactElement, opts: PersonTestOptions = {}): PersonRenderResult {
  const people = opts.people ?? [makePerson()];
  const loading = opts.loading ?? false;
  const route = opts.route ?? "/";

  const fns = {
    setNotice: vi.fn(),
    setPersonId: vi.fn(),
    requestSwitch: vi.fn().mockReturnValue(true),
    confirmSwitch: vi.fn().mockReturnValue(null),
    cancelSwitch: vi.fn(),
    refreshPeople: vi.fn().mockResolvedValue(undefined),
    setSwitchGuard: vi.fn(),
    labelFor: vi.fn((p: ProfileSummary) => p.name),
  };

  function contextFor(personId: number | null): PersonContextValue {
    const person =
      loading || personId === null ? null : people.find((p) => p.id === personId) ?? null;
    return {
      people,
      person,
      loading,
      error: null,
      notice: null,
      pendingSwitch: null,
      ...fns,
      ...opts.overrides,
    };
  }

  let current: ReactNode = ui;
  function tree(value: PersonContextValue): ReactElement {
    return (
      <MemoryRouter initialEntries={[route]}>
        <PersonContext.Provider value={value}>
          {opts.path ? (
            <Routes>
              <Route path={opts.path} element={current} />
            </Routes>
          ) : (
            current
          )}
        </PersonContext.Provider>
      </MemoryRouter>
    );
  }

  const initialId = opts.personId === undefined ? people[0]?.id ?? null : opts.personId;
  const ctx = contextFor(initialId);
  const result = render(tree(ctx));
  const out: PersonRenderResult = {
    ...result,
    ctx,
    // Re-render a new element inside the same context and router.
    rerender(next: ReactNode) {
      current = next;
      result.rerender(tree(out.ctx));
    },
    switchTo(id: number | null) {
      out.ctx = contextFor(id);
      result.rerender(tree(out.ctx));
    },
  };
  return out;
}

/**
 * A promise plus its own resolve/reject, for tests that need to control when
 * an async call (e.g. a mocked API function) settles. Shared here because
 * several screen tests each need one to exercise a loading/in-flight state.
 */
export function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
