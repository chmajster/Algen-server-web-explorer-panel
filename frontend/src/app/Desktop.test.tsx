import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { settingsFixture } from "../test/settings";
import { Desktop } from "./Desktop";

vi.mock("../features/modules/ModuleApp", () => ({ ModuleApp: ({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) => <button onClick={() => onDirtyChange(true)}>mark-module-dirty</button> }));

const controls = { add: vi.fn(() => []), pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(), retry: vi.fn(), setPriority: vi.fn() };
const t = (key: string) => key;

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
    const { container, rerender } = renderDesktop({ interface_scale: 125, larger_text: false });
    const desktop = container.querySelector<HTMLElement>(".desktop");
    expect(desktop?.style.getPropertyValue("--interface-font-size")).toBe("20px");
    expect(desktop?.style.getPropertyValue("--taskbar-height-scaled")).toBe("72.5px");

    const profile = settingsFixture({ interface_scale: 100, larger_text: true });
    rerender(<Desktop user={{ username: profile.username, home: profile.home }} profile={profile} language={profile.language} theme={profile.theme} tasks={[]} uploadControls={controls} toasts={[]} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onTheme={vi.fn()} onLoggedOut={vi.fn()} />);
    expect(desktop).toHaveClass("larger-text");
    expect(desktop?.style.getPropertyValue("--interface-font-size")).toBe("18px");
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

  it("does not restore an identity window after permission is removed", () => {
    localStorage.setItem("webnas_windows_test", JSON.stringify({ windows: [{ id: "identity-1", app: "identity", rect: { x: 20, y: 20, width: 900, height: 600 }, minimized: false, zIndex: 11 }], activeId: "identity-1", counter: 1, topZ: 11 }));
    renderDesktop({ startup_windows: "last", permissions: settingsFixture().permissions });
    expect(screen.queryByRole("dialog", { name: "app.identity" })).not.toBeInTheDocument();
    localStorage.removeItem("webnas_windows_test");
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
});
