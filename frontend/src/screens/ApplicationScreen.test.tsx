import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
});
