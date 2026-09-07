import { FolderPlus, Grid2X2, Image, Link2, RefreshCw, Settings2 } from "lucide-react";
import { useEffect } from "react";
import { WebNAS } from "./WebNASShell";

export function DesktopContextBridge() {
  useEffect(() => {
    const context = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const workspace = target.closest(".desktop-workspace");
      if (!workspace || target.closest("[data-desktop-entry]")) return;
      event.preventDefault();
      event.stopPropagation();
      WebNAS.contextMenu.open({
        x: event.clientX,
        y: event.clientY,
        source: "desktop",
        items: [
          { label: "Nowy folder", icon: <FolderPlus />, action: () => WebNAS.desktop.createFolder() },
          { label: "Nowy skrót", icon: <Link2 />, action: () => WebNAS.desktop.createShortcut() },
          { label: "Wklej", disabled: WebNAS.clipboard.get() === null, action: () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "v", ctrlKey: true, bubbles: true })) },
          { label: "Odśwież", icon: <RefreshCw />, separator: true, action: () => window.dispatchEvent(new Event("webnas:desktop-refresh")) },
          {
            label: "Sortuj",
            icon: <Grid2X2 />,
            children: [
              { label: "Po nazwie", action: () => WebNAS.desktop.sort("name") },
              { label: "Po typie", action: () => WebNAS.desktop.sort("type") },
              { label: "Po dacie", action: () => WebNAS.desktop.sort("date") },
            ],
          },
          { label: "Wyrównaj ikony", action: () => WebNAS.desktop.align() },
          { label: "Ustawienia pulpitu", icon: <Settings2 />, separator: true, action: () => WebNAS.window.open("settings", { initialPath: "personalization" }) },
          { label: "Zmień tapetę", icon: <Image />, action: () => WebNAS.window.open("settings", { initialPath: "personalization" }) },
        ],
      });
    };
    document.addEventListener("contextmenu", context, true);
    return () => document.removeEventListener("contextmenu", context, true);
  }, []);
  return null;
}
