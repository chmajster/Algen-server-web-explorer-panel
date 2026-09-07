export const WEBNAS_LAYERS = {
  desktop: 100,
  windows: 1000,
  "window-overlays": 3000,
  taskbar: 5000,
  "start-menu": 5100,
  "context-menu": 5200,
  "notification-center": 5300,
  toast: 5400,
  modal: 6000,
  "system-critical": 10000,
} as const;

export type WebNASLayer = keyof typeof WEBNAS_LAYERS;

const CSS_PREFIX = "--webnas-layer-";

export class LayerManager {
  private readonly layers = new Map<WebNASLayer, number>(Object.entries(WEBNAS_LAYERS) as [WebNASLayer, number][]);

  get(layer: WebNASLayer): number {
    return this.layers.get(layer) ?? WEBNAS_LAYERS.desktop;
  }

  cssVar(layer: WebNASLayer): string {
    return `var(${CSS_PREFIX}${layer}, ${this.get(layer)})`;
  }

  install(target: HTMLElement = document.documentElement): void {
    for (const [layer, zIndex] of this.layers) target.style.setProperty(`${CSS_PREFIX}${layer}`, String(zIndex));
  }

  uninstall(target: HTMLElement = document.documentElement): void {
    for (const layer of this.layers.keys()) target.style.removeProperty(`${CSS_PREFIX}${layer}`);
  }

  assertOrdering(): void {
    const required: WebNASLayer[] = [
      "desktop",
      "windows",
      "window-overlays",
      "taskbar",
      "start-menu",
      "context-menu",
      "notification-center",
      "toast",
      "modal",
      "system-critical",
    ];
    for (let index = 1; index < required.length; index += 1) {
      if (this.get(required[index]) <= this.get(required[index - 1])) {
        throw new Error(`Invalid WebNAS layer ordering: ${required[index]} must be above ${required[index - 1]}`);
      }
    }
  }
}
