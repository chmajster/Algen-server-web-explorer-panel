import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type ApmidItem } from "../../../api";
import { ApmidApp } from "./ApmidApp";

vi.mock("../../../api", async () => {
  const actual = await vi.importActual<typeof import("../../../api")>("../../../api");
  return {
    ...actual,
    api: {
      ...actual.api,
      apmidDashboard: vi.fn(),
      apmidItems: vi.fn(),
      apmidItem: vi.fn(),
      apmidMembers: vi.fn(),
      apmidItemHistory: vi.fn(),
      apmidItemRelations: vi.fn(),
      apmidHistory: vi.fn(),
      saveApmidItem: vi.fn(),
      deleteApmidItem: vi.fn(),
      apmidUsers: vi.fn(),
      addApmidMembers: vi.fn(),
      updateApmidMember: vi.fn(),
      deleteApmidMember: vi.fn(),
      updateApmidPermissions: vi.fn(),
      resetApmidPermissions: vi.fn(),
      apmidBackups: vi.fn(),
      createApmidBackup: vi.fn(),
      restoreApmidBackup: vi.fn(),
    },
  };
});

const t = (key: string) => key;
const item: ApmidItem = {
  id: "apmid-1", code: "CRM", name: "Customer relations", description: "", active: true,
  business_owner: "Sales", member_count: 1, related_count: 2, created_at: 1, updated_at: 2,
  created_by: "admin", updated_by: "admin",
  effective_permissions: {
    username: "admin", role: "owner", allow: [], deny: [],
    effective: ["view", "update", "members.view", "members.manage", "permissions.view", "permissions.manage", "audit.view", "delete"],
    sources: { view: "role:owner", update: "role:owner", "members.view": "role:owner", "members.manage": "role:owner", "permissions.view": "role:owner", "permissions.manage": "role:owner", "audit.view": "role:owner", delete: "role:owner" },
  },
};

describe("ApmidApp", () => {
  beforeEach(() => {
    vi.mocked(api.apmidDashboard).mockResolvedValue({ total: 1, active: 1, members: 1, without_owner: 0, recent: [] });
    vi.mocked(api.apmidItems).mockResolvedValue({ items: [item], page: 1, page_size: 50, total: 1 });
    vi.mocked(api.apmidItem).mockResolvedValue(item);
    vi.mocked(api.apmidMembers).mockResolvedValue([]);
    vi.mocked(api.apmidItemHistory).mockResolvedValue([]);
    vi.mocked(api.apmidItemRelations).mockResolvedValue([]);
    vi.mocked(api.apmidHistory).mockResolvedValue([]);
    vi.mocked(api.apmidBackups).mockResolvedValue([]);
    vi.mocked(api.saveApmidItem).mockResolvedValue(item);
  });

  it("renders dashboard and searchable APMID list", async () => {
    render(<ApmidApp permissions={["apmid.view", "apmid.create", "apmid.update"]} t={t} toast={vi.fn()} />);
    expect(await screen.findByText("apmid.dashboard.total")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "module.section.apmid" }));
    expect(await screen.findByText("CRM")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("action.search"), { target: { value: "crm" } });
    await waitFor(() => expect(api.apmidItems).toHaveBeenLastCalledWith(expect.objectContaining({ search: "crm" })));
  });

  it("submits create form only when create permission is available", async () => {
    render(<ApmidApp permissions={["apmid.view", "apmid.create"]} t={t} toast={vi.fn()} />);
    await screen.findByText("apmid.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: "module.section.apmid" }));
    fireEvent.click(await screen.findByRole("button", { name: "apmid.create" }));
    fireEvent.change(screen.getByLabelText("apmid.code"), { target: { value: "erp" } });
    fireEvent.change(screen.getByLabelText("common.name"), { target: { value: "ERP" } });
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));
    await waitFor(() => expect(api.saveApmidItem).toHaveBeenCalledWith(expect.objectContaining({ code: "ERP", name: "ERP" }), undefined));
  });

  it("hides create and audit operations without global permissions", async () => {
    render(<ApmidApp permissions={[]} t={t} toast={vi.fn()} />);
    await screen.findByText("apmid.dashboard.total");
    expect(screen.queryByRole("button", { name: "module.section.audit" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "module.section.apmid" }));
    expect(screen.queryByRole("button", { name: "apmid.create" })).not.toBeInTheDocument();
  });

  it("shows a helpful empty member state with accessible filters and add action", async () => {
    render(<ApmidApp permissions={["apmid.view"]} t={t} toast={vi.fn()} />);
    await screen.findByText("apmid.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: "module.section.apmid" }));
    fireEvent.click(await screen.findByRole("button", { name: "CRM" }));
    fireEvent.click(await screen.findByRole("button", { name: "apmid.tab.members" }));

    expect(await screen.findByText("apmid.member.empty")).toBeInTheDocument();
    expect(screen.getByText("apmid.member.emptyHint")).toBeInTheDocument();
    expect(screen.getByLabelText("apmid.member.search")).toBeInTheDocument();
    expect(screen.getByLabelText("apmid.member.filterRole")).toBeInTheDocument();
    expect(screen.getByLabelText("apmid.member.filterStatus")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "apmid.member.addFirst" })).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).queryByRole("table")).not.toBeInTheDocument();
  });

  it("coalesces duplicate backup restores while one request is pending", async () => {
    vi.mocked(api.apmidBackups).mockResolvedValue([{
      id: "backup-1", schema_version: 1, created_at: 1, created_by: "admin",
      description: "test", sha256: "abc", database: "/tmp/apmid.db",
    }]);
    vi.mocked(api.restoreApmidBackup).mockImplementation(() => new Promise(() => {}));
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("RESTORE");

    render(<ApmidApp permissions={["apmid.restore"]} t={t} toast={vi.fn()} />);
    await screen.findByText("apmid.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: "module.section.backups" }));
    const restore = await screen.findByRole("button", { name: "apmid.backup.restore" });
    fireEvent.click(restore);
    fireEvent.click(restore);

    await waitFor(() => expect(api.restoreApmidBackup).toHaveBeenCalledTimes(1));
    expect(prompt).toHaveBeenCalledTimes(1);
    prompt.mockRestore();
  });
});
