import {
  ArrowLeft,
  ArrowRight,
  Boxes,
  Check,
  ChevronDown,
  FileJson,
  LoaderCircle,
  ScrollText,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Translate } from "../../../app/types";

export type WizardStep = {
  key: string;
  label: string;
  description: string;
};

export function WizardHeader({
  canImportCompose,
  t,
  onClose,
  onImportConfig,
  onImportCompose,
}: {
  canImportCompose: boolean;
  t: Translate;
  onClose: () => void;
  onImportConfig: () => void;
  onImportCompose: () => void;
}) {
  return (
    <header className="docker-wizard-header">
      <div className="docker-wizard-heading">
        <span className="docker-wizard-heading-icon"><Boxes /></span>
        <span>
          <h2 id="docker-create-title">{t("docker.createContainer")}</h2>
          <small>{t("docker.wizard.subtitle")}</small>
        </span>
      </div>
      <div className="docker-wizard-header-actions">
        <details className="docker-wizard-import-menu">
          <summary><Upload />{t("docker.wizard.import")}<ChevronDown /></summary>
          <div>
            <button type="button" onClick={onImportConfig}><FileJson /><span><strong>{t("docker.importContainerConfig")}</strong><small>JSON</small></span></button>
            {canImportCompose && <button type="button" onClick={onImportCompose}><ScrollText /><span><strong>{t("docker.importCompose")}</strong><small>YAML</small></span></button>}
          </div>
        </details>
        <button className="icon-button" type="button" aria-label={t("action.close")} onClick={onClose}><X /></button>
      </div>
    </header>
  );
}

export function WizardStepper({
  current,
  furthest,
  steps,
  t,
  onStep,
}: {
  current: number;
  furthest: number;
  steps: WizardStep[];
  t: Translate;
  onStep: (step: number) => void;
}) {
  return (
    <nav className="docker-wizard-stepper" aria-label={t("docker.wizard.progress")}>
      <div className="docker-wizard-mobile-progress">
        <span>{t("docker.wizard.stepOf").replace("{current}", String(current + 1)).replace("{total}", String(steps.length))}</span>
        <strong>{steps[current].label}</strong>
        <i><span style={{ width: `${((current + 1) / steps.length) * 100}%` }} /></i>
      </div>
      <ol>
        {steps.map((item, index) => {
          const completed = index < current;
          const available = index <= furthest && index !== current;
          return (
            <li className={index === current ? "active" : completed ? "done" : ""} key={item.key}>
              <button
                type="button"
                disabled={!available}
                aria-current={index === current ? "step" : undefined}
                onClick={() => onStep(index)}
              >
                <span className="docker-wizard-step-number">{completed ? <Check /> : index + 1}</span>
                <span><strong>{item.label}</strong><small>{item.description}</small></span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function WizardFooter({
  busy,
  createBlockedReason,
  current,
  total,
  t,
  onBack,
  onNext,
  onSubmit,
}: {
  busy: boolean;
  createBlockedReason?: string;
  current: number;
  total: number;
  t: Translate;
  onBack: () => void;
  onNext: () => void;
  onSubmit: () => void;
}) {
  const final = current === total - 1;
  return (
    <footer className="docker-wizard-footer">
      <div className="docker-wizard-draft-status">
        <strong>{t("docker.wizard.stepOf").replace("{current}", String(current + 1)).replace("{total}", String(total))}</strong>
        <small>{t("docker.wizard.autoSave")}</small>
      </div>
      <div className="docker-wizard-footer-actions">
        {createBlockedReason && final && <small className="docker-wizard-block-reason" role="alert">{createBlockedReason}</small>}
        {current > 0 && <button type="button" onClick={onBack}><ArrowLeft />{t("action.back")}</button>}
        {final ? (
          <button className="button-primary docker-wizard-primary-action" type="button" disabled={busy || Boolean(createBlockedReason)} onClick={onSubmit}>
            {busy ? <LoaderCircle className="docker-spin" /> : <Boxes />}
            {t("docker.createContainer")}
          </button>
        ) : (
          <button className="button-primary docker-wizard-primary-action" type="button" disabled={busy} onClick={onNext}>
            {t("action.next")}<ArrowRight />
          </button>
        )}
      </div>
    </footer>
  );
}

export function FormSection({
  children,
  description,
  icon: Icon,
  title,
}: {
  children: ReactNode;
  description?: string;
  icon?: LucideIcon;
  title: string;
}) {
  return (
    <section className="docker-wizard-form-section">
      <header>
        {Icon && <span><Icon /></span>}
        <div><h3>{title}</h3>{description && <p>{description}</p>}</div>
      </header>
      <div className="docker-wizard-section-content">{children}</div>
    </section>
  );
}

export function WizardHelpPanel({
  examples,
  issues,
  summary,
  text,
  title,
  t,
}: {
  examples?: string[];
  issues: string[];
  summary: Array<[string, string]>;
  text: string;
  title: string;
  t: Translate;
}) {
  return (
    <aside className="docker-wizard-help">
      <section>
        <h3>{title}</h3>
        <p>{text}</p>
      </section>
      <section>
        <h3>{t("docker.wizard.currentConfig")}</h3>
        <dl>{summary.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      </section>
      {issues.length > 0 && <section className="docker-wizard-help-issues"><h3>{t("docker.wizard.attention")}</h3><ul>{issues.map((issue) => <li key={issue}>{issue}</li>)}</ul></section>}
      {examples && examples.length > 0 && <section><h3>{t("docker.wizard.examples")}</h3>{examples.map((example) => <code key={example}>{example}</code>)}</section>}
    </aside>
  );
}

export function SummaryCard({
  icon: Icon,
  onEdit,
  rows,
  title,
  t,
}: {
  icon: LucideIcon;
  onEdit: () => void;
  rows: Array<[string, ReactNode]>;
  title: string;
  t: Translate;
}) {
  return (
    <article className="docker-summary-card">
      <header><span><Icon /></span><h3>{title}</h3><button type="button" onClick={onEdit}>{t("action.edit")}</button></header>
      <dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || "—"}</dd></div>)}</dl>
    </article>
  );
}

export function SwitchField({
  checked,
  description,
  label,
  onChange,
}: {
  checked: boolean;
  description: string;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="docker-switch-field">
      <span><strong>{label}</strong><small>{description}</small></span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <i aria-hidden="true" />
    </label>
  );
}
