import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog, Modal } from "./Modal";

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

  it("preserves the active field when the parent passes a new close callback", () => {
    const firstClose = vi.fn();
    const latestClose = vi.fn();
    const fields = <><label>First<input aria-label="First" /></label><label>Second<input aria-label="Second" /></label></>;
    const { rerender } = render(<Modal title="Form" onClose={firstClose}>{fields}</Modal>);
    const second = screen.getByLabelText("Second");
    second.focus();
    fireEvent.change(second, { target: { value: "typed value" } });

    rerender(<Modal title="Form" onClose={latestClose}>{fields}</Modal>);

    expect(second).toHaveFocus();
    expect(second).toHaveValue("typed value");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(firstClose).not.toHaveBeenCalled();
    expect(latestClose).toHaveBeenCalledOnce();
  });
});
