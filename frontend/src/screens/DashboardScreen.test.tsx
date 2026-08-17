import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import DashboardScreen from "./DashboardScreen";
import * as api from "../api";

vi.mock("../api", () => {
  const contact = { name: "Jordan Rivera", email: "e@example.com", phone: null, location: null, links: [] };
  return {
    listProfiles: vi.fn().mockResolvedValue([
      { id: 1, name: "Jordan Rivera", contact, has_master_profile: true },
    ]),
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

/**
 * Renders on the All tab, where every fixture row is visible whatever its
 * stage. The screen opens on "To apply", which deliberately hides anything
 * already sent -- so tests about badges, stage editing, deletion, and refetch
 * say "All" explicitly rather than depending on the default.
 */
async function renderOnAllTab() {
  render(<MemoryRouter><DashboardScreen /></MemoryRouter>);
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
    render(<MemoryRouter><DashboardScreen /></MemoryRouter>);

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
    render(<MemoryRouter><DashboardScreen /></MemoryRouter>);

    expect(await screen.findByRole("button", { name: /to apply 1/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /applied 2/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /closed 1/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /all 4/i })).toBeInTheDocument();
  });

  it("shows Getting Started and profile links in the empty state", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([]);
    render(
      <MemoryRouter>
        <DashboardScreen />
      </MemoryRouter>
    );
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

    render(<MemoryRouter><DashboardScreen /></MemoryRouter>);
    await vi.advanceTimersByTimeAsync(0);
    const callsAfterFirstTick = vi.mocked(api.listApplications).mock.calls.length;

    await vi.advanceTimersByTimeAsync(10_000);

    expect(vi.mocked(api.listApplications).mock.calls.length).toBe(callsAfterFirstTick);
    vi.useRealTimers();
  });

  it("filters to archived applications when the tab is selected", async () => {
    vi.mocked(api.listApplications).mockResolvedValue([{ ...BASE_APP, id: 1 }]);
    render(<MemoryRouter><DashboardScreen /></MemoryRouter>);

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
    // only appear if a refetch happened following the failed action. Counting
    // listApplications calls does NOT work here -- profileId resolving async
    // triggers its own refetch, so the count rises with or without the fix.
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
