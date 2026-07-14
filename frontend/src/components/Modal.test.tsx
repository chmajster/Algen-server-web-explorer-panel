import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./Modal";

describe("modal", () => {
  it("closes with Escape and confirms without using a native dialog", () => {
    const close = vi.fn(); const confirm = vi.fn();
    const { rerender } = render(<ConfirmDialog title="Delete" message="Really?" confirmLabel="Delete" cancelLabel="Cancel" onConfirm={confirm} onClose={close} />);
    expect(screen.getByRole("dialog", { name: "Delete" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(close).toHaveBeenCalledOnce();
    rerender(<ConfirmDialog title="Delete" message="Really?" confirmLabel="Delete" cancelLabel="Cancel" onConfirm={confirm} onClose={close} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalledOnce();
  });
});
