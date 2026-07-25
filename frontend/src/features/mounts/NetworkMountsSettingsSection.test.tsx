import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
const mount = (overrides: Record<string, unknown> = {}) => ({
  id: "mount-1", name: "media", type: "smb", host: "nas.local", remote: "//nas.local/media",
  mount_point: "/mnt/webnas/mnt/media", owner: "admin", allowed_users: [], allowed_groups: [], read_only: false,
  persistent: true, status: "mounted", actual_mounted: true, missing_packages: [],
  last_error: null, last_operation: "mount", last_operation_at: 1_700_000_000,
  jobs: [], fs: { total: 100, used: 40, free: 60, fs_type: "cifs" },
  migration_status: "ready", manual_intervention: false, config: { has_secret: false },
  ...overrides,
});

describe("network mount settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.mounts).mockResolvedValue([]);
    vi.mocked(api.createMount).mockResolvedValue({} as never);
    vi.mocked(api.mountAction).mockResolvedValue({ job: null } as never);
    vi.mocked(api.mountRoots).mockResolvedValue([]);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("shows the Settings section only to administrators", async () => {
    const common = { t, toast: vi.fn(), onSettingsChange: vi.fn().mockResolvedValue(undefined), onOpenApp: vi.fn() };
    const { rerender } = render(<SettingsAppView settings={settingsFixture()} {...common} />);
    expect(screen.queryByRole("button", { name: "settings.category.network" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "settings.category.networkResources" })).not.toBeInTheDocument();

    rerender(<SettingsAppView settings={settingsFixture({ is_admin: true })} {...common} />);
    expect(screen.getByRole("button", { name: "settings.category.network" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.category.networkResources" })).toBeInTheDocument();
  });

  it("opens network resources as a top-level Settings category", async () => {
    render(<SettingsAppView settings={settingsFixture({ is_admin: true })} initialSection="networkResources" t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onOpenApp={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "settings.category.networkResources" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.category.networkResources" })).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(api.mounts).toHaveBeenCalled());
    expect(screen.queryByRole("tab", { name: "settings.networkResources" })).not.toBeInTheDocument();
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

  it("shows a resource summary and an actionable empty state", async () => {
    render(<NetworkMountsSettingsSection isAdmin t={t} toast={vi.fn()} />);
    await waitFor(() => expect(api.mounts).toHaveBeenCalled());

    expect(screen.getByLabelText("mounts.summary")).toBeInTheDocument();
    expect(screen.getByText("mounts.emptyHint")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "mounts.addFirst" })).toBeInTheDocument();
  });

  it("calculates all four summary counters from current resources", async () => {
    vi.mocked(api.mounts).mockResolvedValue([
      mount(),
      mount({ id: "mount-2", name: "archive", actual_mounted: false, status: "unmounted" }),
      mount({ id: "mount-3", name: "broken", actual_mounted: false, status: "error", last_error: "Connection failed" }),
    ] as never);

    render(<NetworkMountsSettingsSection isAdmin t={t} toast={vi.fn()} />);
    const summary = await screen.findByLabelText("mounts.summary");
    expect(within(summary).getByText("mounts.summary.total").parentElement).toHaveTextContent("3");
    expect(within(summary).getByText("mounts.summary.mounted").parentElement).toHaveTextContent("1");
    expect(within(summary).getByText("mounts.summary.unmounted").parentElement).toHaveTextContent("2");
    expect(within(summary).getByText("mounts.summary.attention").parentElement).toHaveTextContent("1");
  });

  it("filters locally by query, status and protocol, then resets filters", async () => {
    vi.mocked(api.mounts).mockResolvedValue([
      mount(),
      mount({ id: "mount-2", name: "backup", type: "nfs", host: "backup.local", remote: "backup.local:/volume", actual_mounted: false, status: "unmounted" }),
      mount({ id: "mount-3", name: "documents", type: "webdav", host: "cloud.local", remote: "https://cloud.local/docs", actual_mounted: false, status: "error" }),
    ] as never);
    render(<NetworkMountsSettingsSection isAdmin t={t} toast={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "media" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("mounts.search"), { target: { value: "documents" } });
    expect(screen.getByRole("heading", { name: "documents" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "media" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("mounts.search"), { target: { value: "backup.local" } });
    expect(screen.queryByRole("heading", { name: "media" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "backup" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("mounts.search"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("mounts.filter.status"), { target: { value: "attention" } });
    expect(screen.getByRole("heading", { name: "documents" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "backup" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("mounts.filter.status"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("mounts.filter.protocol"), { target: { value: "nfs" } });
    expect(screen.getByRole("heading", { name: "backup" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "documents" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("mounts.search"), { target: { value: "nothing" } });
    expect(screen.getByText("mounts.noFilterResults")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "mounts.clearFilters" }));
    expect(screen.getByRole("heading", { name: "media" })).toBeInTheDocument();
    expect(screen.getByLabelText("mounts.filter.protocol")).toHaveValue("all");
  });

  it("keeps primary actions hierarchical and opens the secondary menu", async () => {
    vi.mocked(api.mounts).mockResolvedValue([
      mount(),
      mount({ id: "mount-2", name: "backup", actual_mounted: false, status: "unmounted" }),
    ] as never);
    render(<NetworkMountsSettingsSection isAdmin t={t} toast={vi.fn()} />);
    const mediaCard = (await screen.findByRole("heading", { name: "media" })).closest("article")!;
    const backupCard = screen.getByRole("heading", { name: "backup" }).closest("article")!;

    expect(within(mediaCard).getByRole("button", { name: "mounts.unmount" })).toBeInTheDocument();
    expect(within(backupCard).getByRole("button", { name: "mounts.mount" })).toBeInTheDocument();
    fireEvent.click(within(mediaCard).getByRole("button", { name: "mounts.moreActions" }));
    expect(within(mediaCard).getByRole("menu")).toBeInTheDocument();
    expect(within(mediaCard).getByRole("menuitem", { name: "mounts.remount" })).toBeInTheDocument();
    expect(within(mediaCard).getByRole("menuitem", { name: "action.delete" })).toBeInTheDocument();
  });

  it("disables mutable card actions while an operation is running", async () => {
    vi.mocked(api.mounts).mockResolvedValue([mount({ status: "mounting", actual_mounted: false })] as never);
    render(<NetworkMountsSettingsSection isAdmin t={t} toast={vi.fn()} />);
    const card = (await screen.findByRole("heading", { name: "media" })).closest("article")!;
    expect(card).toHaveAttribute("aria-busy", "true");
    expect(within(card).getByRole("button", { name: "mounts.mount" })).toBeDisabled();
    expect(within(card).getByRole("button", { name: "mounts.test" })).toBeDisabled();
    expect(within(card).getByRole("button", { name: "action.edit" })).toBeDisabled();
    expect(within(card).getByText("mounts.operation.mounting")).toBeInTheDocument();
  });

  it("copies the remote path and reports success", async () => {
    const toast = vi.fn();
    vi.mocked(api.mounts).mockResolvedValue([mount()] as never);
    render(<NetworkMountsSettingsSection isAdmin t={t} toast={toast} />);
    fireEvent.click(await screen.findByRole("button", { name: "mounts.copyRemote" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("//nas.local/media"));
    expect(toast).toHaveBeenCalledWith("mounts.pathCopied", "ok");
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
    vi.mocked(api.mounts).mockResolvedValue([mount({
      status: "missing_packages", actual_mounted: false, missing_packages: ["cifs-utils"],
      last_error: "Missing packages: cifs-utils", last_operation_at: null, fs: null,
    })] as never);

    render(<NetworkMountsSettingsSection isAdmin t={t} toast={vi.fn()} />);

    expect(await screen.findByText("mounts.missingPackages: cifs-utils")).toBeInTheDocument();
    expect(screen.queryByText("Missing packages: cifs-utils")).not.toBeInTheDocument();
  });
});
