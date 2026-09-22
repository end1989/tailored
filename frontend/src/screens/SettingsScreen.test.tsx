import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import SettingsScreen from "./SettingsScreen";
import * as api from "../api";
import type { SettingsShape } from "../types";
import { deferred, makePerson, renderWithPerson } from "../test-utils";
import type { PersonTestOptions } from "../test-utils";

vi.mock("../api", () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  listTemplates: vi.fn(),
}));

vi.mock("../components/McpSetup", () => ({ default: () => <div>MCP setup block</div> }));

function renderScreen(opts?: PersonTestOptions) {
  return renderWithPerson(<SettingsScreen />, opts);
}

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

const JORDAN = makePerson({ id: 1, name: "Jordan Rivera" });
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
});

describe("SettingsScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "slate", label: "Slate", description: "d", best_for: "b" },
    ]);
  });

  it("renders the 'not set' warning pill and note when no API key is configured", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: false,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    renderScreen();
    expect(await screen.findByText("API key: not set")).toBeInTheDocument();
    expect(
      screen.getByText(/Add ANTHROPIC_API_KEY to the .env file and restart/)
    ).toBeInTheDocument();
    expect(screen.queryByText("API key: set")).not.toBeInTheDocument();
  });

  it("renders the 'set' pill with no not-set warning when an API key is configured", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    renderScreen();
    expect(await screen.findByText("API key: set")).toBeInTheDocument();
    expect(screen.queryByText("API key: not set")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Add ANTHROPIC_API_KEY to the .env file and restart to generate/)
    ).not.toBeInTheDocument();
  });

  it("shows the 'How generation works' section with both web-app and MCP blocks", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    renderScreen();
    expect(await screen.findByText("How generation works")).toBeInTheDocument();
    expect(screen.getByText("Web app (this browser)")).toBeInTheDocument();
    expect(screen.getByText("Your own AI agent (MCP)")).toBeInTheDocument();
  });

  it("embeds the MCP setup block in the generation section", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    renderScreen();
    expect(await screen.findByText("MCP setup block")).toBeInTheDocument();
  });

  it("renders template options from the API, not a hardcoded list", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "meridian",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
      { name: "plainwork", label: "Plainwork", description: "d", best_for: "b" },
    ]);
    renderScreen();
    const select = await screen.findByLabelText(/default template/i);
    expect(within(select).getByRole("option", { name: "Ledger" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "Plainwork" })).toBeInTheDocument();
  });

  it("shows template labels rather than raw ids", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "meridian",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
    ]);
    renderScreen();
    const select = await screen.findByLabelText(/default template/i);
    expect(within(select).getByRole("option", { name: "Meridian" })).toBeInTheDocument();
    expect(within(select).queryByRole("option", { name: "meridian" })).toBeNull();
  });

  // The label is display, the name is the contract the backend validates against
  // (api/settings.py rejects anything not in the registry). Options that render the
  // label but carry the label as their value would look right and write garbage.
  it("carries the template id as the option value while showing the label", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "meridian",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
    ]);
    renderScreen();
    const select = (await screen.findByLabelText(/default template/i)) as HTMLSelectElement;
    const ledger = within(select).getByRole("option", { name: "Ledger" }) as HTMLOptionElement;
    expect(ledger.value).toBe("ledger");
    // the saved id must resolve to a real option, or the select shows the wrong entry
    expect(select.value).toBe("meridian");
  });

  it("saves the selected template id, not its label", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "meridian",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.updateSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "ledger",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
    ]);
    renderScreen();
    const select = await screen.findByLabelText(/default template/i);
    fireEvent.change(select, { target: { value: "ledger" } });

    await waitFor(() => {
      const calls = vi.mocked(api.updateSettings).mock.calls;
      expect(calls[calls.length - 1]?.[0]).toEqual({ default_template: "ledger" });
    });
  });
});

describe("SettingsScreen per person", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "slate", label: "Slate", description: "d", best_for: "b" },
    ]);
  });

  it("reads and writes the current person's settings under their name", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ page_size: "A4" }));
    vi.mocked(api.updateSettings).mockResolvedValue(settings({ page_size: "Letter" }));
    renderScreen({ people: [SAM] });

    expect(await screen.findByRole("heading", { name: "Settings for Sam Lee" })).toBeInTheDocument();
    expect(api.getSettings).toHaveBeenCalledWith(2);
    const pageSize = screen.getByLabelText("Page size") as HTMLSelectElement;
    expect(pageSize.value).toBe("A4");

    fireEvent.change(pageSize, { target: { value: "Letter" } });
    await waitFor(() =>
      expect(api.updateSettings).toHaveBeenCalledWith({ page_size: "Letter" }, 2)
    );
    await waitFor(() => expect(pageSize.value).toBe("Letter"));
  });

  it("heads the section with the picker's label", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({
      people: [SAM],
      overrides: { labelFor: (p) => `${p.name} (${p.contact.email})` },
    });
    expect(
      await screen.findByRole("heading", { name: "Settings for Sam Lee (sam@example.com)" })
    ).toBeInTheDocument();
  });

  it("keeps the API key status and theme in an app-wide section", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ api_key_set: true }));
    renderScreen({ people: [JORDAN] });

    const mine = await screen.findByRole("region", { name: "Settings for Jordan Rivera" });
    const appWide = screen.getByRole("region", { name: "App-wide" });

    expect(within(mine).getByLabelText(/default template/i)).toBeInTheDocument();
    expect(within(mine).getByLabelText("Default research depth")).toBeInTheDocument();
    expect(within(mine).getByLabelText("Page size")).toBeInTheDocument();
    expect(within(mine).queryByText("API key set")).not.toBeInTheDocument();

    expect(within(appWide).getByText("API key set")).toBeInTheDocument();
    expect(within(appWide).getByLabelText("Theme")).toBeInTheDocument();
    expect(within(appWide).queryByLabelText(/default template/i)).not.toBeInTheDocument();
  });

  it("hides the previous person's values the moment the person changes", async () => {
    const forSam = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((id?: number) =>
      id === 1 ? Promise.resolve(settings({ page_size: "Letter" })) : forSam.promise
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });
    expect(await screen.findByRole("heading", { name: "Settings for Jordan Rivera" })).toBeInTheDocument();

    act(() => switchTo(2));
    expect(api.getSettings).toHaveBeenLastCalledWith(2);
    // Jordan's values must not sit under Sam's name while Sam's load.
    expect(screen.queryByLabelText("Page size")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Settings for Jordan Rivera" })).toBeNull();
    expect(screen.getByText("Loading...")).toBeInTheDocument();

    await act(async () => {
      forSam.resolve(settings({ page_size: "A4" }));
    });
    expect(screen.getByRole("heading", { name: "Settings for Sam Lee" })).toBeInTheDocument();
    expect((screen.getByLabelText("Page size") as HTMLSelectElement).value).toBe("A4");
  });

  it("ignores a late response for the previous person", async () => {
    const forJordan = deferred<SettingsShape>();
    const forSam = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((id?: number) =>
      id === 1 ? forJordan.promise : forSam.promise
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });

    act(() => switchTo(2));
    await act(async () => {
      forSam.resolve(settings({ page_size: "A4", default_depth: "deep" }));
    });
    expect(screen.getByRole("heading", { name: "Settings for Sam Lee" })).toBeInTheDocument();
    expect((screen.getByLabelText("Page size") as HTMLSelectElement).value).toBe("A4");

    // Jordan's request was still in flight; its answer must not land on Sam.
    await act(async () => {
      forJordan.resolve(settings({ page_size: "Letter", default_depth: "quick" }));
    });
    expect((screen.getByLabelText("Page size") as HTMLSelectElement).value).toBe("A4");
    expect((screen.getByLabelText("Default research depth") as HTMLSelectElement).value).toBe(
      "deep"
    );
    expect(screen.queryByRole("heading", { name: "Settings for Jordan Rivera" })).toBeNull();
  });

  it("does not show a save that returns after a switch on the new person", async () => {
    vi.mocked(api.getSettings).mockImplementation(async (id?: number) =>
      id === 1 ? settings({ page_size: "Letter" }) : settings({ page_size: "A4" })
    );
    const saving = deferred<SettingsShape>();
    vi.mocked(api.updateSettings).mockReturnValue(saving.promise);
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });

    const pageSize = await screen.findByLabelText("Page size");
    fireEvent.change(pageSize, { target: { value: "A4" } });
    expect(api.updateSettings).toHaveBeenCalledWith({ page_size: "A4" }, 1);

    act(() => switchTo(2));
    await screen.findByRole("heading", { name: "Settings for Sam Lee" });
    await act(async () => {
      saving.resolve(settings({ page_size: "A4", default_depth: "quick" }));
    });
    expect(screen.getByRole("heading", { name: "Settings for Sam Lee" })).toBeInTheDocument();
    expect((screen.getByLabelText("Default research depth") as HTMLSelectElement).value).toBe(
      "standard"
    );
  });

  it("edits the app-wide defaults when there are no people", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    vi.mocked(api.updateSettings).mockResolvedValue(settings({ default_depth: "deep" }));
    renderScreen({ people: [], personId: null });

    const depth = await screen.findByLabelText("Default research depth");
    expect(vi.mocked(api.getSettings).mock.calls[0][0]).toBeUndefined();
    expect(screen.queryByRole("heading", { name: /^Settings for/ })).not.toBeInTheDocument();
    // With no people the defaults are app-wide, so they sit in that section.
    expect(
      within(screen.getByRole("region", { name: "App-wide" })).getByLabelText(/default template/i)
    ).toBeInTheDocument();

    fireEvent.change(depth, { target: { value: "deep" } });
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1));
    const [patch, profileId] = vi.mocked(api.updateSettings).mock.calls[0];
    expect(patch).toEqual({ default_depth: "deep" });
    expect(profileId).toBeUndefined();
  });

  it("requests nothing while the person list is loading", () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({ people: [], personId: null, loading: true });
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(api.getSettings).not.toHaveBeenCalled();
  });

  it("shows a failed person list instead of the app-wide defaults", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({
      people: [],
      personId: null,
      overrides: { error: "API 500: Internal Server Error" },
    });
    expect(await screen.findByText("API 500: Internal Server Error")).toBeInTheDocument();
    expect(api.getSettings).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(/default template/i)).not.toBeInTheDocument();
  });
});
