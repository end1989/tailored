import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TemplatesScreen from "./TemplatesScreen";
import * as api from "../api";

vi.mock("../api", () => ({
  listTemplates: vi.fn(),
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  templatePreviewUrl: (name: string) => `/api/templates/preview/${name}`,
}));

const TEMPLATES = [
  {
    name: "meridian",
    label: "Meridian",
    description: "Classic serif with small caps and hairline rules - understated and traditional.",
    best_for: "Corporate, finance, healthcare, government",
  },
  {
    name: "slate",
    label: "Slate",
    description: "Clean contemporary sans-serif with strong hierarchy - the default.",
    best_for: "General purpose - safe everywhere",
  },
  {
    name: "terminal",
    label: "Terminal",
    description: "Technical layout with monospace accents and projects placed forward.",
    best_for: "Engineering, data, technical roles",
  },
  {
    name: "signal",
    label: "Signal",
    description: "Bold headline treatment with a single warm accent color.",
    best_for: "Design, marketing, creative roles",
  },
] as const;

function renderScreen() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <TemplatesScreen />
    </MemoryRouter>
  );
}

describe("TemplatesScreen", () => {
  beforeEach(() => {
    vi.mocked(api.listTemplates).mockResolvedValue([...TEMPLATES]);
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    });
    vi.mocked(api.updateSettings).mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "meridian",
      default_depth: "standard",
      page_size: "Letter",
    });
  });

  it("renders four cards and exactly one Default pill", async () => {
    renderScreen();
    expect(await screen.findByText("Meridian")).toBeInTheDocument();
    expect(screen.getByText("Slate")).toBeInTheDocument();
    expect(screen.getByText("Terminal")).toBeInTheDocument();
    expect(screen.getByText("Signal")).toBeInTheDocument();
    expect(screen.getAllByText("Default")).toHaveLength(1);
  });

  it("clicking Set as default on another card calls updateSettings with that name", async () => {
    renderScreen();
    await screen.findByText("Meridian");
    fireEvent.click(screen.getAllByText("Set as default")[0]);
    expect(api.updateSettings).toHaveBeenCalledWith({ default_template: "meridian" });
  });
});
