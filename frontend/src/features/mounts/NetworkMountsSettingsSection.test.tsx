import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { SettingsAppView } from "../admin/SystemApps";
import { NetworkMountsSettingsSection } from "./NetworkMountsSettingsSection";
import { settingsFixture } from "../../test/settings";

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
    const common = { t, toast: vi.fn(), onSettingsChange: vi.fn().mockResolvedValue(undefined), onOpenApp: vi.fn() };
    const { rerender } = render(<SettingsAppView settings={settingsFixture()} {...common} />);
    expect(screen.queryByRole("button", { name: "settings.category.network" })).not.toBeInTheDocument();

    rerender(<SettingsAppView settings={settingsFixture({ is_admin: true })} {...common} />);
    expect(screen.getByRole("button", { name: "settings.category.network" })).toBeInTheDocument();
  });

  it("uses protocol-dependent fields and never submits mount_point", async () => {
    render(<NetworkMountsSettingsSection isAdmin t={t} toast={vi.fn()} />);
    await waitFor(() => expect(api.mounts).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /mounts.new/ }));

    fireEvent.change(screen.getByLabelText("mounts.name"), { target: { value: "Backup-NAS" } });
    fireEvent.change(screen.getByLabelText("mounts.type"), { target: { value: "nfs" } });
    fireEvent.change(screen.getByLabelText("mounts.host"), { target: { value: "nas.local" } });
    fireEvent.change(screen.getByLabelText("mounts.exportPath"), { target: { value: "/exports/backup" } });
    expect(screen.getByDisplayValue("/mnt/webnas/mnt/Backup-NAS")).toHaveAttribute("readonly");
    expect(screen.queryByLabelText("settings.adminPassword")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));
    await waitFor(() => expect(api.createMount).toHaveBeenCalled());
    const submitted = vi.mocked(api.createMount).mock.calls[0][0] as Record<string, unknown>;
    expect(submitted).not.toHaveProperty("mount_point");
    expect(submitted).not.toHaveProperty("admin_password");
    expect(submitted).toMatchObject({ type: "nfs", export_path: "/exports/backup" });
  });

  it("explains writable network-resource behavior and hides it in read-only mode", async () => {
    render(<NetworkMountsSettingsSection isAdmin t={t} toast={vi.fn()} />);
    await waitFor(() => expect(api.mounts).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /mounts.new/ }));

    expect(screen.getByText("mounts.writeAccessHint")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("mounts.readOnly"));
    expect(screen.queryByText("mounts.writeAccessHint")).not.toBeInTheDocument();
  });

  it("does not load administrative mounts for a regular user", () => {
    render(<NetworkMountsSettingsSection isAdmin={false} t={t} toast={vi.fn()} />);
    expect(api.mounts).not.toHaveBeenCalled();
    expect(screen.queryByText("settings.networkResources")).not.toBeInTheDocument();
  });

  it("shows one localized missing-package warning instead of the raw backend error", async () => {
    vi.mocked(api.mounts).mockResolvedValue([{
      id: "mount-1", name: "media", type: "smb", host: "nas.local", remote: "//nas.local/media",
      mount_point: "/mnt/webnas/mnt/media", owner: "admin", allowed_users: [], allowed_groups: [], read_only: false,
      persistent: true, status: "missing_packages", actual_mounted: false, missing_packages: ["cifs-utils"],
      last_error: "Missing packages: cifs-utils", last_operation: "mount", last_operation_at: null,
      jobs: [], fs: null, migration_status: "ready", config: { has_secret: false },
    }] as never);

    render(<NetworkMountsSettingsSection isAdmin t={t} toast={vi.fn()} />);

    expect(await screen.findByText("mounts.missingPackages: cifs-utils")).toBeInTheDocument();
    expect(screen.queryByText("Missing packages: cifs-utils")).not.toBeInTheDocument();
  });
});
