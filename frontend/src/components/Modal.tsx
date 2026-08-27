import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Maximize2, Minimize2, X } from "lucide-react";
import { minimizedDialogOffset, releaseDialogMinimizedSlot, reserveDialogMinimizedSlot } from "./dialogMinimizedSlots";

const FOCUSABLE = "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex='-1'])";
const visibleDialogOrder: symbol[] = [];

function activateDialog(token: symbol) {
  const index = visibleDialogOrder.indexOf(token);
  if (index >= 0) visibleDialogOrder.splice(index, 1);
  visibleDialogOrder.push(token);
}

function deactivateDialog(token: symbol) {
  const index = visibleDialogOrder.indexOf(token);
  if (index >= 0) visibleDialogOrder.splice(index, 1);
}

function isActiveDialog(token: symbol) {
  return visibleDialogOrder[visibleDialogOrder.length - 1] === token;
}

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
  const [dialogToken] = useState(() => Symbol("dialog"));
  const panel = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(typeof document === "undefined" ? null : document.activeElement as HTMLElement | null);
  const onCloseRef = useRef(onClose);
  const minimizedSlotRef = useRef<number | null>(null);
  const [minimizedSlot, setMinimizedSlot] = useState<number | null>(null);
  const minimized = minimizedSlot !== null;

  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  useEffect(() => {
    if (minimized) return;
    const autofocus = panel.current?.querySelector<HTMLElement>("[autofocus]");
    const focusable = autofocus || panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    if (!panel.current?.contains(document.activeElement)) (focusable || panel.current)?.focus();
  }, [minimized]);

  useEffect(() => {
    if (minimized) {
      deactivateDialog(dialogToken);
      return;
    }
    activateDialog(dialogToken);
    return () => deactivateDialog(dialogToken);
  }, [dialogToken, minimized]);

  useEffect(() => {
    if (minimized) return;
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape" && isActiveDialog(dialogToken)) {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
      }
    }
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [dialogToken, minimized]);

  useEffect(() => {
    const restoreFocus = previousFocus.current;
    return () => {
      releaseDialogMinimizedSlot(minimizedSlotRef.current);
      restoreFocus?.focus();
    };
  }, []);

  function minimize() {
    if (minimizedSlotRef.current !== null) return;
    const slot = reserveDialogMinimizedSlot();
    minimizedSlotRef.current = slot;
    setMinimizedSlot(slot);
  }

  function restore() {
    releaseDialogMinimizedSlot(minimizedSlotRef.current);
    minimizedSlotRef.current = null;
    setMinimizedSlot(null);
  }

  const dialogWindow = (
    <div
      className="dialog-window-layer"
      role="presentation"
      hidden={minimized}
      style={{ position: "fixed", zIndex: 3500, inset: 0, pointerEvents: "none" }}
    >
      <div
        ref={panel}
        className={`modal-panel dialog-window ${wide ? "modal-wide" : ""} ${className}`.trim()}
        role="dialog"
        aria-modal="false"
        aria-labelledby={titleId}
        tabIndex={-1}
        onPointerDown={(event) => { activateDialog(dialogToken); event.stopPropagation(); }}
        onFocusCapture={() => activateDialog(dialogToken)}
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          pointerEvents: "auto",
        }}
      >
        <header className="modal-header">
          <h2 id={titleId}>{title}</h2>
          <div className="modal-header-controls">
            <button
              className="icon-button"
              type="button"
              aria-label={`Minimize ${title}`}
              title={`Minimize ${title}`}
              onClick={minimize}
            >
              <Minimize2 size={18} />
            </button>
            <button className="icon-button" type="button" aria-label={closeLabel} onClick={onClose}><X size={18} /></button>
          </div>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-footer">{footer}</footer>}
      </div>
    </div>
  );

  const restoreButton = minimizedSlot !== null ? (
    <button
      type="button"
      className="button modal-minimized-entry"
      data-minimized-slot={minimizedSlot}
      aria-label={`Restore ${title}`}
      title={`Restore ${title}`}
      onClick={restore}
      style={{ "--dialog-minimized-offset": minimizedDialogOffset(minimizedSlot) } as React.CSSProperties}
    >
      <Maximize2 size={16} />
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</span>
    </button>
  ) : null;

  const dialog = <>{dialogWindow}{restoreButton}</>;
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
  const formId = useId();
  return <Modal title={title} closeLabel={cancelLabel} onClose={onClose} footer={<><button type="button" onClick={onClose}>{cancelLabel}</button><button className="button-primary" type="submit" form={formId}>{confirmLabel}</button></>}>
    <form id={formId} className="input-dialog-form" onSubmit={(event) => { event.preventDefault(); const next = input.current?.value.trim(); if (next) onConfirm(next); }}>
      <label className="field-label">{label}<input ref={input} defaultValue={value} type={type} autoFocus /></label>
    </form>
  </Modal>;
}
