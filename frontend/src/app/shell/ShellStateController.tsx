import { useEffect, useRef } from "react";
import { WebNAS } from "./WebNASShell";
import { defaultShellPreferences, shellPreferencesClient, type ShellPreferences } from "./preferences";
import type { ShellEvent } from "./managers";

function normalized(value: ShellPreferences | null | undefined): ShellPreferences {
  return { ...defaultShellPreferences, ...(value || {}) };
}

export function ShellStateController() {
  const state = useRef<ShellPreferences>(defaultShellPreferences);
  const saveTimer = useRef<number | null>(null);
  const hydrated = useRef(false);

  useEffect(() => {
    let active = true;
    void shellPreferencesClient.get().then((value) => {
      if (!active) return;
      state.current = normalized(value);
      hydrated.current = true;
    }).catch(() => {
      hydrated.current = true;
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const persist = () => {
      if (!hydrated.current) return;
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => {
        saveTimer.current = null;
        void shellPreferencesClient.save(state.current).catch(() => undefined);
      }, 250);
    };

    const update = (patch: Partial<ShellPreferences>) => {
      state.current = { ...state.current, ...patch };
      persist();
    };

    const taskbar = WebNAS.taskbar.subscribe((event: ShellEvent) => {
      if (event.type === "reorder" && Array.isArray(event.detail)) update({ taskbar_order: event.detail.filter((id): id is string => typeof id === "string") });
    });
    const start = WebNAS.startMenu.subscribe((event: ShellEvent) => {
      if (event.type === "reorder" && Array.isArray(event.detail)) update({ start_order: event.detail.filter((id): id is string => typeof id === "string") });
    });
    const desktop = WebNAS.desktop.subscribe((event: ShellEvent) => {
      if (event.type !== "positions" || !Array.isArray(event.detail)) return;
      const positions = new Map((event.detail as Array<{ id: string; x: number; y: number }>).map((item) => [item.id, item]));
      update({
        desktop_entries: state.current.desktop_entries.map((item) => {
          const position = positions.get(item.id);
          return position ? { ...item, position: { x: position.x, y: position.y } } : item;
        }),
      });
    });
    const notifications = WebNAS.notification.subscribe((event: ShellEvent) => {
      if (event.type !== "changed") return;
      const items = WebNAS.notification.list();
      update({
        notifications: {
          unread: WebNAS.notification.unread(),
          read_ids: items.filter((item) => item.read).slice(0, 250).map((item) => item.id),
        },
      });
    });

    const orientation = () => update({
      mobile: {
        ...state.current.mobile,
        mode: WebNAS.device.mode(),
        orientation: window.matchMedia("(orientation: portrait)").matches ? "portrait" : "landscape",
      },
    });
    window.addEventListener("orientationchange", orientation);

    return () => {
      taskbar(); start(); desktop(); notifications();
      window.removeEventListener("orientationchange", orientation);
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    };
  }, []);

  return null;
}
