import { describe, expect, it } from "vitest";
import { LayerManager, WEBNAS_LAYERS } from "./LayerManager";

describe("LayerManager", () => {
  it("keeps context menus above Start and below notifications", () => {
    const layers = new LayerManager();
    layers.assertOrdering();
    expect(layers.get("context-menu")).toBeGreaterThan(layers.get("start-menu"));
    expect(layers.get("notification-center")).toBeGreaterThan(layers.get("context-menu"));
  });

  it("installs and removes CSS layer variables", () => {
    const layers = new LayerManager();
    const target = document.createElement("div");
    layers.install(target);
    expect(target.style.getPropertyValue("--webnas-layer-context-menu")).toBe(String(WEBNAS_LAYERS["context-menu"]));
    layers.uninstall(target);
    expect(target.style.getPropertyValue("--webnas-layer-context-menu")).toBe("");
  });
});
