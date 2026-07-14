import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { forgetAdminPassword } from "./adminCredentials";
import { StoreAppView, UsersApp } from "./SystemApps";

vi.mock("../../api", () => ({ api: { adminUsers: vi.fn(), createUser: vi.fn(), apps: vi.fn(), appAction: vi.fn() } }));

describe("administrative forms", () => {
  beforeEach(() => { vi.clearAllMocks(); forgetAdminPassword(); });

  it("creates a user through an accessible modal without native prompts", async () => {
    vi.mocked(api.adminUsers).mockResolvedValue([]);
    vi.mocked(api.createUser).mockResolvedValue({} as never);
    render(<UsersApp t={(key) => key} toast={vi.fn()} />);
    await waitFor(() => expect(api.adminUsers).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /users.create/ }));
    fireEvent.change(screen.getByLabelText("settings.username"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("settings.newPassword"), { target: { value: "user-secret" } });
    fireEvent.change(screen.getByLabelText("settings.groupsLabel"), { target: { value: "users, media" } });
    const password = screen.getByLabelText("settings.adminPassword");
    expect(password).toHaveAttribute("autocomplete", "current-password");
    fireEvent.change(password, { target: { value: "admin-secret" } });
    fireEvent.click(screen.getByLabelText("admin.rememberPassword"));
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));
    await waitFor(() => expect(api.createUser).toHaveBeenCalledWith(expect.objectContaining({ username: "alice", groups: ["users", "media"], admin_password: "admin-secret" })));
    await waitFor(() => expect(screen.queryByLabelText("settings.adminPassword")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /users.create/ }));
    expect(screen.getByLabelText("settings.adminPassword")).toHaveValue("admin-secret");
    expect(screen.getByLabelText("admin.rememberPassword")).toBeChecked();
  });

  it("shows the reason and log when a Samba installation job fails", async () => {
    vi.mocked(api.apps).mockResolvedValue([{
      id: "samba",
      manifest: { name: "Samba", description: "SMB server", version: "1.0" },
      state: { installed: false }, services: {}, status: "error",
      jobs: [{ id: "job-1", module_id: "samba", action: "install", status: "failed", progress: 45, created_at: 1, finished_at: 2, error: "APT repository is unavailable", log_tail: [{ id: 1, created_at: 1, stream: "stderr", line: "Connection timed out" }] }]
    }] as never);

    render(<StoreAppView t={(key) => key} toast={vi.fn()} />);

    expect(await screen.findByText("APT repository is unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Connection timed out/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("store.installationFailed");
  });
});
