import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  module: vi.fn(),
}));

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return { ...actual, api: { ...actual.api, module: mocks.module } };
});
vi.mock("../../core/realtime/runtimeEvents", () => ({
  runtimeConnectionState: () => "open",
  subscribeRuntimeConnection: () => () => undefined,
  subscribeRuntimeEvent: () => () => undefined,
}));
vi.mock("../../core/runtime/pageVisibility", () => ({ pageIsVisible: () => true }));
vi.mock("../connection/ConnectionStatusMonitor", () => ({ useRefreshOnConnectionRestored: () => undefined }));
vi.mock("./common/ModuleAppShell", () => ({
  ModuleAppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ModuleHealthCard: () => null,
  translateServiceState: (value: string) => value,
}));
vi.mock("./common/ModuleComponents", () => ({
  ModuleBackups: () => null,
  ModuleDangerZone: () => null,
  ModuleDiagnostics: () => null,
  ModuleJobProgress: () => null,
  ModuleLogs: () => null,
  ModuleServiceControls: () => null,
}));
vi.mock("./common/ModuleUninstallDialog", () => ({ ModuleUninstallDialog: () => null }));
vi.mock("../admin/AdminActionDialog", () => ({ AdminActionDialog: () => null }));
vi.mock("../package-center/PackageJobDialog", () => ({ PackageJobDialog: () => null }));

import { ModuleApp } from "./ModuleApp";

const summary = {
  manifest: { name: "Example", version: "1.0", homepage: "", license: "MIT", category: "test" },
  module_status: {
    installed: true,
    update_available: false,
    service_state: "active",
    service_enabled: true,
    services: {},
    health: "healthy",
    health_message: "",
    last_action: "",
    last_action_status: "",
    last_error: "",
    metrics: {},
  },
  capabilities: { logs: false, diagnostics: false, backups: false },
  active_job: null,
};

describe("GenericModuleApp status refresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.module.mockReset();
    mocks.module.mockResolvedValue(summary);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps a low-frequency status refresh while realtime is healthy", async () => {
    render(<ModuleApp moduleId="example-module" permissions={[]} t={(key) => key} toast={vi.fn()} onOpenFolder={vi.fn()} onDirtyChange={vi.fn()} />);
    await act(async () => { await Promise.resolve(); });
    expect(mocks.module).toHaveBeenCalledTimes(1);

    act(() => { vi.advanceTimersByTime(59_999); });
    expect(mocks.module).toHaveBeenCalledTimes(1);

    act(() => { vi.advanceTimersByTime(1); });
    await act(async () => { await Promise.resolve(); });
    expect(mocks.module).toHaveBeenCalledTimes(2);
  });
});
