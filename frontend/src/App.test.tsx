import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import * as api from "./api";
import { PersonProvider } from "./person";

vi.mock("./api", () => ({
  listProfiles: vi.fn().mockResolvedValue([]),
  listApplications: vi.fn().mockResolvedValue([]),
  getSettings: vi.fn().mockResolvedValue({
    api_key_set: false,
    fake_mode: true,
    default_template: "slate",
    default_depth: "standard",
    page_size: "Letter",
  }),
  createProfile: vi.fn(),
  getProfile: vi.fn(),
  updateProfile: vi.fn(),
  uploadDocument: vi.fn(),
  buildProfile: vi.fn(),
  createApplications: vi.fn(),
  getApplication: vi.fn(),
  pasteJobText: vi.fn(),
  updateContent: vi.fn(),
  regenerate: vi.fn(),
  updateSettings: vi.fn(),
  previewUrl: (id: number) => `/api/applications/${id}/preview`,
  exportUrl: (id: number, kind: string) => `/api/applications/${id}/exports/${kind}`,
}));

function renderApp(route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <PersonProvider>
        <App />
      </PersonProvider>
    </MemoryRouter>
  );
}

describe("App shell", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(api.listProfiles).mockResolvedValue([]);
  });

  it("renders the brand and all nav links", () => {
    renderApp();
    expect(screen.getByText("Tailored")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    const nav = screen.getByRole("navigation");
    expect(within(nav).getByRole("link", { name: "Getting Started" })).toHaveAttribute(
      "href",
      "/getting-started"
    );
    expect(screen.getByRole("link", { name: "Add Jobs" })).toHaveAttribute("href", "/add");
    expect(screen.getByRole("link", { name: "Templates" })).toHaveAttribute("href", "/templates");
    expect(screen.getByRole("link", { name: "Profiles" })).toHaveAttribute("href", "/profiles");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");

    const themeToggle = screen.getByRole("button", { name: /switch to (light|dark) theme/i });
    expect(themeToggle).toBeInTheDocument();
    expect(themeToggle).toHaveAttribute("aria-label");
  });

  it("renders the real Dashboard screen on /", async () => {
    renderApp();
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("puts the person picker in the nav, just before the theme toggle", async () => {
    vi.mocked(api.listProfiles).mockResolvedValue([
      {
        id: 1,
        name: "Jordan Rivera",
        contact: { name: "Jordan Rivera", email: "jordan@example.com", links: [] },
        has_master_profile: true,
        created_at: "2026-01-01T00:00:00+00:00",
        inbox_url: null,
      },
    ]);
    renderApp();
    const nav = screen.getByRole("navigation");
    const picker = await within(nav).findByRole("combobox", { name: "Person" });
    expect(picker).toHaveValue("1");
    const toggle = within(nav).getByRole("button", { name: /switch to (light|dark) theme/i });
    expect(picker.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(picker.closest(".nav-end")).toBe(toggle.closest(".nav-end"));
  });

  it("offers Add a person in the nav when there are no people", async () => {
    renderApp();
    const nav = screen.getByRole("navigation");
    expect(await within(nav).findByRole("link", { name: "Add a person" })).toHaveAttribute(
      "href",
      "/profiles?new=1"
    );
    expect(within(nav).queryByRole("combobox", { name: "Person" })).not.toBeInTheDocument();
  });
});
