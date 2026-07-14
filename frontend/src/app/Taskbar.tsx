import type { Translate, WindowInstance } from "./types";
import { appById } from "./catalog";

export function Taskbar({ windows, activeId, t, onSelect }: { windows: WindowInstance[]; activeId: string; t: Translate; onSelect: (item: WindowInstance) => void }) {
  return <footer className="taskbar" aria-label={t("desktop.runningApps")}>
    <div className="taskbar-items">{windows.map((item) => <button key={item.id} type="button" className={`${activeId === item.id ? "active" : ""} ${item.minimized ? "minimized" : ""}`} title={t(appById[item.app].labelKey)} onClick={() => onSelect(item)}>
      {appById[item.app].icon}<span>{t(appById[item.app].labelKey)}</span><i />
    </button>)}</div>
  </footer>;
}
