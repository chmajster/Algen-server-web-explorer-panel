import { describe, expect, it } from "vitest";
import type {
  AnsibleExecution,
  AnsibleScan,
  AppJob,
  HostsManagerOperation,
  NetworkMount,
  NetworkTransaction,
  Task,
  UpdateProgress,
} from "../../api";
import {
  dedupeAndSortActions,
  normalizeAnsibleExecution,
  normalizeAnsibleScan,
  normalizeAppJob,
  normalizeHostsOperation,
  normalizeMountJob,
  normalizeNetworkTransaction,
  normalizeStatus,
  normalizeSystemUpdate,
  normalizeTransfer,
} from "./normalizers";

const t = (key: string) => key;

const transfer: Task = {
  id: "transfer-1",
  username: "alice",
  type: "upload",
  op: "upload",
  status: "running",
  priority: 0,
  created_at: 10,
  source_paths: ["/home/alice/archive.zip"],
  destination_path: "/srv",
  started_at: 11,
  finished_at: null,
  paused_at: null,
  bytes_transferred: 25,
  total_bytes: 100,
  progress_percent: 25,
  progress: 25,
  speed_bps: 1,
  speed_human: "1 B/s",
  average_speed_bps: 1,
  average_speed_human: "1 B/s",
  eta_seconds: 75,
  eta_human: "75s",
  current_file: "archive.zip",
  files_done: 0,
  files_total: 1,
  rsync_exit_code: null,
  error_message: "",
  log_tail: [],
  stderr_tail: [],
  command_preview: [],
  retry_count: 0,
  errors: [],
};

const packageJob: AppJob = {
  id: "package-1",
  module_id: "docker",
  action: "install",
  status: "running",
  progress: 50,
  created_at: 12,
  log_tail: [],
  error: "",
  current_step: "Pulling image",
};

const execution: AnsibleExecution = {
  id: "execution-1",
  package_job_id: "backing-job",
  template_id: "deploy",
  requested_by: "alice",
  status: "running",
  stage: "playbook",
  host_ids: ["host-1"],
  warnings: [],
  summary: {},
  stdout: "",
  stderr: "",
  created_at: 13,
};

describe("background action normalizers", () => {
  it.each([
    ["pending_confirmation", "queued"],
    ["rollback_started", "running"],
    ["cancellation_requested", "paused"],
    ["succeeded", "completed"],
    ["error", "failed"],
    ["canceled", "cancelled"],
  ] as const)("maps source status %s to %s", (source, expected) => {
    expect(normalizeStatus(source)).toBe(expected);
  });

  it("normalizes uploads and package jobs with exact durable targets", () => {
    const upload = normalizeTransfer(transfer, t);
    const docker = normalizeAppJob(packageJob, new Map([["docker", "Docker"]]), t);

    expect(upload).toMatchObject({
      key: "upload:transfer-1",
      source: "upload",
      progress: 25,
      target: { app: "transfers", detailType: "transfer", jobId: "transfer-1" },
    });
    expect(docker).toMatchObject({
      key: "docker:package-1",
      source: "docker",
      subtitle: "Docker",
      target: { app: "operation-progress", moduleId: "docker", section: "Docker", detailType: "package-job", jobId: "package-1" },
    });
  });

  it("normalizes mount, Ansible, Hosts, network, and system jobs", () => {
    const mount: NetworkMount = {
      id: "mount-1",
      name: "Backups",
      type: "nfs",
      host: "nas.local",
      remote: "/backup",
      mount_point: "/mnt/backup",
      owner: "root",
      read_only: false,
      persistent: true,
      status: "mounting",
      actual_mounted: false,
      last_error: "",
      last_operation: "mount",
      last_operation_at: 14,
      missing_packages: [],
      migration_status: "ready",
      manual_intervention: false,
      allowed_users: [],
      allowed_groups: [],
      config: {},
      fs: null,
      jobs: [{ id: "mount-job", action: "mount", status: "running", exit_code: null, error: "", log_tail: [] }],
    };
    const scan: AnsibleScan = {
      id: "scan-1",
      request: { cidr: "10.0.0.0/24" },
      status: "running",
      progress: 70,
      discovered: 4,
      error: "",
      created_at: 15,
    };
    const hosts: HostsManagerOperation = {
      id: "hosts-1",
      host_id: "host-1",
      capability_id: "update_packages",
      module_id: "hosts-manager",
      status: "failed",
      stage: "apt",
      progress: 35,
      package_job_id: "hosts-backing",
      error: "apt failed",
      details: {},
      created_at: 16,
      updated_at: 17,
    };
    const network: NetworkTransaction = {
      id: "network-1",
      provider: "networkmanager",
      state: "pending_confirmation",
      started_at: 18,
      deadline: 60,
      rollback_unit: null,
      target: "eth0",
    };
    const update: UpdateProgress = {
      state: "running",
      running: true,
      pid: 123,
      exit_code: null,
      started_at: 19,
      finished_at: null,
      log: "",
      lines: ["Downloading"],
    };

    expect(normalizeMountJob(mount, mount.jobs[0], t).target).toMatchObject({ app: "settings", detailType: "mount-job" });
    expect(normalizeAnsibleExecution(execution, t).target).toMatchObject({ app: "ansible", detailType: "ansible-job" });
    expect(normalizeAnsibleScan(scan, t).target).toMatchObject({ app: "ansible", detailType: "ansible-scan" });
    expect(normalizeHostsOperation(hosts, t)).toMatchObject({ status: "failed", error: "apt failed", target: { app: "hosts", detailType: "hosts-operation" } });
    expect(normalizeNetworkTransaction(network, t)).toMatchObject({ status: "queued", target: { app: "settings", section: "network" } });
    expect(normalizeSystemUpdate(update, t)).toMatchObject({ status: "running", target: { app: "settings", section: "updates" } });
  });

  it("deduplicates specialized backing jobs and sorts failures before active work", () => {
    const specialized = normalizeAnsibleExecution(execution, t);
    const backing = normalizeAppJob({ ...packageJob, id: "backing-job", module_id: "ansible-controller" }, new Map(), t);
    const failed = { ...normalizeTransfer(transfer, t), key: "transfer:failed", id: "failed", status: "failed" as const };

    const result = dedupeAndSortActions([backing, specialized, failed]);

    expect(result.map((item) => item.key)).toEqual(["transfer:failed", "ansible:execution-1"]);
  });
});
