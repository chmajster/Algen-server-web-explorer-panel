import { AlertTriangle, CheckCircle2, Edit3, Globe2, Link2, Plus, RefreshCw, ShieldAlert, Trash2, Unlink } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import {
  api,
  type ManagedNetworkRoute,
  type NetworkChange,
  type NetworkInterfaceConfiguration,
  type NetworkManagementState,
  type NetworkPlan,
  type NetworkTrafficRule,
  type NetworkTransaction,
} from "../../api";
import type { Translate } from "../../app/types";

const emptyIp = (family: "ipv4" | "ipv6") => ({
  method: family === "ipv4" ? "dhcp" as const : "slaac" as const,
  addresses: [],
  gateway: null,
  metric: 100,
  default_route: true,
  ignore_auto_routes: false,
  ignore_auto_dns: false,
  dns: [],
  search_domains: [],
  privacy_extensions: family === "ipv6",
});

function newInterface(): NetworkInterfaceConfiguration {
  return {
    name: "", kind: "physical", autostart: true, mtu: 1500, parent: null, vlan_id: null, members: [],
    bond_mode: "active-backup", primary: null, miimon: 100, updelay: 0, downdelay: 0, lacp_rate: "slow",
    xmit_hash_policy: "layer2", stp: false, forward_delay: 15, ipv4: emptyIp("ipv4"), ipv6: emptyIp("ipv6"),
  };
}

function newRoute(): ManagedNetworkRoute {
  return { name: "", family: "ipv4", destination: "", route_type: "unicast", gateway: null, interface: null, metric: 100, table: 254, source: null, autostart: true, enabled: true };
}

function newTraffic(): NetworkTrafficRule {
  return { name: "", interface: "", direction: "egress", guaranteed_kbit: 1000, maximum_kbit: 10000, priority: 5, protocol: "any", source_cidr: null, destination_cidr: null, source_port: null, destination_port: null, enabled: true };
}

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const panel = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    const root = panel.current;
    root?.querySelector<HTMLElement>("input, select, button")?.focus();
    const keyboard = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
      if (event.key !== "Tab" || !root) return;
      const focusable = Array.from(root.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex='0']"));
      if (!focusable.length) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", keyboard);
    return () => document.removeEventListener("keydown", keyboard);
  }, []);
  return <div className="network-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={panel} className="network-modal" role="dialog" aria-modal="true" aria-label={title}>
      <header><h3>{title}</h3><button type="button" onClick={onClose} aria-label="Zamknij">×</button></header>
      {children}
    </section>
  </div>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="network-form-field"><span>{label}</span>{children}</label>;
}

function InterfaceForm({ initial, available, onClose, onSubmit }: {
  initial?: NetworkInterfaceConfiguration; available: string[]; onClose: () => void; onSubmit: (value: NetworkInterfaceConfiguration) => void;
}) {
  const [value, setValue] = useState<NetworkInterfaceConfiguration>(() => initial || newInterface());
  const [section, setSection] = useState<"link" | "ipv4" | "ipv6">("link");
  const updateIp = (family: "ipv4" | "ipv6", patch: Partial<NetworkInterfaceConfiguration[typeof family]>) =>
    setValue((current) => ({ ...current, [family]: { ...current[family], ...patch } }));
  const submit = (event: FormEvent) => { event.preventDefault(); onSubmit(value); };
  return <Modal title={initial ? "Edytuj interfejs" : "Nowy interfejs"} onClose={onClose}>
    <form onSubmit={submit}>
      <nav className="network-form-tabs">{(["link", "ipv4", "ipv6"] as const).map((item) => <button type="button" className={section === item ? "active" : ""} onClick={() => setSection(item)} key={item}>{item === "link" ? "Łącze" : item.toUpperCase()}</button>)}</nav>
      <div className="network-form-grid">
        {section === "link" && <>
          <Field label="Rodzaj"><select value={value.kind} onChange={(e) => setValue({ ...value, kind: e.target.value as NetworkInterfaceConfiguration["kind"] })}><option value="physical">Fizyczny</option><option value="bond">Bond</option><option value="vlan">VLAN</option><option value="bridge">Most</option></select></Field>
          <Field label="Nazwa"><input required maxLength={15} pattern="[A-Za-z0-9_.:-]+" value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></Field>
          <Field label="MTU"><input type="number" min={576} max={9216} value={value.mtu} onChange={(e) => setValue({ ...value, mtu: Number(e.target.value) })} /></Field>
          <Field label="Uruchamiaj automatycznie"><input type="checkbox" checked={value.autostart} onChange={(e) => setValue({ ...value, autostart: e.target.checked })} /></Field>
          {value.kind === "vlan" && <><Field label="Interfejs nadrzędny"><select required value={value.parent || ""} onChange={(e) => setValue({ ...value, parent: e.target.value })}><option value="">Wybierz</option>{available.map((name) => <option key={name}>{name}</option>)}</select></Field><Field label="VLAN ID"><input required type="number" min={1} max={4094} value={value.vlan_id || ""} onChange={(e) => setValue({ ...value, vlan_id: Number(e.target.value) })} /></Field></>}
          {(value.kind === "bond" || value.kind === "bridge") && <Field label="Porty składowe"><select multiple value={value.members} onChange={(e) => setValue({ ...value, members: Array.from(e.target.selectedOptions, (option) => option.value) })}>{available.filter((name) => name !== value.name).map((name) => <option key={name}>{name}</option>)}</select></Field>}
          {value.kind === "bond" && <><Field label="Tryb bond"><select value={value.bond_mode} onChange={(e) => setValue({ ...value, bond_mode: e.target.value as NetworkInterfaceConfiguration["bond_mode"] })}>{["active-backup", "balance-rr", "balance-xor", "broadcast", "802.3ad", "balance-tlb", "balance-alb"].map((mode) => <option key={mode}>{mode}</option>)}</select></Field><Field label="miimon (ms)"><input type="number" min={0} max={10000} value={value.miimon} onChange={(e) => setValue({ ...value, miimon: Number(e.target.value) })} /></Field></>}
          {value.kind === "bond" && <><Field label="Interfejs primary"><select disabled={value.bond_mode !== "active-backup"} value={value.primary || ""} onChange={(e) => setValue({ ...value, primary: e.target.value || null })}><option value="">Automatycznie</option>{value.members.map((name) => <option key={name}>{name}</option>)}</select></Field><Field label="updelay / downdelay (ms)"><span className="network-inline-inputs"><input type="number" min={0} value={value.updelay} onChange={(e) => setValue({ ...value, updelay: Number(e.target.value) })} /><input type="number" min={0} value={value.downdelay} onChange={(e) => setValue({ ...value, downdelay: Number(e.target.value) })} /></span></Field><Field label="LACP rate"><select disabled={value.bond_mode !== "802.3ad"} value={value.lacp_rate} onChange={(e) => setValue({ ...value, lacp_rate: e.target.value as "slow" | "fast" })}><option value="slow">slow</option><option value="fast">fast</option></select></Field><Field label="Hash policy"><select value={value.xmit_hash_policy} onChange={(e) => setValue({ ...value, xmit_hash_policy: e.target.value as NetworkInterfaceConfiguration["xmit_hash_policy"] })}>{["layer2", "layer2+3", "layer3+4"].map((item) => <option key={item}>{item}</option>)}</select></Field></>}
          {value.kind === "bridge" && <Field label="STP"><input type="checkbox" checked={value.stp} onChange={(e) => setValue({ ...value, stp: e.target.checked })} /></Field>}
        </>}
        {(section === "ipv4" || section === "ipv6") && (() => {
          const ip = value[section];
          return <>
            <Field label="Metoda"><select value={ip.method} onChange={(e) => updateIp(section, { method: e.target.value as typeof ip.method })}><option value="disabled">Wyłączone</option>{section === "ipv4" ? <option value="dhcp">DHCP</option> : <><option value="slaac">SLAAC</option><option value="dhcpv6">DHCPv6</option></>}<option value="manual">Ręcznie</option></select></Field>
            {ip.method === "manual" && <><Field label="Adresy CIDR (po przecinku)"><input required placeholder={section === "ipv4" ? "192.0.2.10/24" : "2001:db8::10/64"} value={ip.addresses.map((item) => `${item.address}/${item.prefix}`).join(", ")} onChange={(e) => updateIp(section, { addresses: e.target.value.split(",").map((item) => item.trim()).filter((item) => item.includes("/")).map((item) => { const [rawAddress, rawPrefix] = item.split("/", 2); return { address: rawAddress, prefix: Number(rawPrefix) }; }) })} /></Field><Field label="Brama"><input value={ip.gateway || ""} onChange={(e) => updateIp(section, { gateway: e.target.value || null })} /></Field></>}
            <Field label="Metryka"><input type="number" min={0} max={4294967295} value={ip.metric} onChange={(e) => updateIp(section, { metric: Number(e.target.value) })} /></Field>
            <Field label="DNS (po przecinku)"><input value={ip.dns.join(", ")} onChange={(e) => updateIp(section, { dns: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></Field>
            <Field label="Domeny wyszukiwania"><input value={ip.search_domains.join(", ")} onChange={(e) => updateIp(section, { search_domains: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></Field>
            <Field label="Trasa domyślna"><input type="checkbox" checked={ip.default_route} onChange={(e) => updateIp(section, { default_route: e.target.checked })} /></Field>
            <Field label="Ignoruj automatyczne trasy"><input type="checkbox" checked={ip.ignore_auto_routes} onChange={(e) => updateIp(section, { ignore_auto_routes: e.target.checked })} /></Field>
            <Field label="Ignoruj automatyczne DNS"><input type="checkbox" checked={ip.ignore_auto_dns} onChange={(e) => updateIp(section, { ignore_auto_dns: e.target.checked })} /></Field>
            {section === "ipv6" && <Field label="Privacy extensions"><input type="checkbox" checked={ip.privacy_extensions} onChange={(e) => updateIp(section, { privacy_extensions: e.target.checked })} /></Field>}
          </>;
        })()}
      </div>
      <footer><button type="button" onClick={onClose}>Anuluj</button><button className="button-primary" type="submit">Przejdź do planu</button></footer>
    </form>
  </Modal>;
}

function GeneralPanel({ state, onChange, onNavigate }: { state: NetworkManagementState; onChange: (change: NetworkChange) => void; onNavigate: (tab: "interfaces" | "routes" | "connectivity") => void }) {
  const [dnsOpen, setDnsOpen] = useState(false);
  const defaults = state.routing.gateways;
  const dnsServers = state.managed.dns?.servers?.length ? state.managed.dns.servers : state.dns.systemd_resolved.global_servers.length ? state.dns.systemd_resolved.global_servers : state.dns.resolv_conf.nameservers;
  return <div className="network-management-stack">
    <section className="network-management-cards">
      <article><span>Host</span><strong>{state.hostname || "—"}</strong><small>{state.provider.id}</small></article>
      <article><span>Aktywne interfejsy</span><strong>{state.interfaces.filter((item) => item.state === "up").length}</strong><small>z {state.interfaces.length}</small></article>
      <article><span>Brama domyślna</span><strong>{defaults[0]?.address || "—"}</strong><small>{defaults[0]?.device || "Brak"}</small></article>
      <article><span>DNS</span><strong>{dnsServers[0] || "—"}</strong><small>{dnsServers.length} serwerów</small></article>
    </section>
    <div className="network-actionbar"><button onClick={() => onNavigate("interfaces")}>Konfiguruj interfejsy</button><button onClick={() => setDnsOpen(true)}>Konfiguruj DNS</button><button onClick={() => onNavigate("routes")}>Dodaj trasę</button><button onClick={() => onNavigate("connectivity")}>Testuj łączność</button></div>
    {!state.provider.writable && <div className="network-provider-warning"><ShieldAlert /><div><strong>Tryb tylko do odczytu</strong><p>{state.provider.warnings.join(" ") || "Nie wykryto jednoznacznego, obsługiwanego menedżera sieci."}</p></div></div>}
    <section className="network-management-card"><header><div><h3>Stan efektywny</h3><p>Aktualna konfiguracja odczytana z systemu.</p></div></header><dl><div><dt>Domyślna trasa IPv4</dt><dd>{defaults.find((item) => item.family === "ipv4")?.address || "—"}</dd></div><div><dt>Domyślna trasa IPv6</dt><dd>{defaults.find((item) => item.family === "ipv6")?.address || "—"}</dd></div><div><dt>Domeny wyszukiwania</dt><dd>{(state.managed.dns?.search_domains || state.dns.resolv_conf.search).join(", ") || "—"}</dd></div><div><dt>systemd-resolved</dt><dd>{state.dns.systemd_resolved.available ? "aktywny" : "niedostępny"}</dd></div><div><dt>Łączność podstawowa</dt><dd>{state.interfaces.some((item) => item.state === "up" && !item.system) && defaults.length ? "gotowa" : "ograniczona"}</dd></div><div><dt>Automatyczny rollback</dt><dd>{state.transaction ? `aktywny do ${new Date(state.transaction.deadline * 1000).toLocaleTimeString()}` : "brak oczekującej zmiany"}</dd></div></dl></section>
    <section className="network-management-card"><header><div><h3>Konfiguracja DNS</h3><p>Serwery globalne i domeny wyszukiwania.</p></div><button type="button" disabled={!state.provider.writable} onClick={() => setDnsOpen(true)}><Edit3 />Edytuj</button></header><dl><div><dt>Serwery</dt><dd>{dnsServers.join(", ") || "—"}</dd></div><div><dt>Domeny</dt><dd>{(state.managed.dns?.search_domains || state.dns.resolv_conf.search).join(", ") || "—"}</dd></div></dl></section>
    {dnsOpen && <DnsForm state={state} onClose={() => setDnsOpen(false)} onSubmit={(dns) => { setDnsOpen(false); onChange({ operation: "save_dns", dns }); }} />}
  </div>;
}

function DnsForm({ state, onClose, onSubmit }: { state: NetworkManagementState; onClose: () => void; onSubmit: (dns: NonNullable<NetworkManagementState["managed"]["dns"]>) => void }) {
  const [servers, setServers] = useState((state.managed.dns?.servers || state.dns.resolv_conf.nameservers).join(", "));
  const [domains, setDomains] = useState((state.managed.dns?.search_domains || state.dns.resolv_conf.search).join(", "));
  return <Modal title="Konfiguracja DNS" onClose={onClose}><form onSubmit={(e) => { e.preventDefault(); const parsed = servers.split(",").map((v) => v.trim()).filter(Boolean); onSubmit({ automatic: false, servers: parsed, search_domains: domains.split(",").map((v) => v.trim()).filter(Boolean), routing_domains: [], per_interface: Object.fromEntries(state.interfaces.filter((item) => !item.system).map((item) => [item.name, parsed])), priority: 100, ignore_dhcp: true }); }}><div className="network-form-grid"><Field label="Serwery DNS"><input required value={servers} onChange={(e) => setServers(e.target.value)} placeholder="1.1.1.1, 2606:4700:4700::1111" /></Field><Field label="Domeny wyszukiwania"><input value={domains} onChange={(e) => setDomains(e.target.value)} /></Field></div><footer><button type="button" onClick={onClose}>Anuluj</button><button className="button-primary">Przejdź do planu</button></footer></form></Modal>;
}

function InterfacesPanel({ state, onChange }: { state: NetworkManagementState; onChange: (change: NetworkChange) => void }) {
  const [selected, setSelected] = useState("");
  const [editing, setEditing] = useState<NetworkInterfaceConfiguration | null | undefined>(undefined);
  const managed = state.managed.interfaces;
  const names = state.interfaces.map((item) => item.name);
  const current = state.interfaces.find((item) => item.name === selected);
  return <div className="network-management-stack">
    <div className="network-actionbar"><button className="button-primary" disabled={!state.provider.writable} onClick={() => setEditing(null)}><Plus />Utwórz</button><button disabled={!selected || !state.provider.writable} onClick={() => setEditing(managed[selected] || { ...newInterface(), name: selected })}><Edit3 />Edytuj</button><button disabled={!selected || !managed[selected] || !state.provider.writable} onClick={() => onChange({ operation: "delete_interface", interface_name: selected })}><Trash2 />Usuń</button><button disabled={!selected || !state.provider.writable} onClick={() => onChange({ operation: "set_link", interface_name: selected, link_up: current?.state !== "up" })}>{current?.state === "up" ? <Unlink /> : <Link2 />}{current?.state === "up" ? "Rozłącz" : "Połącz"}</button></div>
    <section className="network-management-card"><div className="monitor-table-wrap"><table><thead><tr><th>Nazwa</th><th>Stan</th><th>Rodzaj</th><th>Adresy</th><th>MTU</th><th>Konfiguracja</th></tr></thead><tbody>{state.interfaces.map((item) => <tr key={item.name} className={selected === item.name ? "selected" : ""} onClick={() => setSelected(item.name)}><td><strong>{item.name}</strong></td><td><span className={`network-status ${item.state}`}>{item.state}</span></td><td>{managed[item.name]?.kind || (item.system ? "systemowy" : "fizyczny")}</td><td>{item.addresses.map((address) => `${address.address}/${address.prefix_length}`).join(", ") || "—"}</td><td>{item.mtu || "—"}</td><td>{managed[item.name] ? "zarządzana" : "aktywna"}</td></tr>)}</tbody></table></div></section>
    {current && <section className="network-management-card network-selected-details"><header><div><h3>{current.name}</h3><p>Szczegóły wybranego interfejsu</p></div></header><dl><div><dt>MAC</dt><dd><code>{current.mac_address || "—"}</code></dd></div><div><dt>Carrier</dt><dd>{current.carrier === null ? "—" : current.carrier ? "tak" : "nie"}</dd></div><div><dt>Prędkość / duplex</dt><dd>{current.speed_mbps ? `${current.speed_mbps} Mb/s` : "—"} / {current.duplex || "—"}</dd></div><div><dt>Adresowanie</dt><dd>{managed[current.name]?.ipv4.method?.toUpperCase() || "stan aktywny"}</dd></div><div><dt>Nadrzędny</dt><dd>{managed[current.name]?.parent || "—"}</dd></div><div><dt>Członkowie</dt><dd>{managed[current.name]?.members.join(", ") || "—"}</dd></div></dl></section>}
    {editing !== undefined && <InterfaceForm initial={editing || undefined} available={names} onClose={() => setEditing(undefined)} onSubmit={(value) => { setEditing(undefined); onChange({ operation: "save_interface", interface: value }); }} />}
  </div>;
}

function RouteForm({ initial, interfaces, onClose, onSubmit }: { initial?: ManagedNetworkRoute; interfaces: string[]; onClose: () => void; onSubmit: (route: ManagedNetworkRoute) => void }) {
  const [value, setValue] = useState(initial || newRoute());
  return <Modal title={initial ? "Edytuj trasę" : "Nowa trasa statyczna"} onClose={onClose}><form onSubmit={(e) => { e.preventDefault(); onSubmit(value); }}><div className="network-form-grid">
    <Field label="Nazwa"><input required value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></Field><Field label="Rodzina"><select value={value.family} onChange={(e) => setValue({ ...value, family: e.target.value as "ipv4" | "ipv6" })}><option value="ipv4">IPv4</option><option value="ipv6">IPv6</option></select></Field>
    <Field label="Typ"><select value={value.route_type} onChange={(e) => setValue({ ...value, route_type: e.target.value as ManagedNetworkRoute["route_type"] })}>{["unicast", "blackhole", "unreachable", "prohibit"].map((v) => <option key={v}>{v}</option>)}</select></Field><Field label="Cel"><input required value={value.destination} onChange={(e) => setValue({ ...value, destination: e.target.value })} placeholder="192.0.2.0/24" /></Field>
    {value.route_type === "unicast" && <><Field label="Brama"><input value={value.gateway || ""} onChange={(e) => setValue({ ...value, gateway: e.target.value || null })} /></Field><Field label="Interfejs"><select value={value.interface || ""} onChange={(e) => setValue({ ...value, interface: e.target.value || null })}><option value="">Automatycznie</option>{interfaces.map((name) => <option key={name}>{name}</option>)}</select></Field></>}
    <Field label="Metryka"><input type="number" min={0} value={value.metric} onChange={(e) => setValue({ ...value, metric: Number(e.target.value) })} /></Field><Field label="Tabela"><input type="number" min={1} value={value.table} onChange={(e) => setValue({ ...value, table: Number(e.target.value) })} /></Field><Field label="Adres źródłowy"><input value={value.source || ""} onChange={(e) => setValue({ ...value, source: e.target.value || null })} /></Field><Field label="Aktywna"><input type="checkbox" checked={value.enabled} onChange={(e) => setValue({ ...value, enabled: e.target.checked })} /></Field><Field label="Odtwarzaj po starcie"><input type="checkbox" checked={value.autostart} onChange={(e) => setValue({ ...value, autostart: e.target.checked })} /></Field>
  </div><footer><button type="button" onClick={onClose}>Anuluj</button><button className="button-primary">Przejdź do planu</button></footer></form></Modal>;
}

export function RoutesPanel({ state, onChange }: { state: NetworkManagementState; onChange: (change: NetworkChange) => void }) {
  const [editing, setEditing] = useState<ManagedNetworkRoute | null | undefined>(undefined);
  const [family, setFamily] = useState<"all" | "ipv4" | "ipv6">("all");
  const managed = Object.values(state.managed.routes);
  const visible = managed.filter((route) => family === "all" || route.family === family);
  return <div className="network-management-stack"><div className="network-actionbar"><button className="button-primary" disabled={!state.provider.writable} onClick={() => setEditing(null)}><Plus />Dodaj trasę</button><label>Rodzina <select value={family} onChange={(e) => setFamily(e.target.value as typeof family)}><option value="all">IPv4 + IPv6</option><option value="ipv4">IPv4</option><option value="ipv6">IPv6</option></select></label></div>
    <section className="network-management-card"><header><div><h3>Trasy zarządzane</h3><p>Trwałe trasy zapisane przez panel.</p></div></header><div className="monitor-table-wrap"><table><thead><tr><th>Stan</th><th>Nazwa</th><th>Rodzina</th><th>Cel</th><th>Brama / typ</th><th>Interfejs</th><th>Metryka</th><th>Akcje</th></tr></thead><tbody>{visible.length ? visible.map((route) => <tr key={route.id || route.name}><td><input aria-label={`Włącz trasę ${route.name}`} type="checkbox" checked={route.enabled} onChange={() => onChange({ operation: "save_route", route: { ...route, enabled: !route.enabled } })} /></td><td>{route.name}</td><td>{route.family.toUpperCase()}</td><td><code>{route.destination}</code></td><td>{route.gateway || route.route_type}</td><td>{route.interface || "—"}</td><td>{route.metric}</td><td><button onClick={() => setEditing(route)}><Edit3 /></button><button onClick={() => onChange({ operation: "delete_route", object_id: route.id! })}><Trash2 /></button></td></tr>) : <tr><td colSpan={8}>Brak zarządzanych tras.</td></tr>}</tbody></table></div></section>
    <details className="network-management-card"><summary>Pełna aktywna tablica routingu ({state.routing.routes.length})</summary><div className="monitor-table-wrap"><table><thead><tr><th>Rodzina</th><th>Cel</th><th>Brama</th><th>Interfejs</th><th>Tabela</th></tr></thead><tbody>{state.routing.routes.map((route, index) => <tr key={`${route.family}-${route.destination}-${index}`}><td>{route.family}</td><td><code>{route.destination}</code></td><td>{route.gateway || "—"}</td><td>{route.device || "—"}</td><td>{route.table}</td></tr>)}</tbody></table></div></details>
    {editing !== undefined && <RouteForm initial={editing || undefined} interfaces={state.interfaces.map((item) => item.name)} onClose={() => setEditing(undefined)} onSubmit={(route) => { setEditing(undefined); onChange({ operation: "save_route", route }); }} />}
  </div>;
}

function TrafficForm({ initial, interfaces, onClose, onSubmit }: { initial?: NetworkTrafficRule; interfaces: string[]; onClose: () => void; onSubmit: (rule: NetworkTrafficRule) => void }) {
  const [value, setValue] = useState(initial || { ...newTraffic(), interface: interfaces[0] || "" });
  return <Modal title={initial ? "Edytuj regułę ruchu" : "Nowa reguła ruchu"} onClose={onClose}><form onSubmit={(e) => { e.preventDefault(); onSubmit(value); }}><div className="network-form-grid">
    <Field label="Nazwa"><input required value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></Field><Field label="Interfejs"><select required value={value.interface} onChange={(e) => setValue({ ...value, interface: e.target.value })}>{interfaces.map((name) => <option key={name}>{name}</option>)}</select></Field>
    <Field label="Kierunek"><select value={value.direction} onChange={(e) => setValue({ ...value, direction: e.target.value as "egress" | "ingress" })}><option value="egress">Wychodzący</option><option value="ingress">Przychodzący</option></select></Field><Field label="Protokół"><select value={value.protocol} onChange={(e) => setValue({ ...value, protocol: e.target.value as NetworkTrafficRule["protocol"] })}><option value="any">Dowolny</option><option value="tcp">TCP</option><option value="udp">UDP</option></select></Field>
    <Field label="Gwarantowane (kbit/s)"><input type="number" min={1} value={value.guaranteed_kbit} onChange={(e) => setValue({ ...value, guaranteed_kbit: Number(e.target.value) })} /></Field><Field label="Maksymalne (kbit/s)"><input type="number" min={1} value={value.maximum_kbit} onChange={(e) => setValue({ ...value, maximum_kbit: Number(e.target.value) })} /></Field>
    <Field label="Źródło CIDR"><input value={value.source_cidr || ""} onChange={(e) => setValue({ ...value, source_cidr: e.target.value || null })} /></Field><Field label="Cel CIDR"><input value={value.destination_cidr || ""} onChange={(e) => setValue({ ...value, destination_cidr: e.target.value || null })} /></Field>
    {value.protocol !== "any" && <><Field label="Port źródłowy"><input type="number" min={1} max={65535} value={value.source_port || ""} onChange={(e) => setValue({ ...value, source_port: Number(e.target.value) || null })} /></Field><Field label="Port docelowy"><input type="number" min={1} max={65535} value={value.destination_port || ""} onChange={(e) => setValue({ ...value, destination_port: Number(e.target.value) || null })} /></Field></>}
    <Field label="Priorytet"><input type="number" min={1} max={100} value={value.priority} onChange={(e) => setValue({ ...value, priority: Number(e.target.value) })} /></Field><Field label="Reguła aktywna"><input type="checkbox" checked={value.enabled} onChange={(e) => setValue({ ...value, enabled: e.target.checked })} /></Field>
  </div><footer><button type="button" onClick={onClose}>Anuluj</button><button className="button-primary">Przejdź do planu</button></footer></form></Modal>;
}

export function TrafficPanel({ state, onChange }: { state: NetworkManagementState; onChange: (change: NetworkChange) => void }) {
  const [editing, setEditing] = useState<NetworkTrafficRule | null | undefined>(undefined);
  const rules = Object.values(state.managed.traffic);
  return <div className="network-management-stack"><div className="network-actionbar"><button className="button-primary" disabled={!state.provider.writable || !state.tools.tc} onClick={() => setEditing(null)}><Plus />Dodaj regułę</button>{!state.tools.tc && <span>Brak narzędzia tc.</span>}</div>
    <section className="network-management-card"><div className="monitor-table-wrap"><table><thead><tr><th>Stan</th><th>Nazwa</th><th>Interfejs</th><th>Kierunek</th><th>Filtr</th><th>Minimum</th><th>Maksimum</th><th>Priorytet</th><th>Akcje</th></tr></thead><tbody>{rules.length ? rules.map((rule) => <tr key={rule.id || rule.name}><td><input aria-label={`Włącz regułę ${rule.name}`} type="checkbox" checked={rule.enabled} onChange={() => onChange({ operation: "save_traffic", traffic: { ...rule, enabled: !rule.enabled } })} /></td><td>{rule.name}</td><td>{rule.interface}</td><td>{rule.direction}</td><td>{[rule.protocol, rule.source_cidr, rule.destination_cidr].filter(Boolean).join(" · ")}</td><td>{rule.guaranteed_kbit} kbit/s</td><td>{rule.maximum_kbit} kbit/s</td><td>{rule.priority}</td><td><button onClick={() => setEditing(rule)}><Edit3 /></button><button onClick={() => onChange({ operation: "delete_traffic", object_id: rule.id! })}><Trash2 /></button></td></tr>) : <tr><td colSpan={9}>Brak reguł kontroli ruchu.</td></tr>}</tbody></table></div></section>
    {editing !== undefined && <TrafficForm initial={editing || undefined} interfaces={state.interfaces.map((item) => item.name)} onClose={() => setEditing(undefined)} onSubmit={(traffic) => { setEditing(undefined); onChange({ operation: "save_traffic", traffic }); }} />}
  </div>;
}

function PlanModal({ plan, busy, error, onClose, onApply }: { plan: NetworkPlan; busy: boolean; error: string; onClose: () => void; onApply: (phrase: string) => void }) {
  const [phrase, setPhrase] = useState("");
  return <Modal title="Podgląd planu zmian" onClose={onClose}><div className="network-plan">
    <div className={`network-risk ${plan.high_risk ? "high" : "normal"}`}><ShieldAlert /><div><strong>{plan.high_risk ? "Zmiana wysokiego ryzyka" : "Plan gotowy"}</strong><p>Cel: {plan.target}. Automatyczny rollback po {plan.rollback_seconds} s.</p></div></div>
    {plan.warnings.length > 0 && <ul>{plan.warnings.map((warning) => <li key={warning}><AlertTriangle />{warning}</li>)}</ul>}
    <details open><summary>Polecenia ({plan.commands.length})</summary><pre>{plan.commands.map((command) => command.join(" ")).join("\n") || "Zmiana stanu zarządzanego"}</pre></details>
    <details><summary>Stan przed i po</summary><pre>{JSON.stringify({ before: plan.before, after: plan.after }, null, 2)}</pre></details>
    {plan.high_risk && <Field label={`Wpisz dokładnie: ${plan.required_phrase}`}><input autoFocus value={phrase} onChange={(e) => setPhrase(e.target.value)} /></Field>}
    {error && <p className="error-state" role="alert">{error}</p>}
  </div><footer><button type="button" onClick={onClose}>Anuluj</button><button className="button-primary" disabled={busy || plan.high_risk && phrase !== plan.required_phrase} onClick={() => onApply(phrase)}>{busy ? "Stosowanie…" : "Zastosuj plan"}</button></footer></Modal>;
}

function TransactionBanner({ transaction, busy, onConfirm, onRollback }: { transaction: NetworkTransaction; busy: boolean; onConfirm: () => void; onRollback: () => void }) {
  const [now, setNow] = useState(transaction.started_at);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000); return () => window.clearInterval(timer); }, []);
  const left = Math.max(0, Math.ceil(transaction.deadline - now));
  return <aside className="network-transaction-banner" role="status"><RefreshCw /><div><strong>Sprawdź połączenie — rollback za {left} s</strong><p>Zmiany pozostaną tylko po potwierdzeniu.</p></div><button disabled={busy} onClick={onRollback}>Cofnij teraz</button><button className="button-primary" disabled={busy} onClick={onConfirm}><CheckCircle2 />Zachowaj zmiany</button></aside>;
}

export function NetworkManagementWorkspace({ tab, t, onNavigate }: { tab: "general" | "interfaces" | "traffic" | "routes"; t: Translate; onNavigate: (tab: "interfaces" | "routes" | "connectivity") => void }) {
  const [state, setState] = useState<NetworkManagementState | null>(null);
  const [plan, setPlan] = useState<NetworkPlan | null>(null);
  const [transaction, setTransaction] = useState<NetworkTransaction | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    setError("");
    try { const next = await api.networkManagement(); setState(next); setTransaction(next.transaction); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setLoading(false); }
  }, [t]);
  useEffect(() => { void refresh(); }, [refresh]);
  async function prepare(change: NetworkChange) {
    setBusy(true); setError("");
    try { setPlan(await api.planNetworkChange(change)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setBusy(false); }
  }
  async function apply(phrase: string) {
    if (!plan) return;
    setBusy(true); setError("");
    try { const next = await api.applyNetworkPlan(plan.id, phrase); setPlan(null); await refresh(); setTransaction(next); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setBusy(false); }
  }
  async function finish(action: "confirm" | "rollback") {
    if (!transaction) return;
    setBusy(true); setError("");
    try {
      if (action === "confirm") await api.confirmNetworkTransaction(transaction.id);
      else await api.rollbackNetworkTransaction(transaction.id);
      setTransaction(null); await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setBusy(false); }
  }
  if (loading) return <div className="loading-state">{t("status.loading")}</div>;
  if (!state) return <p className="error-state" role="alert">{error}</p>;
  return <div className="network-management-workspace">
    {transaction?.state === "pending_confirmation" && <TransactionBanner transaction={transaction} busy={busy} onConfirm={() => void finish("confirm")} onRollback={() => void finish("rollback")} />}
    {error && !plan && <p className="error-state" role="alert">{error}</p>}
    <div className="network-management-heading"><div><Globe2 /><span><strong>{state.hostname}</strong><small>{state.provider.id} · {state.provider.writable ? "zapis dostępny" : "tylko odczyt"}</small></span></div><button onClick={() => void refresh()}><RefreshCw />Odśwież</button></div>
    {tab === "general" && <GeneralPanel state={state} onChange={(change) => void prepare(change)} onNavigate={onNavigate} />}
    {tab === "interfaces" && <InterfacesPanel state={state} onChange={(change) => void prepare(change)} />}
    {tab === "routes" && <RoutesPanel state={state} onChange={(change) => void prepare(change)} />}
    {tab === "traffic" && <TrafficPanel state={state} onChange={(change) => void prepare(change)} />}
    {plan && <PlanModal plan={plan} busy={busy} error={error} onClose={() => { setPlan(null); setError(""); }} onApply={(phrase) => void apply(phrase)} />}
  </div>;
}
