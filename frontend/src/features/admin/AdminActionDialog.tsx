import { useState } from "react";
import type { Translate } from "../../app/types";
import { Modal } from "../../components/Modal";

export type AdminField = { name: string; label: string; type?: "text" | "password" | "number" | "select"; value?: string; options?: Array<{ value: string; label: string }>; required?: boolean };

export function AdminActionDialog({ title, fields, danger = false, t, onClose, onSubmit }: {
  title: string; fields: AdminField[]; danger?: boolean; t: Translate; onClose: () => void; onSubmit: (values: Record<string, string>) => Promise<void>;
}) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(fields.map((field) => [field.name, field.value || ""])));
  const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  async function submit(event: React.FormEvent) { event.preventDefault(); setSaving(true); setError(""); try { await onSubmit(values); onClose(); } catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); } finally { setSaving(false); } }
  return <Modal title={title} closeLabel={t("action.close")} onClose={onClose} footer={<><button onClick={onClose}>{t("action.cancel")}</button><button className={danger ? "button-danger" : "button-primary"} disabled={saving} type="submit" form="admin-action-form">{saving ? t("status.loading") : t("action.apply")}</button></>}>
    <form id="admin-action-form" className="admin-action-form" onSubmit={(event) => void submit(event)}>{fields.map((field) => <label className="field-label" key={field.name}>{field.label}{field.type === "select" ? <select required={field.required} value={values[field.name]} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))}>{field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : <input autoFocus={field.name === fields[0]?.name} required={field.required} type={field.type || "text"} value={values[field.name]} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))} />}</label>)}{danger && <p className="danger-note">{t("admin.destructiveWarning")}</p>}{error && <p className="error-state compact-error">{error}</p>}</form>
  </Modal>;
}
