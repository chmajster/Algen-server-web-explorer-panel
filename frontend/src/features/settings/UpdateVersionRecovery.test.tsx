import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UpdateStart } from "../../core/api/contracts";
import { updatesClient } from "../../modules/updates/api/client";
import { UpdateVersionRecovery } from "./UpdateVersionRecovery";

vi.mock("../../modules/updates/api/client", () => ({
  updatesClient: { updateVersions: vi.fn(), recoverUpdate: vi.fn() },
}));
const t = (key: string) => key;
const revision = "a".repeat(40);
const candidates = [{ revision, name: "v0.1.20", kind: "tag" as const, published_at: null }];
const started = { ok: true, state: "waiting", id: "recovery-2" } as UpdateStart;

async function openAndSelect() {
  fireEvent.click(screen.getByRole("button", { name: "updateRecovery.title" }));
  await screen.findByRole("option", { name: /v0.1.20/ });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: revision } });
}

describe("UpdateVersionRecovery", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(updatesClient.updateVersions).mockResolvedValue(candidates);
    vi.mocked(updatesClient.recoverUpdate).mockResolvedValue(started);
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("loads only after opening and requires an explicit selection", async () => {
    render(<UpdateVersionRecovery failedUpdateId="failure-1" disconnected={false} t={t} />);
    expect(updatesClient.updateVersions).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "updateRecovery.title" }));
    await screen.findByRole("option", { name: /v0.1.20/ });
    expect(screen.getByRole("button", { name: "updateRecovery.install" })).toBeDisabled();
    expect(screen.getByText("updateRecovery.warning")).toBeInTheDocument();
    expect(updatesClient.recoverUpdate).not.toHaveBeenCalled();
  });

  it("sends the immutable revision and failure id and updates parent progress", async () => {
    const onStarted = vi.fn();
    render(<UpdateVersionRecovery failedUpdateId="failure-1" disconnected={false} t={t} onStarted={onStarted} />);
    await openAndSelect();
    fireEvent.click(screen.getByRole("button", { name: "updateRecovery.install" }));
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith(started));
    expect(updatesClient.recoverUpdate).toHaveBeenCalledExactlyOnceWith(revision, "failure-1");
    expect(window.confirm).toHaveBeenCalledOnce();
  });

  it("does not install after confirmation is cancelled", async () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    render(<UpdateVersionRecovery failedUpdateId="failure-1" disconnected={false} t={t} />);
    await openAndSelect();
    fireEvent.click(screen.getByRole("button", { name: "updateRecovery.install" }));
    expect(updatesClient.recoverUpdate).not.toHaveBeenCalled();
  });

  it("prevents duplicate submissions and displays starting state", async () => {
    let finish!: (value: UpdateStart) => void;
    vi.mocked(updatesClient.recoverUpdate).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    render(<UpdateVersionRecovery failedUpdateId="failure-1" disconnected={false} t={t} />);
    await openAndSelect();
    const install = screen.getByRole("button", { name: "updateRecovery.install" });
    fireEvent.click(install);
    fireEvent.click(install);
    expect(updatesClient.recoverUpdate).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "updateRecovery.starting" })).toBeDisabled();
    expect(screen.getByRole("combobox")).toBeDisabled();
    await act(async () => finish(started));
  });

  it("shows repository errors and allows retry without automatic installation", async () => {
    vi.mocked(updatesClient.updateVersions).mockRejectedValueOnce(new Error("GitHub unavailable"));
    render(<UpdateVersionRecovery failedUpdateId="failure-1" disconnected={false} t={t} />);
    fireEvent.click(screen.getByRole("button", { name: "updateRecovery.title" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("GitHub unavailable");
    fireEvent.click(screen.getByRole("button", { name: "updateRecovery.refresh" }));
    await screen.findByRole("option", { name: /v0.1.20/ });
    expect(updatesClient.updateVersions).toHaveBeenCalledTimes(2);
    expect(updatesClient.recoverUpdate).not.toHaveBeenCalled();
  });

  it("handles an empty version list", async () => {
    vi.mocked(updatesClient.updateVersions).mockResolvedValue([]);
    render(<UpdateVersionRecovery failedUpdateId="failure-1" disconnected={false} t={t} />);
    fireEvent.click(screen.getByRole("button", { name: "updateRecovery.title" }));
    expect(await screen.findByText("updateRecovery.empty")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "updateRecovery.install" })).toBeDisabled();
  });

  it("keeps a rejected install visible and allows retry", async () => {
    vi.mocked(updatesClient.recoverUpdate).mockRejectedValue(new Error("State changed"));
    render(<UpdateVersionRecovery failedUpdateId="failure-1" disconnected={false} t={t} />);
    await openAndSelect();
    fireEvent.click(screen.getByRole("button", { name: "updateRecovery.install" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("State changed");
    expect(screen.getByRole("button", { name: "updateRecovery.install" })).toBeEnabled();
  });

  it("shows a synchronous preparation failure rather than claiming success", async () => {
    vi.mocked(updatesClient.recoverUpdate).mockResolvedValue({ ...started, ok: false, state: "failed", message: "Download failed" });
    render(<UpdateVersionRecovery failedUpdateId="failure-1" disconnected={false} t={t} />);
    await openAndSelect();
    fireEvent.click(screen.getByRole("button", { name: "updateRecovery.install" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Download failed");
  });

  it("does not allow submission when the connection is lost", async () => {
    const { rerender } = render(<UpdateVersionRecovery failedUpdateId="failure-1" disconnected={false} t={t} />);
    await openAndSelect();
    rerender(<UpdateVersionRecovery failedUpdateId="failure-1" disconnected t={t} />);
    expect(screen.getByRole("button", { name: "updateRecovery.install" })).toBeDisabled();
    expect(updatesClient.recoverUpdate).not.toHaveBeenCalled();
  });
});
