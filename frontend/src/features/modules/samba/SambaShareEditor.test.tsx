import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SambaShareEditor } from "./SambaShareEditor";

const t = (key: string) => key;

describe("Samba share editor", () => {
  it("validates required share fields", () => {
    render(<SambaShareEditor t={t} onClose={vi.fn()} onSave={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));
    expect(screen.getByText("module.samba.shareFormInvalid")).toBeInTheDocument();
  });

  it("edits grouped access and permission fields and returns a typed share", () => {
    const save = vi.fn();
    render(<SambaShareEditor t={t} onClose={vi.fn()} onSave={save} />);
    fireEvent.change(screen.getByLabelText("samba.shareName"), { target: { value: "Media" } });
    fireEvent.change(screen.getByLabelText("files.fullPath"), { target: { value: "/srv/media" } });
    fireEvent.click(screen.getByRole("button", { name: "module.samba.shareTab.access" }));
    fireEvent.change(screen.getByLabelText("samba.validUsers"), { target: { value: "alice, bob" } });
    fireEvent.change(screen.getByLabelText("module.samba.validGroups"), { target: { value: "family" } });
    fireEvent.click(screen.getByRole("button", { name: "module.samba.shareTab.permissions" }));
    fireEvent.change(screen.getByLabelText("create mask"), { target: { value: "0660" } });
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));

    expect(save).toHaveBeenCalledWith(expect.objectContaining({ name: "Media", path: "/srv/media", valid_users: ["alice", "bob"], valid_groups: ["family"], create_mask: "0660" }));
  });
});
