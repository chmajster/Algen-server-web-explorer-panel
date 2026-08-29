import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type AppJob, type Task } from "../../api";
import { resetRuntimeEventsForTests } from "../../core/realtime/runtimeEvents";
import { settingsFixture } from "../../test/settings";
import { useBackgroundActions } from "./useBackgroundActions";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      appJobs: vi.fn(),
      mounts: vi.fn(),
      ansibleJobs: vi.fn(),
      ansibleScans: vi.fn(),
      hostsManagerOperations: vi.fn(),
      activeNetworkTransaction: vi.fn(),
      updateProgress: vi.fn(),
    },
  };
});

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  addEventListener = vi.fn();

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }
}

const packageJob: AppJob = {
  id: "job-1",
  module_id: "samba",
  action: "install",
  status: "running",
  progress: 20,
  created_at: Date.now() / 1000,
  log_tail: [],
  error: "",
};

const transfer: Task = {
  id: "transfer-1",
  username: "test",
  type: "copy",
  op: "copy",
  status: "running",
  priority: 0,
  created_at: Date.now() / 1000,
  source_paths: ["/home/test/file.txt"],
  destination_path: "/srv",
  started_at: null,
  finished_at: null,
  paused_at: null,
  bytes_transferred: 0,
  total_bytes: 10,
  progress_percent: 0,
  progress: 0,
  speed_bps: 0,
  speed_human: "",
  average_speed_bps: 0,
  average_speed_human: "",
  eta_seconds: null,
  eta_human: "",
  current_file: "file.txt",
  files_done: 0,
  files_total: 1,
  rsync_exit_code: null,
  error_message: "",
  log_tail: [],
  stderr_tail: [],
  command_preview: [],
  retry_count: 0,
  errors: [],
};

function Harness({ permissions, tasks = [], pollInterval = 1000 }: { permissions: string[]; tasks?: Task[]; pollInterval?: number }) {
  const { actions } = useBackgroundActions({
    tasks,
    profile: settingsFixture({ permissions }),
    moduleNames: new Map([["samba", "Samba"]]),
    t: (key) => key,
    pollInterval,
  });
  return <output>{actions.map((action) => `${action.key}:${action.status}:${action.progress ?? ""}`).join(",")}</output>;
}

function runtimeSource() {
  const source = FakeEventSource.instances.find((item) => item.url === "/api/events");
  if (!source) throw new Error("Shared runtime EventSource was not created");
  return source;
}

describe("useBackgroundActions", () => {
  beforeEach(() => {
    resetRuntimeEventsForTests();
    FakeEventSource.instances = [];
    vi.clearAllMocks();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.mocked(api.appJobs).mockResolvedValue([packageJob]);
    vi.mocked(api.mounts).mockResolvedValue([]);
    vi.mocked(api.ansibleJobs).mockResolvedValue([]);
    vi.mocked(api.ansibleScans).mockResolvedValue([]);
    vi.mocked(api.hostsManagerOperations).mockResolvedValue([]);
    vi.mocked(api.activeNetworkTransaction).mockResolvedValue(null);
    vi.mocked(api.updateProgress).mockResolvedValue({
      state: "idle",
      running: false,
      pid: null,
      exit_code: null,
      started_at: null,
      finished_at: null,
      log: "",
      lines: [],
    });
  });

  afterEach(() => {
    resetRuntimeEventsForTests();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("loads only permitted sources while preserving the user's transfer tasks", async () => {
    render(<Harness permissions={["transfers.view_own"]} tasks={[transfer]} />);

    expect(await screen.findByText("transfer:transfer-1:running:0")).toBeInTheDocument();
    expect(api.appJobs).not.toHaveBeenCalled();
    expect(api.mounts).not.toHaveBeenCalled();
    expect(api.ansibleJobs).not.toHaveBeenCalled();
    expect(api.hostsManagerOperations).not.toHaveBeenCalled();
  });

  it("refreshes durable jobs through the shared runtime stream and cleans it on unmount", async () => {
    const completed = { ...packageJob, status: "completed" as const, progress: 100, finished_at: Date.now() / 1000 };
    const view = render(<Harness permissions={["modules.view"]} />);

    expect(await screen.findByText("module:job-1:running:20")).toBeInTheDocument();
    await waitFor(() => expect(FakeEventSource.instances.some((item) => item.url === "/api/events")).toBe(true));
    const source = runtimeSource();
    act(() => source.onopen?.());
    vi.mocked(api.appJobs).mockResolvedValue([completed]);
    act(() => {
      source.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "module.updated", revision: 1, data: {} }),
      }));
    });

    expect(await screen.findByText("module:job-1:completed:100")).toBeInTheDocument();
    view.unmount();
    expect(source.close).toHaveBeenCalled();
  });

  it("uses interval polling only while the shared runtime stream is in fallback", async () => {
    const view = render(<Harness permissions={["modules.view"]} pollInterval={20} />);

    expect(await screen.findByText("module:job-1:running:20")).toBeInTheDocument();
    await waitFor(() => expect(api.appJobs).toHaveBeenCalledTimes(1));
    const source = runtimeSource();
    act(() => source.onopen?.());
    await new Promise((resolve) => window.setTimeout(resolve, 45));
    expect(api.appJobs).toHaveBeenCalledTimes(1);

    act(() => source.onerror?.());
    await waitFor(() => expect(api.appJobs.mock.calls.length).toBeGreaterThanOrEqual(2));
    view.unmount();
  });

  it("expires an active action that an event-driven backend refresh no longer returns", async () => {
    vi.useFakeTimers();
    vi.mocked(api.appJobs).mockReset().mockResolvedValueOnce([packageJob]).mockResolvedValue([]);
    render(<Harness permissions={["modules.view"]} />);

    await act(async () => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("module:job-1:running:20")).toBeInTheDocument();
    const source = runtimeSource();
    act(() => source.onopen?.());
    act(() => {
      source.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({ type: "module.updated", revision: 1, data: {} }),
      }));
    });
    await act(async () => vi.advanceTimersByTimeAsync(0));
    expect(api.appJobs).toHaveBeenCalledTimes(2);

    await act(async () => vi.advanceTimersByTimeAsync(17_000));
    expect(document.querySelector("output")).toBeEmptyDOMElement();
  });
});