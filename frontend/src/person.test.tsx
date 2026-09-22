import { act, render, screen, waitFor } from "@testing-library/react";
import { useParams } from "react-router-dom";
import { PERSON_STORAGE_KEY, PersonProvider, usePerson } from "./person";
import type { PersonContextValue } from "./person";
import * as api from "./api";
import { deferred, makePerson, renderWithPerson } from "./test-utils";
import type { ProfileSummary } from "./types";

vi.mock("./api", () => ({ listProfiles: vi.fn() }));

const JORDAN = makePerson();
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
  created_at: "2026-02-01T00:00:00+00:00",
});
const ALEX = makePerson({
  id: 3,
  name: "Alex Kim",
  contact: { name: "Alex Kim", email: "alex@example.com", links: [] },
  created_at: "2026-03-01T00:00:00+00:00",
});

// The value the Probe last rendered with; tests call its functions in act().
let latest: PersonContextValue;

function Probe() {
  const ctx = usePerson();
  latest = ctx;
  const shown = ctx.loading
    ? "loading"
    : ctx.person
      ? `${ctx.person.id}:${ctx.labelFor(ctx.person)}`
      : "none";
  return (
    <div>
      <p data-testid="person">{shown}</p>
      <p data-testid="error">{ctx.error ?? ""}</p>
      <p data-testid="notice">{ctx.notice ?? ""}</p>
      <p data-testid="pending">
        {ctx.pendingSwitch ? `${ctx.pendingSwitch.target}|${ctx.pendingSwitch.message}` : ""}
      </p>
    </div>
  );
}

function store(value: unknown) {
  localStorage.setItem(
    PERSON_STORAGE_KEY,
    typeof value === "string" ? value : JSON.stringify(value)
  );
}

function stored(): unknown {
  return JSON.parse(localStorage.getItem(PERSON_STORAGE_KEY) ?? "null");
}

const shown = () => screen.getByTestId("person");

async function renderProvider(first: ProfileSummary[]) {
  vi.mocked(api.listProfiles).mockResolvedValueOnce(first);
  render(
    <PersonProvider>
      <Probe />
    </PersonProvider>
  );
  await waitFor(() => expect(shown()).not.toHaveTextContent("loading"));
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(api.listProfiles).mockReset();
});

describe("PersonProvider: remembering the person", () => {
  it("is loading with no person until the list arrives, then picks the first and remembers it", async () => {
    const list = deferred<ProfileSummary[]>();
    vi.mocked(api.listProfiles).mockReturnValueOnce(list.promise);
    render(
      <PersonProvider>
        <Probe />
      </PersonProvider>
    );
    expect(shown()).toHaveTextContent("loading");
    expect(latest.person).toBeNull();

    await act(async () => list.resolve([JORDAN, SAM]));

    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(latest.people.map((p) => p.id)).toEqual([1, 2]);
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it("restores the stored person when both id and created_at match", async () => {
    store({ id: 2, created_at: SAM.created_at });
    await renderProvider([JORDAN, SAM]);
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(stored()).toEqual({ id: 2, created_at: SAM.created_at });
  });

  it("falls back to the first person and overwrites the entry when the stored person is gone", async () => {
    store({ id: 9, created_at: "2026-05-01T00:00:00+00:00" });
    await renderProvider([JORDAN, SAM]);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it("falls back when the stored id now belongs to someone created later", async () => {
    // SQLite reissued id 2 after the remembered person was removed.
    store({ id: 2, created_at: "2025-12-01T00:00:00+00:00" });
    await renderProvider([JORDAN, SAM]);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it.each([
    ["not JSON", "{not json"],
    ["an array", "[2]"],
    ["a number", "2"],
    ["null", "null"],
    ["a string id", JSON.stringify({ id: "2", created_at: "2026-02-01T00:00:00+00:00" })],
    ["no created_at", JSON.stringify({ id: 2 })],
  ])("falls back when the stored value is %s", async (_label, raw) => {
    store(raw);
    await renderProvider([JORDAN, SAM]);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it("works in memory when localStorage throws", async () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    try {
      await renderProvider([JORDAN, SAM]);
      expect(shown()).toHaveTextContent("1:Jordan Rivera");
      act(() => latest.setPersonId(2));
      expect(shown()).toHaveTextContent("2:Sam Lee");
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it("changes the stored entry only for a remembered switch", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setPersonId(2, { remember: false }));
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });

    act(() => latest.setPersonId(2));
    expect(stored()).toEqual({ id: 2, created_at: SAM.created_at });
  });

  it("ignores setPersonId for an id nobody has", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setPersonId(42));
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
  });

  it("reports a failed first load as an error, with no person", async () => {
    vi.mocked(api.listProfiles).mockRejectedValueOnce(new Error("API 500: boom"));
    render(
      <PersonProvider>
        <Probe />
      </PersonProvider>
    );
    await waitFor(() => expect(shown()).toHaveTextContent("none"));
    expect(screen.getByTestId("error")).toHaveTextContent("API 500: boom");
    expect(latest.people).toEqual([]);
  });

  it("has no person and no error when there are no people", async () => {
    await renderProvider([]);
    expect(shown()).toHaveTextContent("none");
    expect(latest.error).toBeNull();
    expect(localStorage.getItem(PERSON_STORAGE_KEY)).toBeNull();
  });
});

describe("PersonProvider: refreshing", () => {
  it("refreshPeople(selectId) switches to that person and remembers them", async () => {
    await renderProvider([JORDAN]);
    vi.mocked(api.listProfiles).mockResolvedValueOnce([JORDAN, SAM]);
    await act(() => latest.refreshPeople(2));
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(stored()).toEqual({ id: 2, created_at: SAM.created_at });
  });

  it("keeps the current person and picks up edits to them", async () => {
    store({ id: 2, created_at: SAM.created_at });
    await renderProvider([JORDAN, SAM]);
    vi.mocked(api.listProfiles).mockResolvedValueOnce([
      JORDAN,
      { ...SAM, name: "Sam Lee-Park", inbox_url: "https://outlook.live.com/mail/" },
    ]);
    await act(() => latest.refreshPeople());
    expect(shown()).toHaveTextContent("2:Sam Lee-Park");
    expect(latest.person?.inbox_url).toBe("https://outlook.live.com/mail/");
    expect(screen.getByTestId("notice")).toHaveTextContent("");
  });

  it("falls back to the first person with a notice when the current person is gone", async () => {
    store({ id: 2, created_at: SAM.created_at });
    await renderProvider([JORDAN, SAM]);
    vi.mocked(api.listProfiles).mockResolvedValueOnce([JORDAN]);
    await act(() => latest.refreshPeople());
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(screen.getByTestId("notice")).toHaveTextContent("Sam Lee was removed.");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it("treats a changed created_at as a removal, since the id was reissued", async () => {
    store({ id: 2, created_at: SAM.created_at });
    await renderProvider([JORDAN, SAM]);
    vi.mocked(api.listProfiles).mockResolvedValueOnce([
      JORDAN,
      { ...ALEX, id: 2 },
    ]);
    await act(() => latest.refreshPeople());
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(screen.getByTestId("notice")).toHaveTextContent("Sam Lee was removed.");
  });

  it("keeps a stored entry that still names someone when falling back", async () => {
    // Alex is remembered; Sam was shown for one visit only (remember: false).
    store({ id: 3, created_at: ALEX.created_at });
    await renderProvider([JORDAN, SAM, ALEX]);
    act(() => latest.setPersonId(2, { remember: false }));
    vi.mocked(api.listProfiles).mockResolvedValueOnce([JORDAN, ALEX]);
    await act(() => latest.refreshPeople());
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(stored()).toEqual({ id: 3, created_at: ALEX.created_at });
  });

  it("uses the distinguishing label in the removed notice", async () => {
    const samA = { ...SAM, id: 2 };
    const samB = { ...SAM, id: 3, contact: { ...SAM.contact, email: "" }, created_at: ALEX.created_at };
    store({ id: 3, created_at: samB.created_at });
    await renderProvider([samA, samB]);
    vi.mocked(api.listProfiles).mockResolvedValueOnce([samA]);
    await act(() => latest.refreshPeople());
    expect(screen.getByTestId("notice")).toHaveTextContent("Sam Lee #3 was removed.");
  });

  describe("when the tab becomes visible again", () => {
    let visibility: DocumentVisibilityState = "visible";
    beforeEach(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => visibility,
      });
    });
    afterEach(() => {
      delete (document as unknown as Record<string, unknown>).visibilityState;
    });

    it("refreshes the list", async () => {
      await renderProvider([JORDAN]);
      vi.mocked(api.listProfiles).mockResolvedValueOnce([{ ...JORDAN, name: "Jordan R. Rivera" }]);
      visibility = "visible";
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await waitFor(() => expect(shown()).toHaveTextContent("1:Jordan R. Rivera"));
    });

    it("does not refresh while hidden", async () => {
      await renderProvider([JORDAN]);
      visibility = "hidden";
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      expect(api.listProfiles).toHaveBeenCalledTimes(1);
    });
  });

  it("keeps the last good list when a later refresh fails", async () => {
    await renderProvider([JORDAN]);
    vi.mocked(api.listProfiles).mockRejectedValueOnce(new Error("API 500: boom"));
    await act(() => latest.refreshPeople());
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(latest.error).toBeNull();
  });

  it("ignores a response that arrives after a newer refresh", async () => {
    store({ id: 2, created_at: SAM.created_at });
    await renderProvider([JORDAN, SAM]);
    const older = deferred<ProfileSummary[]>();
    const newer = deferred<ProfileSummary[]>();
    vi.mocked(api.listProfiles).mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = latest.refreshPeople();
      second = latest.refreshPeople();
    });
    await act(async () => {
      newer.resolve([JORDAN, SAM]);
      await second;
    });
    await act(async () => {
      older.resolve([JORDAN]);
      await first;
    });
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(screen.getByTestId("notice")).toHaveTextContent("");
  });
});

describe("PersonProvider: the switch guard", () => {
  const GUARD = "Jordan Rivera has unsaved profile changes.";

  it("switches at once, and remembers, when no guard is set", async () => {
    await renderProvider([JORDAN, SAM]);
    let done = false;
    act(() => {
      done = latest.requestSwitch(2);
    });
    expect(done).toBe(true);
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(stored()).toEqual({ id: 2, created_at: SAM.created_at });
  });

  it("holds a guarded switch as pending until it is confirmed", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setSwitchGuard(GUARD));
    let done = true;
    act(() => {
      done = latest.requestSwitch(2);
    });
    expect(done).toBe(false);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(screen.getByTestId("pending")).toHaveTextContent(`2|${GUARD}`);

    let target: unknown;
    act(() => {
      target = latest.confirmSwitch();
    });
    expect(target).toBe(2);
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(screen.getByTestId("pending")).toHaveTextContent("");
    expect(stored()).toEqual({ id: 2, created_at: SAM.created_at });
  });

  it("stays on the current person when the pending switch is cancelled", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setSwitchGuard(GUARD));
    act(() => {
      latest.requestSwitch(2);
    });
    act(() => latest.cancelSwitch());
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(screen.getByTestId("pending")).toHaveTextContent("");
    expect(stored()).toEqual({ id: 1, created_at: JORDAN.created_at });
  });

  it("guards 'Add a person' too, and hands 'new' back on confirm", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setSwitchGuard(GUARD));
    let done = true;
    act(() => {
      done = latest.requestSwitch("new");
    });
    expect(done).toBe(false);
    expect(screen.getByTestId("pending")).toHaveTextContent(`new|${GUARD}`);
    let target: unknown;
    act(() => {
      target = latest.confirmSwitch();
    });
    expect(target).toBe("new");
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
  });

  it("returns true for 'new' without a guard and leaves the person alone", async () => {
    await renderProvider([JORDAN, SAM]);
    let done = false;
    act(() => {
      done = latest.requestSwitch("new");
    });
    expect(done).toBe(true);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(screen.getByTestId("pending")).toHaveTextContent("");
  });

  it("lets switches through again once the guard is cleared", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setSwitchGuard(GUARD));
    act(() => latest.setSwitchGuard(null));
    let done = false;
    act(() => {
      done = latest.requestSwitch(2);
    });
    expect(done).toBe(true);
    expect(shown()).toHaveTextContent("2:Sam Lee");
  });

  it("does not guard setPersonId, the programmatic path", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setSwitchGuard(GUARD));
    act(() => latest.setPersonId(2, { remember: false }));
    expect(shown()).toHaveTextContent("2:Sam Lee");
    expect(screen.getByTestId("pending")).toHaveTextContent("");
  });

  it("confirmSwitch with nothing pending returns null", async () => {
    await renderProvider([JORDAN, SAM]);
    let target: unknown = "unset";
    act(() => {
      target = latest.confirmSwitch();
    });
    expect(target).toBeNull();
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
  });

  it("clears the notice when the person is switched from the picker", async () => {
    await renderProvider([JORDAN, SAM]);
    act(() => latest.setNotice("Switched to Sam Lee to show this application."));
    act(() => {
      latest.requestSwitch(2);
    });
    expect(screen.getByTestId("notice")).toHaveTextContent("");
  });
});

describe("PersonProvider: labels", () => {
  it("uses the name, and tells duplicates apart by email or else by id", async () => {
    const samA = { ...SAM, id: 2 };
    const samB = { ...SAM, id: 3, contact: { ...SAM.contact, email: "" }, created_at: ALEX.created_at };
    await renderProvider([JORDAN, samA, samB]);
    expect(latest.labelFor(JORDAN)).toBe("Jordan Rivera");
    expect(latest.labelFor(samA)).toBe("Sam Lee (sam@example.com)");
    expect(latest.labelFor(samB)).toBe("Sam Lee #3");
  });

  it("falls back to the id when two people share both name and email", async () => {
    const samA = { ...SAM, id: 2 };
    const samB = { ...SAM, id: 3, created_at: ALEX.created_at };
    await renderProvider([samA, samB]);
    expect(latest.labelFor(samA)).toBe("Sam Lee #2");
    expect(latest.labelFor(samB)).toBe("Sam Lee #3");
  });
});

describe("usePerson", () => {
  it("throws outside a PersonProvider", () => {
    // React reports the render error through console.error and a window
    // "error" event before rethrowing; silence both so the run stays readable.
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const swallow = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", swallow);
    try {
      expect(() => render(<Probe />)).toThrow("usePerson must be used inside <PersonProvider>");
    } finally {
      window.removeEventListener("error", swallow);
      quiet.mockRestore();
    }
  });
});

describe("renderWithPerson", () => {
  it("provides the given people and person, and switchTo re-renders with another", () => {
    const r = renderWithPerson(<Probe />, { people: [JORDAN, SAM], personId: 2 });
    expect(shown()).toHaveTextContent("2:Sam Lee");
    const guard = r.ctx.setSwitchGuard;

    r.switchTo(1);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(r.ctx.person?.id).toBe(1);
    expect(r.ctx.setSwitchGuard).toBe(guard);

    r.switchTo(null);
    expect(shown()).toHaveTextContent("none");
  });

  it("defaults to one person, selected", () => {
    const r = renderWithPerson(<Probe />);
    expect(shown()).toHaveTextContent("1:Jordan Rivera");
    expect(r.ctx.people).toEqual([JORDAN]);
  });

  it("gives no person while loading", () => {
    renderWithPerson(<Probe />, { loading: true });
    expect(shown()).toHaveTextContent("loading");
    expect(latest.person).toBeNull();
  });

  it("mounts the ui at a route pattern", () => {
    function Param() {
      const { id } = useParams();
      return <p>application {id}</p>;
    }
    renderWithPerson(<Param />, { route: "/applications/7", path: "/applications/:id" });
    expect(screen.getByText("application 7")).toBeInTheDocument();
  });

  it("applies overrides over the defaults", () => {
    renderWithPerson(<Probe />, { overrides: { notice: "Sam Lee was removed." } });
    expect(screen.getByTestId("notice")).toHaveTextContent("Sam Lee was removed.");
  });
});
