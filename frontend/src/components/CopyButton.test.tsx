import { act, fireEvent, render, screen } from "@testing-library/react";
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

  it("stops claiming success when a copy fails right after one succeeded", async () => {
    const writeText = vi
      .fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("denied"));
    stubClipboard(writeText);
    render(<CopyButton text="hello world" />);

    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText("Copied!")).toBeInTheDocument();

    // Second click lands well inside the 1.5s success window, so the stale
    // "Copied!" would otherwise mask the failure.
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(/Copy failed/)).toBeInTheDocument();
    expect(screen.queryByText("Copied!")).not.toBeInTheDocument();
  });

  it("keeps 'Copied!' visible past the first click's deadline after a second copy", async () => {
    vi.useFakeTimers();
    try {
      const writeText = vi.fn().mockResolvedValue(undefined);
      stubClipboard(writeText);
      render(<CopyButton text="hello world" />);

      fireEvent.click(screen.getByRole("button"));
      // Flush the awaited clipboard promise so the success state lands.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1400);
      });
      expect(screen.getByText("Copied!")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button"));
      // Past t=1500, where the first click's timer was due.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(200);
      });
      expect(screen.getByText("Copied!")).toBeInTheDocument();

      // The second click's own 1.5s window still expires on schedule.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1400);
      });
      expect(screen.queryByText("Copied!")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("cancels the pending reset when it unmounts", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    const clearTimeoutSpy = vi.spyOn(window, "clearTimeout");
    try {
      const { unmount } = render(<CopyButton text="hello world" />);
      fireEvent.click(screen.getByRole("button"));
      expect(await screen.findByText("Copied!")).toBeInTheDocument();

      clearTimeoutSpy.mockClear();
      unmount();
      expect(clearTimeoutSpy).toHaveBeenCalled();
    } finally {
      clearTimeoutSpy.mockRestore();
    }
  });
});
