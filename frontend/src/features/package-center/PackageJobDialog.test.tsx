import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type AppJob } from "../../api";
import { PackageJobDialog, PackageJobWindow } from "./PackageJobDialog";
import { OPEN_OPERATION_WINDOW_EVENT } from "./operationWindow";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly url: string;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  close = vi.fn();

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }

  emit(job: AppJob) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(job) }));
  }
}

const queued: AppJob = { id: "job-1", module_id: "samba", action: "install", status: "queued", progress: 0, created_at: 1, error: "", current_step: "Queued", log_tail: [] };

describe("PackageJobDialog", () => {
  beforeEach(() => { FakeEventSource.instances = []; vi.stubGlobal("EventSource", FakeEventSource); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("streams progress and logs while the durable job runs", () => {
    render(<PackageJobDialog initialJob={queued} moduleName="Samba" t={(key) => key} onClose={vi.fn()} />);
    const source = FakeEventSource.instances[0];
    expect(source.url).toContain("/api/apps/jobs/job-1/events");

    act(() => {
      source.onopen?.(new Event("open"));
      source.emit({ ...queued, status: "running", progress: 44, current_step: "Installing packages", log_tail: [{ id: 1, created_at: 2, stream: "stdout", line: "Downloading cifs-utils" }] });
    });

    expect(screen.getByText("44%")).toBeInTheDocument();
    expect(screen.getByText("Installing packages")).toBeInTheDocument();
    expect(screen.getByRole("log")).toHaveTextContent("Downloading cifs-utils");
    expect(screen.getByText("package.logConnected")).toBeInTheDocument();

    act(() => source.emit({ ...queued, status: "completed", progress: 100, current_step: "Completed", log_tail: [{ id: 2, created_at: 3, stream: "stdout", line: "Done" }] }));
    expect(screen.getByText("task.completed")).toBeInTheDocument();
    expect(source.close).toHaveBeenCalled();
  });

  it("closes only the log window while leaving the background job untouched", () => {
    const close = vi.fn();
    render(<PackageJobDialog initialJob={queued} t={(key) => key} onClose={close} />);
    expect(screen.getByText("package.backgroundJobHint")).toBeInTheDocument();
    const closeButtons = screen.getAllByRole("button", { name: "action.close" });
    fireEvent.click(closeButtons[closeButtons.length - 1]);
    expect(close).toHaveBeenCalledOnce();
  });

  it("renders operation progress as a separate modal window", () => {
    render(<PackageJobDialog initialJob={queued} moduleName="Menedżer kontenerów" t={(key) => key} onClose={vi.fn()} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveClass("operation-progress-dialog");
    expect(dialog.closest(".modal-backdrop")).not.toBeNull();
  });

  it("renders frameless content inside a native desktop window", () => {
    render(<PackageJobWindow initialJob={queued} moduleName="Samba" t={(key) => key} onClose={vi.fn()} native />);

    expect(screen.getByLabelText("package.liveJobTitle")).toHaveClass("operation-progress-native");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("task.queued")).toBeInTheDocument();
  });

  it("delegates modal requests to the desktop window manager when available", () => {
    const close = vi.fn();
    const listener = (event: Event) => event.preventDefault();
    window.addEventListener(OPEN_OPERATION_WINDOW_EVENT, listener);

    render(<PackageJobDialog initialJob={queued} moduleName="Samba" t={(key) => key} onClose={close} />);

    expect(close).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    window.removeEventListener(OPEN_OPERATION_WINDOW_EVENT, listener);
  });

  it("loads a durable job by id before subscribing to its stream", async () => {
    vi.spyOn(api, "appJob").mockResolvedValue({ ...queued, status: "running", progress: 18 });

    render(<PackageJobDialog jobId="job-1" moduleName="Samba" t={(key) => key} onClose={vi.fn()} />);

    expect(screen.getByText("status.loading")).toBeInTheDocument();
    await waitFor(() => expect(api.appJob).toHaveBeenCalledWith("job-1"));
    expect(await screen.findByText("18%")).toBeInTheDocument();
    expect(FakeEventSource.instances[FakeEventSource.instances.length - 1]?.url).toContain("/api/apps/jobs/job-1/events");
  });

  it("keeps a newer terminal SSE state when an older polling request finishes later", async () => {
    vi.useFakeTimers();
    let resolvePoll: ((job: AppJob) => void) | undefined;
    vi.spyOn(api, "appJob").mockImplementation(() => new Promise((resolve) => { resolvePoll = resolve; }));
    render(<PackageJobDialog initialJob={queued} moduleName="Samba" t={(key) => key} onClose={vi.fn()} />);
    const source = FakeEventSource.instances[0];

    act(() => vi.advanceTimersByTime(2500));
    act(() => source.emit({ ...queued, status: "completed", progress: 100, current_step: "Completed" }));
    await act(async () => resolvePoll?.({ ...queued, status: "running", progress: 30, current_step: "Stale" }));

    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.queryByText("Stale")).not.toBeInTheDocument();
  });
});
