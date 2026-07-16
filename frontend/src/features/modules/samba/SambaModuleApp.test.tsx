import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type ModuleStatus, type ModuleSummary, type SambaConfig } from "../../../api";
import { SambaModuleApp } from "./SambaModuleApp";

vi.mock("../../../api", () => ({ api: { module: vi.fn(), moduleStatus: vi.fn(), moduleConfig: vi.fn(), sambaFirewall: vi.fn(), appJobs: vi.fn(), sambaModuleUsers: vi.fn(), sambaSessions: vi.fn(), testSambaShare: vi.fn(), moduleDiagnostics: vi.fn(), moduleBackups: vi.fn(), validateModuleConfig: vi.fn(), applyModuleConfig: vi.fn(), moduleService: vi.fn(), runModuleDiagnostics: vi.fn(), createModuleBackup: vi.fn(), restoreModuleBackup: vi.fn(), deleteModuleBackup: vi.fn(), sambaModuleUserAction: vi.fn(), openSambaFirewall: vi.fn(), appAction: vi.fn(), appPlan: vi.fn(), uninstallModule: vi.fn(), validateSambaImport: vi.fn() } }));

const t = (key: string) => key;
const status: ModuleStatus = { installed: true, package_version: "4.20", available_version: "4.20", update_available: false, service_state: "active", service_enabled: true, services: { smbd: { state: "active", enabled: true, required: true } }, configuration_valid: true, health: "healthy", health_message: "Samba is healthy", last_action: "restart", last_action_status: "completed", last_error: "", metrics: { shares: 1, sessions: 0, users: 1 } };
const config: SambaConfig = { global_options: { workgroup: "WORKGROUP", "server min protocol": "SMB2" }, shares: [{ name: "Media", path: "/srv/media", comment: "Media files", enabled: true, browseable: true, hidden: false, read_only: true, guest_ok: false, valid_users: [], valid_groups: [], write_list: [], read_list: [], admin_users: [], force_user: null, force_group: null, force_create_mode: "", force_directory_mode: "", inherit_permissions: false, veto_files: "", recycle_bin: false, recycle_versions: true, create_directory: false, directory_owner: "", directory_group: "", directory_mode: "", advanced_options: {}, create_mask: "0664", directory_mask: "0775", allow_proxmox_storage: false }] };

describe("Samba module app", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.moduleStatus).mockResolvedValue(status);
    vi.mocked(api.module).mockResolvedValue({ id: "samba", manifest: { id: "samba", name: "Samba" }, state: { installed: true, installed_version: "4.20", available_version: "4.20", update_available: false }, services: { smbd: "active" }, status: "running", compatible: true, blocked_by_proxmox: false, distribution: {}, jobs: [], module_status: status, capabilities: { backups: true } } as unknown as ModuleSummary);
    vi.mocked(api.moduleConfig).mockResolvedValue(config as unknown as Record<string, unknown>);
    vi.mocked(api.sambaFirewall).mockResolvedValue({ adapter: "ufw", ports: ["445/tcp"], can_manage: true, plan: [["ufw", "allow", "Samba"]] });
    vi.mocked(api.appJobs).mockResolvedValue([]);
    vi.mocked(api.testSambaShare).mockResolvedValue({ share: "Media", path: "/srv/media", resolved_path: "/srv/media", exists: true, is_directory: true, read_only: true, mode: "0755", ok: true, warnings: [], errors: [] });
    vi.mocked(api.moduleDiagnostics).mockResolvedValue({ diagnostics: [], job: null });
    vi.mocked(api.moduleBackups).mockResolvedValue([]);
    vi.mocked(api.sambaModuleUsers).mockResolvedValue([]);
    vi.mocked(api.sambaSessions).mockResolvedValue([]);
  });

  it("shows module health and switches to the share table", async () => {
    render(<SambaModuleApp t={t} toast={vi.fn()} onOpenFolder={vi.fn()} onDirtyChange={vi.fn()} />);
    expect(await screen.findByText("Samba is healthy")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "module.section.shares" }));
    expect(await screen.findByText("Media files")).toBeInTheDocument();
    expect(screen.getByText("module.samba.pathAvailable")).toBeInTheDocument();
  });

  it("opens a selected share from File Manager integration", async () => {
    render(<SambaModuleApp initialSharePath="/srv/media" t={t} toast={vi.fn()} onOpenFolder={vi.fn()} onDirtyChange={vi.fn()} />);
    expect(await screen.findByRole("dialog", { name: "samba.editShare" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("/srv/media")).toBeInTheDocument();
  });

  it("tracks unapplied configuration and presents a structured apply plan", async () => {
    const dirty = vi.fn();
    vi.mocked(api.validateModuleConfig).mockResolvedValue({ ok: true, errors: [], warnings: [], changes: [{ kind: "global_changed", name: "workgroup", before: "WORKGROUP", after: "HOME" }], generated_config: "[global]\nworkgroup = HOME", validator_output: "Loaded services file OK", confirmations_required: [] });
    vi.mocked(api.applyModuleConfig).mockResolvedValue({ job: { id: "job", module_id: "samba", action: "apply", status: "queued", progress: 0, created_at: 1, error: "", log_tail: [] } });
    render(<SambaModuleApp t={t} toast={vi.fn()} onOpenFolder={vi.fn()} onDirtyChange={dirty} />);
    await screen.findByText("Samba is healthy");
    fireEvent.click(screen.getByRole("button", { name: "module.section.configuration" }));
    fireEvent.change(screen.getByLabelText("workgroup"), { target: { value: "HOME" } });
    expect(await screen.findByText("module.unsavedChanges")).toBeInTheDocument();
    await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(true));
    fireEvent.click(screen.getByRole("button", { name: "module.reviewAndApply" }));
    expect(await screen.findByText("module.change.global_changed")).toBeInTheDocument();
  });
});
