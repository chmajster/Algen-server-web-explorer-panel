import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { UpdateProgress } from "../../api";
import { UpdateCompletionDialog, UpdateStatusPage } from "./UpdateStatusPage";

const t = (key: string) => key;

function progress(overrides: Partial<UpdateProgress> = {}): UpdateProgress {
  return {
    id: "update-1",
    state: "waiting",
    phase: "waiting",
    running: true,
    progress: 0,
    pid: null,
    exit_code: null,
    requested_at: 100,
    started_at: null,
    finished_at: null,
    previous_version: "1.0.0",
    target_version: "2.0.0",
    message: "",
    active_count: 0,
    blockers: [],
    log: "update.log",
    lines: [],
    ...overrides,
  };
}

describe("UpdateStatusPage", () => {
  it("shows elapsed minutes and refreshes the timer every second", () => {
    const interval = vi.spyOn(window, "setInterval");
    const startedAt = Math.floor(Date.now() / 1000) - 60;
    render(<UpdateStatusPage value={progress({ state: "running", started_at: startedAt })} connectionError={false} t={t} onRetry={vi.fn()} onReturn={vi.fn()} onLogin={vi.fn()} />);

    expect(screen.getByText("1 min 00 s")).toBeInTheDocument();
    expect(interval).toHaveBeenCalledWith(expect.any(Function), 1000);
    interval.mockRestore();
  });

  it("renders pending, running, success, failed and skipped steps", () => {
    const steps: NonNullable<UpdateProgress["steps"]> = [
      { id: "prepare", status: "success", message: "Ready", started_at: 10, finished_at: 11 },
      { id: "check_operations", status: "running", message: "Checking", started_at: 11, finished_at: null },
      { id: "check_update", status: "pending", message: "", started_at: null, finished_at: null },
      { id: "download_repository", status: "failed", message: "Failed", error: "network error", started_at: 12, finished_at: 13 },
      { id: "download_version", status: "skipped", message: "Not needed", started_at: 13, finished_at: 13 },
    ];
    const { container } = render(<UpdateStatusPage value={progress({ state: "running", phase: "check_operations", steps })} connectionError={false} t={t} onRetry={vi.fn()} onReturn={vi.fn()} onLogin={vi.fn()} />);

    expect(container.querySelectorAll(".update-stepper li")).toHaveLength(5);
    expect(container.querySelector(".update-stepper li.running")).toHaveAttribute("aria-current", "step");
    expect(container.querySelector(".update-stepper li.success")).toBeInTheDocument();
    expect(container.querySelector(".update-stepper li.failed")).toHaveTextContent("network error");
    expect(container.querySelector(".update-stepper li.skipped")).toBeInTheDocument();
    expect(container.querySelector(".update-stepper li.pending")).toBeInTheDocument();
  });

  it("keeps the last step state visible during a temporary connection loss", () => {
    const steps: NonNullable<UpdateProgress["steps"]> = [
      { id: "build_frontend", status: "running", message: "Building", started_at: 10, finished_at: null },
    ];
    const props = { t, onRetry: vi.fn(), onReturn: vi.fn(), onLogin: vi.fn() };
    const { rerender } = render(<UpdateStatusPage value={progress({ state: "running", phase: "build_frontend", progress: 64, steps })} connectionError={false} {...props} />);

    rerender(<UpdateStatusPage value={progress({ state: "running", phase: "build_frontend", progress: 64, steps })} connectionError {...props} />);

    expect(screen.getByText("Building")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "64");
    expect(screen.getByText("updateStatus.reconnecting")).toBeInTheDocument();

    rerender(<UpdateStatusPage value={progress({ state: "completed", phase: "complete", running: false, progress: 100, steps: steps.map((step) => ({ ...step, status: "success", finished_at: 20 })) })} connectionError={false} {...props} />);
    expect(screen.getByText("updateStatus.state.completed")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  it("shows queued and running operations while an update waits", () => {
    render(<UpdateStatusPage
      value={progress({
        active_count: 2,
        blockers: [
          { id: "copy-1", type: "copy", status: "running", started_at: 90, progress: 35, description: "Kopiowanie backupu" },
          { id: "package-1", type: "package.install", status: "queued", started_at: null, progress: null, description: "Instalacja pakietu" },
        ],
      })}
      connectionError={false}
      t={t}
      onRetry={vi.fn()}
      onReturn={vi.fn()}
      onLogin={vi.fn()}
    />);

    expect(screen.getByRole("heading", { name: "updateStatus.title" })).toBeInTheDocument();
    expect(screen.getByText("Kopiowanie backupu")).toBeInTheDocument();
    expect(screen.getByText("Instalacja pakietu")).toBeInTheDocument();
    expect(screen.getByText("35%")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "updateStatus.returnToPanel" })).not.toBeInTheDocument();
  });

  it("keeps the live update log scrolled to the newest line", () => {
    const scrollHeight = vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(480);
    const props = {
      connectionError: false,
      t,
      onRetry: vi.fn(),
      onReturn: vi.fn(),
      onLogin: vi.fn(),
    };
    const { container, rerender } = render(<UpdateStatusPage value={progress({ lines: ["Pierwszy wpis"] })} {...props} />);
    const log = container.querySelector<HTMLPreElement>(".update-status-log pre");

    expect(log).not.toBeNull();
    expect(log?.scrollTop).toBe(480);

    if (log) log.scrollTop = 0;
    rerender(<UpdateStatusPage value={progress({ lines: ["Pierwszy wpis", "Najnowszy wpis"] })} {...props} />);
    expect(log?.scrollTop).toBe(480);
    scrollHeight.mockRestore();
  });

  it("keeps a failed update on the status page and exposes safe recovery actions", () => {
    const retry = vi.fn();
    const returnToPanel = vi.fn();
    const returnToLogin = vi.fn();
    render(<UpdateStatusPage
      value={progress({
        state: "failed",
        phase: "failed",
        failed_phase: "installing",
        running: false,
        progress: 100,
        exit_code: 1,
        finished_at: 200,
        message: "Aktualizacja nie powiodła się.",
        lines: ["Błąd instalatora bez danych wrażliwych"],
      })}
      connectionError
      t={t}
      onRetry={retry}
      onReturn={returnToPanel}
      onLogin={returnToLogin}
    />);

    expect(screen.getByText("Błąd instalatora bez danych wrażliwych")).toBeInTheDocument();
    expect(screen.getByText("updateStatus.phase.installing")).toBeInTheDocument();
    expect(screen.getByText("updateStatus.reconnecting")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.retry" }));
    fireEvent.click(screen.getByRole("button", { name: "updateStatus.returnToLogin" }));
    fireEvent.click(screen.getByRole("button", { name: "updateStatus.returnToPanel" }));
    expect(retry).toHaveBeenCalledOnce();
    expect(returnToLogin).toHaveBeenCalledOnce();
    expect(returnToPanel).toHaveBeenCalledOnce();
  });

  it("shows the version transition in the one-time completion dialog", () => {
    const close = vi.fn();
    render(<UpdateCompletionDialog
      notice={{
        id: "update-1",
        previous_version: "1.0.0",
        current_version: "2.0.0",
        finished_at: 200,
        commit_revision: "abcdef1234567890abcdef1234567890abcdef12",
        commit_date: 300,
      }}
      t={t}
      onClose={close}
    />);

    expect(screen.getByRole("dialog", { name: "updateStatus.successTitle" })).toBeInTheDocument();
    expect(screen.getByText("1.0.0")).toBeInTheDocument();
    expect(screen.getByText("2.0.0")).toBeInTheDocument();
    expect(screen.getByText("abcdef123456")).toHaveAttribute("title", "abcdef1234567890abcdef1234567890abcdef12");
    expect(screen.getByText(new Date(300 * 1000).toLocaleString())).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.close" }));
    expect(close).toHaveBeenCalledOnce();
  });
});
