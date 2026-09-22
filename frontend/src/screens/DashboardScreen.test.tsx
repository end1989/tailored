import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import DashboardScreen from "./DashboardScreen";
import * as api from "../api";
import { makePerson, renderWithPerson } from "../test-utils";
import type { ApplicationDetail, ApplicationSummary } from "../types";

// listProfiles is deliberately absent. The screen reads the person from
// PersonContext; vitest throws on any access to an export this factory does
// not define, so a screen that fetched its own profile list would fail here.
vi.mock("../api", () => {
  return {
    listApplications: vi.fn().mockResolvedValue([
      {
        id: 10,
        profile_id: 1,
        status: "ready",
        version: 2,
        template: "slate",
        depth: "standard",
        url: "https://example.com/a",
        company: "Acme",
        title: "Backend Engineer",
        cost_usd: 0.4321,
        created_at: "2026-07-22T10:00:00",
        error_message: null,
        stage: "applied",
        applied_at: "2026-07-22T10:30:00+00:00",
        archived_at: null,
        last_activity_at: "2026-07-22T10:30:00+00:00",
      },
      {
        id: 11,
        profile_id: 1,
        status: "tailoring",
        version: 1,
        template: "terminal",
        depth: "deep",
        url: "https://example.com/b",
        company: "Globex",
        title: "Platform Engineer",
        cost_usd: 0.1,
        created_at: "2026-07-22T11:00:00",
        error_message: null,
        stage: "drafted",
        applied_at: null,
        archived_at: null,
        last_activity_at: "2026-07-22T11:00:00+00:00",
      },
    ]),
    patchApplication: vi.fn().mockResolvedValue(undefined),
    archiveApplication: vi.fn().mockResolvedValue(undefined),
    restoreApplication: vi.fn().mockResolvedValue(undefined),
    deleteApplication: vi.fn().mockResolvedValue(undefined),
    generateApplication: vi.fn().mockResolvedValue(undefined),
  };
});

const BASE_APP = {
  id: 10,
  profile_id: 1,
  status: "ready" as const,
  version: 2,
  template: "slate" as const,
  depth: "standard" as const,
  url: "https://example.com/a",
  company: "Acme",
  title: "Backend Engineer",
  cost_usd: 0.4321,
  created_at: "2026-07-22T10:00:00",
  error_message: null,
  stage: "applied" as const,
  applied_at: "2026-07-22T10:30:00+00:00",
  archived_at: null,
  last_activity_at: "2026-07-22T10:30:00+00:00",
};

const JORDAN = makePerson();
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
  created_at: "2026-02-01T00:00:00+00:00",
});

// One row per person, both on the default "To apply" tab (stage drafted) and
// both terminal (status ready), so no poll timer is left running.
const JORDAN_ROW: ApplicationSummary = {
  ...BASE_APP,
  id: 10,
  profile_id: 1,
  company: "JordanCo",
  stage: "drafted",
  applied_at: null,
};
const SAM_ROW: ApplicationSummary = {
  ...BASE_APP,
  id: 20,
  profile_id: 2,
  company: "SamCo",
  stage: "drafted",
  applied_at: null,
};

beforeEach(() => {
  // Call history only; the implementations set with mockResolvedValue stay.
  vi.clearAllMocks();
});

/**
 * Renders on the All tab, where every fixture row is visible whatever its
 * stage. The screen opens on "To apply", which deliberately hides anything
 * already sent -- so tests about badges, stage editing, deletion, and refetch
 * say "All" explicitly rather than depending on the default.
 */
async function renderOnAllTab() {
  renderWithPerson(<DashboardScreen />);
  fireEvent.click(await screen.findByRole("button", { name: /^all/i }));
}

describe("DashboardScreen", () => {
  it("renders one row per application with per-status badges", async () => {
    await renderOnAllTab();
    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("Globex")).toBeInTheDocument();
    // Badges name the artifact, not the enum: "ready" alone read as "ready to
    // apply" and collided with the Stage column.
    expect(screen.getByText("Docs ready")).toHaveClass("badge", "badge-ready");
    expect(screen.getByText("Writing")).toHaveClass("badge", "badge-tailoring");
    expect(screen.getByLabelText(/stage for row 1/i)).toHaveValue("applied");
    expect(screen.getAllByText("Open")).toHaveLength(2);
  });

  it("separates what still needs sending from what is already out", async () => {
    // The whole point of the tabs: "which have I applied for and which haven't"
    // must be answerable without reading a stage column row by row.
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 1, company: "NotSentYet", stage: "drafted", applied_at: null },
      { ...BASE_APP, id: 2, company: "AlsoNotSent", stage: "saved", status: "not_started", applied_at: null },
      { ...BASE_APP, id: 3, company: "AlreadySent", stage: "applied" },
      { ...BASE_APP, id: 4, company: "Interviewing", stage: "interview" },
      { ...BASE_APP, id: 5, company: "TurnedDown", stage: "rejected" },
    ]);
    renderWithPerson(<DashboardScreen />);

    // Opens on "To apply": only the two that have not gone out.
    expect(await screen.findByText("NotSentYet")).toBeInTheDocument();
    expect(screen.getByText("AlsoNotSent")).toBeInTheDocument();
    expect(screen.queryByText("AlreadySent")).not.toBeInTheDocument();
    expect(screen.queryByText("TurnedDown")).not.toBeInTheDocument();

    // "Applied" holds everything sent and still live -- including later
    // stages, since an interview is a sent application that progressed.
    fireEvent.click(screen.getByRole("button", { name: /^applied/i }));
    expect(await screen.findByText("AlreadySent")).toBeInTheDocument();
    expect(screen.getByText("Interviewing")).toBeInTheDocument();
    expect(screen.queryByText("NotSentYet")).not.toBeInTheDocument();
    expect(screen.queryByText("TurnedDown")).not.toBeInTheDocument();

    // "Closed" isolates the dead ones so they stop padding the live count.
    fireEvent.click(screen.getByRole("button", { name: /^closed/i }));
    expect(await screen.findByText("TurnedDown")).toBeInTheDocument();
    expect(screen.queryByText("AlreadySent")).not.toBeInTheDocument();
  });

  it("counts every bucket so the split is readable without switching tabs", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 1, company: "A", stage: "drafted", applied_at: null },
      { ...BASE_APP, id: 2, company: "B", stage: "applied" },
      { ...BASE_APP, id: 3, company: "C", stage: "offer" },
      { ...BASE_APP, id: 4, company: "D", stage: "rejected" },
    ]);
    renderWithPerson(<DashboardScreen />);

    expect(await screen.findByRole("button", { name: /to apply 1/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /applied 2/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /closed 1/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /all 4/i })).toBeInTheDocument();
  });

  it("shows Getting Started and profile links in the empty state", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([]);
    renderWithPerson(<DashboardScreen />);
    expect(
      await screen.findByRole("link", { name: /Getting Started/ })
    ).toHaveAttribute("href", "/getting-started");
    expect(screen.getByRole("link", { name: /create your Master Profile/ })).toHaveAttribute(
      "href",
      "/profiles"
    );
    expect(screen.getByRole("link", { name: /add job URLs/ })).toHaveAttribute("href", "/add");
    expect(screen.queryByText("Acme")).not.toBeInTheDocument();
  });

  it("stops polling when every application is in a terminal state", async () => {
    vi.useFakeTimers();
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 1, status: "not_started", stage: "saved" },
    ]);

    renderWithPerson(<DashboardScreen />);
    await vi.advanceTimersByTimeAsync(0);
    const callsAfterFirstTick = vi.mocked(api.listApplications).mock.calls.length;

    await vi.advanceTimersByTimeAsync(10_000);

    expect(vi.mocked(api.listApplications).mock.calls.length).toBe(callsAfterFirstTick);
    vi.useRealTimers();
  });

  it("filters to archived applications when the tab is selected", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([{ ...BASE_APP, id: 1 }]);
    renderWithPerson(<DashboardScreen />);

    fireEvent.click(await screen.findByRole("button", { name: /archived/i }));

    await waitFor(() =>
      expect(api.listApplications).toHaveBeenCalledWith(1, { archived: true })
    );
  });

  it("changes stage from the row without opening the application", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 7, stage: "applied" },
    ]);
    vi.mocked(api.patchApplication).mockResolvedValue({ ...BASE_APP, id: 7, stage: "interview" } as never);
    await renderOnAllTab();

    const select = await screen.findByLabelText(/stage for row 1/i);
    fireEvent.change(select, { target: { value: "interview" } });

    expect(api.patchApplication).toHaveBeenCalledWith(7, { stage: "interview" });
  });

  it("disables the Saved stage option for a ready row", async () => {
    // Regression for I2(a): the backend 422s on stage="saved" once status is
    // "ready"; the dashboard's row dropdown must not offer that choice.
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 7, status: "ready", stage: "applied" },
    ]);
    await renderOnAllTab();

    const select = await screen.findByLabelText(/stage for row 1/i);
    const savedOption = within(select).getByRole("option", { name: "Saved" }) as HTMLOptionElement;
    expect(savedOption.disabled).toBe(true);
  });

  it("asks for confirmation naming the role before deleting", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 3, company: "Initech", title: "Staff Engineer" },
    ]);
    await renderOnAllTab();

    fireEvent.click(await screen.findByLabelText(/select row 1/i));
    fireEvent.click(screen.getByRole("button", { name: /delete permanently/i }));

    expect(screen.getByRole("dialog")).toHaveTextContent("Initech");
    expect(screen.getByRole("dialog")).toHaveTextContent("Staff Engineer");
    expect(api.deleteApplication).not.toHaveBeenCalled();
  });

  it("renders Last activity on its LOCAL calendar day, matching the Application screen's convention", async () => {
    // last_activity_at IS an event's occurred_at (backend derives it as
    // MAX(occurred_at)) -- same value kind as ApplicationScreen's timeline,
    // so it must follow the same local-on-both-sides convention. Built at
    // 23:00 local so local and UTC days genuinely differ under the stubbed
    // TZ, regardless of the runner's own zone.
    vi.stubEnv("TZ", "America/New_York");
    try {
      const instant = new Date(2026, 6, 20, 23, 0, 0); // 2026-07-20 23:00 local
      const expectedLocalDay = instant.toLocaleDateString();
      vi.mocked(api.listApplications).mockResolvedValue([
        { ...BASE_APP, id: 5, last_activity_at: instant.toISOString() },
      ]);

      await renderOnAllTab();

      expect(await screen.findByText(expectedLocalDay)).toBeInTheDocument();
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("refreshes the table even when an action fails", async () => {
    // Regression: reload() used to sit inside the try, so a rejection left the
    // table showing rows the server had already changed until the next poll.
    //
    // Asserted via an observable outcome, not a call count: swapping what the
    // API returns AFTER the screen has settled means the new company name can
    // only appear if a refetch happened following the failed action. A call
    // count would only say a request went out, not that its rows replaced
    // the stale ones.
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 5, company: "Before Co" },
    ]);
    vi.mocked(api.patchApplication).mockRejectedValueOnce(new Error("API 422: nope"));
    await renderOnAllTab();
    await screen.findByText("Before Co");

    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 5, company: "Refetched Co" },
    ]);
    fireEvent.change(await screen.findByLabelText(/stage for row 1/i), {
      target: { value: "offer" },
    });

    await waitFor(() => expect(screen.getByText(/API 422: nope/)).toBeInTheDocument());
    expect(await screen.findByText("Refetched Co")).toBeInTheDocument();
  });

  it("reports how many items failed in a bulk action, not just the first", async () => {
    // Promise.all surfaces only the FIRST rejection, so a 2-of-3 failure would
    // report one error and silently drop the other. allSettled counts them.
    vi.mocked(api.listApplications).mockResolvedValue([
      { ...BASE_APP, id: 1, company: "One" },
      { ...BASE_APP, id: 2, company: "Two" },
      { ...BASE_APP, id: 3, company: "Three" },
    ]);
    vi.mocked(api.archiveApplication)
      .mockRejectedValueOnce(new Error("API 409: busy"))
      .mockResolvedValueOnce(undefined as never)
      .mockRejectedValueOnce(new Error("API 500: boom"));
    await renderOnAllTab();
    await screen.findByText("One");

    for (const n of [1, 2, 3]) {
      fireEvent.click(screen.getByLabelText(new RegExp(`select row ${n}`, "i")));
    }
    fireEvent.click(screen.getByRole("button", { name: /^archive$/i }));

    // All three attempted despite two failures, and the count is reported.
    await waitFor(() =>
      expect(screen.getByText(/2 of 3 could not be archived/i)).toBeInTheDocument()
    );
    expect(vi.mocked(api.archiveApplication)).toHaveBeenCalledTimes(3);
  });
});

describe("DashboardScreen and the current person", () => {
  it("lists the current person's applications, not the first person's", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([SAM_ROW]);
    renderWithPerson(<DashboardScreen />, { people: [JORDAN, SAM], personId: 2 });

    expect(await screen.findByText("SamCo")).toBeInTheDocument();
    const ids = vi.mocked(api.listApplications).mock.calls.map(([id]) => id);
    expect(ids.length).toBeGreaterThan(0);
    expect(ids.every((id) => id === 2)).toBe(true);
  });

  it("makes no request while there is no person, then lists the person once there is one", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([JORDAN_ROW]);
    const { switchTo } = renderWithPerson(<DashboardScreen />, {
      people: [JORDAN],
      personId: null,
    });

    // Regression for the unfiltered first poll: with no person the screen
    // must not fetch every person's applications.
    expect(api.listApplications).not.toHaveBeenCalled();

    act(() => switchTo(1));

    expect(await screen.findByText("JordanCo")).toBeInTheDocument();
    expect(api.listApplications).toHaveBeenCalledWith(1, undefined);
    expect(api.listApplications).not.toHaveBeenCalledWith(undefined, undefined);
  });

  it("makes no request with no people and still points at the first steps", async () => {
    renderWithPerson(<DashboardScreen />, { people: [], personId: null });

    expect(await screen.findByRole("link", { name: /Getting Started/ })).toHaveAttribute(
      "href",
      "/getting-started"
    );
    expect(api.listApplications).not.toHaveBeenCalled();
  });

  it("makes no request and shows no first steps while the people list is loading", () => {
    // Jordan is in the list, but the provider has not settled: no person yet.
    renderWithPerson(<DashboardScreen />, { people: [JORDAN], loading: true });

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /create your Master Profile/ })
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Getting Started/ })).not.toBeInTheDocument();
    expect(api.listApplications).not.toHaveBeenCalled();
  });

  it("shows why there is nothing to list when the people list failed to load", () => {
    renderWithPerson(<DashboardScreen />, {
      people: [],
      personId: null,
      overrides: { error: "API 500: boom" },
    });

    expect(screen.getByText("API 500: boom")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /create your Master Profile/ })
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/No applications yet/)).not.toBeInTheDocument();
    expect(api.listApplications).not.toHaveBeenCalled();
  });

  it("clears the previous person's rows the moment the person changes", async () => {
    vi.mocked(api.listApplications).mockImplementation((profileId) =>
      profileId === 1
        ? Promise.resolve([JORDAN_ROW])
        : new Promise<ApplicationSummary[]>(() => {}) // Sam's list never arrives
    );
    const { switchTo } = renderWithPerson(<DashboardScreen />, { people: [JORDAN, SAM] });
    expect(await screen.findByText("JordanCo")).toBeInTheDocument();

    act(() => switchTo(2));

    // Not after a fetch: straight away, while Sam's list is still pending.
    expect(screen.queryByText("JordanCo")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/stage for row 1/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/select row 1/i)).not.toBeInTheDocument();
    expect(api.listApplications).toHaveBeenLastCalledWith(2, undefined);
  });

  it("ignores a response for the previous person that arrives after a switch", async () => {
    let resolveJordan!: (rows: ApplicationSummary[]) => void;
    vi.mocked(api.listApplications).mockImplementation((profileId) =>
      profileId === 1
        ? new Promise<ApplicationSummary[]>((resolve) => {
            resolveJordan = resolve;
          })
        : Promise.resolve([SAM_ROW])
    );
    const { switchTo } = renderWithPerson(<DashboardScreen />, { people: [JORDAN, SAM] });
    expect(api.listApplications).toHaveBeenCalledWith(1, undefined);

    act(() => switchTo(2));
    expect(await screen.findByText("SamCo")).toBeInTheDocument();

    await act(async () => {
      resolveJordan([JORDAN_ROW]);
    });

    expect(screen.queryByText("JordanCo")).not.toBeInTheDocument();
    expect(screen.getByText("SamCo")).toBeInTheDocument();
  });

  it("closes an open delete confirmation when the person changes", async () => {
    vi.mocked(api.listApplications).mockImplementation((profileId) =>
      Promise.resolve(profileId === 1 ? [JORDAN_ROW] : [])
    );
    const { switchTo } = renderWithPerson(<DashboardScreen />, { people: [JORDAN, SAM] });
    fireEvent.click(await screen.findByLabelText(/select row 1/i));
    fireEvent.click(screen.getByRole("button", { name: /delete permanently/i }));
    expect(screen.getByRole("dialog")).toHaveTextContent("JordanCo");

    act(() => switchTo(2));

    // The dialog listed Jordan's row and its button would still delete it.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.deleteApplication).not.toHaveBeenCalled();
  });

  it("drops an action's error when the action settles after a switch", async () => {
    vi.mocked(api.listApplications).mockImplementation((profileId) =>
      Promise.resolve(profileId === 1 ? [JORDAN_ROW] : [SAM_ROW])
    );
    let rejectPatch!: (reason: Error) => void;
    vi.mocked(api.patchApplication).mockReturnValueOnce(
      new Promise<ApplicationDetail>((_resolve, reject) => {
        rejectPatch = reject;
      })
    );
    const { switchTo } = renderWithPerson(<DashboardScreen />, { people: [JORDAN, SAM] });
    fireEvent.change(await screen.findByLabelText(/stage for row 1/i), {
      target: { value: "applied" },
    });
    expect(api.patchApplication).toHaveBeenCalledWith(10, { stage: "applied" });

    act(() => switchTo(2));
    expect(await screen.findByText("SamCo")).toBeInTheDocument();

    await act(async () => {
      rejectPatch(new Error("API 409: busy"));
    });

    // Jordan's failure is not reported on Sam's dashboard.
    expect(screen.queryByText(/API 409: busy/)).not.toBeInTheDocument();
    expect(screen.getByText("SamCo")).toBeInTheDocument();
  });
});
