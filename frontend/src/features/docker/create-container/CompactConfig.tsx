import { ChevronDown, ChevronUp, Eye, EyeOff, Minus, Plus } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import type { Translate } from "../../../app/types";

export function ConfigSection({
  children,
  defaultOpen = false,
  title,
}: {
  children: ReactNode;
  defaultOpen?: boolean;
  title: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();
  return (
    <section className="docker-config-section">
      <button className="docker-config-section-header" type="button" aria-expanded={open} aria-controls={contentId} onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronUp /> : <ChevronDown />}
        <span>{title}</span>
        <i aria-hidden="true" />
      </button>
      {open && <div className="docker-config-section-content" id={contentId}>{children}</div>}
    </section>
  );
}

export function ConfigRow({
  children,
  description,
  label,
  required,
}: {
  children: ReactNode;
  description?: string;
  label: string;
  required?: boolean;
}) {
  return (
    <div className="docker-config-row">
      <span className="docker-config-label">{label}{required && <b aria-hidden="true">*</b>}</span>
      <div className="docker-config-control">{children}</div>
      {description && <small>{description}</small>}
    </div>
  );
}

export type KeyValueRow = { id: number; key: string; value: string };

export function KeyValueRows({
  addLabel,
  keyLabel,
  rows,
  secret = false,
  t,
  valueLabel,
  onAdd,
  onRemove,
  onUpdate,
}: {
  addLabel: string;
  keyLabel: string;
  rows: KeyValueRow[];
  secret?: boolean;
  t: Translate;
  valueLabel: string;
  onAdd: () => void;
  onRemove: (id: number) => void;
  onUpdate: (id: number, values: Partial<Omit<KeyValueRow, "id">>) => void;
}) {
  const [visible, setVisible] = useState<Record<number, boolean>>({});
  return (
    <div className="docker-kv-editor">
      {rows.map((row) => (
        <div className="docker-kv-row" key={row.id}>
          <input aria-label={keyLabel} value={row.key} onChange={(event) => onUpdate(row.id, { key: event.target.value })} placeholder={keyLabel} />
          <div>
            <input aria-label={valueLabel} type={secret && !visible[row.id] ? "password" : "text"} autoComplete={secret ? "new-password" : undefined} value={row.value} onChange={(event) => onUpdate(row.id, { value: event.target.value })} placeholder={valueLabel} />
            {secret && <button type="button" title={t(visible[row.id] ? "docker.wizard.hideSecret" : "docker.wizard.showSecret")} aria-label={t(visible[row.id] ? "docker.wizard.hideSecret" : "docker.wizard.showSecret")} onClick={() => setVisible((current) => ({ ...current, [row.id]: !current[row.id] }))}>{visible[row.id] ? <EyeOff /> : <Eye />}</button>}
          </div>
          <button type="button" title={t("action.delete")} aria-label={t("action.delete")} onClick={() => onRemove(row.id)}><Minus /></button>
        </div>
      ))}
      <button className="docker-compact-add" type="button" onClick={onAdd}><Plus />{addLabel}</button>
    </div>
  );
}
