import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import PersonPicker from "./PersonPicker";
import { PersonProvider, usePerson } from "../person";
import type { PersonContextValue } from "../person";
import * as api from "../api";
import { makePerson, renderWithPerson } from "../test-utils";
import type { PersonTestOptions } from "../test-utils";

vi.mock("../api", () => ({ listProfiles: vi.fn() }));

const ADD_OPTION = "Add a person…"; // U+2026, as the spec writes it

const JORDAN = makePerson();
const SAM = makePerson({
  id: 2,
  name: "Sam Lee",
  contact: { name: "Sam Lee", email: "sam@example.com", links: [] },
  created_at: "2026-02-01T00:00:00+00:00",
});

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function renderPicker(opts: PersonTestOptions = {}) {
  return renderWithPerson(
    <>
      <PersonPicker />
      <Where />
    </>,
    { people: [JORDAN, SAM], ...opts }
  );
}

const picker = () => screen.getByRole("combobox", { name: "Person" });
const where = () => screen.getByTestId("where");

describe("PersonPicker with people", () => {
  it("lists every person plus Add a person, with the current person selected", () => {
    renderPicker({ personId: 2 });
    const options = within(picker()).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Jordan Rivera", "Sam Lee", ADD_OPTION]);
    expect(picker()).toHaveValue("2");
  });

  it("labels options with labelFor", () => {
    renderPicker({
      overrides: { labelFor: (p) => `${p.name} (${p.contact.email})` },
    });
    expect(within(picker()).getByRole("option", { name: "Sam Lee (sam@example.com)" })).toBeInTheDocument();
  });

  it("asks the provider to switch, and stays on the page", () => {
    const r = renderPicker({ route: "/add" });
    fireEvent.change(picker(), { target: { value: "2" } });
    expect(r.ctx.requestSwitch).toHaveBeenCalledWith(2);
    expect(where()).toHaveTextContent("/add");
  });

  it("goes back to the dashboard after a switch made on an application page", () => {
    renderPicker({ route: "/applications/5" });
    fireEvent.change(picker(), { target: { value: "2" } });
    expect(where()).toHaveTextContent(/^\/$/);
  });

  it("stays on the application page when the guard holds the switch back", () => {
    renderPicker({
      route: "/applications/5",
      overrides: { requestSwitch: vi.fn().mockReturnValue(false) },
    });
    fireEvent.change(picker(), { target: { value: "2" } });
    expect(where()).toHaveTextContent("/applications/5");
    expect(picker()).toHaveValue("1");
  });

  it("opens the create form for Add a person and snaps back to the current person", () => {
    const r = renderPicker();
    fireEvent.change(picker(), { target: { value: "new" } });
    expect(r.ctx.requestSwitch).toHaveBeenCalledWith("new");
    expect(where()).toHaveTextContent("/profiles?new=1");
    expect(picker()).toHaveValue("1");
  });

  it("links the current person's inbox in a new tab", () => {
    renderPicker({
      people: [makePerson({ inbox_url: "https://mail.google.com/mail/?authuser=jordan@gmail.com" })],
    });
    const inbox = screen.getByRole("link", { name: "Inbox" });
    expect(inbox).toHaveAttribute("href", "https://mail.google.com/mail/?authuser=jordan@gmail.com");
    expect(inbox).toHaveAttribute("target", "_blank");
    expect(inbox).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows no Inbox link when the person has no inbox_url", () => {
    renderPicker();
    expect(screen.queryByRole("link", { name: "Inbox" })).not.toBeInTheDocument();
  });
});

describe("PersonPicker without a person", () => {
  it("offers an Add a person link when there are no people", () => {
    renderPicker({ people: [] });
    expect(screen.queryByRole("combobox", { name: "Person" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add a person" })).toHaveAttribute(
      "href",
      "/profiles?new=1"
    );
  });

  it("shows neither the select nor the link while loading", () => {
    renderPicker({ loading: true });
    expect(screen.queryByRole("combobox", { name: "Person" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Add a person" })).not.toBeInTheDocument();
  });

  it("does not claim there are no people when the list failed to load", () => {
    renderPicker({ people: [], overrides: { error: "API 500: boom" } });
    expect(screen.queryByRole("link", { name: "Add a person" })).not.toBeInTheDocument();
  });
});

describe("PersonPicker prompts", () => {
  const pending: PersonContextValue["pendingSwitch"] = {
    target: 2,
    message: "Jordan Rivera has unsaved profile changes.",
  };

  it("shows a held switch inline with Switch anyway and Stay", () => {
    const r = renderPicker({
      route: "/applications/5",
      overrides: { pendingSwitch: pending, confirmSwitch: vi.fn().mockReturnValue(2) },
    });
    const prompt = screen.getByRole("alert");
    expect(prompt).toHaveTextContent("Jordan Rivera has unsaved profile changes.");
    fireEvent.click(within(prompt).getByRole("button", { name: "Switch anyway" }));
    expect(r.ctx.confirmSwitch).toHaveBeenCalled();
    expect(where()).toHaveTextContent(/^\/$/);
  });

  it("Stay cancels the held switch", () => {
    const r = renderPicker({ overrides: { pendingSwitch: pending } });
    fireEvent.click(screen.getByRole("button", { name: "Stay" }));
    expect(r.ctx.cancelSwitch).toHaveBeenCalled();
    expect(where()).toHaveTextContent(/^\/$/);
  });

  it("opens the create form when a held Add a person is confirmed", () => {
    renderPicker({
      overrides: {
        pendingSwitch: { target: "new", message: pending.message },
        confirmSwitch: vi.fn().mockReturnValue("new"),
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Switch anyway" }));
    expect(where()).toHaveTextContent("/profiles?new=1");
  });

  it("shows the notice with a Dismiss button", () => {
    const r = renderPicker({ overrides: { notice: "Sam Lee was removed." } });
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Sam Lee was removed.");
    fireEvent.click(within(notice).getByRole("button", { name: "Dismiss" }));
    expect(r.ctx.setNotice).toHaveBeenCalledWith(null);
  });

  it("shows no prompt and no notice by default", () => {
    renderPicker();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("PersonPicker with the real provider", () => {
  let latest: PersonContextValue;

  function Guard({ message }: { message: string | null }) {
    const ctx = usePerson();
    latest = ctx;
    const { setSwitchGuard } = ctx;
    useEffect(() => {
      setSwitchGuard(message);
      return () => setSwitchGuard(null);
    }, [message, setSwitchGuard]);
    return null;
  }

  function renderLive(message: string | null) {
    render(
      <MemoryRouter>
        <PersonProvider>
          <Guard message={message} />
          <PersonPicker />
        </PersonProvider>
      </MemoryRouter>
    );
  }

  beforeEach(() => {
    localStorage.clear();
    vi.mocked(api.listProfiles).mockReset();
  });

  it("holds a guarded pick, keeps showing the current person, then switches on confirm", async () => {
    vi.mocked(api.listProfiles).mockResolvedValue([JORDAN, SAM]);
    renderLive("Jordan Rivera has unsaved profile changes.");
    await screen.findByRole("combobox", { name: "Person" });

    fireEvent.change(picker(), { target: { value: "2" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Jordan Rivera has unsaved profile changes.");
    expect(picker()).toHaveValue("1");

    fireEvent.click(screen.getByRole("button", { name: "Switch anyway" }));
    expect(picker()).toHaveValue("2");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("switches straight away without a guard", async () => {
    vi.mocked(api.listProfiles).mockResolvedValue([JORDAN, SAM]);
    renderLive(null);
    await screen.findByRole("combobox", { name: "Person" });
    fireEvent.change(picker(), { target: { value: "2" } });
    expect(picker()).toHaveValue("2");
  });

  it("updates the Inbox link when a refresh brings a new email", async () => {
    vi.mocked(api.listProfiles).mockResolvedValueOnce([JORDAN]);
    renderLive(null);
    await screen.findByRole("combobox", { name: "Person" });
    expect(screen.queryByRole("link", { name: "Inbox" })).not.toBeInTheDocument();

    vi.mocked(api.listProfiles).mockResolvedValueOnce([
      { ...JORDAN, inbox_url: "https://mail.google.com/mail/?authuser=jordan@gmail.com" },
    ]);
    await act(() => latest.refreshPeople());
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Inbox" })).toHaveAttribute(
        "href",
        "https://mail.google.com/mail/?authuser=jordan@gmail.com"
      )
    );
  });
});
