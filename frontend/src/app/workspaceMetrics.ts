import type { ViewportMetrics } from "./windowState";

export const NAVBAR_SELECTOR = "[data-main-navbar], .main-navbar, .system-bar, .navbar, header[role='banner']";

function visibleRect(element: HTMLElement) {
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0 ? rect : null;
}

export function navbarElements(root: ParentNode = document) {
  return Array.from(root.querySelectorAll<HTMLElement>(NAVBAR_SELECTOR))
    .filter((element) => !element.closest(".desktop-window"));
}

export function measureWorkspaceMetrics(desktop: HTMLElement, surface: HTMLElement, scale: number): ViewportMetrics {
  const surfaceRect = surface.getBoundingClientRect();
  const width = surfaceRect.width || surface.clientWidth || desktop.clientWidth || window.innerWidth;
  const height = surfaceRect.height || surface.clientHeight || desktop.clientHeight || window.innerHeight;
  const originX = surfaceRect.width ? surfaceRect.left : 0;
  const originY = surfaceRect.height ? surfaceRect.top : 0;
  const surfaceRight = originX + width;
  const surfaceBottom = originY + height;

  const top = navbarElements()
    .map(visibleRect)
    .filter((rect): rect is DOMRect => Boolean(
      rect
      && rect.left < surfaceRight
      && rect.right > originX
      && rect.top <= originY + 1
      && rect.bottom > originY
    ))
    .reduce((inset, rect) => Math.max(inset, Math.min(height, rect.bottom - originY)), 0);

  const taskbarRect = desktop.querySelector<HTMLElement>(".taskbar");
  const visibleTaskbarRect = taskbarRect ? visibleRect(taskbarRect) : null;
  const bottom = visibleTaskbarRect
    && visibleTaskbarRect.left < surfaceRight
    && visibleTaskbarRect.right > originX
    && visibleTaskbarRect.top < surfaceBottom
    && visibleTaskbarRect.bottom > originY
    ? Math.max(0, Math.min(height - top, surfaceBottom - visibleTaskbarRect.top))
    : 0;

  return { width, height, top, right: 0, bottom, left: 0, originX, originY, scale };
}

export function sameViewportMetrics(left: ViewportMetrics, right: ViewportMetrics) {
  return left.width === right.width
    && left.height === right.height
    && left.top === right.top
    && left.right === right.right
    && left.bottom === right.bottom
    && left.left === right.left
    && left.originX === right.originX
    && left.originY === right.originY
    && left.scale === right.scale;
}
