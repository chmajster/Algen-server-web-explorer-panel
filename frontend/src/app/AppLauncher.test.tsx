import { fireEvent, render, screen } from "@testing-library/react";
import { HardDrive, Settings } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { settingsFixture } from "../test/settings";
import { AppLauncher } from "./AppLauncher";
import type { AppDefinition } from "./types";

const appList: AppDefinition[] = [
  { id: "files", labelKey: "File Manager", icon: <HardDrive /> },
  { id: "settings", labelKey: "Settings", icon: <Settings /> },
];
const t = (key: string) => key;

describe("Start menu", () => {
  it("sorts All apps alphabetically by the localized label", () => {
    const { container } = render(<AppLauncher apps={[...appList].reverse()} startPinned={new Set()} desktopShortcuts={new Set()} taskbarPinned={new Set()} profile={settingsFixture({ language: "pl-PL" })} t={t} onOpen={vi.fn()} onToggleStartPin={vi.fn()} onToggleDesktopShortcut={vi.fn()} onToggleTaskbarPin={vi.fn()} onLogout={vi.fn()} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "desktop.allApps" }));

    expect([...container.querySelectorAll(".launcher-list .launcher-open span")].map((item) => item.textContent)).toEqual(["File Manager", "Settings"]);
  });

  it("filters apps, launches the selected app and closes", () => {
    const open = vi.fn(); const close = vi.fn();
    render(<AppLauncher apps={appList} startPinned={new Set(["files", "settings"])} desktopShortcuts={new Set(["files"])} taskbarPinned={new Set(["settings"])} profile={settingsFixture()} t={t} onOpen={open} onToggleStartPin={vi.fn()} onToggleDesktopShortcut={vi.fn()} onToggleTaskbarPin={vi.fn()} onLogout={vi.fn()} onClose={close} />);

    fireEvent.change(screen.getByLabelText("desktop.searchApps"), { target: { value: "settings" } });
    expect(screen.queryByRole("button", { name: "File Manager" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(open).toHaveBeenCalledWith("settings");
    expect(close).toHaveBeenCalled();
  });

  it("closes on Escape and outside click", () => {
    const close = vi.fn();
    render(<AppLauncher apps={appList} startPinned={new Set(["files"])} desktopShortcuts={new Set(["files"])} taskbarPinned={new Set(["files"])} profile={settingsFixture()} t={t} onOpen={vi.fn()} onToggleStartPin={vi.fn()} onToggleDesktopShortcut={vi.fn()} onToggleTaskbarPin={vi.fn()} onLogout={vi.fn()} onClose={close} />);
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.mouseDown(document.body);
    expect(close).toHaveBeenCalledTimes(2);
  });

  it("opens the current user's account settings from the footer", () => {
    const openProfile = vi.fn(); const close = vi.fn();
    render(<AppLauncher apps={appList} startPinned={new Set()} desktopShortcuts={new Set()} taskbarPinned={new Set()} profile={settingsFixture()} t={t} onOpen={vi.fn()} onOpenProfile={openProfile} onToggleStartPin={vi.fn()} onToggleDesktopShortcut={vi.fn()} onToggleTaskbarPin={vi.fn()} onLogout={vi.fn()} onClose={close} />);

    fireEvent.click(screen.getByRole("button", { name: /desktop.openUserSettings/ }));
    expect(openProfile).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
  });

  it("offers separate desktop, Start, and taskbar actions in the All apps context menu", () => {
    const desktop = vi.fn(); const start = vi.fn(); const taskbar = vi.fn();
    render(<div className="desktop"><AppLauncher apps={appList} startPinned={new Set()} desktopShortcuts={new Set()} taskbarPinned={new Set()} profile={settingsFixture()} t={t} onOpen={vi.fn()} onToggleStartPin={start} onToggleDesktopShortcut={desktop} onToggleTaskbarPin={taskbar} onLogout={vi.fn()} onClose={vi.fn()} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "desktop.allApps" }));
    const settings = screen.getByRole("button", { name: "Settings" });

    fireEvent.contextMenu(settings);
    const desktopAction = screen.getByRole("menuitem", { name: "desktop.addToDesktop" });
    fireEvent.mouseDown(desktopAction);
    fireEvent.click(desktopAction);
    expect(desktop).toHaveBeenCalledWith("settings");

    fireEvent.contextMenu(settings);
    fireEvent.click(screen.getByRole("menuitem", { name: "desktop.pinToStart" }));
    expect(start).toHaveBeenCalledWith("settings");

    fireEvent.contextMenu(settings);
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.pinToTaskbar" }));
    expect(taskbar).toHaveBeenCalledWith("settings");
  });

  it("shows recently used applications with a compact relative time", () => {
    const open = vi.fn();
    render(<AppLauncher apps={appList} startPinned={new Set(["files"])} desktopShortcuts={new Set()} taskbarPinned={new Set()} recentApps={[{ id: "settings", usedAt: Date.now() }]} profile={settingsFixture()} t={t} onOpen={open} onToggleStartPin={vi.fn()} onToggleDesktopShortcut={vi.fn()} onToggleTaskbarPin={vi.fn()} onLogout={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByText("desktop.recentlyUsed")).toBeInTheDocument();
    expect(screen.getByText("desktop.justNow")).toBeInTheDocument();
    fireEvent.click(screen.getByText("desktop.justNow").closest("button")!);
    expect(open).toHaveBeenCalledWith("settings");
  });

  it("opens a power menu and runs shutdown or restart separately", () => {
    const shutdown = vi.fn(); const restart = vi.fn();
    render(<AppLauncher apps={appList} startPinned={new Set()} desktopShortcuts={new Set()} taskbarPinned={new Set()} profile={settingsFixture()} t={t} onOpen={vi.fn()} onToggleStartPin={vi.fn()} onToggleDesktopShortcut={vi.fn()} onToggleTaskbarPin={vi.fn()} onShutdown={shutdown} onRestart={restart} onLogout={vi.fn()} onClose={vi.fn()} />);

    const trigger = screen.getByRole("button", { name: "shutdown.powerMenu" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("menuitem", { name: "shutdown.restart" }));
    expect(restart).toHaveBeenCalledOnce();
    expect(shutdown).not.toHaveBeenCalled();

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("menuitem", { name: "shutdown.close" }));
    expect(shutdown).toHaveBeenCalledOnce();
  });
});
