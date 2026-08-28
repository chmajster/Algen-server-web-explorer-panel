import { ArrowDown, Check, ChevronDown, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { DcstIPSet, DcstPort, DcstServiceInput, DcstTag } from "../../../modules/dcst/api/client";
import { DcstObjectBadge } from "./DcstPrimitives";

export type DcstServiceErrors = Partial<Record<"name" | "source" | "destination" | "direction" | "action", string>>;
type EndpointSide = "source" | "destination";

function portLabel(port: DcstPort) {
  const range = port.port_from ? `${port.port_from}${port.port_to && port.port_to !== port.port_from ? `–${port.port_to}` : ""}` : "";
  return `${port.name} · ${port.protocol.toUpperCase()}${range ? `/${range}` : ""}`;
}

function EndpointSelector({
  side,
  draft,
  tags,
  ipsets,
  error,
  onChange,
}: {
  side: EndpointSide;
  draft: DcstServiceInput;
  tags: DcstTag[];
  ipsets: DcstIPSet[];
  error?: string;
  onChange: (draft: DcstServiceInput) => void;
}) {
  const typeKey = side === "source" ? "source_type" : "destination_type";
  const valueKey = side === "source" ? "source_value" : "destination_value";
  const kind = draft[typeKey];
  const value = draft[valueKey];
  const apmids = useMemo(() => [...new Set(tags.map((tag) => tag.apmid))].sort(), [tags]);
  const tag = kind === "tag" ? tags.find((item) => item.name === value) : undefined;
  const ipset = kind === "ipset" ? ipsets.find((item) => item.id === value || item.name === value) : undefined;
  const countText = tag ? `${tag.vm_count} virtual machine${tag.vm_count === 1 ? "" : "s"}` : ipset ? `${ipset.entries.length} address entr${ipset.entries.length === 1 ? "y" : "ies"}` : "";

  function setType(next: DcstServiceInput["source_type"]) {
    onChange({ ...draft, [typeKey]: next, [valueKey]: "" });
  }

  function setValue(next: string) {
    onChange({ ...draft, [valueKey]: next });
  }

  return <fieldset className={`dcst-endpoint-selector ${error ? "has-error" : ""}`}>
    <legend>{side === "source" ? "SOURCE" : "DESTINATION"}</legend>
    <div className="dcst-endpoint-fields">
      <label>
        <span>Object type</span>
        <select value={kind} onChange={(event) => setType(event.target.value as DcstServiceInput["source_type"])}>
          <option value="tag">APMID.ENV TAG</option>
          <option value="apmid">APMID.*</option>
          <option value="ipset">IPSet</option>
          <option value="ip">IP address</option>
          <option value="cidr">CIDR</option>
          <option value="any">Any</option>
        </select>
      </label>
      {kind !== "any" && <label>
        <span>Object</span>
        {kind === "tag" ? <select value={value} onChange={(event) => setValue(event.target.value)}>
          <option value="">Select tag...</option>
          {tags.map((item) => <option key={item.id} value={item.name}>{item.name} · {item.vm_count} VM</option>)}
        </select> : kind === "ipset" ? <select value={value} onChange={(event) => setValue(event.target.value)}>
          <option value="">Select IPSet...</option>
          {ipsets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.entries.length} entries</option>)}
        </select> : kind === "apmid" ? <select value={value} onChange={(event) => setValue(event.target.value)}>
          <option value="">Select APMID...</option>
          {apmids.map((apmid) => <option key={apmid} value={apmid}>{apmid}</option>)}
        </select> : <input
          value={value}
          placeholder={kind === "cidr" ? "10.0.20.0/24" : "10.0.20.15"}
          onChange={(event) => setValue(event.target.value)}
        />}
      </label>}
    </div>
    <div className="dcst-endpoint-preview">
      <DcstObjectBadge type={kind} value={value} tags={tags} ipsets={ipsets} />
      {countText && <small>{countText}</small>}
    </div>
    {error && <small className="dcst-field-error">{error}</small>}
  </fieldset>;
}

export function DcstServiceDrawer({
  open,
  editId,
  draft,
  tags,
  ipsets,
  ports,
  errors,
  saving,
  onDraftChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  editId: string;
  draft: DcstServiceInput;
  tags: DcstTag[];
  ipsets: DcstIPSet[];
  ports: DcstPort[];
  errors: DcstServiceErrors;
  saving: boolean;
  onDraftChange: (draft: DcstServiceInput) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const [advanced, setAdvanced] = useState(false);
  const [portSearch, setPortSearch] = useState("");

  useEffect(() => {
    if (!open) return undefined;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) {
      setAdvanced(false);
      setPortSearch("");
    }
  }, [open]);

  if (!open) return null;

  const visiblePorts = ports.filter((port) => portLabel(port).toLowerCase().includes(portSearch.trim().toLowerCase()));
  const selectedPorts = draft.port_ids.map((id) => ports.find((port) => port.id === id)).filter((port): port is DcstPort => Boolean(port));

  function togglePort(id: string) {
    onDraftChange({
      ...draft,
      port_ids: draft.port_ids.includes(id) ? draft.port_ids.filter((item) => item !== id) : [...draft.port_ids, id],
    });
  }

  return <div className="dcst-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="dcst-drawer" role="dialog" aria-modal="true" aria-labelledby="dcst-service-drawer-title">
      <header className="dcst-drawer-header">
        <div><h3 id="dcst-service-drawer-title">{editId ? "Edit Communication Service" : "Create Communication Service"}</h3><p>Define communication between network security objects.</p></div>
        <button className="icon-button" aria-label="Close service editor" onClick={onClose}><X /></button>
      </header>

      <form className="dcst-drawer-body" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
        <section className="dcst-form-section">
          <header><span>01</span><div><strong>General</strong><small>Policy identity and purpose</small></div></header>
          <label className={errors.name ? "has-error" : ""}>
            <span>Service name</span>
            <input autoFocus value={draft.name} placeholder="WEB_TO_DATABASE" onChange={(event) => onDraftChange({ ...draft, name: event.target.value })} />
            {errors.name && <small className="dcst-field-error">{errors.name}</small>}
          </label>
          <label>
            <span>Description</span>
            <input value={draft.description} placeholder="Allow application servers to PostgreSQL" onChange={(event) => onDraftChange({ ...draft, description: event.target.value })} />
          </label>
        </section>

        <section className="dcst-form-section">
          <header><span>02</span><div><strong>Communication</strong><small>Source and destination security objects</small></div></header>
          <EndpointSelector side="source" draft={draft} tags={tags} ipsets={ipsets} error={errors.source} onChange={onDraftChange} />
          <div className="dcst-drawer-flow" aria-hidden="true"><ArrowDown /></div>
          <EndpointSelector side="destination" draft={draft} tags={tags} ipsets={ipsets} error={errors.destination} onChange={onDraftChange} />
        </section>

        <section className="dcst-form-section">
          <header><span>03</span><div><strong>Policy</strong><small>Traffic direction and firewall action</small></div></header>
          <div className="dcst-field-group">
            <span className="dcst-field-label">Direction</span>
            <div className="dcst-segmented" role="group" aria-label="Traffic direction">
              <button type="button" title="Traffic entering destination." className={draft.direction === "IN" ? "active" : ""} onClick={() => onDraftChange({ ...draft, direction: "IN" })}>IN</button>
              <button type="button" title="Traffic leaving source." className={draft.direction === "OUT" ? "active" : ""} onClick={() => onDraftChange({ ...draft, direction: "OUT" })}>OUT</button>
            </div>
            {errors.direction && <small className="dcst-field-error">{errors.direction}</small>}
          </div>
          <div className="dcst-field-group">
            <span className="dcst-field-label">Action</span>
            <div className="dcst-action-selector" role="group" aria-label="Firewall action">
              {(["ACCEPT", "DROP", "REJECT"] as const).map((action) => <button type="button" key={action} className={`${action.toLowerCase()} ${draft.action === action ? "active" : ""}`} onClick={() => onDraftChange({ ...draft, action })}>
                {draft.action === action && <Check />}{action}
              </button>)}
            </div>
            {errors.action && <small className="dcst-field-error">{errors.action}</small>}
          </div>
        </section>

        <section className="dcst-form-section">
          <header><span>04</span><div><strong>Allowed services</strong><small>Reusable port objects applied to the policy</small></div></header>
          {!!selectedPorts.length && <div className="dcst-selected-ports">
            <span className="dcst-field-label">Selected services</span>
            <div>{selectedPorts.map((port) => <button type="button" key={port.id} onClick={() => togglePort(port.id)}>{portLabel(port)} <X /></button>)}</div>
          </div>}
          <div className="dcst-port-search"><Search /><input value={portSearch} onChange={(event) => setPortSearch(event.target.value)} placeholder="Search port objects..." /></div>
          <div className="dcst-port-library">
            {visiblePorts.map((port) => <button type="button" key={port.id} className={draft.port_ids.includes(port.id) ? "selected" : ""} onClick={() => togglePort(port.id)}>
              <span>{port.name}</span><small>{port.protocol.toUpperCase()} {port.port_from ? `${port.port_from}${port.port_to && port.port_to !== port.port_from ? `–${port.port_to}` : ""}` : ""}</small>
            </button>)}
            {!visiblePorts.length && <p>No matching port objects.</p>}
          </div>
        </section>

        <section className="dcst-form-section dcst-advanced-section">
          <button type="button" className="dcst-advanced-toggle" aria-expanded={advanced} onClick={() => setAdvanced((value) => !value)}>
            <span><strong>Advanced options</strong><small>Enabled state, traffic logging and comment</small></span><ChevronDown className={advanced ? "open" : ""} />
          </button>
          {advanced && <div className="dcst-advanced-content">
            <label className="dcst-check-row"><input type="checkbox" checked={draft.enabled} onChange={(event) => onDraftChange({ ...draft, enabled: event.target.checked })} /><span><strong>Enabled</strong><small>Include this policy in desired state.</small></span></label>
            <label className="dcst-check-row"><input type="checkbox" checked={draft.logging} onChange={(event) => onDraftChange({ ...draft, logging: event.target.checked })} /><span><strong>Log matching traffic</strong><small>Request firewall logging for matching rules.</small></span></label>
            <label><span>Comment</span><textarea rows={3} value={draft.comment} onChange={(event) => onDraftChange({ ...draft, comment: event.target.value })} /></label>
          </div>}
        </section>
      </form>

      <footer className="dcst-drawer-footer">
        <button type="button" onClick={onClose} disabled={saving}>Cancel</button>
        <button className="button-primary" type="button" onClick={onSubmit} disabled={saving}>{saving ? "Saving..." : editId ? "Save Changes" : "Create Service"}</button>
      </footer>
    </aside>
  </div>;
}
