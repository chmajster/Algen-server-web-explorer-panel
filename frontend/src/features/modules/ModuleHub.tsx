import { Boxes, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type ModuleSummary } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { ModuleStatusBadge } from "./common/ModuleAppShell";

export function ModuleHub({ t, toast, onOpen }: { t: Translate; toast: ToastFn; onOpen: (moduleId: string) => void }) {
  const [modules, setModules] = useState<ModuleSummary[]>([]); const [loading, setLoading] = useState(false); const [search, setSearch] = useState("");
  const refresh = useCallback(async () => { setLoading(true); try { setModules(await api.modules()); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"); } finally { setLoading(false); } }, [t, toast]);
  useEffect(() => { void refresh(); }, [refresh]);
  const visible = modules.filter((module) => `${module.manifest.name} ${module.manifest.description}`.toLowerCase().includes(search.toLowerCase()));
  return <section className="system-app module-hub"><header className="feature-header"><div><h2>{t("app.modules")}</h2><p>{t("managed.hubSubtitle")}</p></div><div className="header-actions"><input aria-label={t("action.search")} placeholder={t("action.search")} value={search} onChange={(event) => setSearch(event.target.value)} /><button onClick={() => void refresh()}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button></div></header><div className="card-grid">{visible.map((module) => <article className="data-card" key={module.id}><header><Boxes /><strong>{module.manifest.name}</strong><ModuleStatusBadge status={module.module_status} t={t} /></header><p>{module.manifest.description}</p><dl><dt>{t("module.serviceState")}</dt><dd>{module.module_status.service_state}</dd><dt>{t("module.version")}</dt><dd>{module.module_status.package_version || "—"}</dd></dl><button className="button-primary" onClick={() => onOpen(module.id)}>{t("managed.openModule")}</button></article>)}</div>{!visible.length && <div className="empty-state">{t("managed.noModules")}</div>}</section>;
}
