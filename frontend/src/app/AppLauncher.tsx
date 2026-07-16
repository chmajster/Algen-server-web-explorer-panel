import { ArrowRight, LogOut, Pin, Search, ShieldCheck, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SettingsMe } from "../api";
import type { AppDefinition, AppId, Translate } from "./types";

export function AppLauncher({ apps, pinned, profile, t, onOpen, onTogglePin, onLogout, onClose }: {
  apps: AppDefinition[];
  pinned: Set<AppId>;
  profile: SettingsMe;
  t: Translate;
  onOpen: (app: AppId) => void;
  onTogglePin: (app: AppId) => void;
  onLogout: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const normalized = query.trim().toLocaleLowerCase(profile.language);
  const filtered = useMemo(() => apps.filter((app) => t(app.labelKey).toLocaleLowerCase(profile.language).includes(normalized)), [apps, normalized, profile.language, t]);
  const pinnedApps = filtered.filter((app) => pinned.has(app.id));
  const allVisible = showAll || Boolean(normalized);

  useEffect(() => {
    function click(event: MouseEvent) { if (!ref.current?.contains(event.target as Node)) onClose(); }
    function key(event: KeyboardEvent) { if (event.key === "Escape") onClose(); }
    document.addEventListener("mousedown", click);
    document.addEventListener("keydown", key);
    searchRef.current?.focus();
    return () => { document.removeEventListener("mousedown", click); document.removeEventListener("keydown", key); };
  }, [onClose]);

  function open(app: AppId) { onOpen(app); onClose(); }
  function appButton(app: AppDefinition, compact = false) {
    return <article className={`launcher-app ${app.admin ? "administrative" : ""} ${compact ? "compact" : ""}`} key={app.id}>
      <button className="launcher-open" type="button" onClick={() => open(app.id)}>{app.icon}<span>{t(app.labelKey)}</span>{app.admin && <small><ShieldCheck />{t("desktop.adminApp")}</small>}</button>
      <button className={`launcher-pin ${pinned.has(app.id) ? "active" : ""}`} type="button" aria-label={`${pinned.has(app.id) ? t("desktop.unpin") : t("desktop.pin")} ${t(app.labelKey)}`} title={pinned.has(app.id) ? t("desktop.unpin") : t("desktop.pin")} onClick={() => onTogglePin(app.id)}><Pin /></button>
    </article>;
  }

  return <div ref={ref} className="app-launcher" role="dialog" aria-modal="false" aria-label={t("desktop.mainMenu")}>
    <div className="launcher-search"><Search /><input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("desktop.searchApps")} aria-label={t("desktop.searchApps")} />{query && <button type="button" aria-label={t("action.clear")} onClick={() => setQuery("")}><X /></button>}</div>
    {!allVisible && <><header className="launcher-section-title"><strong>{t("desktop.pinned")}</strong><button type="button" onClick={() => setShowAll(true)}>{t("desktop.allApps")}<ArrowRight /></button></header><div className="launcher-grid">{pinnedApps.map((app) => appButton(app))}</div></>}
    {allVisible && <><header className="launcher-section-title"><strong>{t("desktop.allApps")}</strong>{showAll && !normalized && <button type="button" onClick={() => setShowAll(false)}>{t("action.back")}</button>}</header><div className="launcher-list">{filtered.length > 0 ? filtered.map((app) => appButton(app, true)) : <p className="launcher-empty">{t("desktop.noAppsFound")}</p>}</div></>}
    <footer className="launcher-footer"><div><UserRound /><span><strong>{profile.username}</strong><small>{profile.is_admin ? <><ShieldCheck />{t("desktop.administrator")}</> : t(`rbac.role.${profile.role}`)}</small></span></div><button type="button" title={t("notify.logout")} aria-label={t("notify.logout")} onClick={onLogout}><LogOut /></button></footer>
  </div>;
}
