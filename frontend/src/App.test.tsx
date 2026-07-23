import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

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

describe("App shell", () => {
  it("renders the brand and all nav links", () => {
    render(
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText("Tailored")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Add Jobs" })).toHaveAttribute("href", "/add");
    expect(screen.getByRole("link", { name: "Profiles" })).toHaveAttribute("href", "/profiles");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });

  it("renders the real Dashboard screen on /", async () => {
    render(
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <App />
      </MemoryRouter>
    );
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });
});
