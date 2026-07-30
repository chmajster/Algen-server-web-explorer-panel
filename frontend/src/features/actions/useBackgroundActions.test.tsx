import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type AppJob, type Task } from "../../api";
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

describe("useBackgroundActions", () => {
  beforeEach(() => {
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

  it("subscribes to active durable jobs and cleans SSE plus polling on unmount", async () => {
    const view = render(<Harness permissions={["modules.view"]} />);

    expect(await screen.findByText("module:job-1:running:20")).toBeInTheDocument();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(FakeEventSource.instances[0].url).toContain("/api/apps/jobs/job-1/events");
    act(() => {
      FakeEventSource.instances[0].onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({ ...packageJob, status: "completed", progress: 100, finished_at: Date.now() / 1000 }),
        }),
      );
    });
    expect(await screen.findByText("module:job-1:completed:100")).toBeInTheDocument();
    expect(FakeEventSource.instances[0].close).toHaveBeenCalled();

    const callsBeforeUnmount = vi.mocked(api.appJobs).mock.calls.length;
    view.unmount();
    expect(FakeEventSource.instances[0].close).toHaveBeenCalled();
    await new Promise((resolve) => window.setTimeout(resolve, 45));
    expect(api.appJobs).toHaveBeenCalledTimes(callsBeforeUnmount);
  });

  it("does not let a stale polling response overwrite a newer SSE update", async () => {
    let resolveStale: ((jobs: AppJob[]) => void) | undefined;
    const completed = { ...packageJob, status: "completed" as const, progress: 100, finished_at: Date.now() / 1000 };
    vi.mocked(api.appJobs)
      .mockReset()
      .mockResolvedValueOnce([packageJob])
      .mockImplementationOnce(() => new Promise((resolve) => { resolveStale = resolve; }))
      .mockResolvedValue([completed]);
    const view = render(<Harness permissions={["modules.view"]} pollInterval={20} />);

    expect(await screen.findByText("module:job-1:running:20")).toBeInTheDocument();
    await waitFor(() => expect(api.appJobs).toHaveBeenCalledTimes(2));
    act(() => {
      FakeEventSource.instances[0].onmessage?.(
        new MessageEvent("message", { data: JSON.stringify(completed) }),
      );
    });
    await act(async () => resolveStale?.([packageJob]));

    expect(screen.getByText("module:job-1:completed:100")).toBeInTheDocument();
    view.unmount();
  });

  it("expires an active action that a successful backend refresh no longer returns", async () => {
    vi.useFakeTimers();
    vi.mocked(api.appJobs).mockReset().mockResolvedValueOnce([packageJob]).mockResolvedValue([]);
    render(<Harness permissions={["modules.view"]} pollInterval={1000} />);

    await act(async () => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("module:job-1:running:20")).toBeInTheDocument();

    await act(async () => vi.advanceTimersByTimeAsync(17_000));
    expect(document.querySelector("output")).toBeEmptyDOMElement();
  });
});
