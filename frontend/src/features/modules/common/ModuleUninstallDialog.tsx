import { useEffect, useId, useState } from "react";
import { api, type ModuleSummary, type PackagePlan } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { Modal } from "../../../components/Modal";

type RemovalMode = "packages" | "config" | "data";

export function ModuleUninstallDialog({ item, activeShares = 0, activeSessions = 0, t, toast, onClose, onStarted }: { item: ModuleSummary; activeShares?: number; activeSessions?: number; t: Translate; toast: ToastFn; onClose: () => void; onStarted: (jobId: string) => void }) {
  const formId = `module-uninstall-${useId().replace(/:/g, "")}`;
  const [mode, setMode] = useState<RemovalMode>("packages"); const [createBackup, setCreateBackup] = useState(true); const [confirmName, setConfirmName] = useState(""); const [plan, setPlan] = useState<PackagePlan | null>(null); const [loading, setLoading] = useState(true); const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  const removeData = mode === "data";
  useEffect(() => { setLoading(true); api.appPlan(item.id, "uninstall", removeData).then(setPlan).catch((reason) => setError(reason instanceof Error ? reason.message : t("error.generic"))).finally(() => setLoading(false)); }, [item.id, removeData, t]);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (!plan) return; setSaving(true); setError("");
    try {
      const response = await api.uninstallModule(item.id, { remove_config: mode !== "packages", remove_data: removeData, create_backup: createBackup, confirm_name: confirmName });
      toast(t("module.jobQueued"), "ok", "admin", item.id); onStarted(response.job.id); onClose();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); } finally { setSaving(false); }
  }
  const nameConfirmed = !removeData || confirmName === item.manifest.name || item.id === "samba" && confirmName === "Samba";
  return <Modal wide title={`${t("store.uninstall")}: ${item.manifest.name}`} closeLabel={t("action.close")} onClose={onClose} footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className="button-danger" type="submit" form={formId} disabled={loading || saving || !plan || !nameConfirmed}>{saving ? t("status.loading") : t("store.uninstall")}</button></>}><form id={formId} className="module-uninstall" onSubmit={(event) => void submit(event)}><section className="module-uninstall-impact"><h3>{t("module.uninstallImpact")}</h3><dl><dt>{t("module.samba.sharesCount")}</dt><dd>{activeShares}</dd><dt>{t("module.samba.sessionsCount")}</dt><dd>{activeSessions}</dd></dl>{activeSessions > 0 && <p>{t("module.uninstallSessionsWarning")}</p>}</section><fieldset><legend>{t("module.uninstallScope")}</legend>{(["packages", "config", "data"] as RemovalMode[]).map((value) => <label key={value}><input type="radio" name="removal-mode" value={value} checked={mode === value} onChange={() => setMode(value)} /><span><strong>{t(`module.uninstallMode.${value}`)}</strong><small>{t(`module.uninstallMode.${value}Hint`)}</small></span></label>)}</fieldset><label className="module-backup-option"><input type="checkbox" checked={createBackup} onChange={(event) => setCreateBackup(event.target.checked)} />{t("module.backupBeforeUninstall")}</label>{plan && <section className="module-uninstall-plan"><h3>{t("module.changePlan")}</h3><dl><dt>{t("package.packages")}</dt><dd>{plan.packages.join(", ")}</dd><dt>{t("package.services")}</dt><dd>{plan.services.join(", ")}</dd><dt>{t("package.paths")}</dt><dd>{plan.config_paths.join(", ")}</dd></dl><ol>{plan.steps.map((step) => <li key={step}>{step}</li>)}</ol><ul>{plan.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></section>}{removeData && <label className="field-label">{t("module.typeModuleName").replace("{name}", item.id === "samba" ? "Samba" : item.manifest.name)}<input value={confirmName} onChange={(event) => setConfirmName(event.target.value)} autoComplete="off" /></label>}{error && <p className="error-state compact-error" role="alert">{error}</p>}</form></Modal>;
}
