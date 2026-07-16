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

  it("does not expose administrative module applications to a standard user", () => {
    renderDesktop({ is_admin: false });
    fireEvent.click(screen.getByRole("button", { name: "desktop.mainMenu" }));
    expect(screen.queryByRole("button", { name: "app.samba" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "app.store" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "app.fileManager" }).length).toBeGreaterThan(0);
  });

  it("confirms before closing a module with unapplied changes", async () => {
    localStorage.setItem("webnas_windows_test", JSON.stringify({ windows: [{ id: "samba-1", app: "samba", rect: { x: 20, y: 20, width: 900, height: 600 }, minimized: false, zIndex: 11 }], activeId: "samba-1", counter: 1, topZ: 11 }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderDesktop({ is_admin: true, startup_windows: "last" });
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
