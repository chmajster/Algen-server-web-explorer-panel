import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectionStatusMonitor } from "./ConnectionStatusMonitor";

const t = (key: string) => key;
const language = "pl-PL";

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function advance(milliseconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

describe("ConnectionStatusMonitor", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-30T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps the notification hidden while the backend is available", async () => {
    const check = vi.fn(async () => ({ status: "ok" }));
    render(<ConnectionStatusMonitor check={check} t={t} language={language} />);
    await settle();

    expect(check).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("connection.lost")).not.toBeInTheDocument();
  });

  it("ignores a single failed check", async () => {
    const check = vi.fn()
      .mockRejectedValueOnce(new TypeError("network error"))
      .mockResolvedValue({ status: "ok" });
    render(<ConnectionStatusMonitor check={check} t={t} language={language} />);
    await settle();

    expect(screen.queryByText("connection.lost")).not.toBeInTheDocument();
    await advance(3000);

    expect(check).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("connection.lost")).not.toBeInTheDocument();
  });

  it("reports a confirmed connection loss after two failed checks", async () => {
    const check = vi.fn().mockRejectedValue(new TypeError("network error"));
    render(<ConnectionStatusMonitor check={check} t={t} language={language} />);
    await settle();
    await advance(3000);

    expect(screen.getByRole("alert")).toHaveClass("offline");
    expect(screen.getByText("connection.lost")).toBeInTheDocument();
    expect(screen.getByText("connection.reconnecting")).toBeInTheDocument();
  });

  it("updates the outage timer every second", async () => {
    const check = vi.fn().mockRejectedValue(new TypeError("network error"));
    render(<ConnectionStatusMonitor check={check} t={t} language={language} />);
    await settle();
    await advance(3000);
    await advance(2000);

    expect(screen.getByText("00:00:02")).toBeInTheDocument();
  });

  it("shows recovery, reports the outage duration and hides after five seconds", async () => {
    const restored = vi.fn();
    const check = vi.fn()
      .mockRejectedValueOnce(new TypeError("network error"))
      .mockRejectedValueOnce(new TypeError("network error"))
      .mockResolvedValue({ status: "ok" });
    render(<ConnectionStatusMonitor check={check} onRestored={restored} t={t} language={language} />);
    await settle();
    await advance(3000);
    await advance(3000);

    expect(screen.getByRole("status")).toHaveClass("restored");
    expect(screen.getByText("connection.restored")).toBeInTheDocument();
    expect(screen.getByText("00:00:03")).toBeInTheDocument();
    expect(restored).toHaveBeenCalledWith(3);

    await advance(4999);
    expect(screen.getByText("connection.restored")).toBeInTheDocument();
    await advance(1);
    expect(screen.queryByText("connection.restored")).not.toBeInTheDocument();
  });

  it("does not start another health check while one is in progress", async () => {
    let resolveCheck: ((value: unknown) => void) | undefined;
    const check = vi.fn(() => new Promise<unknown>((resolve) => {
      resolveCheck = resolve;
    }));
    render(<ConnectionStatusMonitor check={check} t={t} language={language} />);
    await settle();

    await advance(9000);
    expect(check).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveCheck?.({ status: "ok" });
      await Promise.resolve();
    });
    await advance(3000);
    expect(check).toHaveBeenCalledTimes(2);
  });

  it("cleans up requests, timers and listeners when unmounted", async () => {
    let requestSignal: AbortSignal | undefined;
    const check = vi.fn((signal: AbortSignal) => new Promise<unknown>((_resolve, reject) => {
      requestSignal = signal;
      signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    const view = render(<ConnectionStatusMonitor check={check} t={t} language={language} />);
    await settle();

    view.unmount();

    expect(requestSignal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    window.dispatchEvent(new Event("focus"));
    await advance(6000);
    expect(check).toHaveBeenCalledTimes(1);
  });
});
