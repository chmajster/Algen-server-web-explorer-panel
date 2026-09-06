import { fireEvent, render, screen } from "@testing-library/react";
import { HardDrive } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { settingsFixture } from "../test/settings";
import { AppLauncher } from "./AppLauncher";
import type { AppDefinition } from "./types";

const apps: AppDefinition[] = [
  { id: "files", labelKey: "File Manager", icon: <HardDrive /> },
];

const t = (key: string) => key;

describe("Start context menu layer", () => {
  it("portals an app context menu directly into the desktop system layer", () => {
    const { container } = render(
      <div className="desktop">
        <AppLauncher
          apps={apps}
          startPinned={new Set(["files"])}
          desktopShortcuts={new Set()}
          taskbarPinned={new Set()}
          profile={settingsFixture()}
          t={t}
          onOpen={vi.fn()}
          onToggleStartPin={vi.fn()}
          onToggleDesktopShortcut={vi.fn()}
          onToggleTaskbarPin={vi.fn()}
          onLogout={vi.fn()}
          onClose={vi.fn()}
        />
      </div>,
    );

    fireEvent.contextMenu(screen.getByRole("button", { name: "File Manager" }));

    const menu = screen.getByRole("menu");
    expect(menu).toHaveClass("launcher-context-menu");
    expect(menu.parentElement).toBe(container.querySelector(".desktop"));
  });
});
