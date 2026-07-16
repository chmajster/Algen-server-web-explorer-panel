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
  it("filters apps, launches the selected app and closes", () => {
    const open = vi.fn(); const close = vi.fn();
    render(<AppLauncher apps={appList} pinned={new Set(["files", "settings"])} profile={settingsFixture()} t={t} onOpen={open} onTogglePin={vi.fn()} onLogout={vi.fn()} onClose={close} />);

    fireEvent.change(screen.getByLabelText("desktop.searchApps"), { target: { value: "settings" } });
    expect(screen.queryByRole("button", { name: "File Manager" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(open).toHaveBeenCalledWith("settings");
    expect(close).toHaveBeenCalled();
  });

  it("closes on Escape and outside click", () => {
    const close = vi.fn();
    render(<AppLauncher apps={appList} pinned={new Set(["files"])} profile={settingsFixture()} t={t} onOpen={vi.fn()} onTogglePin={vi.fn()} onLogout={vi.fn()} onClose={close} />);
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.mouseDown(document.body);
    expect(close).toHaveBeenCalledTimes(2);
  });
});
