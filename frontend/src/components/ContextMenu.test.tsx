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
});
