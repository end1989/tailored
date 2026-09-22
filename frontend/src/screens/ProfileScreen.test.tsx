import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import App from "../App";
import ProfileScreen from "./ProfileScreen";
import * as api from "../api";
import { PersonProvider } from "../person";
import { deferred, makePerson, renderWithPerson } from "../test-utils";
import type { ProfileDetail } from "../types";

vi.mock("../api", () => ({
  listProfiles: vi.fn(),
  getProfile: vi.fn(),
  createProfile: vi.fn(),
  updateProfile: vi.fn(),
  uploadDocument: vi.fn(),
  buildProfile: vi.fn(),
  deleteDocument: vi.fn(),
}));

const contact = { name: "Jordan Rivera", email: "e@example.com", phone: null, location: null, links: [] };

const baseProfileDetail: ProfileDetail = {
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
  created_at: "2026-01-01T00:00:00+00:00",
  inbox_url: null,
  application_count: 0,
};

const JORDAN = makePerson();
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
  created_at: "2026-02-01T00:00:00+00:00",
});

const samDetail: ProfileDetail = {
  ...baseProfileDetail,
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", phone: null, location: null, links: [] },
  master_profile: { ...baseProfileDetail.master_profile, summary_notes: "Sam's notes", experiences: [] },
  documents: [],
  created_at: "2026-02-01T00:00:00+00:00",
};

/** Shows the router location, so a test can see ?new=1 come and go. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

// Mocks are not reset between tests otherwise, and several tests here queue
// one-off responses or assert call counts.
beforeEach(() => {
  vi.mocked(api.listProfiles).mockReset();
  vi.mocked(api.getProfile).mockReset().mockResolvedValue(baseProfileDetail);
  vi.mocked(api.createProfile).mockReset();
  vi.mocked(api.updateProfile).mockReset();
  vi.mocked(api.uploadDocument).mockReset();
  vi.mocked(api.buildProfile).mockReset();
  vi.mocked(api.deleteDocument).mockReset();
  localStorage.clear();
});

describe("ProfileScreen", () => {
  it("renders the current person's documents and master profile editor", async () => {
    renderWithPerson(<ProfileScreen />, { route: "/profiles" });
    expect(await screen.findByDisplayValue("Seasoned engineer notes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Jordan Rivera" })).toBeInTheDocument();
    expect(screen.getByText("resume.pdf")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Acme")).toBeInTheDocument();
    expect(api.getProfile).toHaveBeenCalledWith(1);
  });

  it("has no person picker of its own and never lists profiles itself", async () => {
    renderWithPerson(<ProfileScreen />, { people: [JORDAN, SAM] });
    await screen.findByDisplayValue("Seasoned engineer notes");
    expect(screen.queryByText("Your profiles")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sam Lee" })).not.toBeInTheDocument();
    expect(api.listProfiles).not.toHaveBeenCalled();
    expect(api.getProfile).toHaveBeenCalledTimes(1);
  });

  it("edits the person the picker has chosen", async () => {
    vi.mocked(api.getProfile).mockImplementation(async (id: number) =>
      id === 2 ? samDetail : baseProfileDetail,
    );
    renderWithPerson(<ProfileScreen />, { people: [JORDAN, SAM], personId: 2 });
    expect(await screen.findByDisplayValue("Sam's notes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sam Lee" })).toBeInTheDocument();
    expect(api.getProfile).toHaveBeenCalledWith(2);
    expect(api.getProfile).not.toHaveBeenCalledWith(1);
  });

  it("adding a bullet grows the bullet input list", async () => {
    renderWithPerson(<ProfileScreen />);
    await screen.findByDisplayValue("Seasoned engineer notes");
    expect(screen.getAllByPlaceholderText("Bullet text")).toHaveLength(1);
    fireEvent.click(screen.getByText("Add bullet"));
    expect(screen.getAllByPlaceholderText("Bullet text")).toHaveLength(2);
  });

  it("saves voice notes for the profile and refreshes the people list", async () => {
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    vi.mocked(api.updateProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      voice_notes: "Plain and direct. Never call myself passionate.",
    });
    renderWithPerson(<ProfileScreen />, { overrides: { refreshPeople } });
    const box = await screen.findByLabelText(/voice notes/i);
    fireEvent.change(box, {
      target: { value: "Plain and direct. Never call myself passionate." },
    });
    fireEvent.click(screen.getByRole("button", { name: /save master profile/i }));
    await waitFor(() =>
      expect(api.updateProfile).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          voice_notes: "Plain and direct. Never call myself passionate.",
        }),
      ),
    );
    await waitFor(() => expect(refreshPeople).toHaveBeenCalled());
  });

  it("building the master profile keeps unsaved voice notes", async () => {
    // Build runs intake, which never touches voice notes; reseeding the box
    // from its response would silently discard what the user just typed.
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    vi.mocked(api.buildProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      voice_notes: "",
    });
    renderWithPerson(<ProfileScreen />, { overrides: { refreshPeople } });
    const box = await screen.findByLabelText(/voice notes/i);
    fireEvent.change(box, { target: { value: "Short sentences only." } });
    fireEvent.click(screen.getByRole("button", { name: /build master profile/i }));
    expect(api.buildProfile).toHaveBeenCalledWith(1);
    // The button reads "Building..." until the response has been applied.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /build master profile/i })).toBeEnabled(),
    );
    expect(screen.getByLabelText(/voice notes/i)).toHaveValue("Short sentences only.");
    expect(refreshPeople).toHaveBeenCalled();
  });

  it("shows the voice notes already on the profile", async () => {
    vi.mocked(api.getProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      voice_notes: "Short sentences only.",
    });
    renderWithPerson(<ProfileScreen />);
    expect(await screen.findByDisplayValue("Short sentences only.")).toBeInTheDocument();
  });

  it("renders nothing that depends on a person while the list is loading", () => {
    renderWithPerson(<ProfileScreen />, { people: [], loading: true });
    expect(screen.getByRole("heading", { name: "Profiles" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(api.getProfile).not.toHaveBeenCalled();
  });

  it("shows the list error instead of a create form when people could not be loaded", () => {
    renderWithPerson(<ProfileScreen />, {
      people: [],
      overrides: { error: "API 500: Internal Server Error" },
    });
    expect(screen.getByText("API 500: Internal Server Error")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create person" })).not.toBeInTheDocument();
  });

  it("shows the create form when there are no people; creating clears the guard, then selects the new person", async () => {
    const calls: string[] = [];
    const setSwitchGuard = vi.fn((message: string | null) => {
      calls.push(`guard:${message}`);
    });
    const refreshPeople = vi.fn(async (selectId?: number) => {
      calls.push(`refresh:${selectId}`);
    });
    vi.mocked(api.createProfile).mockResolvedValueOnce({ ...samDetail, id: 7 });
    renderWithPerson(<ProfileScreen />, {
      people: [],
      overrides: { setSwitchGuard, refreshPeople },
    });
    expect(screen.getByText("Add a person")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    const create = screen.getByRole("button", { name: "Create person" });
    expect(create).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "  Sam Lee " } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "sam@example.com" } });
    fireEvent.click(create);

    await waitFor(() => expect(refreshPeople).toHaveBeenCalledWith(7));
    expect(api.createProfile).toHaveBeenCalledWith("Sam Lee", {
      name: "Sam Lee",
      email: "sam@example.com",
      links: [],
    });
    expect(calls[calls.indexOf("refresh:7") - 1]).toBe("guard:null");
  });

  it("?new=1 opens the create form in place of the editor, and Cancel goes back", async () => {
    renderWithPerson(
      <>
        <ProfileScreen />
        <LocationProbe />
      </>,
      { route: "/profiles?new=1" },
    );
    expect(screen.getByRole("button", { name: "Create person" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save master profile/i })).not.toBeInTheDocument();
    expect(api.getProfile).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/profiles$/);
    expect(await screen.findByDisplayValue("Seasoned engineer notes")).toBeInTheDocument();
  });

  it("creating from ?new=1 drops the parameter after the new person is selected", async () => {
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    vi.mocked(api.createProfile).mockResolvedValueOnce({ ...samDetail, id: 7 });
    renderWithPerson(
      <>
        <ProfileScreen />
        <LocationProbe />
      </>,
      { route: "/profiles?new=1", overrides: { refreshPeople } },
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Sam Lee" } });
    fireEvent.click(screen.getByRole("button", { name: "Create person" }));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(/^\/profiles$/),
    );
    expect(refreshPeople).toHaveBeenCalledWith(7);
  });

  it("choosing another person in the nav closes the create form", async () => {
    vi.mocked(api.getProfile).mockImplementation(async (id: number) =>
      id === 2 ? samDetail : baseProfileDetail,
    );
    const { switchTo } = renderWithPerson(
      <>
        <ProfileScreen />
        <LocationProbe />
      </>,
      { people: [JORDAN, SAM], route: "/profiles?new=1" },
    );
    expect(screen.getByRole("button", { name: "Create person" })).toBeInTheDocument();

    act(() => switchTo(2));

    expect(await screen.findByDisplayValue("Sam's notes")).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/profiles$/);
    expect(api.getProfile).toHaveBeenCalledWith(2);
    expect(api.getProfile).not.toHaveBeenCalledWith(1);
  });

  it("a create that finishes after leaving the screen neither navigates back nor clears a guard", async () => {
    const setSwitchGuard = vi.fn();
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    const create = deferred<ProfileDetail>();
    vi.mocked(api.createProfile).mockReturnValueOnce(create.promise);
    function Leave() {
      const navigate = useNavigate();
      return <button onClick={() => navigate("/")}>Leave</button>;
    }
    renderWithPerson(
      <>
        <Routes>
          <Route path="/profiles" element={<ProfileScreen />} />
          <Route path="/" element={<div>Dashboard</div>} />
        </Routes>
        <Leave />
        <LocationProbe />
      </>,
      { people: [JORDAN, SAM], route: "/profiles?new=1", overrides: { setSwitchGuard, refreshPeople } },
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Pat Kim" } });
    fireEvent.click(screen.getByRole("button", { name: "Create person" }));
    fireEvent.click(screen.getByRole("button", { name: "Leave" }));
    expect(screen.getByText("Dashboard")).toBeInTheDocument();

    await act(async () => {
      create.resolve({ ...samDetail, id: 7 });
    });
    // The person was created, so they are still selected. But the form is
    // gone: it owns no guard to clear (the screen now showing may hold one),
    // and it must not pull the browser back to /profiles.
    await waitFor(() => expect(refreshPeople).toHaveBeenCalledWith(7));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(setSwitchGuard).not.toHaveBeenCalled();
  });

  it("renames a person and changes their email through updateProfile, then refreshes the list", async () => {
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    const saved = { ...contact, name: "Jordan A. Rivera", email: "jordan@gmail.com" };
    vi.mocked(api.updateProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      name: "Jordan A. Rivera",
      contact: saved,
    });
    renderWithPerson(<ProfileScreen />, { overrides: { refreshPeople } });
    const nameBox = await screen.findByLabelText("Name");
    const emailBox = screen.getByLabelText("Email");
    expect(nameBox).toHaveValue("Jordan Rivera");
    expect(emailBox).toHaveValue("e@example.com");
    const save = screen.getByRole("button", { name: "Save name and email" });
    expect(save).toBeDisabled();

    fireEvent.change(nameBox, { target: { value: "Jordan A. Rivera " } });
    fireEvent.change(emailBox, { target: { value: "jordan@gmail.com" } });
    fireEvent.click(save);

    await waitFor(() => expect(refreshPeople).toHaveBeenCalled());
    expect(api.updateProfile).toHaveBeenCalledWith(1, { name: "Jordan A. Rivera", contact: saved });
    expect(screen.getByLabelText("Name")).toHaveValue("Jordan A. Rivera");
    expect(screen.getByRole("button", { name: "Save name and email" })).toBeDisabled();
  });

  it("an email-only edit leaves a contact name that came from a resume alone", async () => {
    const resumeContact = { ...contact, name: "Jordan A. Rivera" };
    vi.mocked(api.getProfile).mockResolvedValueOnce({ ...baseProfileDetail, contact: resumeContact });
    vi.mocked(api.updateProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      contact: { ...resumeContact, email: "new@example.com" },
    });
    renderWithPerson(<ProfileScreen />);
    fireEvent.change(await screen.findByLabelText("Email"), {
      target: { value: "new@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save name and email" }));
    await waitFor(() =>
      expect(api.updateProfile).toHaveBeenCalledWith(1, {
        name: "Jordan Rivera",
        contact: { ...resumeContact, email: "new@example.com" },
      }),
    );
  });

  it("will not save a blank name", async () => {
    renderWithPerson(<ProfileScreen />);
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "   " } });
    expect(screen.getByText("A person needs a name.")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save name and email" });
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(api.updateProfile).not.toHaveBeenCalled();
  });

  it("a Build that fills an empty email shows it in the Email box", async () => {
    vi.mocked(api.getProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      contact: { ...contact, email: "" },
    });
    vi.mocked(api.buildProfile).mockResolvedValueOnce({
      ...baseProfileDetail,
      contact: { ...contact, email: "found@example.com" },
    });
    renderWithPerson(<ProfileScreen />);
    expect(await screen.findByLabelText("Email")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: /build master profile/i }));
    await waitFor(() =>
      expect(screen.getByLabelText("Email")).toHaveValue("found@example.com"),
    );
    // The filled email is the saved value now, not an unsaved edit.
    expect(screen.getByRole("button", { name: "Save name and email" })).toBeDisabled();
  });

  it("sets the switch guard while edits are unsaved, comparing by value", async () => {
    const setSwitchGuard = vi.fn();
    renderWithPerson(<ProfileScreen />, {
      overrides: { setSwitchGuard, labelFor: (p) => `${p.name} (work)` },
    });
    const company = await screen.findByDisplayValue("Acme");
    expect(screen.getByRole("heading", { name: "Jordan Rivera (work)" })).toBeInTheDocument();
    expect(setSwitchGuard).not.toHaveBeenCalledWith(expect.any(String));

    fireEvent.change(company, { target: { value: "Acme Corp" } });
    expect(setSwitchGuard).toHaveBeenLastCalledWith(
      "Jordan Rivera (work) has unsaved profile changes.",
    );

    // Typing the old value back is not an unsaved change, even though the
    // editor now holds a different object than the one it loaded.
    fireEvent.change(screen.getByDisplayValue("Acme Corp"), { target: { value: "Acme" } });
    expect(setSwitchGuard).toHaveBeenLastCalledWith(null);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "other@example.com" } });
    expect(setSwitchGuard).toHaveBeenLastCalledWith(
      "Jordan Rivera (work) has unsaved profile changes.",
    );
  });

  it("sets the switch guard while a build is in flight", async () => {
    const setSwitchGuard = vi.fn();
    const build = deferred<ProfileDetail>();
    vi.mocked(api.buildProfile).mockReturnValueOnce(build.promise);
    renderWithPerson(<ProfileScreen />, { overrides: { setSwitchGuard } });
    await screen.findByDisplayValue("Seasoned engineer notes");

    fireEvent.click(screen.getByRole("button", { name: /build master profile/i }));
    expect(setSwitchGuard).toHaveBeenLastCalledWith("Jordan Rivera's profile is building.");
    expect(screen.getByRole("button", { name: /save master profile/i })).toBeDisabled();

    await act(async () => {
      build.resolve(baseProfileDetail);
    });
    await waitFor(() => expect(setSwitchGuard).toHaveBeenLastCalledWith(null));
  });

  it("a build that finishes after a switch never reaches the new person's editor", async () => {
    vi.mocked(api.getProfile).mockImplementation(async (id: number) =>
      id === 2 ? samDetail : baseProfileDetail,
    );
    const build = deferred<ProfileDetail>();
    vi.mocked(api.buildProfile).mockReturnValueOnce(build.promise);
    vi.mocked(api.updateProfile).mockResolvedValueOnce(samDetail);
    const { switchTo, ctx } = renderWithPerson(<ProfileScreen />, { people: [JORDAN, SAM] });
    await screen.findByDisplayValue("Seasoned engineer notes");
    fireEvent.click(screen.getByRole("button", { name: /build master profile/i }));
    expect(api.buildProfile).toHaveBeenCalledWith(1);

    act(() => switchTo(2));
    expect(await screen.findByDisplayValue("Sam's notes")).toBeInTheDocument();
    expect(ctx.refreshPeople).not.toHaveBeenCalled();

    await act(async () => {
      build.resolve({
        ...baseProfileDetail,
        master_profile: { ...baseProfileDetail.master_profile, summary_notes: "Built for Jordan" },
      });
    });
    expect(screen.queryByDisplayValue("Built for Jordan")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Sam's notes")).toBeInTheDocument();
    // The build still changed Jordan's row (has_master_profile), so the list
    // is refreshed even though the editor that asked is gone.
    expect(ctx.refreshPeople).toHaveBeenCalledTimes(1);

    // Saving now writes Sam's own profile to Sam, and nothing to Jordan.
    fireEvent.click(screen.getByRole("button", { name: /save master profile/i }));
    await waitFor(() =>
      expect(api.updateProfile).toHaveBeenCalledWith(
        2,
        expect.objectContaining({
          master_profile: expect.objectContaining({ summary_notes: "Sam's notes" }),
        }),
      ),
    );
    expect(api.updateProfile).not.toHaveBeenCalledWith(1, expect.anything());
  });

  it("leaving the screen with unsaved edits clears the guard", async () => {
    const setSwitchGuard = vi.fn();
    const { unmount } = renderWithPerson(<ProfileScreen />, { overrides: { setSwitchGuard } });
    fireEvent.change(await screen.findByDisplayValue("Seasoned engineer notes"), {
      target: { value: "Changed" },
    });
    expect(setSwitchGuard).toHaveBeenLastCalledWith("Jordan Rivera has unsaved profile changes.");
    unmount();
    expect(setSwitchGuard).toHaveBeenLastCalledWith(null);
  });

  it("adding a pasted document keeps unsaved edits and refreshes the list", async () => {
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    vi.mocked(api.uploadDocument).mockResolvedValueOnce({ id: 6, filename: "notes.txt", kind: "paste" });
    vi.mocked(api.getProfile)
      .mockResolvedValueOnce(baseProfileDetail)
      .mockResolvedValueOnce({
        ...baseProfileDetail,
        documents: [...baseProfileDetail.documents, { id: 6, filename: "notes.txt", kind: "paste" }],
      });
    renderWithPerson(<ProfileScreen />, { overrides: { refreshPeople } });
    const box = await screen.findByLabelText(/voice notes/i);
    fireEvent.change(box, { target: { value: "Short sentences only." } });
    fireEvent.change(screen.getByPlaceholderText("Document name"), { target: { value: "notes.txt" } });
    fireEvent.change(screen.getByPlaceholderText("Paste resume or notes text"), {
      target: { value: "Led the migration." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add pasted text" }));

    expect(await screen.findByText("notes.txt")).toBeInTheDocument();
    expect(api.uploadDocument).toHaveBeenCalledWith(1, {
      filename: "notes.txt",
      text: "Led the migration.",
    });
    expect(screen.getByLabelText(/voice notes/i)).toHaveValue("Short sentences only.");
    expect(refreshPeople).toHaveBeenCalled();
  });

  it("removes a document after an inline confirm", async () => {
    const refreshPeople = vi.fn().mockResolvedValue(undefined);
    vi.mocked(api.deleteDocument).mockResolvedValueOnce({ deleted: 5 });
    vi.mocked(api.getProfile)
      .mockResolvedValueOnce(baseProfileDetail)
      .mockResolvedValueOnce({ ...baseProfileDetail, documents: [] });
    renderWithPerson(<ProfileScreen />, { overrides: { refreshPeople } });

    fireEvent.click(await screen.findByRole("button", { name: "Remove resume.pdf" }));
    expect(screen.getByText("Remove resume.pdf?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "No" }));
    expect(screen.queryByText("Remove resume.pdf?")).not.toBeInTheDocument();
    expect(api.deleteDocument).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Remove resume.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(api.deleteDocument).toHaveBeenCalledWith(1, 5));
    expect(await screen.findByText(/Upload your existing resumes/)).toBeInTheDocument();
    expect(screen.queryByText("resume.pdf")).not.toBeInTheDocument();
    await waitFor(() => expect(refreshPeople).toHaveBeenCalled());
  });

  it("saving a new email updates the Inbox link in the nav", async () => {
    // The real provider and nav: the link comes from the refreshed list.
    const gmail = "jordan.rivera@gmail.com";
    const before = makePerson({ contact, inbox_url: null });
    const after = {
      ...before,
      contact: { ...contact, email: gmail },
      inbox_url: `https://mail.google.com/mail/?authuser=${gmail}`,
    };
    let saved = false;
    vi.mocked(api.listProfiles).mockImplementation(async () => [saved ? after : before]);
    vi.mocked(api.updateProfile).mockImplementation(async (_id, patch) => {
      saved = true;
      return { ...baseProfileDetail, contact: patch.contact ?? contact };
    });
    render(
      <MemoryRouter initialEntries={["/profiles"]}>
        <PersonProvider>
          <App />
        </PersonProvider>
      </MemoryRouter>,
    );
    const emailBox = await screen.findByLabelText("Email");
    expect(screen.queryByRole("link", { name: "Inbox" })).not.toBeInTheDocument();

    fireEvent.change(emailBox, { target: { value: gmail } });
    fireEvent.click(screen.getByRole("button", { name: "Save name and email" }));

    const inbox = await screen.findByRole("link", { name: "Inbox" });
    expect(inbox).toHaveAttribute("href", after.inbox_url);
    expect(api.updateProfile).toHaveBeenCalledWith(1, {
      name: "Jordan Rivera",
      contact: { ...contact, email: gmail },
    });
  });
});
