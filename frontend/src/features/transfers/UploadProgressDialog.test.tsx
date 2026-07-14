import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Task } from "../../api";
import { UploadProgressDialog } from "./UploadProgressDialog";

function uploadTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "upload-1", type: "upload", op: "upload", status: "running", priority: 0, created_at: 100,
    source_paths: ["archive.zip"], destination_path: "/home/alice", started_at: 100, finished_at: null, paused_at: null,
    bytes_transferred: 512, total_bytes: 1024, progress_percent: 50, progress: 50,
    speed_bps: 256, speed_human: "256 B/s", average_speed_bps: 256, average_speed_human: "256 B/s",
    eta_seconds: 2, eta_human: "2s", current_file: "archive.zip", files_done: 0, files_total: 1,
    rsync_exit_code: null, error_message: "", log_tail: [], stderr_tail: [], command_preview: [], retry_count: 0, errors: [],
    ...overrides,
  };
}

describe("upload progress dialog", () => {
  it("shows percentage, transferred bytes, ETA and permits cancellation", () => {
    const cancel = vi.fn();
    render(<UploadProgressDialog tasks={[uploadTask()]} t={(key) => key} onClose={vi.fn()} onCancel={cancel} onRetry={vi.fn()} />);

    expect(screen.getAllByText("50%").length).toBeGreaterThan(0);
    expect(screen.getByText("transfers.eta")).toBeInTheDocument();
    expect(screen.getByText("/home/alice")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /upload.cancelAll/ }));
    expect(cancel).toHaveBeenCalledWith("upload-1");
  });

  it("shows completion time and retry for a failed upload", () => {
    const retry = vi.fn();
    render(<UploadProgressDialog tasks={[uploadTask({ status: "failed", finished_at: 110, error_message: "Network error" })]} t={(key) => key} onClose={vi.fn()} onCancel={vi.fn()} onRetry={retry} />);

    expect(screen.getByText("Network error")).toBeInTheDocument();
    expect(screen.getByText("upload.finished")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /upload.retryFailed/ }));
    expect(retry).toHaveBeenCalledWith("upload-1");
  });
});
