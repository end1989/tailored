import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import AddJobsScreen from "./AddJobsScreen";
import * as api from "../api";
import { deferred, makePerson, renderWithPerson, type PersonTestOptions } from "../test-utils";
import type { SettingsShape, TemplateInfo } from "../types";

// listProfiles is deliberately absent. The screen reads the person from
// PersonContext; vitest throws on any access to an export this factory does
// not define, so a screen that fetched its own profile list would fail here.
vi.mock("../api", () => ({
  getSettings: vi.fn(),
  createApplications: vi.fn(),
  listTemplates: vi.fn(),
}));

const SETTINGS: SettingsShape = {
  api_key_set: true,
  fake_mode: false,
  default_template: "slate",
  default_depth: "standard",
  page_size: "Letter",
};

// A second person's own defaults, different in both fields from SETTINGS.
const SAM_SETTINGS: SettingsShape = { ...SETTINGS, default_template: "meridian", default_depth: "deep" };

const MERIDIAN: TemplateInfo = { name: "meridian", label: "Meridian", description: "d", best_for: "b" };
const SLATE: TemplateInfo = { name: "slate", label: "Slate", description: "d", best_for: "b" };
const LEDGER: TemplateInfo = { name: "ledger", label: "Ledger", description: "d", best_for: "b" };
const PLAINWORK: TemplateInfo = { name: "plainwork", label: "Plainwork", description: "d", best_for: "b" };

const JORDAN = makePerson();
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
  created_at: "2026-02-01T00:00:00+00:00",
});

function renderScreen(opts?: PersonTestOptions) {
  return renderWithPerson(<AddJobsScreen />, opts);
}

/**
 * Types the URLs and returns the submit button once it is enabled. It stays
 * disabled until the current person's settings have loaded, so this is also
 * the wait for those settings.
 */
async function enterUrls(value: string): Promise<HTMLElement> {
  fireEvent.change(screen.getByPlaceholderText("https://..."), { target: { value } });
  const submit = screen.getByRole("button", { name: /add and generate/i });
  await waitFor(() => expect(submit).toBeEnabled());
  return submit;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.createApplications).mockResolvedValue([]);
  vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN, SLATE]);
});

describe("AddJobsScreen", () => {
  it("parses three URL lines into three preview rows", async () => {
    renderScreen();
    await enterUrls("https://a.example/j1\nhttps://b.example/j2\n\nhttps://c.example/j3\n");
    expect(screen.getAllByTestId("job-row")).toHaveLength(3);
    expect(screen.getByText("3 jobs to queue")).toBeInTheDocument();
  });

  it("shows a warning when no API key is set and demo mode is off", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, api_key_set: false });
    renderScreen();
    expect(await screen.findByText(/No API key set/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/Generated with your Anthropic API key/i)
    ).not.toBeInTheDocument();
  });

  it("shows the plain mode note (no warning) when an API key is set", async () => {
    renderScreen();
    expect(
      await screen.findByText(/Generated with your Anthropic API key/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/No API key set/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /See MCP mode/ })).toHaveAttribute(
      "href",
      "/getting-started"
    );
  });

  it("sends generate:false when saving without generating", async () => {
    renderScreen();
    await enterUrls("https://example.com/a\nhttps://example.com/b");
    fireEvent.click(screen.getByLabelText(/save without generating/i));
    fireEvent.click(screen.getByRole("button", { name: /save for later/i }));

    await waitFor(() =>
      expect(api.createApplications).toHaveBeenCalledWith(
        1,
        expect.any(Array),
        expect.any(String),
        expect.any(String),
        false
      )
    );
  });

  it("generates immediately by default", async () => {
    renderScreen();
    fireEvent.click(await enterUrls("https://example.com/a"));

    await waitFor(() =>
      expect(api.createApplications).toHaveBeenCalledWith(
        1,
        [{ url: "https://example.com/a", depth: "standard", template: "slate" }],
        "standard",
        "slate",
        true
      )
    );
  });

  it("renders template options from the API, not a hardcoded list", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, default_template: "meridian" });
    vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN, LEDGER, PLAINWORK]);
    renderScreen();
    const select = await screen.findByLabelText(/default template/i);
    expect(await within(select).findByRole("option", { name: "Ledger" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "Plainwork" })).toBeInTheDocument();
  });

  it("shows template labels rather than raw ids in the default select", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, default_template: "meridian" });
    vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN]);
    renderScreen();
    const select = await screen.findByLabelText(/default template/i);
    expect(await within(select).findByRole("option", { name: "Meridian" })).toBeInTheDocument();
    expect(within(select).queryByRole("option", { name: "meridian" })).toBeNull();
  });

  it("renders per-row template options from the API", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, default_template: "meridian" });
    vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN, LEDGER]);
    renderScreen();
    await enterUrls("https://a.example/j1");
    const row = screen.getByLabelText("Template for row 1");
    expect(await within(row).findByRole("option", { name: "Ledger" })).toBeInTheDocument();
    expect(within(row).getByRole("option", { name: "Meridian" })).toBeInTheDocument();
    expect(within(row).queryByRole("option", { name: "meridian" })).toBeNull();
  });

  // The label is display, the name is the contract: api/applications.py rejects any
  // template not in the registry, so an option that carries the label as its value
  // renders correctly and fails every submit.
  it("queues the template id, not the label, from the default template select", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, default_template: "meridian" });
    vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN, LEDGER]);
    renderScreen();
    const submit = await enterUrls("https://a.example/j1");
    const select = screen.getByLabelText(/default template/i) as HTMLSelectElement;
    const ledger = (await within(select).findByRole("option", { name: "Ledger" })) as HTMLOptionElement;
    expect(ledger.value).toBe("ledger");
    // the saved default must resolve to a real option, or the select shows the wrong entry
    expect(select.value).toBe("meridian");

    fireEvent.change(select, { target: { value: "ledger" } });
    fireEvent.click(submit);

    await waitFor(() => {
      const calls = vi.mocked(api.createApplications).mock.calls;
      const call = calls[calls.length - 1];
      expect(call?.[1]).toEqual([
        { url: "https://a.example/j1", depth: "standard", template: "ledger" },
      ]);
      expect(call?.[3]).toBe("ledger");
    });
  });

  it("queues the template id, not the label, from a per-row override", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SETTINGS, default_template: "meridian" });
    vi.mocked(api.listTemplates).mockResolvedValue([MERIDIAN, LEDGER]);
    renderScreen();
    const submit = await enterUrls("https://a.example/j1");
    const row = screen.getByLabelText("Template for row 1") as HTMLSelectElement;
    const ledger = (await within(row).findByRole("option", { name: "Ledger" })) as HTMLOptionElement;
    expect(ledger.value).toBe("ledger");
    expect(row.value).toBe("meridian");

    fireEvent.change(row, { target: { value: "ledger" } });
    fireEvent.click(submit);

    await waitFor(() => {
      const calls = vi.mocked(api.createApplications).mock.calls;
      const call = calls[calls.length - 1];
      expect(call?.[1]).toEqual([
        { url: "https://a.example/j1", depth: "standard", template: "ledger" },
      ]);
    });
  });
});

describe("AddJobsScreen and the current person", () => {
  it("says whose jobs these are with the person's label, and has no person select of its own", async () => {
    renderScreen({ overrides: { labelFor: (p) => `${p.name} (${p.contact.email})` } });

    expect(
      await screen.findByText("Adding jobs for Jordan Rivera (jordan@example.com)")
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Jordan Rivera/ })).not.toBeInTheDocument();
  });

  it("queues for the current person with that person's defaults, then opens the dashboard", async () => {
    vi.mocked(api.getSettings).mockImplementation((profileId) =>
      Promise.resolve(profileId === 2 ? SAM_SETTINGS : SETTINGS)
    );
    renderWithPerson(
      <Routes>
        <Route path="/add" element={<AddJobsScreen />} />
        <Route path="/" element={<p>Dashboard stub</p>} />
      </Routes>,
      { people: [JORDAN, SAM], personId: 2, route: "/add" }
    );

    const submit = await enterUrls("https://a.example/j1");
    expect(screen.getByText("Adding jobs for Sam Lee")).toBeInTheDocument();
    expect(screen.getByLabelText(/default template/i)).toHaveValue("meridian");
    expect(screen.getByLabelText("Depth for row 1")).toHaveValue("deep");

    fireEvent.click(submit);

    await waitFor(() =>
      expect(api.createApplications).toHaveBeenCalledWith(
        2,
        [{ url: "https://a.example/j1", depth: "deep", template: "meridian" }],
        "deep",
        "meridian",
        true
      )
    );
    expect(await screen.findByText("Dashboard stub")).toBeInTheDocument();
    // One settings request, for Sam: none for the first person, none app-wide.
    expect(vi.mocked(api.getSettings).mock.calls).toEqual([[2]]);
  });

  it("keeps submit disabled until the person's settings have loaded", async () => {
    const settings = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockReturnValue(settings.promise);
    renderScreen();
    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1" },
    });
    const submit = screen.getByRole("button", { name: /add and generate/i });

    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(api.createApplications).not.toHaveBeenCalled();

    await act(async () => {
      settings.resolve(SETTINGS);
    });

    await waitFor(() => expect(submit).toBeEnabled());
  });

  it("shows a settings failure and keeps submit disabled", async () => {
    vi.mocked(api.getSettings).mockRejectedValue(new Error("API 404: profile not found"));
    renderScreen();

    expect(await screen.findByText(/API 404: profile not found/)).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1" },
    });
    expect(screen.getByRole("button", { name: /add and generate/i })).toBeDisabled();
  });

  it("disables submit on a switch until the new person's settings land", async () => {
    const samSettings = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((profileId) =>
      profileId === 2 ? samSettings.promise : Promise.resolve(SETTINGS)
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });
    const submit = await enterUrls("https://a.example/j1");
    expect(screen.getByLabelText(/default template/i)).toHaveValue("slate");

    act(() => switchTo(2));

    expect(screen.getByText("Adding jobs for Sam Lee")).toBeInTheDocument();
    expect(submit).toBeDisabled();

    await act(async () => {
      samSettings.resolve(SAM_SETTINGS);
    });

    await waitFor(() => expect(submit).toBeEnabled());
    expect(screen.getByLabelText(/default template/i)).toHaveValue("meridian");
    expect(screen.getByLabelText("Depth for row 1")).toHaveValue("deep");
  });

  it("ignores the previous person's settings when they arrive after a switch", async () => {
    const jordanSettings = deferred<SettingsShape>();
    vi.mocked(api.getSettings).mockImplementation((profileId) =>
      profileId === 1 ? jordanSettings.promise : Promise.resolve(SAM_SETTINGS)
    );
    const { switchTo } = renderScreen({ people: [JORDAN, SAM] });
    expect(api.getSettings).toHaveBeenCalledWith(1);

    act(() => switchTo(2));
    const submit = await enterUrls("https://a.example/j1");
    expect(screen.getByLabelText(/default template/i)).toHaveValue("meridian");

    await act(async () => {
      jordanSettings.resolve({ ...SETTINGS, default_template: "slate", default_depth: "quick" });
    });

    // Jordan's late defaults did not replace Sam's, and did not disable submit.
    expect(screen.getByLabelText(/default template/i)).toHaveValue("meridian");
    expect(screen.getByLabelText("Depth for row 1")).toHaveValue("deep");
    expect(submit).toBeEnabled();

    fireEvent.click(submit);
    await waitFor(() =>
      expect(api.createApplications).toHaveBeenCalledWith(
        2,
        [{ url: "https://a.example/j1", depth: "deep", template: "meridian" }],
        "deep",
        "meridian",
        true
      )
    );
  });

  it("with no people, points to the create form and cannot submit", () => {
    renderScreen({ people: [], personId: null });

    expect(screen.getByRole("link", { name: "Add a person first" })).toHaveAttribute(
      "href",
      "/profiles?new=1"
    );
    expect(screen.queryByText(/^Adding jobs for/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1" },
    });
    expect(screen.getByRole("button", { name: "Add a person first" })).toBeDisabled();
    expect(api.getSettings).not.toHaveBeenCalled();
  });

  it("shows nothing person-dependent while people are loading", () => {
    renderScreen({ people: [], personId: null, loading: true });

    expect(screen.queryByText(/Add a person first/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Adding jobs for/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1" },
    });
    expect(screen.getByRole("button", { name: /add and generate/i })).toBeDisabled();
    expect(api.getSettings).not.toHaveBeenCalled();
  });

  it("shows why it cannot submit when the people list failed to load", () => {
    renderScreen({ people: [], personId: null, overrides: { error: "API 500: boom" } });

    expect(screen.getByText("API 500: boom")).toBeInTheDocument();
    expect(screen.queryByText(/Add a person first/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1" },
    });
    expect(screen.getByRole("button", { name: /add and generate/i })).toBeDisabled();
  });
});
