import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RbacAccessApp } from "./RbacAccessApp";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
}));

vi.mock("../../core/api/transport", () => ({
  request: mocks.request,
}));

const roles = [
  {
    id: "system:administrator",
    name: "Administrator",
    description: "System administrator",
    active: 1,
    role_type: "system",
    protected: 1,
    permissions: [
      {
        permission: "files.read",
        effect: "allow",
        resource_type: "global",
        resource_id: "*",
        scope: "*",
      },
    ],
  },
];

const permissions = [
  { id: "files.read", category: "files", canonical: "files.read" },
  { id: "files.write", category: "files", canonical: "files.edit" },
  { id: "files.edit", category: "files", canonical: "files.edit" },
  { id: "services.read", category: "services", canonical: "services.view" },
];

const groups = [
  {
    id: "group-1",
    name: "Helpdesk",
    description: "Local support",
    active: 1,
    source: "local",
    managed: 0,
    roles: ["system:administrator"],
    members: [{ provider: "pam", identity_id: "jan", username: "jan" }],
  },
];

const policies = [
  {
    id: "policy-1",
    name: "No production",
    description: "Deny production",
    active: 1,
    effect: "deny",
    permission: "files.read",
    resource_type: "files",
    resource_id: "home",
    scope: "/production",
    conditions: {},
    subjects: [{ subject_type: "user", subject_id: "jan" }],
  },
];

const externalGroups = [
  {
    id: "external-1",
    external_id: "guid-group",
    distinguished_name: "CN=Linux-Admins,DC=example,DC=com",
    name: "Linux-Admins",
    status: "active",
    role_ids: ["system:administrator"],
    parent_ids: [],
  },
];

const audit = [
  {
    id: 1,
    actor: "admin",
    action: "role.create",
    target: "role-1",
    timestamp: 1_700_000_000,
    source_ip: "192.0.2.1",
    before_json: "{}",
    after_json: "{}",
  },
];

function installSuccessfulApi(overrides: Record<string, unknown> = {}) {
  const data: Record<string, unknown> = {
    "/api/rbac/roles": { items: roles },
    "/api/rbac/permissions": { items: permissions },
    "/api/rbac/groups": { items: groups },
    "/api/rbac/policies": { items: policies },
    "/api/rbac/external-groups": { items: externalGroups },
    "/api/rbac/audit?limit=300": { items: audit },
    ...overrides,
  };

  mocks.request.mockImplementation(async (path: string, options?: RequestInit) => {
    if (options?.method && options.method !== "GET") return { ok: true };
    return data[path] ?? { items: [] };
  });
}

function renderApp(toast = vi.fn()) {
  render(
    <RbacAccessApp
      t={vi.fn() as never}
      toast={toast as never}
    />,
  );
  return toast;
}

describe("RbacAccessApp", () => {
  beforeEach(() => {
    mocks.request.mockReset();
  });

  it("loads every RBAC data source on startup", async () => {
    installSuccessfulApi();
    renderApp();

    expect(await screen.findByText("Administrator")).toBeInTheDocument();
    await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(6));
    expect(mocks.request).toHaveBeenCalledWith("/api/rbac/roles");
    expect(mocks.request).toHaveBeenCalledWith("/api/rbac/permissions");
    expect(mocks.request).toHaveBeenCalledWith("/api/rbac/groups");
    expect(mocks.request).toHaveBeenCalledWith("/api/rbac/policies");
    expect(mocks.request).toHaveBeenCalledWith("/api/rbac/external-groups");
    expect(mocks.request).toHaveBeenCalledWith("/api/rbac/audit?limit=300");
  });

  it("refreshes all datasets from the toolbar", async () => {
    const user = userEvent.setup();
    installSuccessfulApi();
    renderApp();

    await screen.findByText("Administrator");
    await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(6));

    await user.click(screen.getByRole("button", { name: /odśwież/i }));

    await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(12));
  });

  it("switches tabs without re-fetching the whole model", async () => {
    const user = userEvent.setup();
    installSuccessfulApi();
    renderApp();

    await screen.findByText("Administrator");
    await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(6));

    const groupsTab = screen.getByRole("button", { name: "Grupy" });
    await user.click(groupsTab);
    expect(groupsTab).toHaveClass("active");
    expect(screen.getByText("Helpdesk")).toBeInTheDocument();

    const policiesTab = screen.getByRole("button", { name: "Polityki" });
    await user.click(policiesTab);
    expect(policiesTab).toHaveClass("active");
    expect(screen.getByText("No production")).toBeInTheDocument();

    expect(mocks.request).toHaveBeenCalledTimes(6);
  });

  it("keeps protected system role names read-only", async () => {
    const user = userEvent.setup();
    installSuccessfulApi();
    renderApp();

    const role = await screen.findByText("Administrator");
    await user.click(role);

    expect(screen.getByLabelText("Nazwa")).toBeDisabled();
    expect(screen.queryByTitle("Usuń")).not.toBeInTheDocument();
    expect(screen.getByTitle("Duplikuj")).toBeInTheDocument();
  });

  it("creates a role with canonical permissions and refreshes the model", async () => {
    const user = userEvent.setup();
    const toast = vi.fn();
    installSuccessfulApi({ "/api/rbac/roles": { items: [] } });
    renderApp(toast);

    await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(6));

    await user.type(screen.getByLabelText("Nazwa"), "File reader");
    await user.click(screen.getByRole("checkbox", { name: "files.read" }));
    await user.click(screen.getByRole("button", { name: /zapisz rolę/i }));

    await waitFor(() => {
      expect(mocks.request).toHaveBeenCalledWith(
        "/api/rbac/roles",
        expect.objectContaining({ method: "POST" }),
      );
    });

    const createCall = mocks.request.mock.calls.find(
      ([path, options]) => path === "/api/rbac/roles" && options?.method === "POST",
    );
    expect(createCall).toBeDefined();
    const payload = JSON.parse(String(createCall?.[1]?.body));
    expect(payload).toMatchObject({
      name: "File reader",
      active: true,
      permissions: [
        {
          permission: "files.read",
          effect: "allow",
          resource_type: "global",
          resource_id: "*",
          scope: "*",
        },
      ],
    });
    expect(toast).toHaveBeenCalledWith("Rola zapisana", "ok", "admin");
    await waitFor(() => expect(mocks.request.mock.calls.length).toBeGreaterThanOrEqual(13));
  });

  it("reports refresh failures through the admin toast", async () => {
    const toast = vi.fn();
    installSuccessfulApi();
    mocks.request.mockImplementation(async (path: string) => {
      if (path === "/api/rbac/roles") throw new Error("RBAC unavailable");
      return { items: [] };
    });

    renderApp(toast);

    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith(
        "RBAC unavailable",
        "error",
        "admin",
      );
    });
  });

  it("does not submit a role while its name is blank", async () => {
    installSuccessfulApi({ "/api/rbac/roles": { items: [] } });
    renderApp();

    await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(6));

    const save = screen.getByRole("button", { name: /zapisz rolę/i });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Nazwa"), { target: { value: "   " } });
    expect(save).toBeDisabled();
    expect(
      mocks.request.mock.calls.filter(
        ([path, options]) => path === "/api/rbac/roles" && options?.method === "POST",
      ),
    ).toHaveLength(0);
  });
});
