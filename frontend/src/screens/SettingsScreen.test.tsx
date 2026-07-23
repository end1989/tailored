import { render, screen } from "@testing-library/react";
import SettingsScreen from "./SettingsScreen";
import * as api from "../api";

vi.mock("../api", () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
}));

describe("SettingsScreen", () => {
  it("renders the 'not set' warning pill and note when no API key is configured", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: false,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    render(<SettingsScreen />);
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
    render(<SettingsScreen />);
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
    render(<SettingsScreen />);
    expect(await screen.findByText("How generation works")).toBeInTheDocument();
    expect(screen.getByText("Web app (this browser)")).toBeInTheDocument();
    expect(screen.getByText("Your own AI agent (MCP)")).toBeInTheDocument();
  });
});
