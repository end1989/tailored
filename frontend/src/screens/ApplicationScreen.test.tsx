import { render, screen } from "@testing-library/react";
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
  cost_usd: 0.25,
  created_at: "2026-07-22T10:00:00",
  error_message: null,
  stage: "drafted",
  applied_at: null,
  archived_at: null,
  last_activity_at: "2026-07-22T10:00:00+00:00",
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
});
