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

  it("uses a fixed fullscreen window and disables gestures on a phone viewport", () => {
    const commit = vi.fn();
    const maximize = vi.fn();
    const { container } = render(<DesktopWindow window={item} active viewport={{ width: 360, height: 740, bottom: 52 }} t={(key) => key} onFocus={vi.fn()} onClose={vi.fn()} onMinimize={vi.fn()} onCommit={commit} onToggleMaximize={maximize}><div>content</div></DesktopWindow>);
    const dialog = screen.getByRole("dialog");

    expect(dialog).toHaveClass("mobile-fullscreen");
    expect(container.querySelector(".resize-handle")).not.toBeInTheDocument();
    fireEvent.pointerDown(container.querySelector(".window-titlebar")!, { clientX: 120, clientY: 20 });
    fireEvent.pointerMove(window, { clientX: 220, clientY: 120 });
    fireEvent.pointerUp(window, { clientX: 220, clientY: 120 });
    fireEvent.doubleClick(container.querySelector(".window-titlebar")!);

    expect(commit).not.toHaveBeenCalled();
    expect(maximize).not.toHaveBeenCalled();
  });

  it("uses the managed module name and icon in the window title", () => {
    const moduleWindow: WindowInstance = { ...item, id: "module-samba", app: "module", moduleId: "samba" };
    const { container } = render(<DesktopWindow window={moduleWindow} active t={(key) => key} onFocus={vi.fn()} onClose={vi.fn()} onMinimize={vi.fn()} onCommit={vi.fn()} onToggleMaximize={vi.fn()}><div /></DesktopWindow>);

    expect(screen.getByRole("dialog", { name: "Samba" })).toBeInTheDocument();
    expect(container.querySelector(".window-app-icon .lucide-share2")).toBeInTheDocument();
  });

  it("uses the operation name in a native progress window title", () => {
    const operationWindow: WindowInstance = {
      ...item,
      id: "operation-progress-1",
      app: "operation-progress",
      deepLink: { type: "package-job", id: "job-1", jobId: "job-1", actionKey: "operation:job-1", section: "Samba", issuedAt: 1 },
    };
    render(<DesktopWindow window={operationWindow} active t={(key) => key === "package.liveJobTitle" ? "Operation: {name}" : key} onFocus={vi.fn()} onClose={vi.fn()} onMinimize={vi.fn()} onCommit={vi.fn()} onToggleMaximize={vi.fn()}><div /></DesktopWindow>);

    expect(screen.getByRole("dialog", { name: "Operation: Samba" })).toHaveAttribute("aria-modal", "false");
  });
});
