import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type IdentityGroup, type IdentityRoles, type IdentityUser } from "../../api";
import { AccessPolicies, IdentityApp } from "./IdentityApp";

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
    expect(screen.queryByRole("button", { name: "identity.savePolicy" })).not.toBeInTheDocument();
  });

  it("hides mutating controls when the viewer only has read permission", async () => {
    render(<IdentityApp permissions={["users.view", "groups.view", "access.view"]} t={(key) => key} toast={vi.fn()} />);
    await screen.findByText("alice");
    expect(screen.queryByRole("button", { name: "identity.user.create" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("alice"));
    expect(screen.queryByRole("button", { name: "action.delete" })).not.toBeInTheDocument();
  });

  it("selects the first permitted tab for group-only access", async () => {
    render(<IdentityApp permissions={["groups.view"]} t={(key) => key} toast={vi.fn()} />);
    expect(await screen.findByPlaceholderText("identity.searchGroups")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("identity.searchUsers")).not.toBeInTheDocument();
  });

  it("keeps access policy mutation out of Users and groups", async () => {
    const openPolicies = vi.fn();
    render(<IdentityApp permissions={["users.view", "groups.view", "access.view", "access.manage_user_permissions", "access.manage_roles"]} t={(key) => key} toast={vi.fn()} onOpenPolicies={openPolicies} />);
    fireEvent.click(await screen.findByText("alice"));
    expect(screen.queryByRole("button", { name: "identity.savePolicy" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "identity.openPolicySettings" }));
    expect(openPolicies).toHaveBeenCalledOnce();
  });

  it("edits user access policies in Settings policies", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(api.saveIdentityUserPolicy).mockResolvedValue(regularUser);
    render(<AccessPolicies permissions={["access.view", "access.manage_user_permissions", "access.manage_roles"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "identity.tab.users" }));
    fireEvent.click(await screen.findByText("alice"));
    fireEvent.click(screen.getByRole("button", { name: "identity.savePolicy" }));
    await waitFor(() => expect(api.saveIdentityUserPolicy).toHaveBeenCalledWith("alice", expect.objectContaining({ role: "operator" })));
  });

  it("keeps the role matrix inside the embedded access policy workspace", async () => {
    const { container } = render(<AccessPolicies permissions={["access.view"]} t={(key) => key} toast={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "identity.tab.roles" })).toHaveClass("active");
    expect(container.querySelector(".access-policy-editor > .identity-role-matrix")).toBeInTheDocument();
    expect(container.querySelector(".access-policy-editor > .identity-tabs")).toBeInTheDocument();
  });

  it("creates a Linux user with optional identity fields from the authenticated session", async () => {
    vi.mocked(api.createIdentityUser).mockResolvedValue(regularUser);
    render(<IdentityApp permissions={["users.view", "users.create"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "identity.user.create" }));
    fireEvent.change(screen.getByLabelText("settings.username"), { target: { value: "bob" } });
    fireEvent.change(screen.getByLabelText("settings.newPassword"), { target: { value: "temporary-password" } });
    fireEvent.change(screen.getByLabelText("identity.optionalUid"), { target: { value: "1200" } });
    fireEvent.change(screen.getByLabelText("identity.optionalGid"), { target: { value: "1300" } });
    fireEvent.change(screen.getByLabelText("identity.supplementaryGroupsHint"), { target: { value: "media, operators, media" } });
    fireEvent.change(screen.getByLabelText("identity.forcePasswordChange"), { target: { value: "true" } });
    expect(screen.queryByLabelText("settings.adminPassword")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));
    await waitFor(() => expect(api.createIdentityUser).toHaveBeenCalledWith(expect.objectContaining({
      username: "bob", uid: 1200, gid: 1300, groups: ["media", "operators"], force_password_change: true,
    })));
  });
});
