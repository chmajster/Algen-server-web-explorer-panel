import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type ResourceDashboard } from "../../api";
import { MonitorApp } from "./MonitorApp";

vi.mock("../../api", () => ({ api: { resources: vi.fn() } }));

const t = (key: string) => key;
const fixture: ResourceDashboard = {
  scope: "admin",
  timestamp: 1_700_000_000,
  cpu_percent: 42,
  cpu_cores: [30, 54],
  cpu_logical_cores: 2,
  cpu_frequency_mhz: 2400,
  ram: { total: 1000, used: 920, free: 80, percent: 92 },
  swap: { total: 0, used: 0, free: 0, percent: 0 },
  allowed_roots: [{ path: "/home/alice", paths: ["/home/alice", "/srv/alice"], filesystem_id: "fs-8-1", device: "/dev/sda1", mountpoint: "/", fs_type: "ext4", total: 1000, used: 960, free: 40, percent: 96, read_bytes_per_sec: 100, write_bytes_per_sec: 200 }],
  mountpoints: [{ path: "/", device: "/dev/sda1", mountpoint: "/", fs_type: "ext4", total: 1000, used: 960, free: 40, percent: 96 }],
  uptime_seconds: 90061,
  boot_time: 1_699_909_939,
  load_average: [0.1, 0.2, 0.3],
  temperature_c: 50,
  webnas_service: "active",
  hostname: "test-server",
  os_name: "Test Linux",
  kernel_version: "6.8.0",
  network_interfaces: [{ name: "eth0", state: "up", rx_bytes: 1000, tx_bytes: 2000, rx_bytes_per_sec: 10, tx_bytes_per_sec: 20, system: false }],
  disk_io: [{ device: "sda", read_bytes: 100, write_bytes: 200, read_bytes_per_sec: 10, write_bytes_per_sec: 20 }],
  alerts: [{ code: "disk_usage", severity: "critical", target: "fs-8-1", value: 96 }],
  warnings: ["Low free space on /home/alice"],
  processes: [{ pid: 42, user: "alice", name: "worker", cpu_percent: 12, memory_percent: 3, rss: 4096, state: "R" }],
};

describe("MonitorApp", () => {
  const resources = vi.mocked(api.resources);

  beforeEach(() => {
    resources.mockReset();
    resources.mockResolvedValue(fixture);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the dashboard with live system, storage, network and process data", async () => {
    render(<MonitorApp t={t} />);

    expect(await screen.findByText("test-server")).toBeInTheDocument();
    expect(screen.getAllByText("monitor.disabled").length).toBeGreaterThan(0);
    expect(screen.getByText("/home/alice")).toBeInTheDocument();
    expect(screen.getByText("/srv/alice")).toBeInTheDocument();
    expect(screen.getByText("eth0")).toBeInTheDocument();
    expect(screen.getByText("worker")).toBeInTheDocument();
    expect(document.querySelector(".monitor-storage-card.critical")).toBeInTheDocument();
    expect(document.querySelector(".monitor-metric.warning")).toBeInTheDocument();
    expect(screen.getByText(/monitor.alert.disk_usage/)).toBeInTheDocument();
    expect(document.querySelectorAll(".monitor-overview-grid .monitor-metric")).toHaveLength(4);
  });

  it("renders safely with null CPU, disabled swap and no temperature", async () => {
    resources.mockResolvedValue({ ...fixture, cpu_percent: null, cpu_cores: [null, 25], temperature_c: null, alerts: [], warnings: [] });
    render(<MonitorApp t={t} />);

    expect(await screen.findByText("test-server")).toBeInTheDocument();
    expect(screen.getAllByText("monitor.disabled").length).toBeGreaterThan(0);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("monitor.ready")).toBeInTheDocument();
  });

  it("renders an empty network section without crashing", async () => {
    resources.mockResolvedValue({ ...fixture, network_interfaces: [] });
    render(<MonitorApp t={t} />);

    expect(await screen.findByText("test-server")).toBeInTheDocument();
    expect(document.querySelectorAll(".monitor-network-card")).toHaveLength(0);
  });

  it("renders multiple network interfaces", async () => {
    resources.mockResolvedValue({
      ...fixture,
      network_interfaces: [
        fixture.network_interfaces[0],
        { name: "docker0", state: "up", rx_bytes: 500, tx_bytes: 700, rx_bytes_per_sec: 3, tx_bytes_per_sec: 4, system: true },
      ],
    });
    render(<MonitorApp t={t} />);

    expect(await screen.findByText("eth0")).toBeInTheDocument();
    expect(screen.getByText("docker0")).toBeInTheDocument();
    expect(screen.getByText("monitor.systemInterface")).toBeInTheDocument();
  });

  it("does not render administrator-only tables for a regular user", async () => {
    resources.mockResolvedValue({ ...fixture, scope: "user", mountpoints: [], processes: [], webnas_service: null });
    render(<MonitorApp t={t} />);

    expect(await screen.findByText("test-server")).toBeInTheDocument();
    expect(screen.queryByText("monitor.allMounts")).not.toBeInTheDocument();
    expect(screen.queryByText("monitor.processes")).not.toBeInTheDocument();
  });

  it("retains the last successful data when refresh fails", async () => {
    resources.mockResolvedValueOnce(fixture).mockRejectedValueOnce(new Error("offline"));
    render(<MonitorApp t={t} />);
    expect(await screen.findByText("test-server")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "action.refresh" }));

    expect(await screen.findByText(/offline/)).toBeInTheDocument();
    expect(screen.getByText("test-server")).toBeInTheDocument();
  });

  it("filters processes locally", async () => {
    resources.mockResolvedValue({
      ...fixture,
      processes: [
        fixture.processes[0],
        { pid: 77, user: "root", name: "database", cpu_percent: 3, memory_percent: 9, rss: 8192, state: "S" },
      ],
    });
    render(<MonitorApp t={t} />);
    expect(await screen.findByText("database")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "monitor.processes" }), { target: { value: "worker" } });

    expect(screen.getByText("worker")).toBeInTheDocument();
    expect(screen.queryByText("database")).not.toBeInTheDocument();
    expect(resources).toHaveBeenCalledTimes(1);
  });

  it("sorts processes by PID", async () => {
    resources.mockResolvedValue({
      ...fixture,
      processes: [
        { pid: 90, user: "root", name: "late", cpu_percent: 1, memory_percent: 1, rss: 100, state: "S" },
        { pid: 10, user: "root", name: "early", cpu_percent: 2, memory_percent: 1, rss: 100, state: "S" },
      ],
    });
    render(<MonitorApp t={t} />);
    await screen.findByText("late");

    fireEvent.click(screen.getByRole("button", { name: "PID" }));
    const table = document.querySelector(".monitor-process-table");
    expect(table).not.toBeNull();
    const rows = within(table as HTMLElement).getAllByRole("row");
    expect(within(rows[1]).getByText("10")).toBeInTheDocument();
  });

  it("pauses polling while hidden and prevents overlapping requests", async () => {
    vi.useFakeTimers();
    resources.mockResolvedValueOnce(fixture);
    render(<MonitorApp t={t} />);
    await act(async () => { await Promise.resolve(); });
    expect(resources).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    fireEvent(document, new Event("visibilitychange"));
    await act(async () => { vi.advanceTimersByTime(4000); });
    expect(resources).toHaveBeenCalledTimes(1);

    let resolveRequest: ((value: ResourceDashboard) => void) | undefined;
    resources.mockImplementation(() => new Promise((resolve) => { resolveRequest = resolve; }));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    fireEvent(document, new Event("visibilitychange"));
    await act(async () => { vi.advanceTimersByTime(10000); });
    expect(resources).toHaveBeenCalledTimes(2);

    await act(async () => { resolveRequest?.(fixture); await Promise.resolve(); });
  });

  it("allows choosing the refresh interval", async () => {
    render(<MonitorApp t={t} />);
    await waitFor(() => expect(resources).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("monitor.interval"), { target: { value: "5000" } });

    expect(screen.getByLabelText("monitor.interval")).toHaveValue("5000");
  });

  it("allows disabling automatic refresh", async () => {
    vi.useFakeTimers();
    render(<MonitorApp t={t} />);
    await act(async () => { await Promise.resolve(); });
    expect(resources).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("checkbox"));
    await act(async () => { vi.advanceTimersByTime(10000); });

    expect(resources).toHaveBeenCalledTimes(1);
  });

  it("polls at the default two-second interval", async () => {
    vi.useFakeTimers();
    render(<MonitorApp t={t} />);
    await act(async () => { await Promise.resolve(); });
    expect(resources).toHaveBeenCalledTimes(1);

    await act(async () => { vi.advanceTimersByTime(1999); });
    expect(resources).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(1); await Promise.resolve(); });

    expect(resources).toHaveBeenCalledTimes(2);
  });
});
