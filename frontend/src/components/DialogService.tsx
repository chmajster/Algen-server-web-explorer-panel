import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Translate } from "../app/types";
import { ConfirmDialog, InputDialog } from "./Modal";

type ConfirmRequest = {
  id: number;
  kind: "confirm";
  message: string;
  danger: boolean;
  t: Translate;
  resolve: (value: boolean) => void;
};

type PromptRequest = {
  id: number;
  kind: "prompt";
  label: string;
  value: string;
  t: Translate;
  resolve: (value: string | null) => void;
};

type DialogRequest = ConfirmRequest | PromptRequest;
type DialogSubscriber = (request: DialogRequest) => void;

let nextRequestId = 1;
let subscriber: DialogSubscriber | null = null;

export function confirmDialog(message: string, t: Translate, danger = false): Promise<boolean> {
  if (!subscriber) return Promise.resolve(typeof window !== "undefined" ? window.confirm(message) : false);
  return new Promise<boolean>((resolve) => {
    subscriber?.({ id: nextRequestId++, kind: "confirm", message, danger, t, resolve });
  });
}

export function promptDialog(t: Translate, label: string, value = ""): Promise<string | null> {
  if (!subscriber) return Promise.resolve(typeof window !== "undefined" ? window.prompt(label, value) : null);
  return new Promise<string | null>((resolve) => {
    subscriber?.({ id: nextRequestId++, kind: "prompt", label, value, t, resolve });
  });
}

function GlobalDialogHost() {
  const [queue, setQueue] = useState<DialogRequest[]>([]);
  const queueRef = useRef<DialogRequest[]>([]);
  const current = queue[0] || null;

  useLayoutEffect(() => {
    const receive: DialogSubscriber = (request) => {
      queueRef.current = [...queueRef.current, request];
      setQueue(queueRef.current);
    };
    subscriber = receive;
    return () => {
      if (subscriber === receive) subscriber = null;
      for (const request of queueRef.current) {
        if (request.kind === "confirm") request.resolve(false);
        else request.resolve(null);
      }
      queueRef.current = [];
    };
  }, []);

  function finish(request: DialogRequest, value: boolean | string | null) {
    if (request.kind === "confirm") request.resolve(Boolean(value));
    else request.resolve(typeof value === "string" ? value : null);
    queueRef.current = queueRef.current.filter((item) => item.id !== request.id);
    setQueue(queueRef.current);
  }

  if (!current) return null;
  if (current.kind === "confirm") {
    return <ConfirmDialog
      title={current.t("action.confirm")}
      message={current.message}
      confirmLabel={current.t("action.confirm")}
      cancelLabel={current.t("action.cancel")}
      danger={current.danger}
      onConfirm={() => finish(current, true)}
      onClose={() => finish(current, false)}
    />;
  }
  return <InputDialog
    key={current.id}
    title={current.t("action.confirm")}
    label={current.label}
    value={current.value}
    confirmLabel={current.t("action.confirm")}
    cancelLabel={current.t("action.cancel")}
    onConfirm={(value) => finish(current, value)}
    onClose={() => finish(current, null)}
  />;
}

function dialogTitle(dialog: HTMLElement): string {
  const labelledBy = dialog.getAttribute("aria-labelledby");
  const labelled = labelledBy ? document.getElementById(labelledBy)?.textContent : "";
  return (labelled || dialog.getAttribute("aria-label") || dialog.querySelector("h1, h2, h3")?.textContent || "Window").trim();
}

function isUpdateDialog(dialog: HTMLElement): boolean {
  const labelledBy = dialog.getAttribute("aria-labelledby") || "";
  const classes = [
    dialog.className,
    dialog.closest<HTMLElement>(".modal-backdrop")?.className || "",
  ].join(" ");
  return labelledBy.startsWith("update-") || /(^|\s)update-(progress|completion|details|status)/.test(classes);
}

function restoreTray(): HTMLElement {
  let tray = document.getElementById("dialog-restore-tray");
  if (!tray) {
    tray = document.createElement("div");
    tray.id = "dialog-restore-tray";
    tray.className = "dialog-restore-tray";
    document.body.appendChild(tray);
  }
  return tray;
}

function LegacyDialogCompatibility() {
  useEffect(() => {
    const cleanups = new Map<HTMLElement, () => void>();

    function enhance(dialog: HTMLElement) {
      if (cleanups.has(dialog) || dialog.getAttribute("aria-modal") !== "true" || isUpdateDialog(dialog)) return;
      dialog.setAttribute("aria-modal", "false");
      dialog.dataset.nonblockingDialog = "true";
      dialog.style.pointerEvents = "auto";

      const layer = dialog.closest<HTMLElement>(".modal-backdrop, .network-modal-backdrop");
      const previousLayerStyle = layer ? {
        background: layer.style.background,
        backdropFilter: layer.style.backdropFilter,
        pointerEvents: layer.style.pointerEvents,
      } : null;
      if (layer) {
        layer.dataset.nonblockingDialogLayer = "true";
        layer.style.background = "transparent";
        layer.style.backdropFilter = "none";
        layer.style.pointerEvents = "none";
      }

      const title = dialogTitle(dialog);
      const minimize = document.createElement("button");
      minimize.type = "button";
      minimize.className = "icon-button legacy-dialog-minimize";
      minimize.setAttribute("aria-label", `Minimize ${title}`);
      minimize.title = `Minimize ${title}`;
      minimize.textContent = "−";

      const header = dialog.querySelector<HTMLElement>(":scope > header") || dialog.querySelector<HTMLElement>("header");
      const closeButton = header?.querySelector<HTMLButtonElement>("button:last-of-type");
      if (header) header.insertBefore(minimize, closeButton || null);
      else dialog.prepend(minimize);

      let restore: HTMLButtonElement | null = null;
      const minimizeDialog = (event: Event) => {
        event.preventDefault();
        event.stopPropagation();
        dialog.hidden = true;
        restore = document.createElement("button");
        restore.type = "button";
        restore.className = "button legacy-dialog-restore";
        restore.textContent = title;
        restore.setAttribute("aria-label", `Restore ${title}`);
        restore.title = `Restore ${title}`;
        restore.addEventListener("click", () => {
          dialog.hidden = false;
          restore?.remove();
          restore = null;
          dialog.focus();
        }, { once: true });
        restoreTray().appendChild(restore);
      };
      minimize.addEventListener("click", minimizeDialog);

      cleanups.set(dialog, () => {
        minimize.removeEventListener("click", minimizeDialog);
        minimize.remove();
        restore?.remove();
        dialog.hidden = false;
        delete dialog.dataset.nonblockingDialog;
        if (layer && previousLayerStyle) {
          layer.style.background = previousLayerStyle.background;
          layer.style.backdropFilter = previousLayerStyle.backdropFilter;
          layer.style.pointerEvents = previousLayerStyle.pointerEvents;
          delete layer.dataset.nonblockingDialogLayer;
        }
        const tray = document.getElementById("dialog-restore-tray");
        if (tray && !tray.childElementCount) tray.remove();
      });
    }

    function scan(root: ParentNode) {
      if (root instanceof HTMLElement && root.matches('[role="dialog"][aria-modal="true"]')) enhance(root);
      root.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]').forEach(enhance);
    }

    scan(document);
    const observer = new MutationObserver((records) => {
      records.forEach((record) => record.addedNodes.forEach((node) => {
        if (node instanceof HTMLElement) scan(node);
      }));
      cleanups.forEach((cleanup, dialog) => {
        if (!document.contains(dialog)) {
          cleanup();
          cleanups.delete(dialog);
        }
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      cleanups.forEach((cleanup) => cleanup());
      cleanups.clear();
    };
  }, []);
  return null;
}

export function DialogInfrastructure() {
  return <><GlobalDialogHost /><LegacyDialogCompatibility /></>;
}
