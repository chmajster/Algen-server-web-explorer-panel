/* eslint-disable react-hooks/refs -- pointer gesture refs are only read and mutated by pointer event handlers */
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Maximize2, Minimize2, X } from "lucide-react";
import { minimizedDialogOffset, releaseDialogMinimizedSlot, reserveDialogMinimizedSlot } from "./dialogMinimizedSlots";

const FOCUSABLE = "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex='-1'])";
const visibleDialogOrder: symbol[] = [];
let dialogZIndexCounter = 3500;
const DIALOG_MARGIN = 8;
const DIALOG_MIN_WIDTH = 320;
const DIALOG_MIN_HEIGHT = 180;
const MOBILE_DIALOG_WIDTH = 700;

type DialogRect = { x: number; y: number; width: number; height: number };
type ResizeEdge = "n" | "e" | "s" | "w" | "ne" | "nw" | "se" | "sw";
type DialogGesture = {
  mode: "move" | "resize";
  edge?: ResizeEdge;
  startX: number;
  startY: number;
  rect: DialogRect;
};

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

function nextDialogZIndex() {
  dialogZIndexCounter += 1;
  return dialogZIndexCounter;
}

function viewportSize() {
  return {
    width: Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0),
    height: Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0),
  };
}

function clampDialogRect(rect: DialogRect): DialogRect {
  const viewport = viewportSize();
  const maxWidth = Math.max(DIALOG_MIN_WIDTH, viewport.width - DIALOG_MARGIN * 2);
  const maxHeight = Math.max(DIALOG_MIN_HEIGHT, viewport.height - DIALOG_MARGIN * 2);
  const width = Math.min(Math.max(DIALOG_MIN_WIDTH, rect.width), maxWidth);
  const height = Math.min(Math.max(DIALOG_MIN_HEIGHT, rect.height), maxHeight);
  const maxX = Math.max(DIALOG_MARGIN, viewport.width - width - DIALOG_MARGIN);
  const maxY = Math.max(DIALOG_MARGIN, viewport.height - height - DIALOG_MARGIN);
  return {
    x: Math.min(Math.max(DIALOG_MARGIN, rect.x), maxX),
    y: Math.min(Math.max(DIALOG_MARGIN, rect.y), maxY),
    width,
    height,
  };
}

function measuredDialogRect(element: HTMLElement): DialogRect {
  const bounds = element.getBoundingClientRect();
  const width = bounds.width || element.offsetWidth || DIALOG_MIN_WIDTH;
  const height = bounds.height || element.offsetHeight || DIALOG_MIN_HEIGHT;
  const viewport = viewportSize();
  const x = bounds.width ? bounds.left : Math.max(DIALOG_MARGIN, (viewport.width - width) / 2);
  const y = bounds.height ? bounds.top : Math.max(DIALOG_MARGIN, (viewport.height - height) / 2);
  return clampDialogRect({ x, y, width, height });
}

function resizeHandleStyle(edge: ResizeEdge): React.CSSProperties {
  const base: React.CSSProperties = { position: "absolute", zIndex: 2, touchAction: "none" };
  if (edge === "n") return { ...base, top: -4, left: 10, right: 10, height: 8, cursor: "ns-resize" };
  if (edge === "s") return { ...base, bottom: -4, left: 10, right: 10, height: 8, cursor: "ns-resize" };
  if (edge === "e") return { ...base, right: -4, top: 10, bottom: 10, width: 8, cursor: "ew-resize" };
  if (edge === "w") return { ...base, left: -4, top: 10, bottom: 10, width: 8, cursor: "ew-resize" };
  if (edge === "ne") return { ...base, top: -4, right: -4, width: 12, height: 12, cursor: "nesw-resize" };
  if (edge === "nw") return { ...base, top: -4, left: -4, width: 12, height: 12, cursor: "nwse-resize" };
  if (edge === "se") return { ...base, bottom: -4, right: -4, width: 12, height: 12, cursor: "nwse-resize" };
  return { ...base, bottom: -4, left: -4, width: 12, height: 12, cursor: "nesw-resize" };
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
  const [layerZIndex, setLayerZIndex] = useState(() => nextDialogZIndex());
  const panel = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(typeof document === "undefined" ? null : document.activeElement as HTMLElement | null);
  const onCloseRef = useRef(onClose);
  const minimizedSlotRef = useRef<number | null>(null);
  const gesture = useRef<DialogGesture | null>(null);
  const restoreRect = useRef<DialogRect | null>(null);
  const [minimizedSlot, setMinimizedSlot] = useState<number | null>(null);
  const [rect, setRect] = useState<DialogRect | null>(null);
  const [maximized, setMaximized] = useState(false);
  const [mobileFullscreen, setMobileFullscreen] = useState(() => typeof window !== "undefined" && window.innerWidth <= MOBILE_DIALOG_WIDTH);
  const minimized = minimizedSlot !== null;

  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  useEffect(() => {
    function updateMobileMode() {
      const mobile = window.innerWidth <= MOBILE_DIALOG_WIDTH;
      setMobileFullscreen(mobile);
      if (mobile) {
        gesture.current = null;
        setMaximized(false);
        setRect(null);
      }
    }
    window.addEventListener("resize", updateMobileMode);
    return () => window.removeEventListener("resize", updateMobileMode);
  }, []);

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
    function move(event: PointerEvent) {
      const current = gesture.current;
      if (!current || mobileFullscreen) return;
      const dx = event.clientX - current.startX;
      const dy = event.clientY - current.startY;
      if (current.mode === "move") {
        setRect(clampDialogRect({ ...current.rect, x: current.rect.x + dx, y: current.rect.y + dy }));
        return;
      }
      const edge = current.edge || "se";
      let { x, y, width, height } = current.rect;
      if (edge.includes("e")) width += dx;
      if (edge.includes("s")) height += dy;
      if (edge.includes("w")) { width -= dx; x += dx; }
      if (edge.includes("n")) { height -= dy; y += dy; }
      if (width < DIALOG_MIN_WIDTH) {
        if (edge.includes("w")) x -= DIALOG_MIN_WIDTH - width;
        width = DIALOG_MIN_WIDTH;
      }
      if (height < DIALOG_MIN_HEIGHT) {
        if (edge.includes("n")) y -= DIALOG_MIN_HEIGHT - height;
        height = DIALOG_MIN_HEIGHT;
      }
      setRect(clampDialogRect({ x, y, width, height }));
    }
    function up() { gesture.current = null; }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
  }, [mobileFullscreen]);

  useEffect(() => {
    if (mobileFullscreen || (!rect && !maximized)) return;
    function resize() {
      if (maximized) {
        const viewport = viewportSize();
        setRect({ x: DIALOG_MARGIN, y: DIALOG_MARGIN, width: Math.max(DIALOG_MIN_WIDTH, viewport.width - DIALOG_MARGIN * 2), height: Math.max(DIALOG_MIN_HEIGHT, viewport.height - DIALOG_MARGIN * 2) });
      } else {
        setRect((current) => current ? clampDialogRect(current) : current);
      }
    }
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [maximized, mobileFullscreen, rect]);

  useEffect(() => {
    const restoreFocus = previousFocus.current;
    return () => {
      releaseDialogMinimizedSlot(minimizedSlotRef.current);
      restoreFocus?.focus();
    };
  }, []);

  function focusDialog() {
    const wasActive = isActiveDialog(dialogToken);
    activateDialog(dialogToken);
    if (!wasActive) setLayerZIndex(nextDialogZIndex());
  }

  function minimize() {
    if (minimizedSlotRef.current !== null) return;
    gesture.current = null;
    const slot = reserveDialogMinimizedSlot();
    minimizedSlotRef.current = slot;
    setMinimizedSlot(slot);
  }

  function restore() {
    releaseDialogMinimizedSlot(minimizedSlotRef.current);
    minimizedSlotRef.current = null;
    focusDialog();
    setMinimizedSlot(null);
  }

  function startMove(event: React.PointerEvent<HTMLElement>) {
    if (mobileFullscreen || maximized || (event.target as HTMLElement).closest("button")) return;
    event.preventDefault();
    focusDialog();
    const current = rect || (panel.current ? measuredDialogRect(panel.current) : null);
    if (!current) return;
    setRect(current);
    gesture.current = { mode: "move", startX: event.clientX, startY: event.clientY, rect: current };
  }

  function startResize(edge: ResizeEdge, event: React.PointerEvent<HTMLElement>) {
    if (mobileFullscreen || maximized) return;
    event.preventDefault();
    event.stopPropagation();
    focusDialog();
    const current = rect || (panel.current ? measuredDialogRect(panel.current) : null);
    if (!current) return;
    setRect(current);
    gesture.current = { mode: "resize", edge, startX: event.clientX, startY: event.clientY, rect: current };
  }

  function toggleMaximize() {
    if (mobileFullscreen || !panel.current) return;
    gesture.current = null;
    if (maximized) {
      setRect(restoreRect.current);
      restoreRect.current = null;
      setMaximized(false);
      return;
    }
    restoreRect.current = rect || measuredDialogRect(panel.current);
    const viewport = viewportSize();
    setRect({
      x: DIALOG_MARGIN,
      y: DIALOG_MARGIN,
      width: Math.max(DIALOG_MIN_WIDTH, viewport.width - DIALOG_MARGIN * 2),
      height: Math.max(DIALOG_MIN_HEIGHT, viewport.height - DIALOG_MARGIN * 2),
    });
    setMaximized(true);
  }

  const positionedStyle: React.CSSProperties = mobileFullscreen
    ? { position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)", pointerEvents: "auto" }
    : rect
      ? { position: "absolute", left: rect.x, top: rect.y, width: rect.width, height: rect.height, transform: "none", pointerEvents: "auto", maxWidth: "none", maxHeight: "none" }
      : { position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)", pointerEvents: "auto" };

  const dialogWindow = (
    <div
      className="dialog-window-layer"
      role="presentation"
      hidden={minimized}
      style={{ position: "fixed", zIndex: layerZIndex, inset: 0, pointerEvents: "none" }}
    >
      <div
        ref={panel}
        className={`modal-panel dialog-window ${maximized ? "dialog-window-maximized" : ""} ${wide ? "modal-wide" : ""} ${className}`.trim()}
        role="dialog"
        aria-modal="false"
        aria-labelledby={titleId}
        tabIndex={-1}
        onPointerDown={(event) => { focusDialog(); event.stopPropagation(); }}
        onFocusCapture={focusDialog}
        style={positionedStyle}
      >
        <header
          className="modal-header"
          onPointerDown={startMove}
          onDoubleClick={() => { if (!mobileFullscreen) toggleMaximize(); }}
          style={{ cursor: mobileFullscreen || maximized ? "default" : "move", touchAction: "none", userSelect: "none" }}
        >
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
            {!mobileFullscreen && <button
              className="icon-button"
              type="button"
              aria-label={`${maximized ? "Restore" : "Maximize"} ${title}`}
              title={`${maximized ? "Restore" : "Maximize"} ${title}`}
              onClick={toggleMaximize}
            >
              <Maximize2 size={18} />
            </button>}
            <button className="icon-button" type="button" aria-label={closeLabel} onClick={onClose}><X size={18} /></button>
          </div>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-footer">{footer}</footer>}
        {!mobileFullscreen && !maximized && (["n", "e", "s", "w", "ne", "nw", "se", "sw"] as ResizeEdge[]).map((edge) => (
          <span
            key={edge}
            className={`dialog-resize-handle dialog-resize-${edge}`}
            aria-hidden="true"
            onPointerDown={(event) => startResize(edge, event)}
            style={resizeHandleStyle(edge)}
          />
        ))}
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
