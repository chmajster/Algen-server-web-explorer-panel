import { AlertTriangle, X } from "lucide-react";
import { useEffect } from "react";

export type DcstConfirmAction = {
  title: string;
  message: string;
  subject?: string;
  confirmLabel?: string;
  destructive?: boolean;
  run: () => Promise<void>;
} | null;

export function DcstConfirmDialog({ action, busy, onCancel, onConfirm }: { action: DcstConfirmAction; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  useEffect(() => {
    if (!action) return undefined;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [action, busy, onCancel]);

  if (!action) return null;
  return <div className="dialog-backdrop dcst-confirm-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel(); }}>
    <div className="dialog-card dcst-confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="dcst-confirm-title" aria-describedby="dcst-confirm-description">
      <header><span className={action.destructive ? "danger" : "warning"}><AlertTriangle /></span><div><h3 id="dcst-confirm-title">{action.title}</h3>{action.subject && <strong>{action.subject}</strong>}</div><button className="icon-button" aria-label="Close confirmation" onClick={onCancel} disabled={busy}><X /></button></header>
      <p id="dcst-confirm-description">{action.message}</p>
      <div className="dialog-actions"><button onClick={onCancel} disabled={busy}>Cancel</button><button className={action.destructive ? "button-danger" : "button-primary"} onClick={onConfirm} disabled={busy}>{busy ? "Working..." : action.confirmLabel || "Confirm"}</button></div>
    </div>
  </div>;
}
