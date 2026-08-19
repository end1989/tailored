import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ProfileScreen from "./ProfileScreen";
import * as api from "../api";

const { baseProfileDetail } = vi.hoisted(() => {
  const contact = { name: "Jordan Rivera", email: "e@example.com", phone: null, location: null, links: [] };
  const baseProfileDetail = {
    id: 1,
    name: "Jordan Rivera",
    contact,
    master_profile: {
      summary_notes: "Seasoned engineer notes",
      experiences: [
        {
          company: "Acme",
          title: "Engineer",
          start: "2020-01",
          end: null,
          location: null,
          bullets: [{ text: "Did a thing", tags: ["python"] }],
        },
      ],
      projects: [],
      skills: [],
      education: [],
      certifications: [],
      extras: [],
    },
    voice_notes: "",
    documents: [{ id: 5, filename: "resume.pdf", kind: "pdf" }],
  };
  return { baseProfileDetail };
});

vi.mock("../api", () => {
  return {
    listProfiles: vi.fn().mockResolvedValue([
      { id: 1, name: "Jordan Rivera", contact: baseProfileDetail.contact, has_master_profile: true },
    ]),
    getProfile: vi.fn().mockResolvedValue(baseProfileDetail),
    createProfile: vi.fn(),
    updateProfile: vi.fn(),
    uploadDocument: vi.fn(),
    buildProfile: vi.fn(),
  };
});

describe("ProfileScreen", () => {
  it("renders profiles, documents, and the master profile editor", async () => {
    render(<ProfileScreen />);
    expect(await screen.findByDisplayValue("Seasoned engineer notes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Jordan Rivera" })).toBeInTheDocument();
    expect(screen.getByText("resume.pdf")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Acme")).toBeInTheDocument();
  });

  it("adding a bullet grows the bullet input list", async () => {
    render(<ProfileScreen />);
    await screen.findByDisplayValue("Seasoned engineer notes");
    expect(screen.getAllByPlaceholderText("Bullet text")).toHaveLength(1);
    fireEvent.click(screen.getByText("Add bullet"));
    expect(screen.getAllByPlaceholderText("Bullet text")).toHaveLength(2);
  });

  it("saves voice notes for the profile", async () => {
    vi.mocked(api.updateProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      voice_notes: "Plain and direct. Never call myself passionate.",
    });
    render(<ProfileScreen />);
    const box = await screen.findByLabelText(/voice notes/i);
    fireEvent.change(box, {
      target: { value: "Plain and direct. Never call myself passionate." },
    });
    fireEvent.click(screen.getByRole("button", { name: /save master profile/i }));
    await waitFor(() =>
      expect(api.updateProfile).toHaveBeenCalledWith(
        expect.any(Number),
        expect.objectContaining({
          voice_notes: "Plain and direct. Never call myself passionate.",
        }),
      ),
    );
  });

  it("building the master profile keeps unsaved voice notes", async () => {
    // Build runs intake, which never touches voice notes; reseeding the box
    // from its response would silently discard what the user just typed.
    vi.mocked(api.buildProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      voice_notes: "",
    });
    render(<ProfileScreen />);
    const box = await screen.findByLabelText(/voice notes/i);
    fireEvent.change(box, { target: { value: "Short sentences only." } });
    fireEvent.click(screen.getByRole("button", { name: /build master profile/i }));
    await waitFor(() => expect(api.buildProfile).toHaveBeenCalled());
    expect(screen.getByLabelText(/voice notes/i)).toHaveValue("Short sentences only.");
  });

  it("shows the voice notes already on the profile", async () => {
    vi.mocked(api.getProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      voice_notes: "Short sentences only.",
    });
    render(<ProfileScreen />);
    expect(await screen.findByDisplayValue("Short sentences only.")).toBeInTheDocument();
  });
});
