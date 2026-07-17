import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ContextMenu } from "./ContextMenu";

describe("context menu", () => {
  it("supports keyboard navigation and Escape", () => {
    const close = vi.fn(); const action = vi.fn();
    render(<ContextMenu x={9999} y={9999} items={[{ label: "Open", action }, { label: "Delete", action }]} onClose={close} />);
    fireEvent.keyDown(document, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(close).toHaveBeenCalledOnce();
  });

  it("uses the desktop portal and focuses without scrolling the application", () => {
    const desktop = document.createElement("div");
    desktop.className = "desktop";
    const windowContent = document.createElement("div");
    windowContent.className = "window-content";
    desktop.append(windowContent);
    document.body.append(desktop);
    const focus = vi.spyOn(HTMLButtonElement.prototype, "focus");

    const { unmount } = render(
      <div data-testid="scroll-container">
        <ContextMenu x={40} y={40} items={[{ label: "Open", action: vi.fn() }]} onClose={vi.fn()} portalTarget={windowContent} />
      </div>,
      { container: windowContent },
    );

    expect(screen.getByRole("menu").parentElement).toBe(desktop);
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });

    unmount();
    focus.mockRestore();
    desktop.remove();
  });
});
