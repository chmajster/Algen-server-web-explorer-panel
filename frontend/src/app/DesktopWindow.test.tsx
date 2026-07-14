import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DesktopWindow } from "./DesktopWindow";
import type { WindowInstance } from "./types";

const item: WindowInstance = { id: "files-1", app: "files", rect: { x: 100, y: 80, width: 800, height: 600 }, minimized: false, zIndex: 12 };

describe("desktop window interactions", () => {
  it("commits a dragged rectangle only when the gesture ends", () => {
    const commit = vi.fn();
    const { container } = render(<DesktopWindow window={item} active t={(key) => key} onFocus={vi.fn()} onClose={vi.fn()} onMinimize={vi.fn()} onCommit={commit} onToggleMaximize={vi.fn()}><div>content</div></DesktopWindow>);
    fireEvent.pointerDown(container.querySelector(".window-titlebar")!, { clientX: 140, clientY: 95 });
    fireEvent.pointerMove(window, { clientX: 240, clientY: 195 });
    expect(commit).not.toHaveBeenCalled();
    fireEvent.pointerUp(window, { clientX: 240, clientY: 195 });
    expect(commit).toHaveBeenCalledOnce();
  });

  it("exposes minimize, maximize and close controls", () => {
    const minimize = vi.fn(); const maximize = vi.fn(); const close = vi.fn();
    render(<DesktopWindow window={item} active t={(key) => key} onFocus={vi.fn()} onClose={close} onMinimize={minimize} onCommit={vi.fn()} onToggleMaximize={maximize}><div /></DesktopWindow>);
    fireEvent.click(screen.getByRole("button", { name: "window.minimize" }));
    fireEvent.click(screen.getByRole("button", { name: "window.maximize" }));
    fireEvent.click(screen.getByRole("button", { name: "action.close" }));
    expect(minimize).toHaveBeenCalledOnce(); expect(maximize).toHaveBeenCalledOnce(); expect(close).toHaveBeenCalledOnce();
  });
});
