import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import GettingStartedScreen from "./GettingStartedScreen";
import * as api from "../api";
import type { ProfileSummary, SettingsShape } from "../types";

vi.mock("../api", () => ({
  getSettings: vi.fn(),
  listProfiles: vi.fn(),
}));
vi.mock("../components/McpSetup", () => ({ default: () => <div>MCP setup block</div> }));

const contact = { name: "", email: "", phone: null, location: null, links: [] };

function renderScreen() {
  return render(
    <MemoryRouter>
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

  it("treats demo mode with a profile as ready", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: false,
      fake_mode: true,
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
    expect(screen.getByText("Demo mode on")).toBeInTheDocument();
  });

  it("deep-links the walkthrough steps to the matching screens", async () => {
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
    await screen.findByText("You're ready to tailor your first job");
    expect(screen.getByRole("link", { name: "Master Profile" })).toHaveAttribute(
      "href",
      "/profiles"
    );
    expect(screen.getByRole("link", { name: "Add job URLs" })).toHaveAttribute("href", "/add");
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "templates" })).toHaveAttribute("href", "/templates");
  });

  it("points users without an Anthropic account at the console", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: false,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listProfiles).mockResolvedValue([]);
    renderScreen();
    const link = await screen.findByRole("link", { name: /anthropic console/i });
    expect(link).toHaveAttribute("href", "https://console.anthropic.com/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("shows a neutral placeholder instead of a verdict while the requests are in flight", () => {
    vi.mocked(api.getSettings).mockReturnValue(new Promise<SettingsShape>(() => {}));
    vi.mocked(api.listProfiles).mockReturnValue(new Promise<ProfileSummary[]>(() => {}));
    renderScreen();
    expect(screen.getByText("Checking…")).toBeInTheDocument();
    expect(screen.queryByText("not set")).not.toBeInTheDocument();
    expect(screen.queryByText("empty")).not.toBeInTheDocument();
    expect(screen.queryByText("Create your profile →")).not.toBeInTheDocument();
    expect(
      screen.queryByText("You're ready to tailor your first job")
    ).not.toBeInTheDocument();
  });

  it("surfaces an error instead of a false verdict when a setup request fails", async () => {
    vi.mocked(api.getSettings).mockRejectedValue(new Error("network down"));
    vi.mocked(api.listProfiles).mockResolvedValue([]);
    renderScreen();
    expect(await screen.findByText(/Couldn't check your setup/)).toBeInTheDocument();
    expect(screen.queryByText("not set")).not.toBeInTheDocument();
    expect(screen.queryByText("empty")).not.toBeInTheDocument();
    expect(screen.queryByText("Create your profile →")).not.toBeInTheDocument();
    expect(
      screen.queryByText("You're ready to tailor your first job")
    ).not.toBeInTheDocument();
  });
});
