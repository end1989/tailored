import { render, screen } from "@testing-library/react";
import McpSetup from "./McpSetup";
import * as api from "../api";

vi.mock("../api", () => ({ getSetup: vi.fn() }));

const SETUP = {
  platform: "windows" as const,
  python_path: "C:\\proj\\.venv\\Scripts\\python.exe",
  mcp_server_path: "C:\\proj\\backend\\mcp_server.py",
  mcp_server_exists: true,
  mcp_command:
    'claude mcp add tailored -- "C:\\proj\\.venv\\Scripts\\python.exe" "C:\\proj\\backend\\mcp_server.py"',
  env_line: "ANTHROPIC_API_KEY=sk-ant-...",
  workflow_guide_tool: "get_workflow_guide",
};

describe("McpSetup", () => {
  it("renders the auto-filled mcp command from the backend", async () => {
    vi.mocked(api.getSetup).mockResolvedValue(SETUP);
    render(<McpSetup />);
    expect(await screen.findByText(SETUP.mcp_command)).toBeInTheDocument();
  });

  it("falls back to a manual template when setup detection fails", async () => {
    vi.mocked(api.getSetup).mockRejectedValue(new Error("boom"));
    render(<McpSetup />);
    expect(
      await screen.findByText(/Couldn't detect your paths automatically/)
    ).toBeInTheDocument();
    expect(screen.getByText(/backend\/mcp_server\.py/)).toBeInTheDocument();
  });

  it("warns when the MCP server file is missing", async () => {
    vi.mocked(api.getSetup).mockResolvedValue({ ...SETUP, mcp_server_exists: false });
    render(<McpSetup />);
    expect(await screen.findByText(/couldn't find it/i)).toBeInTheDocument();
  });
});
