import { useId, useState } from "react";
import type { Translate } from "../../app/types";
import { Modal } from "../../components/Modal";

export type AdminField = {
  name: string;
  label: string;
  type?: "text" | "password" | "number" | "select" | "textarea";
  value?: string;
  options?: Array<{ value: string; label: string }>;
  required?: boolean;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  validate?: (value: string, values: Record<string, string>) => string;
};

export function AdminActionDialog({
  title,
  fields,
  description,
  submitLabel,
  danger = false,
  t,
  onClose,
  onSubmit,
}: {
  title: string;
  fields: AdminField[];
  description?: React.ReactNode;
  submitLabel?: string;
  danger?: boolean;
  t: Translate;
  onClose: () => void;
  onSubmit: (values: Record<string, string>) => Promise<void>;
}) {
  const formId = `admin-action-${useId().replace(/:/g, "")}`;
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries(fields.map((field) => [field.name, field.value || ""])),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  function change(name: string, value: string) {
    setValues((current) => ({ ...current, [name]: value }));
    setFieldErrors((current) => {
      if (!current[name]) return current;
      const next = { ...current };
      delete next[name];
      return next;
    });
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const validation = Object.fromEntries(
      fields
        .map((field) => [field.name, field.validate?.(values[field.name] || "", values) || ""] as const)
        .filter(([, message]) => message),
    );
    setFieldErrors(validation);
    if (Object.keys(validation).length) return;
    setSaving(true);
    setError("");
    try {
      await onSubmit(values);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("error.generic"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={title}
      closeLabel={t("action.close")}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>{t("action.cancel")}</button>
          <button className={danger ? "button-danger" : "button-primary"} disabled={saving} type="submit" form={formId}>
            {saving ? t("status.loading") : submitLabel || t("action.apply")}
          </button>
        </>
      }
    >
      <form
        id={formId}
        className="admin-action-form"
        onKeyDown={(event) => event.stopPropagation()}
        onPointerDown={(event) => event.stopPropagation()}
        onSubmit={(event) => void submit(event)}
      >
        {description}
        {fields.map((field, index) => {
          const fieldId = `${formId}-${field.name}`;
          const common = {
            id: fieldId,
            name: field.name,
            required: field.required,
            value: values[field.name],
            "aria-invalid": Boolean(fieldErrors[field.name]),
            onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
              change(field.name, event.target.value),
          };
          return (
            <label className="field-label" htmlFor={fieldId} key={field.name}>
              {field.label}
              {field.type === "select" ? (
                <select {...common}>
                  {field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              ) : field.type === "textarea" ? (
                <textarea
                  {...common}
                  autoFocus={index === 0}
                  spellCheck={false}
                  minLength={field.minLength}
                  maxLength={field.maxLength}
                />
              ) : (
                <input
                  {...common}
                  autoFocus={index === 0}
                  autoComplete={field.type === "password" ? "new-password" : "off"}
                  spellCheck={false}
                  type={field.type || "text"}
                  minLength={field.minLength}
                  maxLength={field.maxLength}
                  pattern={field.pattern}
                />
              )}
              {fieldErrors[field.name] && <span className="docker-field-error" role="alert">{fieldErrors[field.name]}</span>}
            </label>
          );
        })}
        {danger && <p className="danger-note">{t("admin.destructiveWarning")}</p>}
        {error && <p className="error-state compact-error" role="alert">{error}</p>}
      </form>
    </Modal>
  );
}
