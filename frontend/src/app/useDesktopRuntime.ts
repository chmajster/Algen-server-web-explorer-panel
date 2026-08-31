import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { measureWorkspaceMetrics, navbarElements, sameViewportMetrics } from "./workspaceMetrics";
import type { ViewportMetrics } from "./windowState";

export function useDesktopClock(showSeconds: boolean): Date {
  const [clock, setClock] = useState(new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), showSeconds ? 1000 : 30000);
    return () => window.clearInterval(timer);
  }, [showSeconds]);
  return clock;
}

export function useSystemDarkMode(): boolean {
  const [systemDark, setSystemDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const change = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  return systemDark;
}

export function useDesktopViewport(interfaceScale: number) {
  const [viewport, setViewport] = useState<ViewportMetrics>(() => ({ width: window.innerWidth, height: window.innerHeight, bottom: 58 * interfaceScale, scale: interfaceScale }));
  const desktopRef = useRef<HTMLDivElement>(null);
  const surfaceRef = useRef<HTMLElement>(null);
  const initialViewportMetrics = useRef(viewport);

  useLayoutEffect(() => {
    const desktop = desktopRef.current;
    const surface = surfaceRef.current;
    if (!desktop || !surface) return;
    let animationFrame = 0;
    const measure = () => {
      const next = measureWorkspaceMetrics(desktop, surface, interfaceScale);
      initialViewportMetrics.current = next;
      setViewport((current) => sameViewportMetrics(current, next) ? current : next);
    };
    const scheduleMeasure = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(measure);
    };
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(scheduleMeasure);
    resizeObserver?.observe(desktop);
    resizeObserver?.observe(surface);
    const observeChrome = () => {
      const taskbar = desktop.querySelector<HTMLElement>(".taskbar");
      if (taskbar) resizeObserver?.observe(taskbar);
      navbarElements().forEach((navbar) => resizeObserver?.observe(navbar));
      scheduleMeasure();
    };
    const mutationObserver = typeof MutationObserver === "undefined" ? null : new MutationObserver(observeChrome);
    if (document.body) mutationObserver?.observe(document.body, { childList: true, subtree: true });
    measure();
    observeChrome();
    window.addEventListener("resize", scheduleMeasure);
    window.addEventListener("orientationchange", scheduleMeasure);
    window.visualViewport?.addEventListener("resize", scheduleMeasure);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      window.removeEventListener("resize", scheduleMeasure);
      window.removeEventListener("orientationchange", scheduleMeasure);
      window.visualViewport?.removeEventListener("resize", scheduleMeasure);
    };
  }, [interfaceScale]);

  return { viewport, desktopRef, surfaceRef, initialViewportMetrics };
}
