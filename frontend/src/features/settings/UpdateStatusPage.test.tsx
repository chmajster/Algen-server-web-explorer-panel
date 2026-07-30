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
      notice={{ id: "update-1", previous_version: "1.0.0", current_version: "2.0.0", finished_at: 200 }}
      t={t}
      onClose={close}
    />);

    expect(screen.getByRole("dialog", { name: "updateStatus.successTitle" })).toBeInTheDocument();
    expect(screen.getByText("1.0.0")).toBeInTheDocument();
    expect(screen.getByText("2.0.0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.close" }));
    expect(close).toHaveBeenCalledOnce();
  });
});
