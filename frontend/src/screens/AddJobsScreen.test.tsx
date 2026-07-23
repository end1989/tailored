import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AddJobsScreen from "./AddJobsScreen";

vi.mock("../api", () => {
  const contact = { name: "Eldon", email: "e@example.com", phone: null, location: null, links: [] };
  return {
    listProfiles: vi.fn().mockResolvedValue([
      { id: 1, name: "Eldon", contact, has_master_profile: true },
    ]),
    getSettings: vi.fn().mockResolvedValue({
      api_key_set: true,
      fake_mode: false,
      default_template: "slate",
      default_depth: "standard",
      page_size: "Letter",
    }),
    createApplications: vi.fn().mockResolvedValue([]),
  };
});

describe("AddJobsScreen", () => {
  it("parses three URL lines into three preview rows", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AddJobsScreen />
      </MemoryRouter>
    );
    await screen.findByRole("option", { name: "Eldon" });
    fireEvent.change(screen.getByPlaceholderText("https://..."), {
      target: { value: "https://a.example/j1\nhttps://b.example/j2\n\nhttps://c.example/j3\n" },
    });
    expect(screen.getAllByTestId("job-row")).toHaveLength(3);
    expect(screen.getByText("3 jobs to queue")).toBeInTheDocument();
  });
});
