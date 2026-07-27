import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import SettingsScreen from "./SettingsScreen";
import * as api from "../api";

vi.mock("../api", () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  listTemplates: vi.fn(),
}));

vi.mock("../components/McpSetup", () => ({ default: () => <div>MCP setup block</div> }));

function renderScreen() {
  return render(
    <MemoryRouter>
      <SettingsScreen />
    </MemoryRouter>
  );
}

describe("SettingsScreen", () => {
  beforeEach(() => {
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
