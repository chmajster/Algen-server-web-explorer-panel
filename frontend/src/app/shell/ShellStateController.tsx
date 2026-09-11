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
  const pending = useRef<ShellPreferencesPatch>({});

  useEffect(() => {
    let active = true;
    const flushPending = (base: ShellPreferences) => {
      const queued = pending.current;
      pending.current = {};
      state.current = { ...base, ...queued };
      hydrated.current = true;
      if (Object.keys(queued).length === 0) return;
      void shellPreferencesClient.patch(queued).catch(() => undefined);
    };

    void shellPreferencesClient.get().then((value) => {
      if (!active) return;
      flushPending(normalized(value));
    }).catch(() => {
      if (!active) return;
      flushPending(state.current);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const scheduledTimers = timers.current;
    const update = (key: keyof ShellPreferences, patch: ShellPreferencesPatch) => {
      state.current = { ...state.current, ...patch };
      if (!hydrated.current) {
        pending.current = { ...pending.current, ...patch };
        return;
      }
      const existing = scheduledTimers.get(key);
      if (existing !== undefined) window.clearTimeout(existing);
      scheduledTimers.set(key, window.setTimeout(() => {
        scheduledTimers.delete(key);
        void shellPreferencesClient.patch(patch).catch(() => undefined);
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
      for (const timer of scheduledTimers.values()) window.clearTimeout(timer);
      scheduledTimers.clear();
    };
  }, []);

  return null;
}
