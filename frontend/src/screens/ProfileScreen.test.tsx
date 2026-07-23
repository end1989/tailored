import { fireEvent, render, screen } from "@testing-library/react";
import ProfileScreen from "./ProfileScreen";

vi.mock("../api", () => {
  const contact = { name: "Jordan Rivera", email: "e@example.com", phone: null, location: null, links: [] };
  const detail = {
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
    documents: [{ id: 5, filename: "resume.pdf", kind: "pdf" }],
  };
  return {
    listProfiles: vi.fn().mockResolvedValue([
      { id: 1, name: "Jordan Rivera", contact, has_master_profile: true },
    ]),
    getProfile: vi.fn().mockResolvedValue(detail),
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
});
