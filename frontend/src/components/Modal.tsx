import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

const FOCUSABLE = "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex='-1'])";

export function Modal({ title, children, onClose, footer, wide = false, closeLabel = "×", className = "" }: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  footer?: React.ReactNode;
  wide?: boolean;
  closeLabel?: string;
  className?: string;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(typeof document === "undefined" ? null : document.activeElement as HTMLElement | null);
  const onCloseRef = useRef(onClose);

  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  useEffect(() => {
    const restoreFocus = previousFocus.current;
    const autofocus = panel.current?.querySelector<HTMLElement>("[autofocus]");
    const focusable = autofocus || panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    if (!panel.current?.contains(document.activeElement)) (focusable || panel.current)?.focus();
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
      }
    }
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("keydown", escape);
      restoreFocus?.focus();
    };
  }, []);

  function trapFocus(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab" || !panel.current) return;
    const nodes = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].sort((left, right) => (
      left === right ? 0 : left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1
    ));
    if (!nodes.length) {
      event.preventDefault();
      panel.current.focus();
      return;
    }
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && (event.target === first || document.activeElement === first || event.target === panel.current)) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && (event.target === last || document.activeElement === last)) { event.preventDefault(); first.focus(); }
  }

  const dialog = (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onCloseRef.current()}>
      <div ref={panel} className={`modal-panel ${wide ? "modal-wide" : ""} ${className}`.trim()} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} onKeyDown={trapFocus} onPointerDown={(event) => event.stopPropagation()}>
        <header className="modal-header"><h2 id={titleId}>{title}</h2><button className="icon-button" type="button" aria-label={closeLabel} onClick={onClose}><X size={18} /></button></header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-footer">{footer}</footer>}
      </div>
    </div>
  );
  const portalTarget = typeof document === "undefined" ? null : document.querySelector<HTMLElement>(".desktop") || document.body;
  return portalTarget ? createPortal(dialog, portalTarget) : dialog;
}

export function ConfirmDialog({ title, message, confirmLabel, cancelLabel, danger = false, onConfirm, onClose }: {
  title: string;
  message: React.ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return <Modal title={title} closeLabel={cancelLabel} onClose={onClose} footer={<><button type="button" onClick={onClose}>{cancelLabel}</button><button className={danger ? "button-danger" : "button-primary"} type="button" onClick={onConfirm}>{confirmLabel}</button></>}><p>{message}</p></Modal>;
}

export function InputDialog({ title, label, value, confirmLabel, cancelLabel, type = "text", onConfirm, onClose }: {
  title: string;
  label: string;
  value?: string;
  confirmLabel: string;
  cancelLabel: string;
  type?: string;
  onConfirm: (value: string) => void;
  onClose: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return <Modal title={title} closeLabel={cancelLabel} onClose={onClose} footer={<><button type="button" onClick={onClose}>{cancelLabel}</button><button className="button-primary" type="submit" form="input-dialog-form">{confirmLabel}</button></>}>
    <form id="input-dialog-form" onSubmit={(event) => { event.preventDefault(); const next = input.current?.value.trim(); if (next) onConfirm(next); }}>
      <label className="field-label">{label}<input ref={input} defaultValue={value} type={type} autoFocus /></label>
    </form>
  </Modal>;
}
