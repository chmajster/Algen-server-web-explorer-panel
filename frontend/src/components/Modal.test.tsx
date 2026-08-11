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

  it("renders over the desktop instead of being clipped by a parent window", () => {
    const close = vi.fn();
    const { rerender } = render(<div className="desktop" data-testid="desktop"><div data-testid="small-window" /></div>);
    rerender(<div className="desktop" data-testid="desktop"><div data-testid="small-window"><Modal title="Full overlay" onClose={close}><p>Content</p></Modal></div></div>);

    const desktop = screen.getByTestId("desktop");
    const smallWindow = screen.getByTestId("small-window");
    const dialog = screen.getByRole("dialog", { name: "Full overlay" });
    const backdrop = dialog.parentElement;
    expect(backdrop).toHaveClass("modal-backdrop");
    expect(backdrop?.parentElement).toBe(desktop);
    expect(smallWindow).not.toContainElement(dialog);
  });

  it("keeps keyboard focus inside the dialog and restores it after closing", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const close = vi.fn();
    const { unmount } = render(<Modal title="Keyboard dialog" onClose={close} footer={<button>Last action</button>}><input aria-label="First field" autoFocus /></Modal>);
    const first = screen.getByLabelText("First field");
    const last = screen.getByRole("button", { name: "Last action" });
    const closeButton = screen.getByRole("button", { name: "×" });

    expect(first).toHaveFocus();
    last.focus();
    const dialog = screen.getByRole("dialog", { name: "Keyboard dialog" });
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(closeButton).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();

    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });
});
