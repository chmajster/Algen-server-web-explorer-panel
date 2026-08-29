import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  resetRuntimeEventsForTests,
  runtimeConnectionState,
  subscribeRuntimeEvent,
} from "./runtimeEvents";

class MockEventSource {
  static instances: MockEventSource[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string, public options?: EventSourceInit) {
    MockEventSource.instances.push(this);
  }

  close() { this.closed = true; }
  open() { this.onopen?.(); }
  message(value: unknown) { this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(value) })); }
  error() { this.onerror?.(); }
}

beforeEach(() => {
  vi.useFakeTimers();
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource);
  resetRuntimeEventsForTests();
});

afterEach(() => {
  resetRuntimeEventsForTests();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("runtime event stream", () => {
  it("shares one EventSource between subscribers", () => {
    const first = subscribeRuntimeEvent("task.updated", vi.fn());
    const second = subscribeRuntimeEvent("job.updated", vi.fn());
    expect(MockEventSource.instances).toHaveLength(1);
    first();
    second();
  });

  it("dispatches typed runtime events", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeRuntimeEvent("task.updated", listener);
    MockEventSource.instances[0].open();
    MockEventSource.instances[0].message({ type: "task.updated", revision: 4, data: {} });
    expect(runtimeConnectionState()).toBe("open");
    expect(listener).toHaveBeenCalledWith({ type: "task.updated", revision: 4, data: {} });
    unsubscribe();
  });

  it("enters fallback on loss and reconnects with backoff without duplicate streams", () => {
    const unsubscribe = subscribeRuntimeEvent("task.updated", vi.fn());
    const first = MockEventSource.instances[0];
    first.open();
    first.error();
    expect(first.closed).toBe(true);
    expect(runtimeConnectionState()).toBe("fallback");
    expect(MockEventSource.instances).toHaveLength(1);

    vi.advanceTimersByTime(999);
    expect(MockEventSource.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(MockEventSource.instances).toHaveLength(2);
    expect(runtimeConnectionState()).toBe("connecting");
    unsubscribe();
  });
});
