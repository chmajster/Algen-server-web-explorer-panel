import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api, type ModuleBackup, type ModuleStatus, type ModuleSummary, type ModuleValidationResult, type PackagePlan } from "../../../api";
import { ModuleApplyPlanDialog } from "./ModuleApplyPlanDialog";
import { ModuleAppShell } from "./ModuleAppShell";
import { ModuleBackups, ModuleDiagnostics, ModuleJobProgress } from "./ModuleComponents";
import { ModuleUninstallDialog } from "./ModuleUninstallDialog";

const t = (key: string) => key;
const status: ModuleStatus = { installed: true, package_version: "4.20", available_version: "4.20", update_available: false, service_state: "active", service_enabled: true, services: {}, configuration_valid: true, health: "healthy", health_message: "Ready", last_action: "restart", last_action_status: "completed", last_error: "", metrics: {} };

describe("module common UI", () => {
  it("shows status and switches shared shell sections", () => {
    const section = vi.fn();
    render(<ModuleAppShell name="Samba" status={status} section="overview" sections={["overview", "logs"]} t={t} onSection={section}><p>content</p></ModuleAppShell>);

    expect(screen.getByText("module.health.healthy")).toBeInTheDocument();
    expect(screen.getByText("4.20", { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "module.section.logs" }));
    expect(section).toHaveBeenCalledWith("logs");
  });

  it("renders active and failed job state accessibly", () => {
    const { rerender } = render(<ModuleJobProgress job={{ id: "1", module_id: "samba", action: "apply", operation: "apply", status: "running", progress: 55, created_at: 1, error: "", current_step: "Validate", log_tail: [] }} t={t} />);
    expect(screen.getByText("task.running", { exact: false })).toBeInTheDocument();
    rerender(<ModuleJobProgress job={{ id: "1", module_id: "samba", action: "apply", operation: "apply", status: "failed", progress: 70, created_at: 1, error: "reload failed", current_step: "Reload", log_tail: [] }} t={t} />);
    expect(screen.getByText("reload failed")).toBeInTheDocument();
  });

  it("renders diagnostics and backup actions", () => {
    const restore = vi.fn(); const remove = vi.fn();
    const backup: ModuleBackup = { id: "a".repeat(32), module_id: "samba", created_at: 1, created_by: "admin", description: "Before edit", automatic: true, checksum: "b".repeat(64), package_version: "4.20", size: 1024, files: ["smb.conf"] };
    const { rerender } = render(<ModuleDiagnostics diagnostics={[{ status: "critical", severity: "critical", title: "Anonymous write", description: "Guest can write", details: "/srv/public", recommended_action: "Disable guest write" }]} t={t} />);
    expect(screen.getByText("Anonymous write")).toBeInTheDocument();
    expect(screen.getByText(/Disable guest write/)).toBeInTheDocument();
    rerender(<ModuleBackups backups={[backup]} t={t} onCreate={vi.fn()} onRestore={restore} onDelete={remove} />);
    fireEvent.click(screen.getByRole("button", { name: "module.restore" }));
    fireEvent.click(screen.getByRole("button", { name: "action.delete" }));
    expect(restore).toHaveBeenCalledWith(backup);
    expect(remove).toHaveBeenCalledWith(backup);
  });

  it("requires explicit SMB1 acknowledgement before applying a plan", async () => {
    const apply = vi.fn().mockResolvedValue(undefined);
    const validation: ModuleValidationResult = { ok: true, errors: [], warnings: ["SMB1 warning"], changes: [{ kind: "global_changed", name: "server min protocol", before: "SMB2", after: "NT1" }], generated_config: "[global]", validator_output: "Loaded services file OK", confirmations_required: ["smb1"] };
    render(<ModuleApplyPlanDialog validation={validation} t={t} onClose={vi.fn()} onApply={apply} />);
    expect(screen.queryByLabelText("settings.adminPassword")).not.toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "module.applyConfiguration" });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByText("module.confirm.smb1"));
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() => expect(apply).toHaveBeenCalledWith(["smb1"]));
  });

  it("requires the Samba name for destructive uninstall and preserves share paths", async () => {
    const plan: PackagePlan = { module_id: "samba", action: "uninstall", distribution: { id: "debian", name: "Debian", version_id: "12", architecture: "x86_64", package_manager: "apt-get" }, compatible: true, blocked_by_proxmox: false, packages: ["samba"], services: ["smbd"], ports: [], config_paths: ["/etc/samba/smb.conf"], data_paths: ["/var/lib/samba"], permissions: [], dependencies: [], conflicts: [], warnings: ["Shared data is preserved"], requires_reboot: false, remove_data: true, steps: ["Remove package samba"] };
    const summary = { id: "samba", manifest: { id: "samba", name: "Samba" }, state: { installed: true }, module_status: status } as unknown as ModuleSummary;
    const planSpy = vi.spyOn(api, "appPlan").mockResolvedValue(plan); const uninstall = vi.spyOn(api, "uninstallModule").mockResolvedValue({ job: { id: "job", module_id: "samba", action: "uninstall", status: "queued", progress: 0, created_at: 1, error: "", log_tail: [] } });
    render(<ModuleUninstallDialog item={summary} activeShares={2} activeSessions={1} t={t} toast={vi.fn()} onClose={vi.fn()} onStarted={vi.fn()} />);
    await screen.findByText("Remove package samba");
    fireEvent.click(screen.getByText("module.uninstallMode.data"));
    expect(screen.queryByLabelText("settings.adminPassword")).not.toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "store.uninstall" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("module.typeModuleName"), { target: { value: "Samba" } });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    await waitFor(() => expect(uninstall).toHaveBeenCalledWith("samba", expect.objectContaining({ remove_config: true, remove_data: true, create_backup: true, confirm_name: "Samba" })));
    expect(plan.data_paths).not.toContain("/srv/media");
    planSpy.mockRestore(); uninstall.mockRestore();
  });
});
