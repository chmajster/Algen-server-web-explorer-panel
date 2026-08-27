import { fireEvent, render, screen } from "@testing-library/react";
import { Settings } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { settingsFixture } from "../test/settings";
import { AppLauncher } from "./AppLauncher";
import type { AppDefinition } from "./types";

const appList: AppDefinition[] = [
  { id: "settings", labelKey: "Settings", icon: <Settings /> },
];
const t = (key: string) => key;

describe("Start menu recent applications", () => {
  it("offers the same desktop, Start, and taskbar actions as All apps", () => {
    const desktop = vi.fn();
    const start = vi.fn();
    const taskbar = vi.fn();

    render(
      <div className="desktop">
        <AppLauncher
          apps={appList}
          startPinned={new Set()}
          desktopShortcuts={new Set()}
          taskbarPinned={new Set()}
          recentApps={[{ id: "settings", usedAt: Date.now() }]}
          profile={settingsFixture()}
          t={t}
          onOpen={vi.fn()}
          onToggleStartPin={start}
          onToggleDesktopShortcut={desktop}
          onToggleTaskbarPin={taskbar}
          onLogout={vi.fn()}
          onClose={vi.fn()}
        />
      </div>,
    );

    const recentApp = screen.getByText("desktop.justNow").closest("button")!;

    fireEvent.contextMenu(recentApp);
    fireEvent.click(screen.getByRole("menuitem", { name: "desktop.addToDesktop" }));
    expect(desktop).toHaveBeenCalledWith("settings");

    fireEvent.contextMenu(recentApp);
    fireEvent.click(screen.getByRole("menuitem", { name: "desktop.pinToStart" }));
    expect(start).toHaveBeenCalledWith("settings");

    fireEvent.contextMenu(recentApp);
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.pinToTaskbar" }));
    expect(taskbar).toHaveBeenCalledWith("settings");
  });
});
