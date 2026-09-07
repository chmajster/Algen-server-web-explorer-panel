import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";
import { DesktopWorkspace } from "./DesktopWorkspace";
import type { DesktopProps } from "./desktop/types";
import { apps, moduleRegistry } from "./registry/builtinModules";
import { WebNAS } from "./shell/WebNASShell";
import type { AppId } from "./types";

export function DesktopWorkspacePortal(props: DesktopProps) {
  const [target, setTarget] = useState<Element | null>(null);
  const [moduleNames, setModuleNames] = useState<Map<string, string>>(new Map());

  useEffect(() => {
    let cancelled = false;
    let frame = 0;
    const find = () => {
      const surface = document.querySelector(".desktop-surface");
      if (!surface) { frame = window.requestAnimationFrame(find); return; }
      if (!cancelled) {
        setTarget(surface);
        surface.closest(".desktop")?.classList.add("webnas-managed-workspace");
      }
    };
    find();
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frame);
      document.querySelector(".desktop")?.classList.remove("webnas-managed-workspace");
    };
  }, []);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const values = await api.modules();
        if (active) setModuleNames(new Map(values.filter((item) => item.state.installed).map((item) => [item.id, item.manifest.name])));
      } catch { /* module center surfaces backend errors */ }
    };
    void refresh();
    const changed = () => void refresh();
    window.addEventListener("webnas:modules-changed", changed);
    return () => { active = false; window.removeEventListener("webnas:modules-changed", changed); };
  }, []);

  const availableApps = useMemo(() => apps
    .filter((app) => !app.hidden && moduleRegistry.availableFor(app.id, props.profile.permissions, props.profile.is_admin))
    .map((app) => ({ id: app.id, label: props.t(app.labelKey), icon: app.icon })), [props.profile.is_admin, props.profile.permissions, props.t]);

  if (!target || !props.profile.show_desktop_shortcuts) return null;

  const toggleAppShortcut = (app: AppId) => {
    const current = new Set(props.profile.desktop_shortcut_apps);
    if (current.has(app)) current.delete(app); else current.add(app);
    void props.onSettingsChange({ desktop_shortcut_apps: [...current] });
  };
  const toggleModuleShortcut = (moduleId: string) => {
    const current = new Set(props.profile.desktop_shortcut_modules);
    if (current.has(moduleId)) current.delete(moduleId); else current.add(moduleId);
    void props.onSettingsChange({ desktop_shortcut_modules: [...current] });
  };

  return createPortal(<DesktopWorkspace
    apps={availableApps}
    modules={moduleNames}
    appIds={new Set(props.profile.desktop_shortcut_apps)}
    moduleIds={new Set(props.profile.desktop_shortcut_modules)}
    home={props.user.home}
    uploadControls={props.uploadControls}
    t={props.t}
    openApp={(app, initialPath, moduleId) => {
      if (app === "module" && moduleId) WebNAS.window.open("module", { moduleId });
      else if (initialPath) WebNAS.window.open(app, { initialPath });
      else WebNAS.app.open(app);
    }}
    toggleAppShortcut={toggleAppShortcut}
    toggleModuleShortcut={toggleModuleShortcut}
  />, target);
}
