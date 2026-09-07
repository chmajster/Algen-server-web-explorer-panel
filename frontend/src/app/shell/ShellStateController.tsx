import { useEffect, useRef } from "react";
import { WebNAS } from "./WebNASShell";
import { defaultShellPreferences, shellPreferencesClient, type ShellPreferences, type ShellPreferencesPatch } from "./preferences";
import type { ShellEvent } from "./managers";

function normalized(value: ShellPreferences | null | undefined): ShellPreferences {
  return { ...defaultShellPreferences, ...(value || {}) };
}

export function ShellStateController() {
  const state = useRef<ShellPreferences>(defaultShellPreferences);
  const timers = useRef(new Map<string, number>());
  const hydrated = useRef(false);

  useEffect(() => {
    let active = true;
    void shellPreferencesClient.get().then((value) => {
      if (!active) return;
      state.current = normalized(value);
      hydrated.current = true;
    }).catch(() => { hydrated.current = true; });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const update = (key: keyof ShellPreferences, patch: ShellPreferencesPatch) => {
      state.current = { ...state.current, ...patch };
      if (!hydrated.current) return;
      const existing = timers.current.get(key);
      if (existing !== undefined) window.clearTimeout(existing);
      timers.current.set(key, window.setTimeout(() => {
        timers.current.delete(key);
        void shellPreferencesClient.patch(patch).then((value) => { state.current = normalized(value); }).catch(() => undefined);
      }, 200));
    };

    const taskbar = WebNAS.taskbar.subscribe((event: ShellEvent) => {
      if (event.type === "reorder" && Array.isArray(event.detail)) {
        update("taskbar_order", { taskbar_order: event.detail.filter((id): id is string => typeof id === "string") });
      }
    });
    const start = WebNAS.startMenu.subscribe((event: ShellEvent) => {
      if (event.type === "reorder" && Array.isArray(event.detail)) {
        update("start_order", { start_order: event.detail.filter((id): id is string => typeof id === "string") });
      }
    });
    const desktop = WebNAS.desktop.subscribe((event: ShellEvent) => {
      if (event.type !== "positions" || !Array.isArray(event.detail)) return;
      const positions = new Map((event.detail as Array<{ id: string; x: number; y: number }>).map((item) => [item.id, item]));
      const desktopEntries = state.current.desktop_entries.map((item) => {
        const position = positions.get(item.id);
        return position ? { ...item, position: { x: position.x, y: position.y } } : item;
      });
      update("desktop_entries", { desktop_entries: desktopEntries });
    });
    const notifications = WebNAS.notification.subscribe((event: ShellEvent) => {
      if (event.type !== "changed") return;
      const items = WebNAS.notification.list();
      update("notifications", {
        notifications: {
          unread: WebNAS.notification.unread(),
          read_ids: items.filter((item) => item.read).slice(0, 250).map((item) => item.id),
        },
      });
    });

    const orientation = () => update("mobile", {
      mobile: {
        ...state.current.mobile,
        mode: WebNAS.device.mode(),
        orientation: window.matchMedia("(orientation: portrait)").matches ? "portrait" : "landscape",
      },
    });
    orientation();
    window.addEventListener("orientationchange", orientation);

    return () => {
      taskbar(); start(); desktop(); notifications();
      window.removeEventListener("orientationchange", orientation);
      for (const timer of timers.current.values()) window.clearTimeout(timer);
      timers.current.clear();
    };
  }, []);

  return null;
}
