import type { InterfaceFont } from "../api";

export const interfaceFontStacks = {
  system: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  segoe: '"Segoe UI", system-ui, sans-serif',
  arial: "Arial, Helvetica, sans-serif",
  verdana: "Verdana, Geneva, sans-serif",
  tahoma: "Tahoma, Verdana, sans-serif",
  georgia: 'Georgia, "Times New Roman", serif',
  monospace: '"Cascadia Code", "Segoe UI Mono", Consolas, monospace',
} as const satisfies Record<InterfaceFont, string>;

export const interfaceFontOptions = Object.keys(interfaceFontStacks) as InterfaceFont[];
