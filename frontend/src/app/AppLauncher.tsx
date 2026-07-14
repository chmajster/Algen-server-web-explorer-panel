import { useEffect, useRef } from "react";
import { Pin } from "lucide-react";
import type { AppDefinition, AppId, Translate } from "./types";

export function AppLauncher({ apps, pinned, t, onOpen, onTogglePin, onClose }: {
  apps: AppDefinition[];
  pinned: Set<AppId>;
  t: Translate;
  onOpen: (app: AppId) => void;
  onTogglePin: (app: AppId) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function click(event: MouseEvent) { if (!ref.current?.contains(event.target as Node)) onClose(); }
    function key(event: KeyboardEvent) { if (event.key === "Escape") onClose(); }
    document.addEventListener("mousedown", click);
    document.addEventListener("keydown", key);
    ref.current?.querySelector<HTMLButtonElement>(".launcher-open")?.focus();
    return () => { document.removeEventListener("mousedown", click); document.removeEventListener("keydown", key); };
  }, [onClose]);
  return <div ref={ref} className="app-launcher" role="dialog" aria-label={t("desktop.mainMenu")}>
    <header><strong>{t("desktop.applications")}</strong><span>{t("desktop.launcherHint")}</span></header>
    <div className="launcher-grid">{apps.map((app) => <article key={app.id}>
      <button className="launcher-open" type="button" onClick={() => { onOpen(app.id); onClose(); }}>{app.icon}<span>{t(app.labelKey)}</span></button>
      <button className={`launcher-pin ${pinned.has(app.id) ? "active" : ""}`} type="button" title={pinned.has(app.id) ? t("desktop.unpin") : t("desktop.pin")} onClick={() => onTogglePin(app.id)}><Pin /></button>
    </article>)}</div>
  </div>;
}
