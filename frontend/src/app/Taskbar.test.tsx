import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { settingsFixture } from "../test/settings";
import { apps } from "./catalog";
import { Taskbar } from "./Taskbar";
import type { WindowInstance } from "./types";

const runningFile: WindowInstance = { id: "files-1", app: "files", rect: { x: 20, y: 20, width: 800, height: 600 }, minimized: false, zIndex: 12 };
const handlers = () => ({
  onToggleLauncher: vi.fn(), onToggleNotifications: vi.fn(), onToggleTheme: vi.fn(), onApp: vi.fn(), onOpenNew: vi.fn(), onTogglePin: vi.fn(), onWindow: vi.fn(), onCloseApp: vi.fn(), onTaskbarSettings: vi.fn(), onAlignment: vi.fn(), onLogout: vi.fn(),
});

function renderTaskbar(overrides: { pinned?: Set<"files" | "monitor">; windows?: WindowInstance[]; activeId?: string } = {}) {
  const events = handlers();
  render(<Taskbar apps={apps.filter((app) => ["files", "monitor", "settings"].includes(app.id))} pinned={overrides.pinned || new Set(["monitor"])} windows={overrides.windows || [runningFile]} activeId={overrides.activeId ?? runningFile.id} profile={settingsFixture()} resolvedTheme="light" clockText="12:00" dateText="17.07.2026" activeTransfers={0} launcherOpen={false} notificationsOpen={false} t={(key) => key} {...events} />);
  return events;
}

describe("Windows-like taskbar", () => {
  it("shows pinned apps first and appends running unpinned apps", () => {
    renderTaskbar();
    const buttons = within(screen.getByLabelText("desktop.runningApps")).getAllByRole("button");
    expect(buttons.map((button) => button.getAttribute("aria-label"))).toEqual(["app.monitor", "app.fileManager"]);
    expect(buttons[0]).toHaveClass("pinned");
    expect(buttons[1]).toHaveClass("running", "active");
  });

  it("opens a right-click menu with window operations and pinning", () => {
    const events = renderTaskbar();
    fireEvent.contextMenu(screen.getByRole("button", { name: "app.fileManager" }));

    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "window.minimize" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "window.maximize" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "taskbar.pinToTaskbar" })).toBeInTheDocument();
    fireEvent.click(within(menu).getByRole("menuitem", { name: "taskbar.closeWindow" }));
    expect(events.onCloseApp).toHaveBeenCalledWith("files");
  });

  it("allows alignment and taskbar settings from the empty taskbar menu", () => {
    const events = renderTaskbar();
    const taskbar = screen.getByLabelText("desktop.taskbar");
    fireEvent.contextMenu(taskbar);
    const menu = screen.getByRole("menu");
    expect(menu).toHaveClass("taskbar-context-menu");
    expect(taskbar).not.toContainElement(menu);
    expect(menu.parentElement).toBe(taskbar.parentElement);
    fireEvent.click(screen.getByRole("menuitem", { name: "settings.alignLeft" }));
    expect(events.onAlignment).toHaveBeenCalledWith("left");

    fireEvent.contextMenu(screen.getByLabelText("desktop.taskbar"));
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.settings" }));
    expect(events.onTaskbarSettings).toHaveBeenCalledOnce();
  });

  it("exposes each running window and bulk actions for grouped applications", () => {
    const second = { ...runningFile, id: "files-2", minimized: true, zIndex: 13 };
    const events = renderTaskbar({ windows: [runningFile, second], activeId: runningFile.id });
    fireEvent.contextMenu(screen.getByRole("button", { name: "app.fileManager" }));
    expect(screen.getByLabelText("taskbar.windowCount: 2")).toHaveTextContent("2");
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.minimizeAll" }));
    expect(events.onWindow).toHaveBeenCalledWith(second, "minimize");
    expect(events.onWindow).toHaveBeenCalledWith(runningFile, "minimize");
  });
});
