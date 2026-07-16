import { useId, useState } from "react";
import type { Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import { forgetAdminPassword, getRememberedAdminPassword, rememberAdminPassword } from "./adminCredentials";

export type AdminField = { name: string; label: string; type?: "text" | "password" | "number" | "select" | "textarea"; value?: string; options?: Array<{ value: string; label: string }>; required?: boolean };

export function AdminActionDialog({ title, fields, description, danger = false, allowRememberPassword = true, t, onClose, onSubmit }: {
  title: string; fields: AdminField[]; description?: React.ReactNode; danger?: boolean; allowRememberPassword?: boolean; t: Translate; onClose: () => void; onSubmit: (values: Record<string, string>) => Promise<void>;
}) {
  const formId = `admin-action-${useId().replace(/:/g, "")}`;
  const hasAdminPassword = fields.some((field) => field.name === "admin_password");
  const storedPassword = allowRememberPassword ? getRememberedAdminPassword() : "";
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(fields.map((field) => [field.name, field.value || (field.name === "admin_password" ? storedPassword : "")])));
  const [rememberPassword, setRememberPassword] = useState(Boolean(storedPassword));
  const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  async function submit(event: React.FormEvent) { event.preventDefault(); setSaving(true); setError(""); try { await onSubmit(values); if (hasAdminPassword && allowRememberPassword) { if (rememberPassword) rememberAdminPassword(values.admin_password); else forgetAdminPassword(); } onClose(); } catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); } finally { setSaving(false); } }
  return <Modal title={title} closeLabel={t("action.close")} onClose={onClose} footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className={danger ? "button-danger" : "button-primary"} disabled={saving} type="submit" form={formId}>{saving ? t("status.loading") : t("action.apply")}</button></>}>
    <form id={formId} className="admin-action-form" onKeyDown={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()} onSubmit={(event) => void submit(event)}>{description}{fields.map((field, index) => { const fieldId = `${formId}-${field.name}`; return <label className="field-label" htmlFor={fieldId} key={field.name}>{field.label}{field.type === "select" ? <select id={fieldId} name={field.name} required={field.required} value={values[field.name]} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))}>{field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : field.type === "textarea" ? <textarea id={fieldId} name={field.name} autoFocus={index === 0} spellCheck={false} required={field.required} value={values[field.name]} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))} /> : <input id={fieldId} name={field.name} autoFocus={index === 0} autoComplete={field.name === "admin_password" ? "current-password" : field.type === "password" ? "new-password" : "off"} spellCheck={false} required={field.required} type={field.type || "text"} value={values[field.name]} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))} />}</label>; })}{hasAdminPassword && allowRememberPassword && <label className="remember-password"><input type="checkbox" checked={rememberPassword} onChange={(event) => setRememberPassword(event.target.checked)} /> <span>{t("admin.rememberPassword")}</span></label>}{hasAdminPassword && allowRememberPassword && <small className="credential-note">{t("admin.rememberPasswordHint")}</small>}{hasAdminPassword && !allowRememberPassword && <small className="credential-note">{t("identity.freshPamRequired")}</small>}{danger && <p className="danger-note">{t("admin.destructiveWarning")}</p>}{error && <p className="error-state compact-error" role="alert">{error}</p>}</form>
  </Modal>;
}
