import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CONNECTION_RESTORED_EVENT,
  ConnectionRefreshScope,
  ConnectionStatusMonitor,
  useRefreshOnConnectionRestored,
} from "./ConnectionStatusMonitor";

const t = (key: string) => key;
const language = "pl-PL";

class FakeWebSocket {
  readyState = 0;
  onopen: WebSocket["onopen"] = null;
  onmessage: WebSocket["onmessage"] = null;
  onclose: WebSocket["onclose"] = null;
  onerror: WebSocket["onerror"] = null;
  sent: string[] = [];

  constructor(readonly url: string) {}

  open() {
    this.readyState = 1;
    this.onopen?.call(this as unknown as WebSocket, new Event("open"));
  }

  heartbeat(payload: Record<string, unknown> = {}) {
    this.onmessage?.call(this as unknown as WebSocket, new MessageEvent("message", {
      data: JSON.stringify({ type: "heartbeat", status: "ok", service: "webnas", ...payload }),
    }));
  }

  send(data: string) {
    if (this.readyState !== 1) throw new DOMException("socket is not open", "InvalidStateError");
    this.sent.push(data);
  }

  close() {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.onclose?.call(this as unknown as WebSocket, new Event("close") as CloseEvent);
  }
}

function socketFactory() {
  const sockets: FakeWebSocket[] = [];
  const factory = vi.fn((url: string) => {
    const socket = new FakeWebSocket(url);
    sockets.push(socket);
    return socket as unknown as WebSocket;
  });
  return { sockets, factory };
}

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

  it("shows a planned handover without the global offline alert", async () => {
    const check = vi.fn()
      .mockResolvedValueOnce({ status: "ok", deployment_phase: "switching", update_id: "update-1" })
      .mockResolvedValue({ status: "ok", deployment_phase: null });
    render(<ConnectionStatusMonitor check={check} t={t} language={language} />);
    await settle();

    expect(screen.getByRole("status")).toHaveClass("switching");
    expect(screen.getByText("connection.switching")).toBeInTheDocument();
    expect(screen.queryByText("connection.lost")).not.toBeInTheDocument();

    await advance(3000);
    expect(screen.getByRole("status")).toHaveClass("restored");
    expect(screen.getByText("connection.restored")).toBeInTheDocument();
  });

  it("still reports a real outage when a planned handover stops responding", async () => {
    const check = vi.fn()
      .mockResolvedValueOnce({ status: "ok", deployment_phase: "switching" })
      .mockRejectedValue(new TypeError("network error"));
    render(<ConnectionStatusMonitor check={check} intervalMs={1000} t={t} language={language} />);
    await settle();
    expect(screen.getByText("connection.switching")).toBeInTheDocument();

    await advance(4000);
    expect(screen.getByRole("alert")).toHaveClass("offline");
    expect(screen.getByText("connection.lost")).toBeInTheDocument();
  });

  it("treats two timed-out requests as a confirmed connection loss", async () => {
    const check = vi.fn((signal: AbortSignal) => new Promise<unknown>((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("timed out", "AbortError")));
    }));
    render(<ConnectionStatusMonitor check={check} t={t} language={language} />);
    await settle();
    await advance(5500);

    expect(check).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("alert")).toHaveClass("offline");
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

  it("checks immediately when the browser tab becomes active again", async () => {
    const check = vi.fn(async () => ({ status: "ok" }));
    render(<ConnectionStatusMonitor check={check} t={t} language={language} />);
    await settle();
    await advance(300);

    window.dispatchEvent(new Event("focus"));
    await settle();

    expect(check).toHaveBeenCalledTimes(2);
  });

  it("uses the WebSocket heartbeat as the primary connection signal", async () => {
    const { sockets, factory } = socketFactory();
    render(<ConnectionStatusMonitor
      webSocketFactory={factory}
      webSocketUrl="ws://webnas/api/health/ws"
      t={t}
      language={language}
    />);
    await settle();

    expect(factory).toHaveBeenCalledWith("ws://webnas/api/health/ws");
    act(() => {
      sockets[0].open();
      sockets[0].heartbeat();
    });

    expect(sockets[0].sent).toContain("ping");
    expect(screen.queryByText("connection.lost")).not.toBeInTheDocument();
  });

  it("reports loss immediately when an established WebSocket closes and reconnects", async () => {
    const { sockets, factory } = socketFactory();
    render(<ConnectionStatusMonitor
      webSocketFactory={factory}
      webSocketUrl="ws://webnas/api/health/ws"
      reconnectDelayMs={1000}
      t={t}
      language={language}
    />);
    await settle();
    act(() => {
      sockets[0].open();
      sockets[0].heartbeat();
      sockets[0].close();
    });

    expect(screen.getByRole("alert")).toHaveClass("offline");
    expect(screen.getByText("connection.lost")).toBeInTheDocument();

    await advance(1000);
    expect(factory).toHaveBeenCalledTimes(2);
  });

  it("uses the heartbeat watchdog when a WebSocket stays open but stops responding", async () => {
    const { sockets, factory } = socketFactory();
    render(<ConnectionStatusMonitor
      webSocketFactory={factory}
      webSocketUrl="ws://webnas/api/health/ws"
      heartbeatTimeoutMs={6000}
      t={t}
      language={language}
    />);
    await settle();
    act(() => {
      sockets[0].open();
      sockets[0].heartbeat();
    });

    await advance(6000);

    expect(screen.getByRole("alert")).toHaveClass("offline");
    expect(screen.getByText("connection.lost")).toBeInTheDocument();
  });

  it("reports recovery when a reconnected WebSocket receives a heartbeat", async () => {
    const restored = vi.fn();
    const { sockets, factory } = socketFactory();
    render(<ConnectionStatusMonitor
      webSocketFactory={factory}
      webSocketUrl="ws://webnas/api/health/ws"
      reconnectDelayMs={1000}
      onRestored={restored}
      t={t}
      language={language}
    />);
    await settle();
    act(() => {
      sockets[0].open();
      sockets[0].heartbeat();
      sockets[0].close();
    });
    await advance(1000);
    act(() => {
      sockets[1].open();
      sockets[1].heartbeat();
    });

    expect(screen.getByRole("status")).toHaveClass("restored");
    expect(screen.getByText("connection.restored")).toBeInTheDocument();
    expect(restored).toHaveBeenCalledWith(1);
  });

  it("refreshes only the active application view after recovery", () => {
    const activeRefresh = vi.fn();
    const inactiveRefresh = vi.fn();
    function RefreshProbe({ refresh }: { refresh: () => void }) {
      useRefreshOnConnectionRestored(refresh);
      return null;
    }
    render(<>
      <ConnectionRefreshScope active><RefreshProbe refresh={activeRefresh} /></ConnectionRefreshScope>
      <ConnectionRefreshScope active={false}><RefreshProbe refresh={inactiveRefresh} /></ConnectionRefreshScope>
    </>);

    act(() => window.dispatchEvent(new CustomEvent(CONNECTION_RESTORED_EVENT)));

    expect(activeRefresh).toHaveBeenCalledTimes(1);
    expect(inactiveRefresh).not.toHaveBeenCalled();
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
