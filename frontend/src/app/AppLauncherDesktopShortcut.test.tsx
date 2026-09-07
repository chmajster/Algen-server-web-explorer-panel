import { fireEvent, render, screen } from "@testing-library/react";
import { Settings } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { settingsFixture } from "../test/settings";
import { AppLauncher } from "./AppLauncher";
import type { AppDefinition } from "./types";

const apps: AppDefinition[] = [
  { id: "settings", labelKey: "Settings", icon: <Settings /> },
];
const t = (key: string) => key;

function renderLauncher(desktopShortcuts = new Set<string>()) {
  const toggleDesktop = vi.fn();
  render(
    <div className="desktop">
      <AppLauncher
        apps={apps}
        startPinned={new Set(["settings"])}
        desktopShortcuts={desktopShortcuts}
        taskbarPinned={new Set()}
        profile={settingsFixture()}
        t={t}
        onOpen={vi.fn()}
        onToggleStartPin={vi.fn()}
        onToggleDesktopShortcut={toggleDesktop}
        onToggleTaskbarPin={vi.fn()}
        onLogout={vi.fn()}
        onClose={vi.fn()}
      />
    </div>,
  );
  return toggleDesktop;
}

describe("Start menu desktop shortcuts", () => {
  it("adds a pinned application to the desktop from its context menu", () => {
    const toggleDesktop = renderLauncher();

    fireEvent.contextMenu(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "desktop.addToDesktop" }));

    expect(toggleDesktop).toHaveBeenCalledWith("settings");
  });

  it("shows the remove action when the application is already on the desktop", () => {
    renderLauncher(new Set(["settings"]));

    fireEvent.contextMenu(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("menuitem", { name: "desktop.removeFromDesktop" })).toBeInTheDocument();
  });

  it("keeps Start and taskbar shortcut actions in the same context menu", () => {
    renderLauncher();

    fireEvent.contextMenu(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("menuitem", { name: "desktop.addToDesktop" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "desktop.unpinFromStart" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "taskbar.pinToTaskbar" })).toBeInTheDocument();
  });
});
