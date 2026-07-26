import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AddJobsScreen from "./AddJobsScreen";
import * as api from "../api";

const contact = { name: "Jordan Rivera", email: "e@example.com", phone: null, location: null, links: [] };

vi.mock("../api", () => ({
  listProfiles: vi.fn(),
  getSettings: vi.fn(),
  createApplications: vi.fn(),
}));

function renderScreen() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AddJobsScreen />
    </MemoryRouter>
  );
}

describe("AddJobsScreen", () => {
  beforeEach(() => {
    vi.mocked(api.listProfiles).mockResolvedValue([
      { id: 1, name: "Jordan Rivera", contact, has_master_profile: true },
    ]);
    vi.mocked(api.createApplications).mockResolvedValue([]);
  });

  it("parses three URL lines into three preview rows", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    renderScreen();
    await screen.findByRole("option", { name: "Jordan Rivera" });
    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1\nhttps://b.example/j2\n\nhttps://c.example/j3\n" },
    });
    expect(screen.getAllByTestId("job-row")).toHaveLength(3);
    expect(screen.getByText("3 jobs to queue")).toBeInTheDocument();
  });

  it("shows a warning when no API key is set and demo mode is off", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: false,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    renderScreen();
    expect(await screen.findByText(/No API key set/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/Generated with your Anthropic API key/i)
    ).not.toBeInTheDocument();
  });

  it("shows the plain mode note (no warning) when an API key is set", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    renderScreen();
    expect(
      await screen.findByText(/Generated with your Anthropic API key/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/No API key set/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /See MCP mode/ })).toHaveAttribute(
      "href",
      "/getting-started"
    );
  });
});
