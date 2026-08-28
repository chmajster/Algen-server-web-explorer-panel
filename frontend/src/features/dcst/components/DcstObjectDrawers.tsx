import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import type { DcstPort } from "../../../modules/dcst/api/client";

function DrawerShell({ title, description, open, saving, onClose, onSubmit, submitLabel, children }: { title: string; description: string; open: boolean; saving: boolean; onClose: () => void; onSubmit: () => void; submitLabel: string; children: ReactNode }) {
  useEffect(() => {
    if (!open) return undefined;
    const handleKey = (event: KeyboardEvent) => { if (event.key === "Escape" && !saving) onClose(); };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, saving, onClose]);

  if (!open) return null;
  return <div className="dcst-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}>
    <aside className="dcst-drawer dcst-object-editor-drawer" role="dialog" aria-modal="true" aria-label={title}>
      <header className="dcst-drawer-header"><div><h3>{title}</h3><p>{description}</p></div><button className="icon-button" aria-label={`Close ${title}`} onClick={onClose} disabled={saving}><X /></button></header>
      <form className="dcst-drawer-body" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>{children}</form>
      <footer className="dcst-drawer-footer"><button type="button" onClick={onClose} disabled={saving}>Cancel</button><button className="button-primary" type="button" onClick={onSubmit} disabled={saving}>{saving ? "Saving..." : submitLabel}</button></footer>
    </aside>
  </div>;
}

export function DcstIPSetDrawer({ open, editId, draft, saving, onDraftChange, onClose, onSubmit }: { open: boolean; editId: string; draft: { name: string; description: string; entries: string }; saving: boolean; onDraftChange: (draft: { name: string; description: string; entries: string }) => void; onClose: () => void; onSubmit: () => void }) {
  return <DrawerShell open={open} title={editId ? "Edit IP Set" : "Create IP Set"} description="Manage reusable IP addresses and CIDR ranges." saving={saving} onClose={onClose} onSubmit={onSubmit} submitLabel={editId ? "Save Changes" : "Create IP Set"}>
    <section className="dcst-form-section"><header><span>01</span><div><strong>General</strong><small>Object name and description</small></div></header>
      <label><span>Name</span><input autoFocus value={draft.name} onChange={(event) => onDraftChange({ ...draft, name: event.target.value })} placeholder="INTERNET_SERVICES" /></label>
      <label><span>Description</span><input value={draft.description} onChange={(event) => onDraftChange({ ...draft, description: event.target.value })} placeholder="External services allowed by policy" /></label>
    </section>
    <section className="dcst-form-section"><header><span>02</span><div><strong>Entries</strong><small>One IP address or CIDR per line</small></div></header>
      <label><span>IP / CIDR entries</span><textarea rows={12} value={draft.entries} onChange={(event) => onDraftChange({ ...draft, entries: event.target.value })} placeholder={"1.1.1.1\n8.8.8.8\n10.20.0.0/16"} /></label>
    </section>
  </DrawerShell>;
}

export function DcstPortDrawer({ open, editId, draft, saving, onDraftChange, onClose, onSubmit }: { open: boolean; editId: string; draft: { name: string; protocol: DcstPort["protocol"]; port_from: number | null; port_to: number | null; description: string }; saving: boolean; onDraftChange: (draft: { name: string; protocol: DcstPort["protocol"]; port_from: number | null; port_to: number | null; description: string }) => void; onClose: () => void; onSubmit: () => void }) {
  return <DrawerShell open={open} title={editId ? "Edit Port Object" : "Create Port Object"} description="Create a reusable transport definition for communication services." saving={saving} onClose={onClose} onSubmit={onSubmit} submitLabel={editId ? "Save Changes" : "Create Port Object"}>
    <section className="dcst-form-section"><header><span>01</span><div><strong>Port definition</strong><small>Protocol and port range</small></div></header>
      <label><span>Name</span><input autoFocus value={draft.name} onChange={(event) => onDraftChange({ ...draft, name: event.target.value })} placeholder="POSTGRESQL" /></label>
      <label><span>Protocol</span><select value={draft.protocol} onChange={(event) => { const protocol = event.target.value as DcstPort["protocol"]; onDraftChange({ ...draft, protocol, port_from: protocol === "icmp" ? null : draft.port_from ?? 443, port_to: protocol === "icmp" ? null : draft.port_to ?? 443 }); }}><option value="tcp">TCP</option><option value="udp">UDP</option><option value="tcp+udp">TCP + UDP</option><option value="icmp">ICMP</option></select></label>
      {draft.protocol !== "icmp" && <div className="dcst-inline-fields">
        <label><span>Port from</span><input type="number" min={1} max={65535} value={draft.port_from ?? ""} onChange={(event) => onDraftChange({ ...draft, port_from: event.target.value ? Number(event.target.value) : null })} /></label>
        <label><span>Port to</span><input type="number" min={1} max={65535} value={draft.port_to ?? ""} onChange={(event) => onDraftChange({ ...draft, port_to: event.target.value ? Number(event.target.value) : null })} /></label>
      </div>}
      <label><span>Description</span><textarea rows={4} value={draft.description} onChange={(event) => onDraftChange({ ...draft, description: event.target.value })} /></label>
    </section>
  </DrawerShell>;
}

export function DcstInfoDrawer({ title, description, open, onClose, children }: { title: string; description: string; open: boolean; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    if (!open) return undefined;
    const handleKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  if (!open) return null;
  return <div className="dcst-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="dcst-drawer dcst-details-drawer" role="dialog" aria-modal="true" aria-label={title}>
      <header className="dcst-drawer-header"><div><h3>{title}</h3><p>{description}</p></div><button className="icon-button" aria-label={`Close ${title}`} onClick={onClose}><X /></button></header>
      <div className="dcst-drawer-body">{children}</div>
    </aside>
  </div>;
}
