import { RefreshCw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type RbacAssignment, type RbacRole } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "./AdminActionDialog";

export function AccessControlApp({ t, toast }: { t: Translate; toast: ToastFn }) {
  const [assignments, setAssignments] = useState<RbacAssignment[]>([]); const [loading, setLoading] = useState(false); const [selected, setSelected] = useState<RbacAssignment | null>(null);
  const refresh = useCallback(async () => { setLoading(true); try { setAssignments(await api.rbacAssignments()); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"); } finally { setLoading(false); } }, [t, toast]);
  useEffect(() => { void refresh(); }, [refresh]);
  async function save(values: Record<string, string>) { if (!selected) return; await api.saveRbacAssignment({ username: selected.username, role: values.role as RbacRole, allow: split(values.allow), deny: split(values.deny) }); toast(t("admin.actionCompleted"), "ok", "admin"); await refresh(); }
  return <section className="system-app"><header className="feature-header"><div><h2>{t("app.access")}</h2><p>{t("rbac.subtitle")}</p></div><button onClick={() => void refresh()}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button></header><div className="data-list">{assignments.map((assignment) => <article className="data-row rbac-row" key={assignment.username}><ShieldCheck /><strong>{assignment.username}</strong><span>UID {assignment.uid}</span><span className={`status-badge ${assignment.role === "admin" ? "completed" : "running"}`}>{t(`rbac.role.${assignment.role}`)}</span><span>{assignment.permissions.length} {t("rbac.permissions")}</span><button onClick={() => setSelected(assignment)}>{t("action.edit")}</button></article>)}</div>{selected && <AdminActionDialog title={`${t("rbac.edit")}: ${selected.username}`} fields={[{ name: "role", label: t("rbac.role"), type: "select", value: selected.role, options: (["admin", "operator", "auditor", "user"] as RbacRole[]).map((role) => ({ value: role, label: t(`rbac.role.${role}`) })) }, { name: "allow", label: t("rbac.allow"), value: selected.allow.join(", ") }, { name: "deny", label: t("rbac.deny"), value: selected.deny.join(", ") }]} t={t} onClose={() => setSelected(null)} onSubmit={save} />}</section>;
}
function split(value: string) { return value.split(",").map((item) => item.trim()).filter(Boolean); }
