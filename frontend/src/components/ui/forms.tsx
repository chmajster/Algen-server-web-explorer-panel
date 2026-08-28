import { Search } from "lucide-react";
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

function classes(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function FormField({ label, htmlFor, error, hint, disabled = false, children, className = "" }: {
  label: ReactNode;
  htmlFor: string;
  error?: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const descriptionId = `${htmlFor}-description`;
  return <div className={classes("wn-form-field", disabled && "is-disabled", error && "has-error", className)}>
    <label htmlFor={htmlFor}>{label}</label>
    {children}
    {error ? <small id={descriptionId} className="wn-field-error" role="alert">{error}</small> : hint ? <small id={descriptionId} className="wn-field-hint">{hint}</small> : null}
  </div>;
}

export function TextInput({ label, error, hint, className = "", id: requestedId, ...props }: InputHTMLAttributes<HTMLInputElement> & {
  label?: ReactNode;
  error?: ReactNode;
  hint?: ReactNode;
}) {
  const generatedId = useId();
  const id = requestedId || generatedId;
  const input = <input
    {...props}
    id={id}
    className={classes("wn-text-input", className)}
    aria-invalid={Boolean(error) || undefined}
    aria-describedby={error || hint ? `${id}-description` : props["aria-describedby"]}
  />;
  return label ? <FormField label={label} htmlFor={id} error={error} hint={hint} disabled={props.disabled}>{input}</FormField> : input;
}

export function SearchInput({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <label className={classes("wn-search-input", className)}>
    <Search aria-hidden="true" />
    <span className="visually-hidden">{props["aria-label"] || "Search"}</span>
    <input type="search" {...props} />
  </label>;
}

export function Select({ label, error, hint, className = "", id: requestedId, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & {
  label?: ReactNode;
  error?: ReactNode;
  hint?: ReactNode;
}) {
  const generatedId = useId();
  const id = requestedId || generatedId;
  const select = <select
    {...props}
    id={id}
    className={classes("wn-select", className)}
    aria-invalid={Boolean(error) || undefined}
    aria-describedby={error || hint ? `${id}-description` : props["aria-describedby"]}
  >{children}</select>;
  return label ? <FormField label={label} htmlFor={id} error={error} hint={hint} disabled={props.disabled}>{select}</FormField> : select;
}

export function Checkbox({ label, className = "", ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: ReactNode }) {
  return <label className={classes("wn-checkbox", className)}>
    <input type="checkbox" {...props} />
    <span>{label}</span>
  </label>;
}

export function Switch({ checked, onChange, label, disabled = false, className = "" }: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  disabled?: boolean;
  className?: string;
}) {
  return <button
    type="button"
    role="switch"
    aria-checked={checked}
    disabled={disabled}
    className={classes("wn-switch", className)}
    onClick={() => onChange(!checked)}
  >
    <span className="wn-switch-track" aria-hidden="true"><i /></span>
    <span>{label}</span>
  </button>;
}
