import { fireEvent, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog, InputDialog, Modal } from "./Modal";

describe("dialog window", () => {
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

  it("renders as a non-blocking desktop window without a blurred backdrop", () => {
    const close = vi.fn();
    const { rerender } = render(<div className="desktop" data-testid="desktop"><div data-testid="small-window" /></div>);
    rerender(<div className="desktop" data-testid="desktop"><div data-testid="small-window"><Modal title="Floating dialog" onClose={close}><p>Content</p></Modal></div></div>);

    const desktop = screen.getByTestId("desktop");
    const smallWindow = screen.getByTestId("small-window");
    const dialog = screen.getByRole("dialog", { name: "Floating dialog" });
    const layer = dialog.parentElement;
    expect(dialog).toHaveAttribute("aria-modal", "false");
    expect(layer).toHaveClass("dialog-window-layer");
    expect(layer).not.toHaveClass("modal-backdrop");
    expect(layer?.parentElement).toBe(desktop);
    expect(smallWindow).not.toContainElement(dialog);
    expect(document.querySelector(".modal-backdrop")).not.toBeInTheDocument();
  });

  it("can be minimized and restored while keeping its content", () => {
    const close = vi.fn();
    render(<Modal title="Minimizable" onClose={close}><input aria-label="Draft" defaultValue="keep me" /></Modal>);
    const draft = screen.getByLabelText("Draft");
    fireEvent.change(draft, { target: { value: "changed" } });

    fireEvent.click(screen.getByRole("button", { name: "Minimize Minimizable" }));
    expect(screen.queryByRole("dialog", { name: "Minimizable" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore Minimizable" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Restore Minimizable" }));
    expect(screen.getByRole("dialog", { name: "Minimizable" })).toBeInTheDocument();
    expect(screen.getByLabelText("Draft")).toHaveValue("changed");
  });

  it("ignores Escape while minimized", () => {
    const close = vi.fn();
    render(<Modal title="Minimized escape" onClose={close}><input aria-label="Draft" /></Modal>);
    fireEvent.click(screen.getByRole("button", { name: "Minimize Minimized escape" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Restore Minimized escape" })).toBeInTheDocument();
  });

  it("assigns distinct restore slots to concurrent minimized dialogs", () => {
    render(<><Modal title="First minimized" onClose={vi.fn()}><p>First</p></Modal><Modal title="Second minimized" onClose={vi.fn()}><p>Second</p></Modal></>);
    fireEvent.click(screen.getByRole("button", { name: "Minimize First minimized" }));
    fireEvent.click(screen.getByRole("button", { name: "Minimize Second minimized" }));
    const first = screen.getByRole("button", { name: "Restore First minimized" });
    const second = screen.getByRole("button", { name: "Restore Second minimized" });
    expect(first).not.toHaveAttribute("data-minimized-slot", second.getAttribute("data-minimized-slot"));
    expect(first.style.getPropertyValue("--dialog-minimized-offset")).not.toBe(second.style.getPropertyValue("--dialog-minimized-offset"));
  });

  it("does not leak minimized slots under StrictMode", () => {
    render(<StrictMode><Modal title="Strict minimized" onClose={vi.fn()}><p>Draft</p></Modal></StrictMode>);
    fireEvent.click(screen.getByRole("button", { name: "Minimize Strict minimized" }));
    const firstSlot = screen.getByRole("button", { name: "Restore Strict minimized" }).getAttribute("data-minimized-slot");
    fireEvent.click(screen.getByRole("button", { name: "Restore Strict minimized" }));
    fireEvent.click(screen.getByRole("button", { name: "Minimize Strict minimized" }));
    expect(screen.getByRole("button", { name: "Restore Strict minimized" })).toHaveAttribute("data-minimized-slot", firstSlot);
  });

  it("gives concurrent input dialogs unique form ids", () => {
    render(<><InputDialog title="First input" label="First value" confirmLabel="Save first" cancelLabel="Cancel" onConfirm={vi.fn()} onClose={vi.fn()} /><InputDialog title="Second input" label="Second value" confirmLabel="Save second" cancelLabel="Cancel" onConfirm={vi.fn()} onClose={vi.fn()} /></>);
    const firstButton = screen.getByRole("button", { name: "Save first" });
    const secondButton = screen.getByRole("button", { name: "Save second" });
    expect(firstButton.getAttribute("form")).toBeTruthy();
    expect(secondButton.getAttribute("form")).toBeTruthy();
    expect(firstButton.getAttribute("form")).not.toBe(secondButton.getAttribute("form"));
    expect(document.getElementById(firstButton.getAttribute("form") || "")).toBeInstanceOf(HTMLFormElement);
    expect(document.getElementById(secondButton.getAttribute("form") || "")).toBeInstanceOf(HTMLFormElement);
    expect(document.getElementById(firstButton.getAttribute("form") || "")).toHaveClass("input-dialog-form");
  });

  it("does not trap focus and restores the opener after closing", () => {
    const opener = document.createElement("button");
    const outside = document.createElement("button");
    document.body.append(opener, outside);
    opener.focus();
    const close = vi.fn();
    const { unmount } = render(<Modal title="Keyboard dialog" onClose={close}><input aria-label="First field" autoFocus /></Modal>);
    const first = screen.getByLabelText("First field");

    expect(first).toHaveFocus();
    outside.focus();
    expect(outside).toHaveFocus();

    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
    outside.remove();
  });
});
