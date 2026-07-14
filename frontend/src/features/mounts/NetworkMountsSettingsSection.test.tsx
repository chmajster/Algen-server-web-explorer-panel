import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { SettingsAppView } from "../admin/SystemApps";
import { NetworkMountsSettingsSection } from "./NetworkMountsSettingsSection";

vi.mock("../../api", () => ({
  api: {
    mounts: vi.fn(), createMount: vi.fn(), updateMount: vi.fn(), deleteMount: vi.fn(),
    mountAction: vi.fn(), mountLogs: vi.fn(), mountRoots: vi.fn()
  }
}));

const t = (key: string) => key;

describe("network mount settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.mounts).mockResolvedValue([]);
    vi.mocked(api.createMount).mockResolvedValue({} as never);
    vi.mocked(api.mountRoots).mockResolvedValue([]);
  });

  it("shows the Settings section only to administrators", async () => {
    const { rerender } = render(<SettingsAppView language="en-US" theme="dark" isAdmin={false} t={t} toast={vi.fn()} onLanguage={vi.fn()} onTheme={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "settings.networkResources" })).not.toBeInTheDocument();

    rerender(<SettingsAppView language="en-US" theme="dark" isAdmin t={t} toast={vi.fn()} onLanguage={vi.fn()} onTheme={vi.fn()} />);
    expect(screen.getByRole("button", { name: "settings.networkResources" })).toBeInTheDocument();
  });

  it("uses protocol-dependent fields and never submits mount_point", async () => {
    render(<NetworkMountsSettingsSection isAdmin t={t} toast={vi.fn()} />);
    await waitFor(() => expect(api.mounts).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /mounts.new/ }));

    fireEvent.change(screen.getByLabelText("mounts.name"), { target: { value: "Backup-NAS" } });
    fireEvent.change(screen.getByLabelText("mounts.type"), { target: { value: "nfs" } });
    fireEvent.change(screen.getByLabelText("mounts.host"), { target: { value: "nas.local" } });
    fireEvent.change(screen.getByLabelText("mounts.exportPath"), { target: { value: "/exports/backup" } });
    fireEvent.change(screen.getByLabelText("settings.adminPassword"), { target: { value: "secret" } });

    expect(screen.getByDisplayValue("/mnt/webnas/mnt/Backup-NAS")).toHaveAttribute("readonly");
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));
    await waitFor(() => expect(api.createMount).toHaveBeenCalled());
    const submitted = vi.mocked(api.createMount).mock.calls[0][0] as Record<string, unknown>;
    expect(submitted).not.toHaveProperty("mount_point");
    expect(submitted).toMatchObject({ type: "nfs", export_path: "/exports/backup" });
  });

  it("does not load administrative mounts for a regular user", () => {
    render(<NetworkMountsSettingsSection isAdmin={false} t={t} toast={vi.fn()} />);
    expect(api.mounts).not.toHaveBeenCalled();
    expect(screen.queryByText("settings.networkResources")).not.toBeInTheDocument();
  });
});
