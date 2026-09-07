import { ContextMenuManager } from "./ContextMenuManager";
import { LayerManager } from "./LayerManager";

export type WebNASDeviceMode = "mobile" | "tablet" | "desktop";

export class DeviceManager {
  mode(): WebNASDeviceMode {
    if (typeof window === "undefined") return "desktop";
    if (window.matchMedia("(max-width: 640px)").matches) return "mobile";
    if (window.matchMedia("(max-width: 1024px)").matches) return "tablet";
    return "desktop";
  }

  get isMobile(): boolean { return this.mode() === "mobile"; }
  get isTablet(): boolean { return this.mode() === "tablet"; }
  get isDesktop(): boolean { return this.mode() === "desktop"; }
}

export class WebNASShellRuntime {
  readonly layer = new LayerManager();
  readonly contextMenu = new ContextMenuManager();
  readonly device = new DeviceManager();

  install(): void {
    this.layer.assertOrdering();
    this.layer.install();
  }

  uninstall(): void {
    this.contextMenu.close();
    this.layer.uninstall();
  }
}

export const WebNAS = new WebNASShellRuntime();

declare global {
  interface Window {
    WebNAS?: WebNASShellRuntime;
  }
}
