import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import GettingStartedScreen from "./GettingStartedScreen";
import * as api from "../api";

vi.mock("../api", () => ({
  getSettings: vi.fn(),
  listProfiles: vi.fn(),
}));
vi.mock("../components/McpSetup", () => ({ default: () => <div>MCP setup block</div> }));

const contact = { name: "", email: "", phone: null, location: null, links: [] };

function renderScreen() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <GettingStartedScreen />
    </MemoryRouter>
  );
}

describe("GettingStartedScreen", () => {
  it("shows the ready confirmation when a profile exists and the API key is set", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listProfiles).mockResolvedValue([
      { id: 1, name: "Me", contact, has_master_profile: true },
    ]);
    renderScreen();
    expect(
      await screen.findByText("You're ready to tailor your first job")
    ).toBeInTheDocument();
  });

  it("prompts to create a profile and shows 'not set' when nothing is configured", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: false,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listProfiles).mockResolvedValue([]);
    renderScreen();
    expect(await screen.findByText("Create your profile →")).toBeInTheDocument();
    expect(screen.getByText("not set")).toBeInTheDocument();
    expect(
      screen.queryByText("You're ready to tailor your first job")
    ).not.toBeInTheDocument();
  });
});
