import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

describe("App shell", () => {
  it("renders the brand and all nav links", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText("Tailored")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Add Jobs" })).toHaveAttribute("href", "/add");
    expect(screen.getByRole("link", { name: "Profiles" })).toHaveAttribute("href", "/profiles");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });

  it("renders the Dashboard placeholder on /", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });
});
