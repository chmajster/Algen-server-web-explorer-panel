import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { settingsFixture } from "../test/settings";
import { DesktopEnhancements } from "./DesktopEnhancements";

const t = (key: string) => key;

function renderDesktop(overrides = {}) {
  const save = vi.fn().mockResolvedValue(undefined);
  const toast = vi.fn();
  const profile = settingsFixture({ language: "pl-PL", ...overrides });
  const view = render(<>
    <div className="desktop"><main className="desktop-surface"><div className="desktop-background-child" /></main></div>
    <DesktopEnhancements profile={profile} t={t} toast={toast} onSettingsChange={save} />
  </>);
  return { ...view, save, toast };
}

describe("DesktopEnhancements", () => {
  it("opens a wallpaper context menu and can hide desktop icons", async () => {
    const { container, save } = renderDesktop({ show_desktop_shortcuts: true });

    fireEvent.contextMenu(container.querySelector(".desktop-surface") as HTMLElement, { clientX: 50, clientY: 60 });
    fireEvent.click(screen.getByRole("menuitem", { name: "Ukryj ikony pulpitu" }));

    await waitFor(() => expect(save).toHaveBeenCalledWith({ show_desktop_shortcuts: false }));
  });

  it("opens the desktop menu from an empty background child and exposes advanced desktop controls", () => {
    const { container } = renderDesktop({ taskbar_alignment: "center", theme: "system", wallpaper_fit: "cover" });

    fireEvent.contextMenu(container.querySelector(".desktop-background-child") as HTMLElement, { clientX: 80, clientY: 90 });

    expect(screen.getByRole("menuitem", { name: "Zarządzaj pulpitem" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Rozmiar ikon: Małe" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Dopasowanie tapety: Dopasuj do ekranu" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Wyrównanie paska: Do lewej" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Motyw: Ciemny" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Wyłącz powiadomienia" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Wyłącz przezroczystość okien" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Pokaż sekundy zegara" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Przywróć domyślne ustawienia pulpitu" })).toBeInTheDocument();
  });

  it("changes taskbar alignment from the desktop context menu", async () => {
    const { container, save } = renderDesktop({ taskbar_alignment: "center" });

    fireEvent.contextMenu(container.querySelector(".desktop-surface") as HTMLElement, { clientX: 50, clientY: 60 });
    fireEvent.click(screen.getByRole("menuitem", { name: "Wyrównanie paska: Do lewej" }));

    await waitFor(() => expect(save).toHaveBeenCalledWith({ taskbar_alignment: "left" }));
  });
});
