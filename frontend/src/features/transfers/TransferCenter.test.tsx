import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Task } from "../../api";
import { settingsFixture } from "../../test/settings";
import { TransferCenter } from "./TransferCenter";

const task: Task = {
  id: "task-1", username: "bob", type: "copy", op: "copy", status: "running", priority: 0,
  created_at: 1, source_paths: ["/home/bob/source"], destination_path: "/home/bob/target",
  started_at: 1, finished_at: null, paused_at: null, bytes_transferred: 10, total_bytes: 100,
  progress_percent: 10, progress: 10, speed_bps: 10, speed_human: "10 B/s", average_speed_bps: 10,
  average_speed_human: "10 B/s", eta_seconds: 9, eta_human: "9s", current_file: "source",
  files_done: 0, files_total: 1, rsync_exit_code: null, error_message: "", log_tail: [], stderr_tail: [],
  command_preview: [], retry_count: 0, errors: [],
};

const uploadControls = {
  add: vi.fn(), pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(), retry: vi.fn(), setPriority: vi.fn(),
};

describe("TransferCenter permissions", () => {
  it("shows global transfers to an auditor without mutating controls", () => {
    const settings = settingsFixture({ permissions: ["transfers.view_own", "transfers.view_all"] });
    render(<TransferCenter tasks={[task]} settings={settings} t={(key) => key} toast={vi.fn()} uploadControls={uploadControls} />);

    expect(screen.getAllByText(/bob/).length).toBeGreaterThan(0);
    expect(screen.queryByTitle("transfers.pause")).not.toBeInTheDocument();
    expect(screen.queryByTitle("transfers.cancel")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle("transfers.details"));
    expect(screen.getByRole("combobox")).toBeDisabled();
  });

  it("reveals and highlights the exact transfer selected from Actions Center", async () => {
    const close = vi.fn();
    const settings = settingsFixture({ permissions: ["transfers.view_own"] });
    const { container } = render(
      <TransferCenter
        tasks={[{ ...task, username: settings.username }]}
        settings={settings}
        selectedTaskId="task-1"
        onSelectedTaskClose={close}
        t={(key) => key}
        toast={vi.fn()}
        uploadControls={uploadControls}
      />,
    );

    const card = container.querySelector('[data-task-id="task-1"]');
    await waitFor(() => expect(card).toHaveClass("action-target-highlight"));
    expect(screen.getByText("/home/bob/source")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("transfers.details"));
    expect(close).toHaveBeenCalledOnce();
  });
});
