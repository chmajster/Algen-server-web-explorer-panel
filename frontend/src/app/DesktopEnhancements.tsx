import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Eye, EyeOff, Grid2X2, LayoutGrid, Monitor, Package, PanelBottom, RefreshCw, Search, SlidersHorizontal, Sparkles, Trash2 } from "lucide-react";
import { api, type ModuleSummary, type SettingsMe, type SettingsPatch } from "../api";
import { ContextMenu, type ContextMenuItem } from "../components/ContextMenu";
import { confirmDialog } from "../components/DialogService";
import { Modal } from "../components/Modal";
import { apps, moduleRegistry } from "./registry/builtinModules";
import type { ToastFn, Translate } from "./types";
import "./desktop-enhancements.css";

type DesktopEnhancementsProps = {
  profile: SettingsMe;
  t: Translate;
  toast: ToastFn;
  onSettingsChange: (patch: SettingsPatch) => Promise<void>;
};

type MenuState = { x: number; y: number; portalTarget: Element | null } | null;

const copy = {
  "pl-PL": {
    manage: "Zarządzaj pulpitem",
    refresh: "Odśwież pulpit",
    refreshed: "Pulpit odświeżony",
    showIcons: "Pokaż ikony pulpitu",
    hideIcons: "Ukryj ikony pulpitu",
    iconSize: "Rozmiar ikon",
    small: "Małe",
    medium: "Średnie",
    large: "Duże",
    welcomeOn: "Pokaż widżet powitalny",
    welcomeOff: "Ukryj widżet powitalny",
    title: "Menedżer pulpitu",
    subtitle: "Zarządzaj skrótami, menu Start, paskiem zadań i wyglądem pulpitu.",
    search: "Szukaj aplikacji lub modułu",
    appearance: "Wygląd i zachowanie",
    applications: "Aplikacje",
    modules: "Zainstalowane moduły",
    desktop: "Pulpit",
    start: "Start",
    taskbar: "Pasek zadań",
    none: "Brak elementów pasujących do wyszukiwania.",
    loading: "Ładowanie modułów…",
    showDesktopIcons: "Ikony na pulpicie",
    welcomeWidget: "Widżet powitalny",
    startup: "Po zalogowaniu",
    startupLast: "Przywróć ostatnie okna",
    startupNone: "Nie przywracaj okien",
    wallpaperFit: "Dopasowanie tapety",
    cover: "Wypełnij",
    contain: "Dopasuj",
    stretch: "Rozciągnij",
    center: "Wyśrodkuj",
    clearShortcuts: "Wyczyść skróty pulpitu",
    clearConfirm: "Usunąć wszystkie skróty aplikacji i modułów z pulpitu?",
    close: "Zamknij",
    saveFailed: "Nie udało się zapisać ustawień pulpitu.",
  },
  "en-US": {
    manage: "Manage desktop",
    refresh: "Refresh desktop",
    refreshed: "Desktop refreshed",
    showIcons: "Show desktop icons",
    hideIcons: "Hide desktop icons",
    iconSize: "Icon size",
    small: "Small",
    medium: "Medium",
    large: "Large",
    welcomeOn: "Show welcome widget",
    welcomeOff: "Hide welcome widget",
    title: "Desktop manager",
    subtitle: "Manage shortcuts, Start, taskbar and desktop appearance.",
    search: "Search applications or modules",
    appearance: "Appearance and behavior",
    applications: "Applications",
    modules: "Installed modules",
    desktop: "Desktop",
    start: "Start",
    taskbar: "Taskbar",
    none: "No items match your search.",
    loading: "Loading modules…",
    showDesktopIcons: "Desktop icons",
    welcomeWidget: "Welcome widget",
    startup: "After sign-in",
    startupLast: "Restore last windows",
    startupNone: "Do not restore windows",
    wallpaperFit: "Wallpaper fit",
    cover: "Cover",
    contain: "Contain",
    stretch: "Stretch",
    center: "Center",
    clearShortcuts: "Clear desktop shortcuts",
    clearConfirm: "Remove all application and module shortcuts from the desktop?",
    close: "Close",
    saveFailed: "Could not save desktop settings.",
  },
} as const;

function toggled(values: readonly string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

export function DesktopEnhancements({ profile, t, toast, onSettingsChange }: DesktopEnhancementsProps) {
  const text = copy[profile.language];
  const [menu, setMenu] = useState<MenuState>(null);
  const [managerOpen, setManagerOpen] = useState(false);
  const [modules, setModules] = useState<ModuleSummary[]>([]);
  const [modulesLoading, setModulesLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);

  const refreshModules = useCallback(async (announce = false) => {
    setModulesLoading(true);
    try {
      setModules(await api.modules());
      window.dispatchEvent(new Event("webnas:modules-changed"));
      if (announce) toast(text.refreshed, "ok");
    } catch (error) {
      if (announce) toast(error instanceof Error ? error.message : text.saveFailed, "error");
    } finally {
      setModulesLoading(false);
    }
  }, [text.refreshed, text.saveFailed, toast]);

  useEffect(() => {
    function contextMenu(event: MouseEvent) {
      const target = event.target;
      if (!(target instanceof HTMLElement) || !target.classList.contains("desktop-surface")) return;
      event.preventDefault();
      setMenu({ x: event.clientX, y: event.clientY, portalTarget: target.closest(".desktop") });
    }
    document.addEventListener("contextmenu", contextMenu);
    return () => document.removeEventListener("contextmenu", contextMenu);
  }, []);

  useEffect(() => {
    if (!managerOpen) return;
    void refreshModules();
  }, [managerOpen, refreshModules]);

  async function save(patch: SettingsPatch) {
    if (saving) return;
    setSaving(true);
    try {
      await onSettingsChange(patch);
    } catch (error) {
      toast(error instanceof Error ? error.message : text.saveFailed, "error");
    } finally {
      setSaving(false);
    }
  }

  const installedModuleIds = useMemo(() => new Set(modules.filter((item) => item.state.installed).map((item) => item.id)), [modules]);
  const normalized = query.trim().toLocaleLowerCase(profile.language);
  const visibleApps = useMemo(() => apps
    .filter((app) => !app.hidden && moduleRegistry.availableFor(app.id, profile.permissions, profile.is_admin))
    .filter((app) => !app.moduleId || installedModuleIds.has(app.moduleId))
    .filter((app) => !normalized || t(app.labelKey).toLocaleLowerCase(profile.language).includes(normalized))
    .sort((a, b) => t(a.labelKey).localeCompare(t(b.labelKey), profile.language)), [installedModuleIds, normalized, profile.is_admin, profile.language, profile.permissions, t]);
  const visibleModules = useMemo(() => modules
    .filter((item) => item.state.installed)
    .filter((item) => !normalized || item.manifest.name.toLocaleLowerCase(profile.language).includes(normalized) || item.id.toLocaleLowerCase(profile.language).includes(normalized))
    .sort((a, b) => a.manifest.name.localeCompare(b.manifest.name, profile.language)), [modules, normalized, profile.language]);

  const menuItems: ContextMenuItem[] = [
    { label: text.manage, icon: <SlidersHorizontal />, action: () => setManagerOpen(true) },
    { label: text.refresh, icon: <RefreshCw />, action: () => void refreshModules(true) },
    { label: profile.show_desktop_shortcuts ? text.hideIcons : text.showIcons, icon: profile.show_desktop_shortcuts ? <EyeOff /> : <Eye />, separator: true, action: () => void save({ show_desktop_shortcuts: !profile.show_desktop_shortcuts }) },
    { label: `${text.iconSize}: ${text.small}`, icon: profile.desktop_shortcut_size === "small" ? <Check /> : <Grid2X2 />, action: () => void save({ desktop_shortcut_size: "small" }) },
    { label: `${text.iconSize}: ${text.medium}`, icon: profile.desktop_shortcut_size === "medium" ? <Check /> : <Grid2X2 />, action: () => void save({ desktop_shortcut_size: "medium" }) },
    { label: `${text.iconSize}: ${text.large}`, icon: profile.desktop_shortcut_size === "large" ? <Check /> : <Grid2X2 />, action: () => void save({ desktop_shortcut_size: "large" }) },
    { label: profile.show_welcome_widget ? text.welcomeOff : text.welcomeOn, icon: <Sparkles />, separator: true, action: () => void save({ show_welcome_widget: !profile.show_welcome_widget }) },
  ];

  return <>
    {menu && <ContextMenu x={menu.x} y={menu.y} portalTarget={menu.portalTarget} className="desktop-management-context" items={menuItems} onClose={() => setMenu(null)} />}
    {managerOpen && <Modal title={text.title} closeLabel={text.close} wide className="desktop-manager-modal" onClose={() => setManagerOpen(false)} footer={<><button type="button" onClick={() => setManagerOpen(false)}>{text.close}</button></>}>
      <section className="desktop-manager">
        <header className="desktop-manager-intro"><SlidersHorizontal aria-hidden="true" /><div><strong>{text.title}</strong><span>{text.subtitle}</span></div></header>
        <div className="desktop-manager-search"><Search aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={text.search} aria-label={text.search} /></div>

        <section className="desktop-manager-section">
          <h3>{text.appearance}</h3>
          <div className="desktop-manager-settings-grid">
            <label><span>{text.showDesktopIcons}</span><input type="checkbox" checked={profile.show_desktop_shortcuts} disabled={saving} onChange={() => void save({ show_desktop_shortcuts: !profile.show_desktop_shortcuts })} /></label>
            <label><span>{text.welcomeWidget}</span><input type="checkbox" checked={profile.show_welcome_widget} disabled={saving} onChange={() => void save({ show_welcome_widget: !profile.show_welcome_widget })} /></label>
            <label><span>{text.iconSize}</span><select value={profile.desktop_shortcut_size} disabled={saving} onChange={(event) => void save({ desktop_shortcut_size: event.target.value as "small" | "medium" | "large" })}><option value="small">{text.small}</option><option value="medium">{text.medium}</option><option value="large">{text.large}</option></select></label>
            <label><span>{text.startup}</span><select value={profile.startup_windows} disabled={saving} onChange={(event) => void save({ startup_windows: event.target.value as "last" | "none" })}><option value="last">{text.startupLast}</option><option value="none">{text.startupNone}</option></select></label>
            <label><span>{text.wallpaperFit}</span><select value={profile.wallpaper_fit} disabled={saving} onChange={(event) => void save({ wallpaper_fit: event.target.value as "cover" | "contain" | "stretch" | "center" })}><option value="cover">{text.cover}</option><option value="contain">{text.contain}</option><option value="stretch">{text.stretch}</option><option value="center">{text.center}</option></select></label>
          </div>
        </section>

        <section className="desktop-manager-section">
          <div className="desktop-manager-section-heading"><h3>{text.applications}</h3><span>{visibleApps.length}</span></div>
          <div className="desktop-manager-list">
            {visibleApps.map((app) => <article key={app.id} className="desktop-manager-item">
              <span className="desktop-manager-item-icon" aria-hidden="true">{app.icon}</span>
              <div className="desktop-manager-item-copy"><strong>{t(app.labelKey)}</strong><small>{app.id}</small></div>
              <div className="desktop-manager-item-actions">
                <button type="button" disabled={saving} className={profile.desktop_shortcut_apps.includes(app.id) ? "active" : ""} aria-pressed={profile.desktop_shortcut_apps.includes(app.id)} onClick={() => void save({ desktop_shortcut_apps: toggled(profile.desktop_shortcut_apps, app.id) })}><Monitor />{text.desktop}</button>
                <button type="button" disabled={saving} className={profile.start_pinned_apps.includes(app.id) ? "active" : ""} aria-pressed={profile.start_pinned_apps.includes(app.id)} onClick={() => void save({ start_pinned_apps: toggled(profile.start_pinned_apps, app.id) })}><LayoutGrid />{text.start}</button>
                <button type="button" disabled={saving} className={profile.pinned_apps.includes(app.id) ? "active" : ""} aria-pressed={profile.pinned_apps.includes(app.id)} onClick={() => void save({ pinned_apps: toggled(profile.pinned_apps, app.id) })}><PanelBottom />{text.taskbar}</button>
              </div>
            </article>)}
            {!visibleApps.length && <p className="desktop-manager-empty">{text.none}</p>}
          </div>
        </section>

        <section className="desktop-manager-section">
          <div className="desktop-manager-section-heading"><h3>{text.modules}</h3><span>{visibleModules.length}</span></div>
          {modulesLoading && <p className="desktop-manager-loading">{text.loading}</p>}
          {!modulesLoading && <div className="desktop-manager-list">
            {visibleModules.map((item) => <article key={item.id} className="desktop-manager-item">
              <span className="desktop-manager-item-icon" aria-hidden="true"><Package /></span>
              <div className="desktop-manager-item-copy"><strong>{item.manifest.name}</strong><small>{item.id}</small></div>
              <div className="desktop-manager-item-actions">
                <button type="button" disabled={saving} className={profile.desktop_shortcut_modules.includes(item.id) ? "active" : ""} aria-pressed={profile.desktop_shortcut_modules.includes(item.id)} onClick={() => void save({ desktop_shortcut_modules: toggled(profile.desktop_shortcut_modules, item.id) })}><Monitor />{text.desktop}</button>
                <button type="button" disabled={saving} className={profile.pinned_modules.includes(item.id) ? "active" : ""} aria-pressed={profile.pinned_modules.includes(item.id)} onClick={() => void save({ pinned_modules: toggled(profile.pinned_modules, item.id) })}><PanelBottom />{text.taskbar}</button>
              </div>
            </article>)}
            {!visibleModules.length && <p className="desktop-manager-empty">{text.none}</p>}
          </div>}
        </section>

        <footer className="desktop-manager-danger-zone"><button type="button" className="button-danger" disabled={saving || (!profile.desktop_shortcut_apps.length && !profile.desktop_shortcut_modules.length)} onClick={() => void (async () => { if (await confirmDialog(text.clearConfirm, t)) await save({ desktop_shortcut_apps: [], desktop_shortcut_modules: [] }); })()}><Trash2 />{text.clearShortcuts}</button></footer>
      </section>
    </Modal>}
  </>;
}
