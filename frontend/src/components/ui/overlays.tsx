import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { Modal as WindowModal } from "../Modal";

const FOCUSABLE = "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex='-1'])";

export function Modal({ open, title, children, footer, onClose, wide = false, className = "" }: {
  open: boolean;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  wide?: boolean;
  className?: string;
}) {
  if (!open) return null;
  return <WindowModal title={title} footer={footer} onClose={onClose} wide={wide} className={`wn-modal ${className}`.trim()}>{children}</WindowModal>;
}

export function Drawer({ open, title, description, children, footer, onClose, side = "right" }: {
  open: boolean;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  side?: "left" | "right";
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE);
    (first || panel)?.focus();
    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = [...panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((element) => !element.hidden);
      if (!focusable.length) {
        event.preventDefault();
        panelRef.current.focus();
        return;
      }
      const firstElement = focusable[0];
      const lastElement = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    }
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      previous?.focus();
    };
  }, [onClose, open]);

  if (!open || typeof document === "undefined") return null;
  return createPortal(<div className="wn-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside ref={panelRef} className={`wn-drawer is-${side}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <header>
        <div><h2 id={titleId}>{title}</h2>{description ? <p>{description}</p> : null}</div>
        <button type="button" className="wn-icon-button" aria-label="Close" onClick={onClose}><X /></button>
      </header>
      <div className="wn-drawer-body">{children}</div>
      {footer ? <footer>{footer}</footer> : null}
    </aside>
  </div>, document.body);
}

export function ConfirmDialog({ open, title, message, confirmLabel = "Confirm", cancelLabel = "Cancel", busy = false, destructive = false, onConfirm, onCancel }: {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  busy?: boolean;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return <Modal open={open} title={title} onClose={onCancel} footer={<>
    <button type="button" className="button-secondary" disabled={busy} onClick={onCancel}>{cancelLabel}</button>
    <button type="button" className={destructive ? "button-danger" : "button-primary"} disabled={busy} onClick={onConfirm}>{confirmLabel}</button>
  </>}>
    <div className="wn-confirm-copy">{message}</div>
  </Modal>;
}

export function DangerConfirmDialog(props: Omit<Parameters<typeof ConfirmDialog>[0], "destructive">) {
  return <ConfirmDialog {...props} destructive />;
}
