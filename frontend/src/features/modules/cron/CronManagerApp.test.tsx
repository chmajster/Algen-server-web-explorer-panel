import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type CronJob, type CronManagerStatus } from "../../../api";
import { CronManagerApp } from "./CronManagerApp";

vi.mock("../../../api", async () => {
  const actual = await vi.importActual<typeof import("../../../api")>("../../../api");
  return { ...actual, api: { ...actual.api, cronStatus: vi.fn(), cronJobs: vi.fn(), cronDiagnostics: vi.fn(), cronLogs: vi.fn(), cronHistory: vi.fn(), validateCronJob: vi.fn(), createCronJob: vi.fn(), updateCronJob: vi.fn(), deleteCronJob: vi.fn(), setCronJobEnabled: vi.fn(), duplicateCronJob: vi.fn(), appJob: vi.fn() } };
});

const t = (key: string) => key;
const status: CronManagerStatus = { installed: true, crontab_available: true, daemon: "cron", service_state: "active", service_enabled: true, configuration_valid: true, timezone: "Europe/Warsaw", config_path: "/etc/cron.d/webnas", blocked_by_proxmox: false, dashboard: { active: 1, inactive: 0, errors: 0, recently_run: 0, total: 1 } };
const job: CronJob = { id: "11111111-1111-4111-8111-111111111111", name: "Backup NAS", description: "", user: "root", schedule: "*/5 * * * *", command: "/usr/local/bin/backup.sh", working_directory: null, environment: [], timeout_seconds: null, enabled: true, source: "webnas", status: "enabled", read_only: false, created_at: 1, updated_at: 1, created_by: "admin", updated_by: "admin", last_run_at: null, last_run_status: null, next_run_at: 2_000_000_000, source_label: "WebNAS" };
const external: CronJob = { ...job, id: "external-111111111111111111111111", name: "System cleanup", source: "cron_d", status: "external", source_label: "/etc/cron.d/system", read_only: true };

describe("CronManagerApp", () => {
  beforeEach(() => {
    vi.mocked(api.cronStatus).mockResolvedValue(status);
    vi.mocked(api.cronJobs).mockResolvedValue({ items: [job, external], total: 2 });
    vi.mocked(api.cronDiagnostics).mockResolvedValue({ items: [] });
    vi.mocked(api.cronLogs).mockResolvedValue({ source: "journal:cron", sources: [{ id: "journal:cron", label: "cron" }], entries: [], truncated: false });
    vi.mocked(api.cronHistory).mockResolvedValue({ available: false, reason: "No data", entries: [] });
    vi.mocked(api.validateCronJob).mockResolvedValue({ valid: true, normalized: "*/5 * * * *", explanation: "Runs every 5 minutes.", next_run_at: 2_000_000_000, generated_entry: "*/5 * * * * root /bin/true", warnings: [] });
    vi.mocked(api.createCronJob).mockResolvedValue({ job: { id: "queue", module_id: "cron", action: "manage", status: "queued", progress: 0, created_at: 1, log_tail: [], error: "" } });
    vi.mocked(api.setCronJobEnabled).mockResolvedValue({ job: { id: "queue", module_id: "cron", action: "manage", status: "queued", progress: 0, created_at: 1, log_tail: [], error: "" } });
    vi.mocked(api.appJob).mockResolvedValue({ id: "queue", module_id: "cron", action: "manage", status: "completed", progress: 100, created_at: 1, log_tail: [], error: "" });
  });

  it("renders dashboard, managed and read-only external jobs and filters the list", async () => {
    render(<CronManagerApp permissions={["cron.view", "cron.logs"]} t={t} toast={vi.fn()} />);
    expect(await screen.findByText("Backup NAS")).toBeInTheDocument();
    expect(screen.getByText("System cleanup")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "action.edit: System cleanup" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("action.search"), { target: { value: "cleanup" } });
    expect(screen.queryByText("Backup NAS")).not.toBeInTheDocument();
    expect(screen.getByText("System cleanup")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("cron.statusFilter"), { target: { value: "enabled" } });
    expect(screen.getByText("cron.empty.filtered")).toBeInTheDocument();
  });

  it("creates a validated job with explicit confirmation and PAM password", async () => {
    render(<CronManagerApp permissions={["cron.view", "cron.create", "cron.edit"]} t={t} toast={vi.fn()} />);
    await screen.findByText("Backup NAS");
    fireEvent.click(screen.getByRole("button", { name: "cron.new" }));
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.change(dialog.getByLabelText("common.name"), { target: { value: "Report" } });
    fireEvent.change(dialog.getByLabelText("cron.command"), { target: { value: "/bin/true" } });
    await waitFor(() => expect(api.validateCronJob).toHaveBeenCalled());
    fireEvent.change(dialog.getByLabelText("cron.confirmationValue"), { target: { value: "cron:create" } });
    fireEvent.change(dialog.getByLabelText("cron.currentPassword"), { target: { value: "password" } });
    fireEvent.click(dialog.getByRole("button", { name: "action.save" }));
    await waitFor(() => expect(api.createCronJob).toHaveBeenCalledWith(expect.objectContaining({ name: "Report", command: "/bin/true" }), { confirmation: "cron:create", pam_password: "password" }));
  });

  it("enables and disables only when the dedicated permission is present", async () => {
    const { rerender } = render(<CronManagerApp permissions={["cron.view"]} t={t} toast={vi.fn()} />);
    await screen.findByText("Backup NAS");
    expect(screen.queryByRole("button", { name: "cron.disable: Backup NAS" })).not.toBeInTheDocument();
    rerender(<CronManagerApp permissions={["cron.view", "cron.enable"]} t={t} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "cron.disable: Backup NAS" }));
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.change(dialog.getByLabelText(/cron.confirmationHint/), { target: { value: job.id } });
    fireEvent.change(dialog.getByLabelText("cron.currentPassword"), { target: { value: "password" } });
    fireEvent.click(dialog.getByRole("button", { name: "action.confirm" }));
    await waitFor(() => expect(api.setCronJobEnabled).toHaveBeenCalledWith(job.id, false, { confirmation: job.id, pam_password: "password" }));
  });

  it("shows loading and recoverable API error states", async () => {
    vi.mocked(api.cronStatus).mockRejectedValueOnce(new Error("offline"));
    vi.mocked(api.cronJobs).mockRejectedValueOnce(new Error("offline"));
    render(<CronManagerApp permissions={["cron.view"]} t={t} toast={vi.fn()} />);
    expect(screen.getByText("status.loading")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("offline");
    expect(screen.getByRole("button", { name: "action.retry" })).toBeInTheDocument();
  });

  it("exposes diagnostics and bounded log filters", async () => {
    render(<CronManagerApp permissions={["cron.view", "cron.logs"]} t={t} toast={vi.fn()} />);
    await screen.findByText("Backup NAS");
    fireEvent.click(screen.getByRole("button", { name: "cron.diagnostics" }));
    await waitFor(() => expect(api.cronDiagnostics).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "cron.logs" }));
    await waitFor(() => expect(api.cronLogs).toHaveBeenCalledWith(expect.objectContaining({ limit: 300 })));
    expect(screen.getByLabelText("cron.jobFilter")).toBeInTheDocument();
  });
});
