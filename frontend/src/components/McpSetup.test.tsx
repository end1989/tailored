import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import McpSetup from "./McpSetup";
import * as api from "../api";
import { makePerson, renderWithPerson } from "../test-utils";

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

const GUIDE = "Read Tailored's workflow guide (the get_workflow_guide tool), then ";
const URL_LIST = "<paste your job URLs, one per line>";

// The <pre> under a field label is exactly what its Copy button copies.
function promptUnder(label: string): string | null {
  const field = screen.getByText(label).closest(".field");
  return field?.querySelector("pre")?.textContent ?? null;
}

function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

describe("McpSetup", () => {
  beforeEach(() => {
    vi.mocked(api.getSetup).mockResolvedValue(SETUP);
  });

  it("renders the auto-filled mcp command from the backend", async () => {
    renderWithPerson(<McpSetup />);
    expect(await screen.findByText(SETUP.mcp_command)).toBeInTheDocument();
    expect(screen.queryByText(/couldn't find it/i)).not.toBeInTheDocument();
  });

  it("falls back to a manual template when setup detection fails", async () => {
    vi.mocked(api.getSetup).mockRejectedValue(new Error("boom"));
    renderWithPerson(<McpSetup />);
    expect(
      await screen.findByText(/Couldn't detect your paths automatically/)
    ).toBeInTheDocument();
    expect(screen.getByText(/backend\/mcp_server\.py/)).toBeInTheDocument();
  });

  it("warns when the MCP server file is missing", async () => {
    vi.mocked(api.getSetup).mockResolvedValue({ ...SETUP, mcp_server_exists: false });
    renderWithPerson(<McpSetup />);
    expect(await screen.findByText(/couldn't find it/i)).toBeInTheDocument();
  });

  it("shows the batch queue prompt with a copy button", async () => {
    renderWithPerson(<McpSetup />);
    expect(
      await screen.findByText(/queue these jobs for Jordan Rivera \(profile_id 1\)/i)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy batch prompt/i })).toBeInTheDocument();
  });

  it("names the current person and their profile_id in both prompts", async () => {
    renderWithPerson(<McpSetup />, { people: [makePerson({ id: 3, name: "Sam Lee" })] });
    await screen.findByText(SETUP.mcp_command);
    expect(promptUnder("2. Ask your agent")).toBe(
      `${GUIDE}tailor a resume and cover letter for Sam Lee (profile_id 3) from <job url>.`
    );
    expect(promptUnder("Or hand it a whole list")).toBe(
      `${GUIDE}queue these jobs for Sam Lee (profile_id 3) and work through them one at a time:\n${URL_LIST}`
    );
    expect(screen.queryByText(/my profile/)).not.toBeInTheDocument();
  });

  it("copies the prompt that names the person", async () => {
    const writeText = stubClipboard();
    renderWithPerson(<McpSetup />, { people: [makePerson({ id: 3, name: "Sam Lee" })] });
    await screen.findByText(SETUP.mcp_command);
    fireEvent.click(screen.getByRole("button", { name: "Copy prompt" }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        `${GUIDE}tailor a resume and cover letter for Sam Lee (profile_id 3) from <job url>.`
      )
    );
  });

  it("uses the person's name, not a label disambiguated for the picker", async () => {
    renderWithPerson(<McpSetup />, {
      people: [makePerson({ id: 3, name: "Sam Lee" })],
      overrides: { labelFor: (p) => `${p.name} #${p.id}` },
    });
    await screen.findByText(SETUP.mcp_command);
    expect(promptUnder("2. Ask your agent")).toContain("for Sam Lee (profile_id 3) from");
  });

  it("follows the picker when the person changes", async () => {
    const { switchTo } = renderWithPerson(<McpSetup />, {
      people: [makePerson({ id: 1, name: "Jordan Rivera" }), makePerson({ id: 2, name: "Sam Lee" })],
    });
    await screen.findByText(SETUP.mcp_command);
    expect(promptUnder("2. Ask your agent")).toContain("for Jordan Rivera (profile_id 1)");
    act(() => {
      switchTo(2);
    });
    expect(promptUnder("2. Ask your agent")).toContain("for Sam Lee (profile_id 2)");
    expect(promptUnder("Or hand it a whole list")).toContain("for Sam Lee (profile_id 2)");
    expect(screen.queryByText(/Jordan Rivera/)).not.toBeInTheDocument();
  });

  it("keeps the 'my profile' prompts when there are no people", async () => {
    renderWithPerson(<McpSetup />, { people: [], personId: null });
    await screen.findByText(SETUP.mcp_command);
    expect(promptUnder("2. Ask your agent")).toBe(`${GUIDE}tailor my profile for <job url>.`);
    expect(promptUnder("Or hand it a whole list")).toBe(
      `${GUIDE}queue these jobs for my profile and work through them one at a time:\n${URL_LIST}`
    );
  });

  it("shows no prompt while the person list is still loading", async () => {
    renderWithPerson(<McpSetup />, { people: [], personId: null, loading: true });
    // The register command does not depend on the person, so it still shows.
    expect(await screen.findByText(SETUP.mcp_command)).toBeInTheDocument();
    expect(screen.queryByText("2. Ask your agent")).not.toBeInTheDocument();
    expect(screen.queryByText("Or hand it a whole list")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy prompt" })).not.toBeInTheDocument();
  });
});
