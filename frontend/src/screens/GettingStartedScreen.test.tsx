import { act, screen } from "@testing-library/react";
import GettingStartedScreen from "./GettingStartedScreen";
import * as api from "../api";
import type { SettingsShape } from "../types";
import { makePerson, renderWithPerson } from "../test-utils";
import type { PersonTestOptions } from "../test-utils";

vi.mock("../api", () => ({
  getSettings: vi.fn(),
  listProfiles: vi.fn(),
}));
vi.mock("../components/McpSetup", () => ({ default: () => <div>MCP setup block</div> }));

function settings(over: Partial<SettingsShape> = {}): SettingsShape {
  return {
    api_key_set: true,
    fake_mode: false,
    default_template: "slate",
    default_depth: "standard",
    page_size: "Letter",
    ...over,
  };
}

function renderScreen(opts?: PersonTestOptions) {
  return renderWithPerson(<GettingStartedScreen />, opts);
}

describe("GettingStartedScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the ready confirmation when a profile exists and the API key is set", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    renderScreen();
    expect(
      await screen.findByText("You're ready to tailor your first job")
    ).toBeInTheDocument();
  });

  it("prompts to create a profile and shows 'not set' when nothing is configured", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: false }));
    renderScreen({ people: [], personId: null });
    expect(await screen.findByText("Create your profile →")).toBeInTheDocument();
    expect(screen.getByText("not set")).toBeInTheDocument();
    expect(
      screen.queryByText("You're ready to tailor your first job")
    ).not.toBeInTheDocument();
  });

  it("treats demo mode with a profile as ready", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(
      settings({ api_key_set: false, fake_mode: true })
    );
    renderScreen();
    expect(
      await screen.findByText("You're ready to tailor your first job")
    ).toBeInTheDocument();
    expect(screen.getByText("Demo mode on")).toBeInTheDocument();
  });

  it("deep-links the walkthrough steps to the matching screens", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
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
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: false }));
    renderScreen({ people: [], personId: null });
    const link = await screen.findByRole("link", { name: /anthropic console/i });
    expect(link).toHaveAttribute("href", "https://console.anthropic.com/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("shows a neutral placeholder instead of a verdict while the requests are in flight", () => {
    vi.mocked(api.getSettings).mockReturnValue(new Promise<SettingsShape>(() => {}));
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
    renderScreen({ people: [], personId: null });
    expect(await screen.findByText(/Couldn't check your setup/)).toBeInTheDocument();
    expect(screen.queryByText("not set")).not.toBeInTheDocument();
    expect(screen.queryByText("empty")).not.toBeInTheDocument();
    expect(screen.queryByText("Create your profile →")).not.toBeInTheDocument();
    expect(
      screen.queryByText("You're ready to tailor your first job")
    ).not.toBeInTheDocument();
  });

  it("reads the person list from the picker, never from listProfiles", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen();
    await screen.findByText("You're ready to tailor your first job");
    expect(api.listProfiles).not.toHaveBeenCalled();
  });

  it("judges the current person's profile, not whether anyone has one", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    renderScreen({
      people: [
        makePerson({ id: 1, name: "Jordan Rivera", has_master_profile: true }),
        makePerson({ id: 2, name: "Sam Lee", has_master_profile: false }),
      ],
      personId: 2,
    });
    expect(await screen.findByText("Master Profile for Sam Lee:")).toBeInTheDocument();
    expect(screen.getByText("empty")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create your profile →" })).toHaveAttribute(
      "href",
      "/profiles"
    );
    expect(
      screen.queryByText("You're ready to tailor your first job")
    ).not.toBeInTheDocument();
  });

  it("changes its verdict when the picker switches person", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    const { switchTo } = renderScreen({
      people: [
        makePerson({ id: 1, name: "Jordan Rivera", has_master_profile: true }),
        makePerson({ id: 2, name: "Sam Lee", has_master_profile: false }),
      ],
      personId: 2,
    });
    await screen.findByText("empty");
    act(() => {
      switchTo(1);
    });
    expect(screen.getByText("Master Profile for Jordan Rivera:")).toBeInTheDocument();
    expect(screen.getByText("created")).toBeInTheDocument();
    expect(screen.getByText("You're ready to tailor your first job")).toBeInTheDocument();
    // The app-wide API key status does not depend on the person: one request only.
    expect(api.getSettings).toHaveBeenCalledTimes(1);
  });

  it("names the person with the picker's label", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({
      people: [makePerson({ id: 4, name: "Sam Lee" })],
      overrides: { labelFor: (p) => `${p.name} #${p.id}` },
    });
    expect(await screen.findByText("Master Profile for Sam Lee #4:")).toBeInTheDocument();
  });

  it("gives no verdict while the person list is still loading", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    renderScreen({ people: [], personId: null, loading: true });
    // Let the resolved settings request land; the verdict must still wait.
    await act(async () => {
      await Promise.resolve();
    });
    expect(api.getSettings).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Checking…")).toBeInTheDocument();
    expect(screen.queryByText("empty")).not.toBeInTheDocument();
    expect(screen.queryByText("Create your profile →")).not.toBeInTheDocument();
  });

  it("surfaces a failed person list instead of calling the profile empty", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    renderScreen({
      people: [],
      personId: null,
      overrides: { error: "API 500: Internal Server Error" },
    });
    expect(
      await screen.findByText(/Couldn't check your setup.*API 500: Internal Server Error/)
    ).toBeInTheDocument();
    expect(screen.queryByText("empty")).not.toBeInTheDocument();
    expect(screen.queryByText("Create your profile →")).not.toBeInTheDocument();
  });
});
