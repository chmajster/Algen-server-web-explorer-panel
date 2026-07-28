import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type ModuleSummary } from "../api";
import { settingsFixture } from "../test/settings";
import { Desktop } from "./Desktop";
import { interfaceFontStacks } from "./interfaceFonts";

vi.mock("../features/modules/ModuleApp", () => ({ ModuleApp: ({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) => <button onClick={() => onDirtyChange(true)}>mark-module-dirty</button> }));

const controls = { add: vi.fn(() => []), pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(), retry: vi.fn(), setPriority: vi.fn() };
const t = (key: string) => key;

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.removeItem("webnas_windows_test");
  sessionStorage.removeItem("webnas_windows_test_session");
  localStorage.removeItem("webnas_recent_apps_test");
});

function renderDesktop(overrides = {}) {
  const profile = settingsFixture(overrides);
  return render(<Desktop user={{ username: profile.username, home: profile.home }} profile={profile} language={profile.language} theme={profile.theme} tasks={[]} uploadControls={controls} toasts={[]} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onTheme={vi.fn()} onLoggedOut={vi.fn()} />);
}

describe("personalized desktop", () => {
  it("renders a user wallpaper and the selected taskbar alignment", () => {
    const { container } = renderDesktop({ wallpaper: "https://example.com/wallpaper.jpg", taskbar_alignment: "left" });
    expect(container.querySelector(".desktop-surface")).toHaveStyle({ backgroundImage: 'url("https://example.com/wallpaper.jpg")' });
    expect(container.querySelector(".taskbar")).toHaveClass("taskbar-left");
  });

  it("hides desktop shortcuts and disables animations from preferences", () => {
    const { container } = renderDesktop({ show_desktop_shortcuts: false, animations_enabled: false });
    expect(screen.queryByLabelText("desktop.shortcuts")).not.toBeInTheDocument();
    expect(container.querySelector(".desktop")).toHaveClass("no-animations");
  });

  it("applies interface scale and larger text to the desktop typography", () => {
    const previousRootFontSize = document.documentElement.style.fontSize;
    const { container, rerender, unmount } = renderDesktop({ interface_scale: 125, larger_text: false });
    const desktop = container.querySelector<HTMLElement>(".desktop");
    expect(desktop?.style.getPropertyValue("--ui-scale")).toBe("1.25");
    expect(desktop?.style.getPropertyValue("--interface-scale")).toBe("1.25");
    expect(desktop?.style.getPropertyValue("--text-scale")).toBe("1");
    expect(document.documentElement.style.fontSize).toBe("20px");
    expect(document.documentElement.style.getPropertyValue("--interface-scale")).toBe("1.25");

    let profile = settingsFixture({ interface_scale: 100, larger_text: true });
    rerender(<Desktop user={{ username: profile.username, home: profile.home }} profile={profile} language={profile.language} theme={profile.theme} tasks={[]} uploadControls={controls} toasts={[]} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onTheme={vi.fn()} onLoggedOut={vi.fn()} />);
    expect(desktop).toHaveClass("larger-text");
    expect(desktop?.style.getPropertyValue("--text-scale")).toBe("1.125");
    expect(desktop?.style.getPropertyValue("--interface-scale")).toBe("1");
    expect(document.documentElement.style.fontSize).toBe("16px");

    profile = settingsFixture({ interface_scale: 200, larger_text: false });
    rerender(<Desktop user={{ username: profile.username, home: profile.home }} profile={profile} language={profile.language} theme={profile.theme} tasks={[]} uploadControls={controls} toasts={[]} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onTheme={vi.fn()} onLoggedOut={vi.fn()} />);
    expect(desktop?.style.getPropertyValue("--ui-scale")).toBe("2");
    expect(desktop?.style.getPropertyValue("--interface-scale")).toBe("2");
    expect(document.documentElement.style.fontSize).toBe("32px");

    unmount();
    expect(document.documentElement.style.fontSize).toBe(previousRootFontSize);
  });

  it("applies and reapplies the selected global interface font", () => {
    const { container, rerender } = renderDesktop({ interface_font: "verdana" });
    const desktop = container.querySelector<HTMLElement>(".desktop");
    expect(desktop?.style.getPropertyValue("--font-family-ui")).toBe(interfaceFontStacks.verdana);
    expect(document.documentElement.style.getPropertyValue("--font-family-ui")).toBe(interfaceFontStacks.verdana);

    const profile = settingsFixture({ interface_font: "georgia" });
    rerender(<Desktop user={{ username: profile.username, home: profile.home }} profile={profile} language={profile.language} theme={profile.theme} tasks={[]} uploadControls={controls} toasts={[]} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onTheme={vi.fn()} onLoggedOut={vi.fn()} />);
    expect(desktop?.style.getPropertyValue("--font-family-ui")).toBe(interfaceFontStacks.georgia);
  });

  it("does not expose administrative module applications to a standard user", () => {
    renderDesktop({ is_admin: false });
    fireEvent.click(screen.getByRole("button", { name: "desktop.mainMenu" }));
    expect(screen.queryByRole("button", { name: "app.samba" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "app.store" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "app.identity" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "app.fileManager" }).length).toBeGreaterThan(0);
  });

  it("shows one identity application only with users.view permission", () => {
    renderDesktop({ permissions: [...settingsFixture().permissions, "users.view", "groups.view", "access.view"] });
    fireEvent.click(screen.getByRole("button", { name: "desktop.mainMenu" }));
    fireEvent.click(screen.getByRole("button", { name: "desktop.allApps" }));
    expect(screen.getByRole("button", { name: "app.identity" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "app.users" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "app.groups" })).not.toBeInTheDocument();
  });

  it("shows the unified identity application with group-only access", () => {
    renderDesktop({ permissions: [...settingsFixture().permissions, "groups.view"] });
    fireEvent.click(screen.getByRole("button", { name: "desktop.mainMenu" }));
    fireEvent.click(screen.getByRole("button", { name: "desktop.allApps" }));
    expect(screen.getByRole("button", { name: "app.identity" })).toBeInTheDocument();
  });

  it("keeps Samba inside the shared module applications instead of the launcher", () => {
    renderDesktop({ is_admin: true, permissions: [...settingsFixture().permissions, "modules.view", "modules.install"] });
    fireEvent.click(screen.getByRole("button", { name: "desktop.mainMenu" }));
    fireEvent.click(screen.getByRole("button", { name: "desktop.allApps" }));
    expect(screen.queryByRole("button", { name: "app.samba" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "app.modules" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "app.store" })).toBeInTheDocument();
  });

  it("opens current-user information when the profile in Start is clicked", async () => {
    renderDesktop();
    fireEvent.click(screen.getByRole("button", { name: "desktop.mainMenu" }));
    fireEvent.click(screen.getByRole("button", { name: /desktop.openUserSettings/ }));

    expect(screen.getByRole("dialog", { name: "app.settings" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "settings.category.account" })).toBeInTheDocument();
    expect(screen.getAllByText("test").length).toBeGreaterThan(0);
  });

  it("adds Ansible to the Start application list only when its module is installed", async () => {
    vi.spyOn(api, "modules").mockResolvedValue([{ id: "ansible-controller", manifest: { name: "Ansible Automation Controller" }, state: { installed: true, update_available: false }, jobs: [], module_status: { health: "healthy" } }] as unknown as ModuleSummary[]);
    renderDesktop({ is_admin: true, permissions: [...settingsFixture().permissions, "modules.view"] });

    await waitFor(() => expect(api.modules).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "desktop.mainMenu" }));
    fireEvent.click(screen.getByRole("button", { name: "desktop.allApps" }));
    expect(screen.getByRole("button", { name: "ansible.name" })).toBeInTheDocument();
  });

  it("does not restore an identity window after permission is removed", () => {
    localStorage.setItem("webnas_windows_test", JSON.stringify({ windows: [{ id: "identity-1", app: "identity", rect: { x: 20, y: 20, width: 900, height: 600 }, minimized: false, zIndex: 11 }], activeId: "identity-1", counter: 1, topZ: 11 }));
    renderDesktop({ startup_windows: "last", permissions: settingsFixture().permissions });
    expect(screen.queryByRole("dialog", { name: "app.identity" })).not.toBeInTheDocument();
    localStorage.removeItem("webnas_windows_test");
  });

  it("saves the current windows synchronously before an F5 reload and restores them", () => {
    localStorage.removeItem("webnas_windows_test");
    const first = renderDesktop({ startup_windows: "last" });
    fireEvent.click(within(screen.getByLabelText("desktop.taskbar")).getByRole("button", { name: "app.monitor" }));
    expect(screen.getByRole("dialog", { name: "app.monitor" })).toBeInTheDocument();

    window.dispatchEvent(new Event("pagehide"));
    const saved = JSON.parse(localStorage.getItem("webnas_windows_test") || "{}") as { windows?: Array<{ app: string }> };
    expect(saved.windows).toEqual(expect.arrayContaining([expect.objectContaining({ app: "monitor" })]));

    first.unmount();
    renderDesktop({ startup_windows: "last" });
    expect(screen.getByRole("dialog", { name: "app.monitor" })).toBeInTheDocument();
    localStorage.removeItem("webnas_windows_test");
  });

  it("restores windows from the current browser tab after F5 even with an empty-desktop startup preference", () => {
    const first = renderDesktop({ startup_windows: "none" });
    fireEvent.click(within(screen.getByLabelText("desktop.taskbar")).getByRole("button", { name: "app.monitor" }));
    expect(screen.getByRole("dialog", { name: "app.monitor" })).toBeInTheDocument();
    expect(sessionStorage.getItem("webnas_windows_test_session")).toContain('"app":"monitor"');

    first.unmount();
    renderDesktop({ startup_windows: "none" });
    expect(screen.getByRole("dialog", { name: "app.monitor" })).toBeInTheDocument();
  });

  it("confirms before closing a module with unapplied changes", async () => {
    localStorage.setItem("webnas_windows_test", JSON.stringify({ windows: [{ id: "samba-1", app: "samba", rect: { x: 20, y: 20, width: 900, height: 600 }, minimized: false, zIndex: 11 }], activeId: "samba-1", counter: 1, topZ: 11 }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderDesktop({ is_admin: true, startup_windows: "last", permissions: [...settingsFixture().permissions, "modules.view", "modules.configure"] });
    fireEvent.click(await screen.findByRole("button", { name: "mark-module-dirty" }));
    fireEvent.click(screen.getByRole("button", { name: "action.close" }));
    expect(screen.getByRole("dialog", { name: "app.samba" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.close" }));
    expect(screen.queryByRole("dialog", { name: "app.samba" })).not.toBeInTheDocument();
    expect(confirm).toHaveBeenCalledTimes(2);
    confirm.mockRestore();
    localStorage.removeItem("webnas_windows_test");
  });

  it("controls a running window from the taskbar context menu", () => {
    localStorage.setItem("webnas_windows_test", JSON.stringify({ windows: [{ id: "transfers-1", app: "transfers", rect: { x: 20, y: 20, width: 900, height: 600 }, minimized: false, zIndex: 11 }], activeId: "transfers-1", counter: 1, topZ: 11 }));
    renderDesktop({ startup_windows: "last" });
    const taskbar = screen.getByLabelText("desktop.taskbar");
    expect(screen.getByRole("dialog", { name: "app.transfers" })).toBeInTheDocument();

    fireEvent.contextMenu(within(taskbar).getByRole("button", { name: "app.transfers" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "window.minimize" }));
    expect(screen.queryByRole("dialog", { name: "app.transfers" })).not.toBeInTheDocument();

    fireEvent.contextMenu(within(taskbar).getByRole("button", { name: "app.transfers" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.showWindow" }));
    expect(screen.getByRole("dialog", { name: "app.transfers" })).toBeInTheDocument();

    fireEvent.contextMenu(within(taskbar).getByRole("button", { name: "app.transfers" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.closeWindow" }));
    expect(screen.queryByRole("dialog", { name: "app.transfers" })).not.toBeInTheDocument();
    localStorage.removeItem("webnas_windows_test");
  });

  it("persists pinning changes through user settings", () => {
    const profile = settingsFixture({ pinned_apps: ["monitor", "settings"] });
    const save = vi.fn().mockResolvedValue(undefined);
    render(<Desktop user={{ username: profile.username, home: profile.home }} profile={profile} language={profile.language} theme={profile.theme} tasks={[]} uploadControls={controls} toasts={[]} t={t} toast={vi.fn()} onSettingsChange={save} onTheme={vi.fn()} onLoggedOut={vi.fn()} />);

    fireEvent.contextMenu(within(screen.getByLabelText("desktop.taskbar")).getByRole("button", { name: "app.monitor" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.unpinFromTaskbar" }));
    expect(save).toHaveBeenCalledWith({ pinned_apps: ["settings"] });
  });

  it("keeps a running application on the taskbar after pinning it and closing its window", () => {
    localStorage.setItem("webnas_windows_test", JSON.stringify({ windows: [{ id: "transfers-1", app: "transfers", rect: { x: 20, y: 20, width: 900, height: 600 }, minimized: false, zIndex: 11 }], activeId: "transfers-1", counter: 1, topZ: 11 }));
    const profile = settingsFixture({ pinned_apps: [] });
    const save = vi.fn().mockResolvedValue(undefined);
    render(<Desktop user={{ username: profile.username, home: profile.home }} profile={profile} language={profile.language} theme={profile.theme} tasks={[]} uploadControls={controls} toasts={[]} t={t} toast={vi.fn()} onSettingsChange={save} onTheme={vi.fn()} onLoggedOut={vi.fn()} />);
    const taskbar = screen.getByLabelText("desktop.taskbar");
    const transfersButton = within(taskbar).getByRole("button", { name: "app.transfers" });

    fireEvent.contextMenu(transfersButton);
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.pinToTaskbar" }));
    expect(save).toHaveBeenCalledWith({ pinned_apps: ["transfers"] });
    expect(transfersButton).toHaveClass("pinned");

    fireEvent.contextMenu(transfersButton);
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.closeWindow" }));
    expect(screen.queryByRole("dialog", { name: "app.transfers" })).not.toBeInTheDocument();
    expect(within(taskbar).getByRole("button", { name: "app.transfers" })).toHaveClass("pinned");
    localStorage.removeItem("webnas_windows_test");
  });

  it("persists a specific module on the taskbar after its window is closed", async () => {
    localStorage.setItem("webnas_windows_test", JSON.stringify({ windows: [{ id: "module-1", app: "module", moduleId: "linux-updates", rect: { x: 20, y: 20, width: 900, height: 600 }, minimized: false, zIndex: 11 }], activeId: "module-1", counter: 1, topZ: 11 }));
    vi.spyOn(api, "modules").mockResolvedValue([{ id: "linux-updates", manifest: { name: "Aktualizacje systemu" }, state: { installed: true, update_available: false }, jobs: [], module_status: { health: "healthy" } }] as unknown as ModuleSummary[]);
    const base = settingsFixture();
    const profile = settingsFixture({ startup_windows: "last", pinned_apps: [], pinned_modules: [], permissions: [...base.permissions, "modules.view"] });
    const save = vi.fn().mockResolvedValue(undefined);
    render(<Desktop user={{ username: profile.username, home: profile.home }} profile={profile} language={profile.language} theme={profile.theme} tasks={[]} uploadControls={controls} toasts={[]} t={t} toast={vi.fn()} onSettingsChange={save} onTheme={vi.fn()} onLoggedOut={vi.fn()} />);
    const taskbar = screen.getByLabelText("desktop.taskbar");
    const moduleButton = await within(taskbar).findByRole("button", { name: "Aktualizacje systemu" });

    fireEvent.contextMenu(moduleButton);
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.pinToTaskbar" }));
    expect(save).toHaveBeenCalledWith({ pinned_modules: ["linux-updates"] });
    expect(moduleButton).toHaveClass("pinned");

    fireEvent.contextMenu(moduleButton);
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.closeWindow" }));
    expect(within(taskbar).getByRole("button", { name: "Aktualizacje systemu" })).toHaveClass("pinned");
    localStorage.removeItem("webnas_windows_test");
  });

  it("persists independent desktop, Start, and taskbar destinations from All apps", () => {
    const profile = settingsFixture({ pinned_apps: [], start_pinned_apps: [], desktop_shortcut_apps: [] });
    const save = vi.fn().mockResolvedValue(undefined);
    const { container } = render(<Desktop user={{ username: profile.username, home: profile.home }} profile={profile} language={profile.language} theme={profile.theme} tasks={[]} uploadControls={controls} toasts={[]} t={t} toast={vi.fn()} onSettingsChange={save} onTheme={vi.fn()} onLoggedOut={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "desktop.mainMenu" }));
    fireEvent.click(screen.getByRole("button", { name: "desktop.allApps" }));
    const allApps = container.querySelector<HTMLElement>(".launcher-list");
    expect(allApps).not.toBeNull();
    const monitor = within(allApps as HTMLElement).getByRole("button", { name: "app.monitor" });

    fireEvent.contextMenu(monitor);
    fireEvent.click(screen.getByRole("menuitem", { name: "desktop.addToDesktop" }));
    expect(save).toHaveBeenCalledWith({ desktop_shortcut_apps: ["monitor"] });

    fireEvent.contextMenu(monitor);
    fireEvent.click(screen.getByRole("menuitem", { name: "desktop.pinToStart" }));
    expect(save).toHaveBeenCalledWith({ start_pinned_apps: ["monitor"] });

    fireEvent.contextMenu(monitor);
    fireEvent.click(screen.getByRole("menuitem", { name: "taskbar.pinToTaskbar" }));
    expect(save).toHaveBeenCalledWith({ pinned_apps: ["monitor"] });
  });
});
