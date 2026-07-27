import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ApplicationScreen from "./ApplicationScreen";
import * as api from "../api";
import type { ApplicationDetail } from "../types";

vi.mock("../api", () => ({
  getApplication: vi.fn(),
  pasteJobText: vi.fn(),
  updateContent: vi.fn(),
  regenerate: vi.fn(),
  retryApplication: vi.fn(),
  generateApplication: vi.fn(),
  addEvent: vi.fn(),
  deleteEvent: vi.fn(),
  listEvents: vi.fn(),
  patchApplication: vi.fn(),
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

  it("keeps the same calendar day from timeline date input to display west of UTC", async () => {
    // Regression for I3: new Date("2026-07-20").toISOString() stores UTC
    // midnight; rendering it with a bare toLocaleDateString() converts back
    // to local time and shows one day early for any negative UTC offset.
    vi.stubEnv("TZ", "America/New_York");
    try {
      vi.mocked(api.getApplication)
        .mockResolvedValueOnce({ ...base, status: "ready" })
        .mockResolvedValueOnce({
          ...base,
          status: "ready",
          events: [
            {
              id: 9,
              application_id: 1,
              kind: "note",
              body: "Called Tuesday",
              occurred_at: "2026-07-20T00:00:00.000Z",
              created_at: "2026-07-20T00:00:00.000Z",
            },
          ],
        });
      vi.mocked(api.addEvent).mockResolvedValue({
        id: 9,
        application_id: 1,
        kind: "note",
        body: "Called Tuesday",
        occurred_at: "2026-07-20T00:00:00.000Z",
        created_at: "2026-07-20T00:00:00.000Z",
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
          expect.objectContaining({ occurred_at: "2026-07-20T00:00:00.000Z" })
        )
      );

      expect(await screen.findByText("7/20/2026")).toBeInTheDocument();
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
