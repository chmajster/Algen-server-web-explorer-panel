import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppJob } from "../../api";
import { PackageJobDialog } from "./PackageJobDialog";

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
  afterEach(() => vi.unstubAllGlobals());

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
});
