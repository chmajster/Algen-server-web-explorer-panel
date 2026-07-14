import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { UsersApp } from "./SystemApps";

vi.mock("../../api", () => ({ api: { adminUsers: vi.fn(), createUser: vi.fn() } }));

describe("administrative forms", () => {
  it("creates a user through an accessible modal without native prompts", async () => {
    vi.mocked(api.adminUsers).mockResolvedValue([]);
    vi.mocked(api.createUser).mockResolvedValue({} as never);
    render(<UsersApp t={(key) => key} toast={vi.fn()} />);
    await waitFor(() => expect(api.adminUsers).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /users.create/ }));
    fireEvent.change(screen.getByLabelText("settings.username"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("settings.newPassword"), { target: { value: "user-secret" } });
    fireEvent.change(screen.getByLabelText("settings.groupsLabel"), { target: { value: "users, media" } });
    fireEvent.change(screen.getByLabelText("settings.adminPassword"), { target: { value: "admin-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));
    await waitFor(() => expect(api.createUser).toHaveBeenCalledWith(expect.objectContaining({ username: "alice", groups: ["users", "media"], admin_password: "admin-secret" })));
  });
});
