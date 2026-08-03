import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { ShutdownDialog } from "./ShutdownDialog";

const t = (key: string) => key;

afterEach(() => vi.restoreAllMocks());

describe("ShutdownDialog", () => {
  it("schedules a countdown and allows it to be cancelled", async () => {
    vi.spyOn(api, "shutdownPolicy").mockResolvedValue({ detailed_information: false });
    vi.spyOn(api, "scheduleShutdown").mockResolvedValue({ state: "scheduled", deadline: Date.now() / 1000 + 10, remaining_seconds: 10, blocker_count: 0, error: "" });
    vi.spyOn(api, "shutdownStatus").mockResolvedValue({ state: "scheduled", deadline: Date.now() / 1000 + 10, remaining_seconds: 10, blocker_count: 0, error: "" });
    const cancel = vi.spyOn(api, "cancelShutdown").mockResolvedValue({ state: "cancelled" });
    const close = vi.fn();

    render(<ShutdownDialog t={t} onClose={close} />);
    await waitFor(() => expect(api.scheduleShutdown).toHaveBeenCalledWith(10));
    const cancelButtons = screen.getAllByRole("button", { name: "action.cancel" });
    fireEvent.click(cancelButtons[cancelButtons.length - 1]);
    await waitFor(() => expect(cancel).toHaveBeenCalled());
    expect(close).toHaveBeenCalled();
  });

  it("keeps the transfer safeguard when shut down now is requested", async () => {
    vi.spyOn(api, "shutdownPolicy").mockResolvedValue({ detailed_information: true });
    vi.spyOn(api, "scheduleShutdown")
      .mockResolvedValueOnce({ state: "scheduled", deadline: Date.now() / 1000 + 10, remaining_seconds: 10, blocker_count: 1, error: "" })
      .mockResolvedValueOnce({ state: "waiting_for_transfers", deadline: Date.now() / 1000, remaining_seconds: 0, blocker_count: 1, error: "" });
    vi.spyOn(api, "shutdownStatus").mockResolvedValue({ state: "waiting_for_transfers", deadline: Date.now() / 1000, remaining_seconds: 0, blocker_count: 1, error: "" });

    render(<ShutdownDialog t={t} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("shutdown.countdown")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "shutdown.now" }));
    await waitFor(() => expect(api.scheduleShutdown).toHaveBeenLastCalledWith(0));
    expect(await screen.findByText("shutdown.waitingForTransfers")).toBeInTheDocument();
    expect(screen.getByText("systemctl poweroff")).toBeInTheDocument();
  });
});
