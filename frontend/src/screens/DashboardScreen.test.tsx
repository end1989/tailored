import { render, screen } from "@testing-library/react";
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

describe("DashboardScreen", () => {
  it("renders one row per application with per-status badges", async () => {
    render(
      <MemoryRouter>
        <DashboardScreen />
      </MemoryRouter>
    );
    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("Globex")).toBeInTheDocument();
    expect(screen.getByText("ready")).toHaveClass("badge", "badge-ready");
    expect(screen.getByText("tailoring")).toHaveClass("badge", "badge-tailoring");
    expect(screen.getByText("$0.4321")).toBeInTheDocument();
    expect(screen.getAllByText("Open")).toHaveLength(2);
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
});
