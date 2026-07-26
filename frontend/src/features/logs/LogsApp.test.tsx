import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type LogEntry, type LogSourcesResponse } from "../../api";
import { LogsApp } from "./LogsApp";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    api: {
      ...actual.api,
      logSources: vi.fn(), logEntries: vi.fn(), logServices: vi.fn(), logBoots: vi.fn(), logContainers: vi.fn(),
      logSavedViews: vi.fn(), createLogSavedView: vi.fn(), deleteLogSavedView: vi.fn(), exportLogs: vi.fn(),
    },
  };
});

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, EventListener>();
  closed = false;
  constructor(public url: string) { FakeEventSource.instances.push(this); }
  addEventListener(name: string, listener: EventListener) { this.listeners.set(name, listener); }
  close() { this.closed = true; }
  emit(entry: LogEntry) { this.onmessage?.({ data: JSON.stringify(entry) } as MessageEvent); }
}

const sources: LogSourcesResponse = {
  groups: [
    { id: "journal", label: "journal", items: [{ id: "journal", label: "System journal", available: true, status: "available", permission: "logs.view_system" }] },
    { id: "services", label: "services", items: [] },
    { id: "containers", label: "containers", items: [] },
  ],
  capabilities: { journal: true, docker: true, live: true, export: true },
};
const entry: LogEntry = {
  id: "cursor-1", timestamp: "2026-07-25T10:20:30.123Z", priority: 3, severity: "error", source: "journal",
  unit: "webnas.service", identifier: "python", hostname: "nas", pid: 123, uid: 1000, message: "Example failure",
  cursor: "cursor-1", fields: { _BOOT_ID: "a".repeat(32), _CMDLINE: "python webnas" },
};
const permissions = ["logs.view_own", "logs.view_system", "logs.view_services", "logs.view_containers", "logs.live", "logs.export", "logs.saved_views.manage"];
const t = (key: string) => key;

describe("LogsApp", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("prompt", vi.fn().mockReturnValue("My errors"));
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
    vi.mocked(api.logSources).mockResolvedValue(sources);
    vi.mocked(api.logEntries).mockResolvedValue({ items: [entry], next_cursor: "next", has_more: true, direction: "older", limit: 300, truncated: false });
    vi.mocked(api.logServices).mockResolvedValue({ items: [{ unit: "webnas.service", load: "loaded", active: "active", sub: "running", description: "WebNAS" }], status: "available" });
    vi.mocked(api.logBoots).mockResolvedValue({ items: [{ id: "a".repeat(32), index: 0, first: null, last: null, current: true }], status: "available" });
    vi.mocked(api.logContainers).mockResolvedValue({ items: [{ id: "b".repeat(64), name: "proxy", image: "nginx", state: "running", status: "Up" }], status: "available" });
    vi.mocked(api.logSavedViews).mockResolvedValue({ items: [] });
  });

  it("renders detected sources, dynamic services, containers and virtualized entries", async () => {
    render(<LogsApp permissions={permissions} t={t} toast={vi.fn()} />);

    expect(await screen.findByText("Example failure")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /System journal/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /webnas.service/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /proxy/ })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("debounces full-text search and sends filters to the backend", async () => {
    render(<LogsApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("Example failure");
    vi.mocked(api.logEntries).mockClear();

    fireEvent.change(screen.getByLabelText("logs.search"), { target: { value: '"exact failure"' } });
    expect(api.logEntries).not.toHaveBeenCalled();
    await waitFor(() => expect(api.logEntries).toHaveBeenCalledWith(expect.objectContaining({ query: '"exact failure"' }), expect.any(AbortSignal)), { timeout: 1200 });

    fireEvent.click(screen.getByRole("button", { name: /logs.filters/ }));
    fireEvent.change(screen.getByLabelText("PID"), { target: { value: "123" } });
    fireEvent.click(screen.getByText("logs.onlyErrors"));
    await waitFor(() => expect(api.logEntries).toHaveBeenLastCalledWith(expect.objectContaining({ pid: 123, priority: [0, 1, 2, 3] }), expect.any(AbortSignal)));
  });

  it("selects services and boots without client-side filtering", async () => {
    render(<LogsApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("Example failure");

    fireEvent.click(screen.getByRole("button", { name: /webnas.service/ }));
    await waitFor(() => expect(api.logEntries).toHaveBeenLastCalledWith(expect.objectContaining({ source: "service:webnas.service", unit: "webnas.service" }), expect.any(AbortSignal)));
    fireEvent.click(screen.getByRole("button", { name: /logs.filters/ }));
    fireEvent.change(screen.getByLabelText("logs.boot"), { target: { value: "a".repeat(32) } });
    await waitFor(() => expect(api.logEntries).toHaveBeenLastCalledWith(expect.objectContaining({ boot_id: "a".repeat(32) }), expect.any(AbortSignal)));
  });

  it("loads older pages and opens a complete details panel", async () => {
    render(<LogsApp permissions={permissions} t={t} toast={vi.fn()} />);
    fireEvent.click(await screen.findByText("Example failure"));
    expect(screen.getByText("logs.entryDetails")).toBeInTheDocument();
    expect(screen.getByText("_BOOT_ID")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /logs.copyMessage/ }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("Example failure");

    fireEvent.click(screen.getByText("logs.loadOlder"));
    await waitFor(() => expect(api.logEntries).toHaveBeenCalledWith(expect.objectContaining({ cursor: "next" }), undefined));
  });

  it("renders an inferred traceback as one expandable error and preserves formatting", async () => {
    const traceback = [
      "Traceback (most recent call last):",
      '  File "/app/main.py", line 4, in run',
      "    value.get()",
      "AttributeError: list has no attribute get",
    ].join("\n");
    vi.mocked(api.logEntries).mockResolvedValue({
      items: [{
        ...entry,
        id: "traceback",
        message: traceback,
        original_priority: 6,
        original_severity: "info",
        priority: 3,
        severity: "error",
        severity_inferred: true,
        severity_reason: "python_traceback",
        fields: { merged_count: 4 },
      }],
      next_cursor: null, has_more: false, direction: "older", limit: 300, truncated: false,
    });

    render(<LogsApp permissions={permissions} t={t} toast={vi.fn()} />);

    const summary = await screen.findByText("AttributeError: list has no attribute get");
    expect(screen.getAllByText("logs.severity.error")).toHaveLength(2);
    fireEvent.click(summary);
    expect(screen.getByText("logs.severityCorrected", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("info (6)")).toBeInTheDocument();
    expect(screen.getByText("error (3)")).toBeInTheDocument();
    const formatted = screen.getByText((_content, element) => element?.tagName === "PRE" && element.textContent === traceback);
    expect(formatted.tagName).toBe("PRE");
    expect(formatted).toHaveTextContent('File "/app/main.py", line 4, in run', { normalizeWhitespace: false });

    fireEvent.click(screen.getByText("logs.copyRecord"));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining("[error/3; original=info/6]"));
  });

  it("uses effective priority for the errors filter and supports legacy entries", async () => {
    render(<LogsApp permissions={permissions} t={t} toast={vi.fn()} />);
    expect(await screen.findByText("Example failure")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /logs.filters/ }));
    fireEvent.click(screen.getByText("logs.onlyErrors"));
    await waitFor(() => expect(api.logEntries).toHaveBeenLastCalledWith(
      expect.objectContaining({ priority: [0, 1, 2, 3] }),
      expect.any(AbortSignal),
    ));
    fireEvent.click(screen.getByText("Example failure"));
    expect(screen.getAllByText("error (3)")).toHaveLength(2);
  });

  it("buffers live entries while paused and closes the stream on unmount", async () => {
    const { unmount } = render(<LogsApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("Example failure");
    fireEvent.click(screen.getByRole("button", { name: /logs.live/ }));
    expect(FakeEventSource.instances).toHaveLength(1);
    const stream = FakeEventSource.instances[0];
    fireEvent.click(screen.getByRole("button", { name: /logs.pause/ }));
    act(() => stream.emit({ ...entry, id: "cursor-2", message: "New live entry" }));
    expect(screen.queryByText("New live entry")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /logs.resume/ })).toHaveTextContent("1");

    fireEvent.click(screen.getByRole("button", { name: /logs.resume/ }));
    expect(await screen.findByText("New live entry")).toBeInTheDocument();
    unmount();
    expect(stream.closed).toBe(true);
  });

  it("exports and stores the current view", async () => {
    vi.mocked(api.exportLogs).mockResolvedValue({ blob: new Blob(["data"]), filename: "logs.json", truncated: false });
    vi.mocked(api.createLogSavedView).mockResolvedValue({ id: "c".repeat(32), name: "My errors", source: "journal", query: "", filters: {}, columns: [], sort: "newest", view_mode: "compact", builtin: false });
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:test"), revokeObjectURL: vi.fn() });
    render(<LogsApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("Example failure");

    fireEvent.change(screen.getByLabelText("logs.export"), { target: { value: "json" } });
    await waitFor(() => expect(api.exportLogs).toHaveBeenCalledWith(expect.objectContaining({ format: "json", source: "journal" })));
    fireEvent.click(screen.getByTitle("logs.saveView"));
    await waitFor(() => expect(api.createLogSavedView).toHaveBeenCalled());
    expect(await screen.findByText("My errors")).toBeInTheDocument();
  });
});
