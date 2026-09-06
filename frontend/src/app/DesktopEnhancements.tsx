import { useCallback, useEffect, useMemo, useState } from "react";
import { AlignCenter, AlignLeft, Bell, BellOff, Check, Clock3, Eye, EyeOff, Grid2X2, Image, LayoutGrid, Monitor, Moon, Package, PanelBottom, RefreshCw, Search, SlidersHorizontal, Sparkles, Sun, Trash2, WandSparkles } from "lucide-react";
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
    cover: "Wypełnij ekran",
    contain: "Dopasuj do ekranu",
    stretch: "Rozciągnij",
    center: "Wyśrodkuj",
    taskbarAlignment: "Wyrównanie paska",
    left: "Do lewej",
    centered: "Na środku",
    theme: "Motyw",
    themeSystem: "Zgodny z systemem",
    themeLight: "Jasny",
    themeDark: "Ciemny",
    notificationsOn: "Włącz powiadomienia",
    notificationsOff: "Wyłącz powiadomienia",
    transfersOn: "Pokaż wskaźnik transferów",
    transfersOff: "Ukryj wskaźnik transferów",
    actionsOn: "Pokaż działania w tle",
    actionsOff: "Ukryj działania w tle",
    transparencyOn: "Włącz przezroczystość okien",
    transparencyOff: "Wyłącz przezroczystość okien",
    animationsOn: "Włącz animacje",
    animationsOff: "Wyłącz animacje",
    secondsOn: "Pokaż sekundy zegara",
    secondsOff: "Ukryj sekundy zegara",
    clearShortcuts: "Wyczyść skróty pulpitu",
    clearConfirm: "Usunąć wszystkie skróty aplikacji i modułów z pulpitu?",
    resetDesktop: "Przywróć domyślne ustawienia pulpitu",
    resetConfirm: "Przywrócić domyślne ustawienia wyglądu i zachowania pulpitu? Skróty aplikacji nie zostaną usunięte.",
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
    cover: "Fill screen",
    contain: "Fit to screen",
    stretch: "Stretch",
    center: "Center",
    taskbarAlignment: "Taskbar alignment",
    left: "Left",
    centered: "Center",
    theme: "Theme",
    themeSystem: "Use system setting",
    themeLight: "Light",
    themeDark: "Dark",
    notificationsOn: "Enable notifications",
    notificationsOff: "Disable notifications",
    transfersOn: "Show transfer indicator",
    transfersOff: "Hide transfer indicator",
    actionsOn: "Show background actions",
    actionsOff: "Hide background actions",
    transparencyOn: "Enable window transparency",
    transparencyOff: "Disable window transparency",
    animationsOn: "Enable animations",
    animationsOff: "Disable animations",
    secondsOn: "Show clock seconds",
    secondsOff: "Hide clock seconds",
    clearShortcuts: "Clear desktop shortcuts",
    clearConfirm: "Remove all application and module shortcuts from the desktop?",
    resetDesktop: "Restore default desktop settings",
    resetConfirm: "Restore default desktop appearance and behavior? Application shortcuts will not be removed.",
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
      if (!(target instanceof HTMLElement)) return;
      const surface = target.closest(".desktop-surface");
      if (!surface) return;
      if (target.closest(".desktop-window, .desktop-shortcuts, .desktop-welcome, .desktop-widget, .context-menu, .modal-panel")) return;
      event.preventDefault();
      setMenu({ x: event.clientX, y: event.clientY, portalTarget: surface.closest(".desktop") });
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

  async function clearShortcuts() {
    if (await confirmDialog(text.clearConfirm, t)) await save({ desktop_shortcut_apps: [], desktop_shortcut_modules: [] });
  }

  async function resetDesktop() {
    if (!(await confirmDialog(text.resetConfirm, t))) return;
    await save({
      show_desktop_shortcuts: true,
      desktop_shortcut_size: "medium",
      show_welcome_widget: false,
      wallpaper_fit: "cover",
      taskbar_alignment: "center",
      startup_windows: "last",
      theme: "system",
      show_notifications: true,
      show_transfer_indicator: true,
      show_background_actions_indicator: true,
      window_transparency: true,
      animations_enabled: true,
      clock_show_seconds: false,
    });
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
    { label: profile.show_welcome_widget ? text.welcomeOff : text.welcomeOn, icon: <Sparkles />, action: () => void save({ show_welcome_widget: !profile.show_welcome_widget }) },

    { label: `${text.wallpaperFit}: ${text.cover}`, icon: profile.wallpaper_fit === "cover" ? <Check /> : <Image />, separator: true, action: () => void save({ wallpaper_fit: "cover" }) },
    { label: `${text.wallpaperFit}: ${text.contain}`, icon: profile.wallpaper_fit === "contain" ? <Check /> : <Image />, action: () => void save({ wallpaper_fit: "contain" }) },
    { label: `${text.wallpaperFit}: ${text.stretch}`, icon: profile.wallpaper_fit === "stretch" ? <Check /> : <Image />, action: () => void save({ wallpaper_fit: "stretch" }) },
    { label: `${text.wallpaperFit}: ${text.center}`, icon: profile.wallpaper_fit === "center" ? <Check /> : <Image />, action: () => void save({ wallpaper_fit: "center" }) },

    { label: `${text.taskbarAlignment}: ${text.left}`, icon: profile.taskbar_alignment === "left" ? <Check /> : <AlignLeft />, separator: true, action: () => void save({ taskbar_alignment: "left" }) },
    { label: `${text.taskbarAlignment}: ${text.centered}`, icon: profile.taskbar_alignment === "center" ? <Check /> : <AlignCenter />, action: () => void save({ taskbar_alignment: "center" }) },
    { label: `${text.theme}: ${text.themeSystem}`, icon: profile.theme === "system" ? <Check /> : <Monitor />, action: () => void save({ theme: "system" }) },
    { label: `${text.theme}: ${text.themeLight}`, icon: profile.theme === "light" ? <Check /> : <Sun />, action: () => void save({ theme: "light" }) },
    { label: `${text.theme}: ${text.themeDark}`, icon: profile.theme === "dark" ? <Check /> : <Moon />, action: () => void save({ theme: "dark" }) },

    { label: `${text.startup}: ${text.startupLast}`, icon: profile.startup_windows === "last" ? <Check /> : <LayoutGrid />, separator: true, action: () => void save({ startup_windows: "last" }) },
    { label: `${text.startup}: ${text.startupNone}`, icon: profile.startup_windows === "none" ? <Check /> : <LayoutGrid />, action: () => void save({ startup_windows: "none" }) },
    { label: profile.show_notifications ? text.notificationsOff : text.notificationsOn, icon: profile.show_notifications ? <BellOff /> : <Bell />, action: () => void save({ show_notifications: !profile.show_notifications }) },
    { label: profile.show_transfer_indicator ? text.transfersOff : text.transfersOn, icon: <PanelBottom />, action: () => void save({ show_transfer_indicator: !profile.show_transfer_indicator }) },
    { label: profile.show_background_actions_indicator ? text.actionsOff : text.actionsOn, icon: <WandSparkles />, action: () => void save({ show_background_actions_indicator: !profile.show_background_actions_indicator }) },
    { label: profile.window_transparency ? text.transparencyOff : text.transparencyOn, icon: <Sparkles />, action: () => void save({ window_transparency: !profile.window_transparency }) },
    { label: profile.animations_enabled ? text.animationsOff : text.animationsOn, icon: <WandSparkles />, action: () => void save({ animations_enabled: !profile.animations_enabled }) },
    { label: profile.clock_show_seconds ? text.secondsOff : text.secondsOn, icon: <Clock3 />, action: () => void save({ clock_show_seconds: !profile.clock_show_seconds }) },

    { label: text.clearShortcuts, icon: <Trash2 />, separator: true, disabled: !profile.desktop_shortcut_apps.length && !profile.desktop_shortcut_modules.length, action: () => void clearShortcuts() },
    { label: text.resetDesktop, icon: <RefreshCw />, action: () => void resetDesktop() },
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
            <label><span>{text.taskbarAlignment}</span><select value={profile.taskbar_alignment} disabled={saving} onChange={(event) => void save({ taskbar_alignment: event.target.value as "left" | "center" })}><option value="left">{text.left}</option><option value="center">{text.centered}</option></select></label>
            <label><span>{text.theme}</span><select value={profile.theme} disabled={saving} onChange={(event) => void save({ theme: event.target.value as "system" | "light" | "dark" })}><option value="system">{text.themeSystem}</option><option value="light">{text.themeLight}</option><option value="dark">{text.themeDark}</option></select></label>
            <label><span>{profile.show_notifications ? text.notificationsOff : text.notificationsOn}</span><input type="checkbox" checked={profile.show_notifications} disabled={saving} onChange={() => void save({ show_notifications: !profile.show_notifications })} /></label>
            <label><span>{profile.window_transparency ? text.transparencyOff : text.transparencyOn}</span><input type="checkbox" checked={profile.window_transparency} disabled={saving} onChange={() => void save({ window_transparency: !profile.window_transparency })} /></label>
            <label><span>{profile.animations_enabled ? text.animationsOff : text.animationsOn}</span><input type="checkbox" checked={profile.animations_enabled} disabled={saving} onChange={() => void save({ animations_enabled: !profile.animations_enabled })} /></label>
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

        <footer className="desktop-manager-danger-zone"><button type="button" className="button-danger" disabled={saving || (!profile.desktop_shortcut_apps.length && !profile.desktop_shortcut_modules.length)} onClick={() => void clearShortcuts()}><Trash2 />{text.clearShortcuts}</button><button type="button" disabled={saving} onClick={() => void resetDesktop()}><RefreshCw />{text.resetDesktop}</button></footer>
      </section>
    </Modal>}
  </>;
}
