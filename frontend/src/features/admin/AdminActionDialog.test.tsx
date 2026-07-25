import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AdminActionDialog } from "./AdminActionDialog";

const t = (key: string) => key;

describe("AdminActionDialog confirmations", () => {
  it("fills an action dialog that has no fields or custom description", () => {
    render(<AdminActionDialog title="services.restart: webnas.service" fields={[]} t={t} onClose={vi.fn()} onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    const dialog = screen.getByRole("dialog", { name: "services.restart: webnas.service" });
    expect(within(dialog).getByText("admin.confirmAction")).toBeInTheDocument();
    expect(within(dialog).getByText("admin.confirmActionHint")).toBeInTheDocument();
    expect(within(dialog).getByText("admin.confirmActionImmediate")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "action.confirm" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "action.apply" })).not.toBeInTheDocument();
  });

  it("uses a stronger warning for an empty destructive confirmation", () => {
    render(<AdminActionDialog title="action.delete: storage" fields={[]} danger t={t} onClose={vi.fn()} onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    const dialog = screen.getByRole("dialog", { name: "action.delete: storage" });
    expect(within(dialog).getByText("admin.confirmDangerousAction")).toBeInTheDocument();
    expect(within(dialog).getByText("admin.confirmDangerousActionHint")).toBeInTheDocument();
    expect(dialog.querySelector(".admin-action-confirmation")).toHaveClass("danger");
  });

  it("keeps a supplied description and form action label", () => {
    render(<AdminActionDialog title="Custom" fields={[]} description={<p>Detailed impact</p>} t={t} onClose={vi.fn()} onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    expect(screen.getByText("Detailed impact")).toBeInTheDocument();
    expect(screen.queryByText("admin.confirmAction")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));
  });
});
