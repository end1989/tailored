import { fireEvent, render, screen } from "@testing-library/react";
import CopyButton from "./CopyButton";

function stubClipboard(writeText: () => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
}

describe("CopyButton", () => {
  it("copies the text and shows 'Copied!'", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    render(<CopyButton text="hello world" label="Copy" />);
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText("Copied!")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith("hello world");
  });

  it("shows a fallback message when the clipboard write rejects", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    stubClipboard(writeText);
    render(<CopyButton text="hello world" />);
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(/Copy failed/)).toBeInTheDocument();
  });
});
