import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { settingsFixture } from "../test/settings";
import { DesktopEnhancements } from "./DesktopEnhancements";

const t = (key: string) => key;

describe("DesktopEnhancements", () => {
  it("opens a wallpaper context menu and can hide desktop icons", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const toast = vi.fn();
    const profile = settingsFixture({ language: "pl-PL", show_desktop_shortcuts: true });

    const { container } = render(<>
      <div className="desktop"><main className="desktop-surface" /></div>
      <DesktopEnhancements profile={profile} t={t} toast={toast} onSettingsChange={save} />
    </>);

    fireEvent.contextMenu(container.querySelector(".desktop-surface") as HTMLElement, { clientX: 50, clientY: 60 });
    fireEvent.click(screen.getByRole("menuitem", { name: "Ukryj ikony pulpitu" }));

    await waitFor(() => expect(save).toHaveBeenCalledWith({ show_desktop_shortcuts: false }));
  });
});
