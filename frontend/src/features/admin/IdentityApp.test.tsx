import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type IdentityGroup, type IdentityRoles, type IdentityUser } from "../../api";
import { IdentityApp } from "./IdentityApp";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, api: { ...actual.api, identityUsers: vi.fn(), identityGroups: vi.fn(), identityRoles: vi.fn(), identityHistory: vi.fn(), createIdentityUser: vi.fn(), saveIdentityUserPolicy: vi.fn() } };
});

const permission = { id: "services.restart", category: "services", operation: "restart", applications: ["services"], risk: "high" as const, mutating: true, label_key: "permissions.services.restart", description_key: "permissions.category.services.description" };
const roles: IdentityRoles = { permissions: [permission], roles: { admin: [permission.id], operator: [permission.id], auditor: [], user: [] } };
const regularUser: IdentityUser = { username: "alice", uid: 1001, gid: 100, primary_group: "users", supplementary_groups: ["ops"], groups: ["users", "ops"], home: "/home/alice", shell: "/bin/bash", gecos: "Alice", locked: false, password_change_required: false, is_system: false, manageable: true, linux_admin: false, role: "operator", role_source: "assignment", is_admin: false, allow: [], deny: [], permissions: [permission.id], denied_permissions: [], permission_sources: { [permission.id]: ["group:ops"] } };
const linuxAdmin: IdentityUser = { ...regularUser, username: "root-admin", uid: 1000, linux_admin: true, manageable: false, role: "admin", role_source: "linux-admin", is_admin: true, permission_sources: { [permission.id]: ["linux-admin"] } };
const group: IdentityGroup = { name: "ops", groupname: "ops", gid: 1100, primary_users: [], supplementary_members: ["alice"], members: ["alice"], is_system: false, protected: false, manageable: true, allow: [permission.id], deny: [], inheriting_users: ["alice"], inheriting_count: 1 };

describe("IdentityApp", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.identityUsers).mockResolvedValue([regularUser, linuxAdmin]);
    vi.mocked(api.identityGroups).mockResolvedValue([group]);
    vi.mocked(api.identityRoles).mockResolvedValue(roles);
    vi.mocked(api.identityHistory).mockResolvedValue([]);
  });

  it("shows effective permission sources and locks Linux administrator policy controls", async () => {
    render(<IdentityApp permissions={["users.view", "access.view", "access.manage_user_permissions", "access.manage_roles"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByText("alice"));
    expect(await screen.findByText(/group:ops/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("root-admin"));
    expect(await screen.findByText("identity.linuxAdminProtection")).toBeInTheDocument();
    expect(screen.getByLabelText(/services.restart identity.permissionState/)).toBeDisabled();
  });

  it("hides mutating controls when the viewer only has read permission", async () => {
    render(<IdentityApp permissions={["users.view", "groups.view", "access.view"]} t={(key) => key} toast={vi.fn()} />);
    await screen.findByText("alice");
    expect(screen.queryByRole("button", { name: "identity.user.create" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("alice"));
    expect(screen.queryByRole("button", { name: "action.delete" })).not.toBeInTheDocument();
  });

  it("surfaces last-administrator protection returned by the backend", async () => {
    const toast = vi.fn();
    vi.mocked(api.saveIdentityUserPolicy).mockRejectedValue(new ApiError("Cannot remove last administrator", 409, "LAST_ADMIN_PROTECTION"));
    render(<IdentityApp permissions={["users.view", "groups.view", "access.view", "access.manage_user_permissions", "access.manage_roles"]} t={(key) => key} toast={toast} />);
    fireEvent.click(await screen.findByText("alice"));
    fireEvent.click(await screen.findByRole("button", { name: "identity.savePolicy" }));
    fireEvent.change(screen.getByLabelText("settings.adminPassword"), { target: { value: "pam" } });
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Cannot remove last administrator", "error", "admin"));
  });

  it("creates a Linux user with optional identity fields and fresh PAM confirmation", async () => {
    vi.mocked(api.createIdentityUser).mockResolvedValue(regularUser);
    render(<IdentityApp permissions={["users.view", "users.create"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "identity.user.create" }));
    fireEvent.change(screen.getByLabelText("settings.username"), { target: { value: "bob" } });
    fireEvent.change(screen.getByLabelText("settings.newPassword"), { target: { value: "temporary-password" } });
    fireEvent.change(screen.getByLabelText("identity.optionalUid"), { target: { value: "1200" } });
    fireEvent.change(screen.getByLabelText("identity.optionalGid"), { target: { value: "1300" } });
    fireEvent.change(screen.getByLabelText("identity.supplementaryGroupsHint"), { target: { value: "media, operators, media" } });
    fireEvent.change(screen.getByLabelText("identity.forcePasswordChange"), { target: { value: "true" } });
    fireEvent.change(screen.getByLabelText("settings.adminPassword"), { target: { value: "fresh-pam" } });
    expect(screen.queryByText("admin.rememberPassword")).not.toBeInTheDocument();
    expect(screen.getByText("identity.freshPamRequired")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));
    await waitFor(() => expect(api.createIdentityUser).toHaveBeenCalledWith(expect.objectContaining({
      username: "bob", uid: 1200, gid: 1300, groups: ["media", "operators"], force_password_change: true, admin_password: "fresh-pam",
    })));
  });
});
