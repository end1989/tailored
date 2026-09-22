import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import TemplatesScreen from "./TemplatesScreen";
import * as api from "../api";
import type { SettingsShape } from "../types";
import { deferred, makePerson, renderWithPerson } from "../test-utils";
import type { PersonTestOptions } from "../test-utils";

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

// The card whose title is this template's label.
function card(label: string): HTMLElement {
  return screen.getByText(label, { selector: ".card-title" }).closest(".template-card") as HTMLElement;
}

const JORDAN = makePerson({ id: 1, name: "Jordan Rivera" });
const SAM = makePerson({ id: 2, name: "Sam Lee" });

function renderScreen(opts?: PersonTestOptions) {
  return renderWithPerson(<TemplatesScreen />, opts);
}

describe("TemplatesScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    await waitFor(() => expect(screen.getAllByText("Default")).toHaveLength(1));
  });

  it("clicking Set as default on another card calls updateSettings with that name", async () => {
    renderScreen();
    await screen.findByText("Default");
    fireEvent.click(screen.getAllByText("Set as default")[0]);
    expect(api.updateSettings).toHaveBeenCalledWith({ default_template: "meridian" }, 1);
  });

  it("renders each preview as a true-page-width thumbnail with an open-full-size link", async () => {
    const { container } = renderScreen();
    await screen.findByText("Meridian");

    const thumbs = container.querySelectorAll(".preview-thumb");
    expect(thumbs).toHaveLength(4);

    const links = screen.getAllByRole("link", { name: /open full size/i });
    expect(links).toHaveLength(4);

    TEMPLATES.forEach((t, i) => {
      const iframe = screen.getByTitle(t.label) as HTMLIFrameElement;
      expect(iframe.closest(".preview-thumb")).not.toBeNull();
      expect(iframe.getAttribute("sandbox")).toBe("");
      expect(iframe.style.width).toBe("816px");
      expect(iframe.style.height).toBe("1056px");
      expect(iframe.style.position).toBe("absolute");

      expect(links[i]).toHaveAttribute("href", `/api/templates/preview/${t.name}`);
      expect(links[i]).toHaveAttribute("target", "_blank");
      expect(links[i]).toHaveAttribute("rel", "noreferrer");
    });
  });
});

describe("TemplatesScreen per person", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listTemplates).mockResolvedValue([...TEMPLATES]);
  });

  it("marks the current person's default and names them", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ default_template: "terminal" }));
    renderScreen({ people: [SAM] });

    expect(await screen.findByRole("heading", { name: "Settings for Sam Lee" })).toBeInTheDocument();
    expect(api.getSettings).toHaveBeenCalledWith(2);
    await waitFor(() => expect(within(card("Terminal")).getByText("Default")).toBeInTheDocument());
    expect(within(card("Slate")).queryByText("Default")).not.toBeInTheDocument();
  });

  it("heads the page's person section with the picker's label", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({ people: [SAM], overrides: { labelFor: (p) => `${p.name} #${p.id}` } });
    expect(await screen.findByRole("heading", { name: "Settings for Sam Lee #2" })).toBeInTheDocument();
  });

  it("sets the default for the person who was current at the click", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ default_template: "slate" }));
    vi.mocked(api.updateSettings).mockResolvedValue(settings({ default_template: "signal" }));
    renderScreen({ people: [SAM] });
    await waitFor(() => expect(within(card("Slate")).getByText("Default")).toBeInTheDocument());

    fireEvent.click(within(card("Signal")).getByRole("button", { name: "Set as default" }));
    expect(api.updateSettings).toHaveBeenCalledWith({ default_template: "signal" }, 2);
    await waitFor(() => expect(within(card("Signal")).getByText("Default")).toBeInTheDocument());
    expect(within(card("Slate")).queryByText("Default")).not.toBeInTheDocument();
  });

  it("drops the previous person's Default the moment the person changes", async () => {
    const forSam = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((id?: number) =>
      id === 1 ? Promise.resolve(settings({ default_template: "meridian" })) : forSam.promise
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });
    await waitFor(() => expect(within(card("Meridian")).getByText("Default")).toBeInTheDocument());

    act(() => switchTo(2));
    expect(screen.queryByText("Default")).not.toBeInTheDocument();
    // Until Sam's settings arrive, nothing can be written on Sam's behalf.
    for (const button of screen.getAllByRole("button", { name: "Set as default" })) {
      expect(button).toBeDisabled();
    }

    await act(async () => {
      forSam.resolve(settings({ default_template: "signal" }));
    });
    expect(within(card("Signal")).getByText("Default")).toBeInTheDocument();
    expect(screen.getAllByText("Default")).toHaveLength(1);
  });

  it("ignores a late response for the previous person", async () => {
    const forJordan = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((id?: number) =>
      id === 1 ? forJordan.promise : Promise.resolve(settings({ default_template: "signal" }))
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });
    await screen.findByText("Meridian");
    expect(api.getSettings).toHaveBeenLastCalledWith(1);

    act(() => switchTo(2));
    expect(api.getSettings).toHaveBeenLastCalledWith(2);
    await waitFor(() => expect(within(card("Signal")).getByText("Default")).toBeInTheDocument());
    await act(async () => {
      forJordan.resolve(settings({ default_template: "meridian" }));
    });
    expect(within(card("Signal")).getByText("Default")).toBeInTheDocument();
    expect(within(card("Meridian")).queryByText("Default")).not.toBeInTheDocument();
  });

  it("keeps Set as default disabled until the person's settings load", async () => {
    vi.mocked(api.getSettings).mockReturnValue(new Promise<SettingsShape>(() => {}));
    renderScreen({ people: [SAM] });
    await screen.findByText("Meridian");
    const buttons = screen.getAllByRole("button", { name: "Set as default" });
    expect(buttons).toHaveLength(4);
    for (const button of buttons) expect(button).toBeDisabled();
  });

  it("sets the app-wide default when there are no people", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings({ default_template: "slate" }));
    vi.mocked(api.updateSettings).mockResolvedValue(settings({ default_template: "meridian" }));
    renderScreen({ people: [], personId: null });
    await waitFor(() => expect(within(card("Slate")).getByText("Default")).toBeInTheDocument());
    expect(vi.mocked(api.getSettings).mock.calls[0][0]).toBeUndefined();
    expect(screen.queryByRole("heading", { name: /^Settings for/ })).not.toBeInTheDocument();

    fireEvent.click(within(card("Meridian")).getByRole("button", { name: "Set as default" }));
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1));
    const [patch, profileId] = vi.mocked(api.updateSettings).mock.calls[0];
    expect(patch).toEqual({ default_template: "meridian" });
    expect(profileId).toBeUndefined();
  });

  it("requests no settings while the person list is loading", async () => {
    vi.mocked(api.getSettings).mockResolvedValue(settings());
    renderScreen({ people: [], personId: null, loading: true });
    await screen.findByText("Meridian");
    expect(api.getSettings).not.toHaveBeenCalled();
    for (const button of screen.getAllByRole("button", { name: "Set as default" })) {
      expect(button).toBeDisabled();
    }
  });
});
