import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ApplicationScreen from "./ApplicationScreen";
import * as api from "../api";
import type { ApplicationDetail } from "../types";

vi.mock("../api", () => ({
  getApplication: vi.fn(),
  pasteJobText: vi.fn(),
  updateContent: vi.fn(),
  fetchEditPreview: vi.fn(),
  regenerate: vi.fn(),
  retryApplication: vi.fn(),
  generateApplication: vi.fn(),
  addEvent: vi.fn(),
  deleteEvent: vi.fn(),
  listEvents: vi.fn(),
  patchApplication: vi.fn(),
  listTemplates: vi.fn(),
  setApplicationTemplate: vi.fn(),
  previewUrl: (id: number) => `/api/applications/${id}/preview`,
  exportUrl: (id: number, kind: string) => `/api/applications/${id}/exports/${kind}`,
}));

const base: Omit<ApplicationDetail, "status"> = {
  id: 1,
  profile_id: 1,
  version: 1,
  template: "slate",
  depth: "standard",
  url: "https://example.com/job",
  company: "Acme",
  title: "Backend Engineer",
  cost_usd: 0.4321,
  created_at: "2026-07-22T10:00:00",
  error_message: null,
  stage: "applied",
  applied_at: null,
  archived_at: null,
  last_activity_at: "2026-07-01T00:00:00+00:00",
  resume: null,
  cover_letter_md: null,
  tailoring_notes: null,
  research: null,
  parsed: null,
  raw_text_present: false,
  events: [],
};

/**
 * What the edit-mode preview endpoint returns, in miniature: the same
 * vocabulary the real templates emit (backend/templates/_edit.html).
 */
const EDIT_HTML = `<!DOCTYPE html><html><body>
  <p contenteditable="plaintext-only" data-edit-path="headline">Backend Engineer</p>
  <p contenteditable="plaintext-only" data-edit-path="summary">Eight years of Python.</p>
  <section data-node-path="sections.0">
    <h2><span contenteditable="plaintext-only" data-edit-path="sections.0.title">Experience</span></h2>
    <div class="item" data-node-path="sections.0.items.0">
      <div class="item-head"><span class="primary" data-locked>Engineer</span></div>
      <ul class="bullets">
        <li><span contenteditable="plaintext-only" data-edit-path="sections.0.items.0.bullets.0">Built the thing.</span><span class="edit-del" data-delete-path="sections.0.items.0.bullets.0">x</span></li>
        <li><span contenteditable="plaintext-only" data-edit-path="sections.0.items.0.bullets.1">Shipped it.</span><span class="edit-del" data-delete-path="sections.0.items.0.bullets.1">x</span></li>
      </ul>
    </div>
  </section>
</body></html>`;

const READY_RESUME = {
  contact: {
    name: "Jordan Rivera",
    email: "e@example.com",
    phone: null,
    location: null,
    links: [],
  },
  headline: "Backend Engineer",
  summary: "Eight years of Python.",
  sections: [
    {
      type: "experience" as const,
      title: "Experience",
      items: [
        {
          company: "Initech",
          role: "Engineer",
          start: "2020",
          end: null,
          location: null,
          bullets: ["Built the thing.", "Shipped it."],
        },
      ],
    },
  ],
};

/** The editable preview loads into the frame asynchronously; wait for it. */
async function editorFrame(): Promise<Document> {
  const frame = (await screen.findByTitle("Resume preview")) as HTMLIFrameElement;
  await waitFor(() => {
    expect(frame.contentDocument?.querySelector("[data-edit-path]")).toBeTruthy();
  });
  return frame.contentDocument as Document;
}

function typeInto(doc: Document, path: string, text: string) {
  const el = doc.querySelector(`[data-edit-path="${path}"]`) as HTMLElement;
  el.textContent = text;
  fireEvent.input(el);
}

function renderAt() {
  return render(
    <MemoryRouter initialEntries={["/applications/1"]}>
      <Routes>
        <Route path="/applications/:id" element={<ApplicationScreen />} />
      </Routes>
    </MemoryRouter>
  );
}

// renderScreen is used by tests that don't care about a specific status/detail
// shape — it sets its own default mock so it never depends on whatever the
// previous test in this file left behind (mocks are not reset between tests).
function renderScreen() {
  vi.mocked(api.getApplication).mockResolvedValue({ ...base, status: "ready" });
  return renderAt();
}

describe("ApplicationScreen", () => {
  // The screen fetches the template registry on mount. A bare vi.fn() returns
  // undefined, which throws inside the effect, so every test needs this seeded
  // whether or not it cares about templates. The tests that do care override it
  // in their own body. Same convention as AddJobsScreen/SettingsScreen.
  beforeEach(() => {
    vi.mocked(api.listTemplates).mockResolvedValue([]);
    vi.mocked(api.fetchEditPreview).mockResolvedValue(EDIT_HTML);
  });

  it("shows the paste panel when status is needs_paste", async () => {
    vi.mocked(api.getApplication).mockResolvedValue({ ...base, status: "needs_paste" });
    renderAt();
    expect(await screen.findByText("Paste the job posting")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Paste the full job posting text here")
    ).toBeInTheDocument();
  });

  it("shows all four tabs when status is ready", async () => {
    vi.mocked(api.getApplication).mockResolvedValue({
      ...base,
      status: "ready",
      resume: {
        contact: { name: "Jordan Rivera", email: "e@example.com", phone: null, location: null, links: [] },
        headline: "Backend Engineer",
        summary: "A summary.",
        sections: [],
      },
      cover_letter_md: "Dear team,",
      tailoring_notes: "Emphasized Python work.",
    });
    renderAt();
    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cover Letter" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Research" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exports" })).toBeInTheDocument();
  });

  it("shows a Retry button when status is error", async () => {
    vi.mocked(api.getApplication).mockResolvedValue({
      ...base,
      status: "error",
      error_message: "boom",
    });
    renderAt();
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("logs a timeline entry", async () => {
    vi.mocked(api.addEvent).mockResolvedValue({
      id: 1, application_id: 1, kind: "callback",
      body: "Recruiter called", occurred_at: "2026-07-01T00:00:00+00:00",
      created_at: "2026-07-01T00:00:00+00:00",
    });
    renderScreen();

    fireEvent.change(await screen.findByLabelText(/entry type/i), {
      target: { value: "callback" },
    });
    fireEvent.change(screen.getByLabelText(/entry note/i), {
      target: { value: "Recruiter called" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add to timeline/i }));

    await waitFor(() =>
      expect(api.addEvent).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ kind: "callback", body: "Recruiter called" })
      )
    );
  });

  it("changes stage from the application screen", async () => {
    vi.mocked(api.patchApplication).mockResolvedValueOnce({ ...base, status: "ready", stage: "offer" });
    renderScreen();

    fireEvent.change(await screen.findByLabelText(/^stage$/i), {
      target: { value: "offer" },
    });

    await waitFor(() =>
      expect(api.patchApplication).toHaveBeenCalledWith(1, { stage: "offer" })
    );
  });

  it("renders the application's cost", async () => {
    // The dashboard redesign removed the Cost column, taking with it the only
    // assertion in the suite that a cost value reaches the DOM. This restores it
    // on the screen that still displays cost.
    renderScreen();
    expect(await screen.findByText(/0\.4321/)).toBeInTheDocument();
  });

  it("stops polling once a not_started application is fetched", async () => {
    // Regression for I1: ApplicationScreen kept its own TERMINAL list that
    // omitted "not_started", so the 2s poll never stopped for exactly the
    // rows this feature added (open a saved job from the dashboard).
    vi.useFakeTimers();
    try {
      vi.mocked(api.getApplication).mockResolvedValue({ ...base, status: "not_started" });

      renderAt();
      await vi.advanceTimersByTimeAsync(0);
      const callsAfterFirstTick = vi.mocked(api.getApplication).mock.calls.length;

      await vi.advanceTimersByTimeAsync(10_000);

      expect(vi.mocked(api.getApplication).mock.calls.length).toBe(callsAfterFirstTick);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows a Generate action for a not_started application and starts it", async () => {
    // Regression for I1: not_started rows opened from the dashboard were a
    // dead end on this screen — there was no way to kick off generation here.
    vi.mocked(api.getApplication).mockResolvedValue({ ...base, status: "not_started" });
    vi.mocked(api.generateApplication).mockResolvedValue({ ...base, status: "queued" });
    renderAt();

    fireEvent.click(await screen.findByRole("button", { name: /generate/i }));

    await waitFor(() => expect(api.generateApplication).toHaveBeenCalledWith(1));
  });

  it("disables the Saved stage option once the application is ready", async () => {
    // Regression for I2(a): the backend 422s on stage="saved" once status is
    // "ready"; the dropdown must not offer a choice that always fails.
    renderScreen();

    const select = await screen.findByLabelText(/^stage$/i);
    const savedOption = within(select).getByRole("option", { name: "saved" }) as HTMLOptionElement;
    expect(savedOption.disabled).toBe(true);
  });

  it("surfaces a stage-change error and leaves the select unchanged on a 422", async () => {
    // Regression for I2(b): the stage handler had no try/catch, so a rejected
    // patchApplication call silently left the <select> showing a value the
    // server never accepted, with nothing shown to the user.
    vi.mocked(api.patchApplication).mockRejectedValueOnce(
      new Error("API 422: cannot set stage to saved while status is ready")
    );
    renderScreen();

    const select = await screen.findByLabelText(/^stage$/i);
    expect(select).toHaveValue("applied");
    fireEvent.change(select, { target: { value: "offer" } });

    expect(await screen.findByText(/422/)).toBeInTheDocument();
    expect(select).toHaveValue("applied");
  });

  it("sends the ISO instant for LOCAL midnight of the picked calendar day, not UTC midnight", async () => {
    // Regression for the timeZone:"UTC" fix wave: that fix sent
    // new Date("2026-07-20").toISOString(), which parses the date-only string
    // as UTC midnight. For any negative UTC offset that instant, re-rendered
    // in local time, falls on the previous calendar day. The correct write
    // side builds the instant from LOCAL midnight (new Date(y, m-1, d)) so it
    // survives the round trip regardless of the viewer's offset. Expectation
    // is derived from new Date(y, m-1, d).toISOString() rather than a
    // hardcoded string, so this test verifies the same thing at any TZ,
    // including UTC itself.
    vi.stubEnv("TZ", "America/New_York");
    try {
      const expectedIso = new Date(2026, 6, 20).toISOString();
      vi.mocked(api.getApplication)
        .mockResolvedValueOnce({ ...base, status: "ready" })
        .mockResolvedValueOnce({ ...base, status: "ready" }); // re-fetch after onChanged()
      vi.mocked(api.addEvent).mockResolvedValue({
        id: 9,
        application_id: 1,
        kind: "note",
        body: "Called Tuesday",
        occurred_at: expectedIso,
        created_at: expectedIso,
      });

      renderAt();
      fireEvent.change(await screen.findByLabelText(/entry note/i), {
        target: { value: "Called Tuesday" },
      });
      fireEvent.change(screen.getByLabelText(/date/i), { target: { value: "2026-07-20" } });
      fireEvent.click(screen.getByRole("button", { name: /add to timeline/i }));

      await waitFor(() =>
        expect(api.addEvent).toHaveBeenCalledWith(
          1,
          expect.objectContaining({ occurred_at: expectedIso })
        )
      );
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("renders a blank-date (default-path) event on its LOCAL calendar day, not its UTC day", async () => {
    // Regression: the default path never has a user-picked date -- the
    // backend stamps the current instant, and API/MCP-created events land
    // here too. The previous fix forced toLocaleDateString(undefined,
    // { timeZone: "UTC" }) on read, which is correct only for the
    // UTC-midnight sentinel from the OTHER path. For a real wall-clock
    // instant, forcing UTC shows the wrong day whenever local and UTC
    // disagree on the calendar day. Built at 23:00 local so local and UTC
    // days differ under the stubbed TZ regardless of the runner's own zone.
    vi.stubEnv("TZ", "America/New_York");
    try {
      const instant = new Date(2026, 6, 20, 23, 0, 0); // 2026-07-20 23:00 local
      const occurredAt = instant.toISOString();
      const expectedLocalDay = instant.toLocaleDateString();
      // Sanity check the fixture actually straddles the UTC day boundary;
      // otherwise this test would pass for the wrong reason.
      expect(occurredAt.slice(0, 10)).not.toBe(
        `${instant.getFullYear()}-${String(instant.getMonth() + 1).padStart(2, "0")}-${String(
          instant.getDate()
        ).padStart(2, "0")}`
      );

      vi.mocked(api.getApplication).mockResolvedValueOnce({
        ...base,
        status: "ready",
        events: [
          {
            id: 9,
            application_id: 1,
            kind: "note",
            body: "Called Tuesday",
            occurred_at: occurredAt,
            created_at: occurredAt,
          },
        ],
      });

      renderAt();

      expect(await screen.findByText(expectedLocalDay)).toBeInTheDocument();
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("offers every registered template in the switcher", async () => {
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
    ]);
    renderScreen();
    const select = await screen.findByLabelText(/template/i);
    expect(within(select).getByRole("option", { name: "Ledger" })).toBeInTheDocument();
  });

  it("selects the application's own template, not just the first registered one", async () => {
    // Regression: nothing pinned the switcher's *displayed* value, so deleting
    // value={detail.template} from the <select> left the whole suite green.
    // The blind spot was the fixture: base.template is "slate", which no test
    // seeded into the mocked registry, and React selects the first option when
    // a controlled value matches none -- so the correct render and the broken
    // one both showed "Meridian". Seeding slate *second* makes them differ:
    // controlled -> "slate", uncontrolled -> "meridian".
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "slate", label: "Slate", description: "d", best_for: "b" },
    ]);
    renderScreen();
    const select = (await screen.findByLabelText(/template/i)) as HTMLSelectElement;
    // The select renders as soon as `detail` arrives; its options arrive from a
    // separate listTemplates() promise. Wait for an option before reading the
    // value so this asserts the rendered selection rather than the empty-select
    // placeholder.
    await screen.findByRole("option", { name: "Slate" });
    expect(select.value).toBe("slate");
  });

  it("switches template and shows the new one", async () => {
    // slate (the fixture's own template) is seeded here too, so the pre-change
    // assertion below distinguishes a select bound to detail.template from one
    // that ignores it and defaults to the first option.
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "slate", label: "Slate", description: "d", best_for: "b" },
      { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
    ]);
    vi.mocked(api.setApplicationTemplate).mockResolvedValue({
      ...base,
      status: "ready",
      template: "ledger",
    });
    renderScreen();
    const select = (await screen.findByLabelText(/template/i)) as HTMLSelectElement;
    // fireEvent.change cannot select an option that does not exist yet: it
    // would leave e.target.value === "" and send that to the API. Wait for the
    // option, and confirm the starting value, before firing.
    await screen.findByRole("option", { name: "Ledger" });
    expect(select.value).toBe("slate");
    fireEvent.change(select, { target: { value: "ledger" } });
    await waitFor(() =>
      expect(api.setApplicationTemplate).toHaveBeenCalledWith(base.id, "ledger"),
    );
    await waitFor(() => expect(select.value).toBe("ledger"));
  });

  it("surfaces a failed template switch instead of silently reverting", async () => {
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "meridian", label: "Meridian", description: "d", best_for: "b" },
      { name: "ledger", label: "Ledger", description: "d", best_for: "b" },
    ]);
    vi.mocked(api.setApplicationTemplate).mockRejectedValue(new Error("boom"));
    renderScreen();
    const select = await screen.findByLabelText(/template/i);
    fireEvent.change(select, { target: { value: "ledger" } });
    expect(await screen.findByText(/boom/i)).toBeInTheDocument();
  });
});

describe("ApplicationScreen inline editing", () => {
  beforeEach(() => {
    // Mocks are not reset between tests in this file, and several of these
    // assert on call counts.
    vi.clearAllMocks();
    vi.mocked(api.listTemplates).mockResolvedValue([]);
    vi.mocked(api.fetchEditPreview).mockResolvedValue(EDIT_HTML);
    vi.mocked(api.getApplication).mockResolvedValue({
      ...base,
      status: "ready",
      resume: READY_RESUME,
      cover_letter_md: "Dear team,\n\nI build data systems.",
    });
    vi.mocked(api.updateContent).mockResolvedValue({
      ...base,
      status: "ready",
      resume: READY_RESUME,
      cover_letter_md: "Dear team,",
      style_violations: [],
    });
  });

  it("offers no Save until something is typed", async () => {
    renderAt();
    await editorFrame();
    expect(
      screen.getByText(/Click any text to edit it/)
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("sends the edited text, keeping the locked facts", async () => {
    renderAt();
    const doc = await editorFrame();
    typeInto(doc, "summary", "Nine years of Python.");
    typeInto(doc, "sections.0.items.0.bullets.1", "Shipped it twice.");

    fireEvent.click(await screen.findByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.updateContent).toHaveBeenCalled());

    const [id, patch] = vi.mocked(api.updateContent).mock.calls[0];
    expect(id).toBe(1);
    expect(patch.resume?.summary).toBe("Nine years of Python.");
    const section = patch.resume?.sections[0];
    if (section?.type !== "experience") throw new Error("wrong section");
    expect(section.items[0].bullets).toEqual(["Built the thing.", "Shipped it twice."]);
    // untouched, and never editable in the first place
    expect(section.items[0].company).toBe("Initech");
    expect(section.items[0].start).toBe("2020");
  });

  it("removes a bullet when its delete marker is clicked", async () => {
    renderAt();
    const doc = await editorFrame();
    const marker = doc.querySelector(
      '[data-delete-path="sections.0.items.0.bullets.0"]'
    ) as HTMLElement;
    fireEvent.click(marker);

    fireEvent.click(await screen.findByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.updateContent).toHaveBeenCalled());
    const section = vi.mocked(api.updateContent).mock.calls[0][1].resume?.sections[0];
    if (section?.type !== "experience") throw new Error("wrong section");
    expect(section.items[0].bullets).toEqual(["Shipped it."]);
  });

  it("reports style hits after a save and offers to fix the mechanical ones", async () => {
    vi.mocked(api.updateContent).mockResolvedValue({
      ...base,
      status: "ready",
      resume: READY_RESUME,
      cover_letter_md: "Dear team,",
      style_violations: [
        {
          field: "Summary",
          path: "summary",
          rule: "curly quote",
          excerpt: 'the \u201cingestion\u201d layer',
          advice: "use a straight quote",
          mechanical: true,
          message: "Summary: curly quote near ...",
        },
        {
          field: "Experience 'Initech' bullet 1",
          path: "sections.0.items.0.bullets.0",
          rule: "em dash",
          excerpt: "systems \u2014 the unglamorous",
          advice: "rewrite the sentence",
          mechanical: false,
          message: "Experience 'Initech' bullet 1: em dash near ...",
        },
      ],
    });
    renderAt();
    const doc = await editorFrame();
    typeInto(doc, "summary", "Anything.");
    fireEvent.click(await screen.findByRole("button", { name: "Save" }));

    expect(await screen.findByText("2 style hits")).toBeInTheDocument();
    expect(screen.getByText("curly quote")).toBeInTheDocument();
    expect(screen.getByText("em dash")).toBeInTheDocument();
    // the judgment call is marked as such, and only the mechanical one is offered
    expect(screen.getByText("your call")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Clean the 1 mechanical" })
    ).toBeInTheDocument();
  });

  it("highlights the flagged field where it sits in the preview", async () => {
    vi.mocked(api.updateContent).mockResolvedValue({
      ...base,
      status: "ready",
      resume: READY_RESUME,
      cover_letter_md: null,
      style_violations: [
        {
          field: "Summary",
          path: "summary",
          rule: "em dash",
          excerpt: "x",
          advice: "y",
          mechanical: false,
          message: "z",
        },
      ],
    });
    renderAt();
    const doc = await editorFrame();
    typeInto(doc, "summary", "Anything.");
    fireEvent.click(await screen.findByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(
        doc.querySelector('[data-edit-path="summary"]')?.classList.contains("edit-violation")
      ).toBe(true);
    });
  });

  it("asks the server to apply the mechanical fixes", async () => {
    vi.mocked(api.updateContent).mockResolvedValue({
      ...base,
      status: "ready",
      resume: READY_RESUME,
      cover_letter_md: null,
      style_violations: [
        {
          field: "Summary",
          path: "summary",
          rule: "curly quote",
          excerpt: "x",
          advice: "y",
          mechanical: true,
          message: "z",
        },
      ],
    });
    // The clean rewrites the text, so the refetched preview really is a
    // different document -- that is what makes the frame get written again.
    vi.mocked(api.fetchEditPreview).mockResolvedValueOnce(EDIT_HTML);
    vi.mocked(api.fetchEditPreview).mockResolvedValue(EDIT_HTML);
    renderAt();
    const doc = await editorFrame();
    typeInto(doc, "summary", "Anything.");
    fireEvent.click(await screen.findByRole("button", { name: "Save" }));
    fireEvent.click(await screen.findByRole("button", { name: "Clean the 1 mechanical" }));
    await waitFor(() => expect(api.fetchEditPreview).toHaveBeenCalledTimes(2));

    await waitFor(() => expect(api.updateContent).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.updateContent).mock.calls[1][1].clean).toBe(true);
  });

  it("keeps highlighting what survived a Clean", async () => {
    const emDash = {
      field: "Experience 'Initech' bullet 1",
      path: "sections.0.items.0.bullets.0",
      rule: "em dash",
      excerpt: "x",
      advice: "y",
      mechanical: false,
      message: "z",
    };
    const curly = {
      field: "Summary",
      path: "summary",
      rule: "curly quote",
      excerpt: "x",
      advice: "y",
      mechanical: true,
      message: "z",
    };
    vi.mocked(api.updateContent).mockResolvedValueOnce({
      ...base,
      status: "ready",
      resume: READY_RESUME,
      cover_letter_md: null,
      style_violations: [curly, emDash],
    });
    vi.mocked(api.updateContent).mockResolvedValueOnce({
      ...base,
      status: "ready",
      resume: READY_RESUME,
      cover_letter_md: null,
      style_violations: [emDash],
    });
    renderAt();
    const doc = await editorFrame();
    typeInto(doc, "summary", "Anything.");
    fireEvent.click(await screen.findByRole("button", { name: "Save" }));
    fireEvent.click(await screen.findByRole("button", { name: "Clean the 1 mechanical" }));

    await waitFor(() => expect(screen.getByText("1 style hit")).toBeInTheDocument());
    // the frame was rewritten by the clean, so this is a new node
    const frame = (await screen.findByTitle("Resume preview")) as HTMLIFrameElement;
    await waitFor(() => {
      const el = frame.contentDocument?.querySelector(
        '[data-edit-path="sections.0.items.0.bullets.0"]'
      );
      expect(el?.classList.contains("edit-violation")).toBe(true);
    });
    expect(
      frame.contentDocument?.querySelector('[data-edit-path="summary"]')
        ?.classList.contains("edit-violation")
    ).toBe(false);
  });

  it("discards typed edits on Revert", async () => {
    renderAt();
    const doc = await editorFrame();
    typeInto(doc, "summary", "Nine years of Python.");
    fireEvent.click(await screen.findByRole("button", { name: "Revert" }));

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    });
    expect(api.updateContent).not.toHaveBeenCalled();
    // the preview was reloaded from the server, discarding the typing
    await waitFor(() => expect(api.fetchEditPreview).toHaveBeenCalledTimes(2));
  });

  it("locks the template switcher while there are unsaved edits", async () => {
    vi.mocked(api.listTemplates).mockResolvedValue([
      { name: "slate", label: "Slate", description: "", best_for: "" },
      { name: "terminal", label: "Terminal", description: "", best_for: "" },
    ]);
    renderAt();
    const doc = await editorFrame();
    const select = screen.getByLabelText("Template") as HTMLSelectElement;
    expect(select.disabled).toBe(false);
    typeInto(doc, "summary", "Nine years of Python.");
    await waitFor(() => expect(select.disabled).toBe(true));
  });

  it("keeps the preview read-only while the pipeline is running", async () => {
    vi.mocked(api.getApplication).mockResolvedValue({
      ...base,
      status: "rendering",
      resume: READY_RESUME,
    });
    renderAt();
    const frame = (await screen.findByTitle("Resume preview")) as HTMLIFrameElement;
    expect(frame.getAttribute("src")).toBe("/api/applications/1/preview");
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(api.fetchEditPreview).not.toHaveBeenCalled();
  });

  it("will not regenerate over unsaved edits", async () => {
    renderAt();
    const doc = await editorFrame();
    const button = screen.getByRole("button", { name: "Regenerate" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    typeInto(doc, "summary", "Nine years of Python.");
    await waitFor(() => expect(button.disabled).toBe(true));
  });

  it("goes read-only once a regeneration is actually running", async () => {
    vi.mocked(api.getApplication)
      .mockResolvedValueOnce({ ...base, status: "ready", resume: READY_RESUME })
      .mockResolvedValue({ ...base, status: "tailoring", resume: READY_RESUME });
    vi.mocked(api.regenerate).mockResolvedValue({ ...base, status: "queued", resume: null });
    renderAt();
    await editorFrame();

    fireEvent.change(
      screen.getByPlaceholderText(/Emphasize the data pipeline work/),
      { target: { value: "shorter summary" } }
    );
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));

    // the run takes over: no editing surface, and the plain preview is back
    await waitFor(() => {
      const frame = screen.getByTitle("Resume preview") as HTMLIFrameElement;
      expect(frame.getAttribute("src")).toBe("/api/applications/1/preview");
    });
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(api.updateContent).not.toHaveBeenCalled();
  });

  it("edits the cover letter in place and saves it", async () => {
    renderAt();
    fireEvent.click(await screen.findByRole("button", { name: "Cover Letter" }));
    const box = screen.getByLabelText("Cover letter") as HTMLTextAreaElement;
    expect(box.value).toBe("Dear team,\n\nI build data systems.");

    fireEvent.change(box, { target: { value: "Dear team,\n\nI build data pipelines." } });
    fireEvent.click(await screen.findByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.updateContent).toHaveBeenCalled());
    expect(vi.mocked(api.updateContent).mock.calls[0][1].cover_letter_md).toBe(
      "Dear team,\n\nI build data pipelines."
    );
  });

  it("reverts the cover letter to what the server has", async () => {
    renderAt();
    fireEvent.click(await screen.findByRole("button", { name: "Cover Letter" }));
    const box = screen.getByLabelText("Cover letter") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "Something else." } });
    fireEvent.click(await screen.findByRole("button", { name: "Revert" }));
    await waitFor(() => expect(box.value).toBe("Dear team,\n\nI build data systems."));
    expect(api.updateContent).not.toHaveBeenCalled();
  });
});
