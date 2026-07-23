import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import DashboardScreen from "./DashboardScreen";

vi.mock("../api", () => {
  const contact = { name: "Eldon", email: "e@example.com", phone: null, location: null, links: [] };
  return {
    listProfiles: vi.fn().mockResolvedValue([
      { id: 1, name: "Eldon", contact, has_master_profile: true },
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
      },
    ]),
  };
});

describe("DashboardScreen", () => {
  it("renders one row per application with per-status badges", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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
});
