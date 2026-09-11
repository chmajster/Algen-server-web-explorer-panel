import { AlertTriangle, CheckCircle2, Edit3, Globe2, Link2, Plus, RefreshCw, ShieldAlert, Trash2, Unlink } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import {
  api,
  setApiBaseUrl,
  type ManagedNetworkRoute,
  type NetworkChange,
  type NetworkInterfaceConfiguration,
  type NetworkManagementState,
  type NetworkPlan,
  type NetworkTrafficRule,
  type NetworkTransaction,
} from "../../api";
import type { Translate } from "../../app/types";

const NETWORK_COPY_EN: Record<string, string> = {
  "Zamknij": "Close",
  "Edytuj interfejs": "Edit interface",
  "Nowy interfejs": "New interface",
  "Łącze": "Link",
  "Rodzaj": "Type",
  "Fizyczny": "Physical",
  "Nazwa": "Name",
  "Uruchamiaj automatycznie": "Start automatically",
  "Interfejs nadrzędny": "Parent interface",
  "Wybierz": "Select",
  "Porty składowe": "Member ports",
  "Interfejs primary": "Primary interface",
  "Automatycznie": "Automatically",
  "Metoda": "Method",
  "Wyłączone": "Disabled",
  "Ręcznie": "Manually",
  "Adresy CIDR (po przecinku)": "CIDR addresses (comma-separated)",
  "Brama": "Gateway",
  "Metryka": "Metric",
  "DNS (po przecinku)": "DNS (comma-separated)",
  "Domeny wyszukiwania": "Search domains",
  "Trasa domyślna": "Default route",
  "Ignoruj automatyczne trasy": "Ignore automatic routes",
  "Ignoruj automatyczne DNS": "Ignore automatic DNS",
  "Anuluj": "Cancel",
  "Przejdź do planu": "Continue to plan",
  "Aktywne interfejsy": "Active interfaces",
  "Brama domyślna": "Default gateway",
  "Brak": "None",
  "serwerów": "servers",
  "Konfiguruj interfejsy": "Configure interfaces",
  "Konfiguruj DNS": "Configure DNS",
  "Dodaj trasę": "Add route",
  "Testuj łączność": "Test connectivity",
  "Tryb tylko do odczytu": "Read-only mode",
  "Nie wykryto jednoznacznego, obsługiwanego menedżera sieci.": "No unambiguous supported network manager was detected.",
  "Stan efektywny": "Effective state",
  "Aktualna konfiguracja odczytana z systemu.": "Current configuration read from the system.",
  "Domyślna trasa IPv4": "Default IPv4 route",
  "Domyślna trasa IPv6": "Default IPv6 route",
  "Łączność podstawowa": "Basic connectivity",
  "aktywny": "active",
  "niedostępny": "unavailable",
  "gotowa": "ready",
  "ograniczona": "limited",
  "Automatyczny rollback": "Automatic rollback",
  "brak oczekującej zmiany": "no pending change",
  "aktywny do": "active until",
  "Konfiguracja DNS": "DNS configuration",
  "Serwery globalne i domeny wyszukiwania.": "Global servers and search domains.",
  "Serwery DNS": "DNS servers",
  "Serwery": "Servers",
  "Usuń serwer DNS": "Remove DNS server",
  "Dodaj serwer DNS": "Add DNS server",
  "Domeny": "Domains",
  "Utwórz": "Create",
  "Edytuj": "Edit",
  "Usuń": "Delete",
  "Rozłącz": "Disconnect",
  "Połącz": "Connect",
  "Stan": "State",
  "Adresy": "Addresses",
  "Konfiguracja": "Configuration",
  "systemowy": "system",
  "fizyczny": "physical",
  "zarządzana": "managed",
  "aktywna": "active",
  "Szczegóły wybranego interfejsu": "Selected interface details",
  "tak": "yes",
  "nie": "no",
  "Prędkość / duplex": "Speed / duplex",
  "Adresowanie": "Addressing",
  "stan aktywny": "active state",
  "Nadrzędny": "Parent",
  "Członkowie": "Members",
  "Edytuj trasę": "Edit route",
  "Nowa trasa statyczna": "New static route",
  "Rodzina": "Family",
  "Cel": "Destination",
  "Brama / typ": "Gateway / type",
  "Interfejs": "Interface",
  "Tabela": "Table",
  "Adres źródłowy": "Source address",
  "Odtwarzaj po starcie": "Restore at startup",
  "Trasy zarządzane": "Managed routes",
  "Trwałe trasy zapisane przez panel.": "Persistent routes saved by the panel.",
  "Włącz trasę": "Enable route",
  "Akcje": "Actions",
  "Brak zarządzanych tras.": "No managed routes.",
  "Pełna aktywna tablica routingu": "Full active routing table",
  "Edytuj regułę ruchu": "Edit traffic rule",
  "Nowa reguła ruchu": "New traffic rule",
  "Kierunek": "Direction",
  "Wychodzący": "Outbound",
  "Przychodzący": "Inbound",
  "Protokół": "Protocol",
  "Dowolny": "Any",
  "Gwarantowane (kbit/s)": "Guaranteed (kbit/s)",
  "Maksymalne (kbit/s)": "Maximum (kbit/s)",
  "Źródło CIDR": "Source CIDR",
  "Cel CIDR": "Destination CIDR",
  "Port źródłowy": "Source port",
  "Port docelowy": "Destination port",
  "Priorytet": "Priority",
  "Reguła aktywna": "Rule enabled",
  "Dodaj regułę": "Add rule",
  "Brak narzędzia tc.": "The tc tool is unavailable.",
  "Filtr": "Filter",
  "Minimum": "Minimum",
  "Maksimum": "Maximum",
  "Włącz regułę": "Enable rule",
  "Brak reguł kontroli ruchu.": "No traffic control rules.",
  "Podgląd planu zmian": "Change plan preview",
  "Plan gotowy": "Plan ready",
  "Zmiana wysokiego ryzyka": "High-risk change",
  "Brak trwałego mechanizmu rollbacku systemd. Zastosowanie planu jest zablokowane.": "A persistent systemd rollback mechanism is unavailable. Applying the plan is blocked.",
  "Stan przed i po": "Before and after",
  "Polecenia": "Commands",
  "Zmiana stanu zarządzanego": "Managed state change",
  "Wpisz dokładnie": "Enter exactly",
  "Stosowanie…": "Applying…",
  "Zastosuj plan": "Apply plan",
  "Konfiguracja zachowana": "Configuration kept",
  "Przywrócono poprzednią konfigurację": "Previous configuration restored",
  "Nie udało się potwierdzić przed upływem czasu": "Confirmation timed out",
  "Trwa przywracanie poprzedniej konfiguracji": "Restoring previous configuration",
  "Wysyłanie potwierdzenia": "Sending confirmation",
  "Utracono połączenie — trwa ponowne łączenie": "Connection lost — reconnecting",
  "Oczekiwanie na potwierdzenie": "Waiting for confirmation",
  "Nowa konfiguracja sieci oczekuje na potwierdzenie. Automatyczne przywrócenie za": "The new network configuration is awaiting confirmation. Automatic rollback in",
  "Przywróć teraz": "Restore now",
  "Zachowaj konfigurację": "Keep configuration",
  "zapis dostępny": "writable",
  "tylko odczyt": "read-only",
  "Odśwież": "Refresh",
  "Brak uprawnienia do modyfikacji konfiguracji sieci.": "You do not have permission to modify network configuration.",
  "Automatyczny rollback po": "Automatic rollback after",
  "z": "of",
  "Most": "Bridge",
  "Tryb bond": "Bond mode",
  "Aktywna": "Enabled"
} as const;

function networkText(polish: string) {
  const configured = typeof localStorage !== "undefined" ? localStorage.getItem("webnas_language") : null;
  return configured === "en-US" ? NETWORK_COPY_EN[polish] || polish : polish;
}

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
      if (root?.hidden) return;
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
      <header><h3>{title}</h3><button type="button" onClick={onClose} aria-label={networkText("Zamknij")}>×</button></header>
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
  return <Modal title={initial ? networkText("Edytuj interfejs") : networkText("Nowy interfejs")} onClose={onClose}>
    <form onSubmit={submit}>
      <nav className="network-form-tabs">{(["link", "ipv4", "ipv6"] as const).map((item) => <button type="button" className={section === item ? "active" : ""} onClick={() => setSection(item)} key={item}>{item === "link" ? networkText("Łącze") : item.toUpperCase()}</button>)}</nav>
      <div className="network-form-grid">
        {section === "link" && <>
          <Field label={networkText("Rodzaj")}><select value={value.kind} onChange={(e) => setValue({ ...value, kind: e.target.value as NetworkInterfaceConfiguration["kind"] })}><option value="physical">{networkText("Fizyczny")}</option><option value="bond">Bond</option><option value="vlan">VLAN</option><option value="bridge">{networkText("Most")}</option></select></Field>
          <Field label={networkText("Nazwa")}><input required maxLength={15} pattern="[A-Za-z0-9_.:-]+" value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></Field>
          <Field label="MTU"><input type="number" min={576} max={9216} value={value.mtu} onChange={(e) => setValue({ ...value, mtu: Number(e.target.value) })} /></Field>
          <Field label={networkText("Uruchamiaj automatycznie")}><input type="checkbox" checked={value.autostart} onChange={(e) => setValue({ ...value, autostart: e.target.checked })} /></Field>
          {value.kind === "vlan" && <><Field label={networkText("Interfejs nadrzędny")}><select required value={value.parent || ""} onChange={(e) => setValue({ ...value, parent: e.target.value })}><option value="">{networkText("Wybierz")}</option>{available.map((name) => <option key={name}>{name}</option>)}</select></Field><Field label="VLAN ID"><input required type="number" min={1} max={4094} value={value.vlan_id || ""} onChange={(e) => setValue({ ...value, vlan_id: Number(e.target.value) })} /></Field></>}
          {(value.kind === "bond" || value.kind === "bridge") && <Field label={networkText("Porty składowe")}><select multiple value={value.members} onChange={(e) => setValue({ ...value, members: Array.from(e.target.selectedOptions, (option) => option.value) })}>{available.filter((name) => name !== value.name).map((name) => <option key={name}>{name}</option>)}</select></Field>}
          {value.kind === "bond" && <><Field label={networkText("Tryb bond")}><select value={value.bond_mode} onChange={(e) => setValue({ ...value, bond_mode: e.target.value as NetworkInterfaceConfiguration["bond_mode"] })}>{["active-backup", "balance-rr", "balance-xor", "broadcast", "802.3ad", "balance-tlb", "balance-alb"].map((mode) => <option key={mode}>{mode}</option>)}</select></Field><Field label="miimon (ms)"><input type="number" min={0} max={10000} value={value.miimon} onChange={(e) => setValue({ ...value, miimon: Number(e.target.value) })} /></Field></>}
          {value.kind === "bond" && <><Field label={networkText("Interfejs primary")}><select disabled={value.bond_mode !== "active-backup"} value={value.primary || ""} onChange={(e) => setValue({ ...value, primary: e.target.value || null })}><option value="">{networkText("Automatycznie")}</option>{value.members.map((name) => <option key={name}>{name}</option>)}</select></Field><Field label="updelay / downdelay (ms)"><span className="network-inline-inputs"><input type="number" min={0} value={value.updelay} onChange={(e) => setValue({ ...value, updelay: Number(e.target.value) })} /><input type="number" min={0} value={value.downdelay} onChange={(e) => setValue({ ...value, downdelay: Number(e.target.value) })} /></span></Field><Field label="LACP rate"><select disabled={value.bond_mode !== "802.3ad"} value={value.lacp_rate} onChange={(e) => setValue({ ...value, lacp_rate: e.target.value as "slow" | "fast" })}><option value="slow">slow</option><option value="fast">fast</option></select></Field><Field label="Hash policy"><select value={value.xmit_hash_policy} onChange={(e) => setValue({ ...value, xmit_hash_policy: e.target.value as NetworkInterfaceConfiguration["xmit_hash_policy"] })}>{["layer2", "layer2+3", "layer3+4"].map((item) => <option key={item}>{item}</option>)}</select></Field></>}
          {value.kind === "bridge" && <Field label="STP"><input type="checkbox" checked={value.stp} onChange={(e) => setValue({ ...value, stp: e.target.checked })} /></Field>}
        </>}
        {(section === "ipv4" || section === "ipv6") && (() => {
          const ip = value[section];
          return <>
            <Field label={networkText("Metoda")}><select value={ip.method} onChange={(e) => updateIp(section, { method: e.target.value as typeof ip.method })}><option value="disabled">{networkText("Wyłączone")}</option>{section === "ipv4" ? <option value="dhcp">DHCP</option> : <><option value="slaac">SLAAC</option><option value="dhcpv6">DHCPv6</option></>}<option value="manual">{networkText("Ręcznie")}</option></select></Field>
            {ip.method === "manual" && <><Field label={networkText("Adresy CIDR (po przecinku)")}><input required placeholder={section === "ipv4" ? "192.0.2.10/24" : "2001:db8::10/64"} value={ip.addresses.map((item) => `${item.address}/${item.prefix}`).join(", ")} onChange={(e) => updateIp(section, { addresses: e.target.value.split(",").map((item) => item.trim()).filter((item) => item.includes("/")).map((item) => { const [rawAddress, rawPrefix] = item.split("/", 2); return { address: rawAddress, prefix: Number(rawPrefix) }; }) })} /></Field><Field label={networkText("Brama")}><input value={ip.gateway || ""} onChange={(e) => updateIp(section, { gateway: e.target.value || null })} /></Field></>}
            <Field label={networkText("Metryka")}><input type="number" min={0} max={4294967295} value={ip.metric} onChange={(e) => updateIp(section, { metric: Number(e.target.value) })} /></Field>
            <Field label={networkText("DNS (po przecinku)")}><input value={ip.dns.join(", ")} onChange={(e) => updateIp(section, { dns: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></Field>
            <Field label={networkText("Domeny wyszukiwania")}><input value={ip.search_domains.join(", ")} onChange={(e) => updateIp(section, { search_domains: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></Field>
            <Field label={networkText("Trasa domyślna")}><input type="checkbox" checked={ip.default_route} onChange={(e) => updateIp(section, { default_route: e.target.checked })} /></Field>
            <Field label={networkText("Ignoruj automatyczne trasy")}><input type="checkbox" checked={ip.ignore_auto_routes} onChange={(e) => updateIp(section, { ignore_auto_routes: e.target.checked })} /></Field>
            <Field label={networkText("Ignoruj automatyczne DNS")}><input type="checkbox" checked={ip.ignore_auto_dns} onChange={(e) => updateIp(section, { ignore_auto_dns: e.target.checked })} /></Field>
            {section === "ipv6" && <Field label="Privacy extensions"><input type="checkbox" checked={ip.privacy_extensions} onChange={(e) => updateIp(section, { privacy_extensions: e.target.checked })} /></Field>}
          </>;
        })()}
      </div>
      <footer><button type="button" onClick={onClose}>{networkText("Anuluj")}</button><button className="button-primary" type="submit">{networkText("Przejdź do planu")}</button></footer>
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
      <article><span>{networkText("Aktywne interfejsy")}</span><strong>{state.interfaces.filter((item) => item.state === "up").length}</strong><small>{networkText("z")} {state.interfaces.length}</small></article>
      <article><span>{networkText("Brama domyślna")}</span><strong>{defaults[0]?.address || "—"}</strong><small>{defaults[0]?.device || networkText("Brak")}</small></article>
      <article><span>DNS</span><strong>{dnsServers[0] || "—"}</strong><small>{dnsServers.length} {networkText("serwerów")}</small></article>
    </section>
    <div className="network-actionbar"><button onClick={() => onNavigate("interfaces")}>{networkText("Konfiguruj interfejsy")}</button><button onClick={() => setDnsOpen(true)}>{networkText("Konfiguruj DNS")}</button><button onClick={() => onNavigate("routes")}>{networkText("Dodaj trasę")}</button><button onClick={() => onNavigate("connectivity")}>{networkText("Testuj łączność")}</button></div>
    {!state.provider.writable && <div className="network-provider-warning"><ShieldAlert /><div><strong>{networkText("Tryb tylko do odczytu")}</strong><p>{state.provider.warnings.join(" ") || networkText("Nie wykryto jednoznacznego, obsługiwanego menedżera sieci.")}</p></div></div>}
    <section className="network-management-card"><header><div><h3>{networkText("Stan efektywny")}</h3><p>{networkText("Aktualna konfiguracja odczytana z systemu.")}</p></div></header><dl><div><dt>{networkText("Domyślna trasa IPv4")}</dt><dd>{defaults.find((item) => item.family === "ipv4")?.address || "—"}</dd></div><div><dt>{networkText("Domyślna trasa IPv6")}</dt><dd>{defaults.find((item) => item.family === "ipv6")?.address || "—"}</dd></div><div><dt>{networkText("Domeny wyszukiwania")}</dt><dd>{(state.managed.dns?.search_domains || state.dns.resolv_conf.search).join(", ") || "—"}</dd></div><div><dt>systemd-resolved</dt><dd>{state.dns.systemd_resolved.available ? networkText("aktywny") : networkText("niedostępny")}</dd></div><div><dt>{networkText("Łączność podstawowa")}</dt><dd>{state.interfaces.some((item) => item.state === "up" && !item.system) && defaults.length ? networkText("gotowa") : networkText("ograniczona")}</dd></div><div><dt>{networkText("Automatyczny rollback")}</dt><dd>{state.transaction ? `${networkText("aktywny do")} ${new Date(state.transaction.deadline * 1000).toLocaleTimeString()}` : networkText("brak oczekującej zmiany")}</dd></div></dl></section>
    <section className="network-management-card"><header><div><h3>{networkText("Konfiguracja DNS")}</h3><p>{networkText("Serwery globalne i domeny wyszukiwania.")}</p></div><button type="button" disabled={!state.provider.writable} onClick={() => setDnsOpen(true)}><Edit3 />{networkText("Edytuj")}</button></header><dl><div><dt>{networkText("Serwery")}</dt><dd>{dnsServers.join(", ") || "—"}</dd></div><div><dt>{networkText("Domeny")}</dt><dd>{(state.managed.dns?.search_domains || state.dns.resolv_conf.search).join(", ") || "—"}</dd></div></dl></section>
    {dnsOpen && <DnsForm state={state} onClose={() => setDnsOpen(false)} onSubmit={(dns) => { setDnsOpen(false); onChange({ operation: "save_dns", dns }); }} />}
  </div>;
}

function DnsForm({ state, onClose, onSubmit }: { state: NetworkManagementState; onClose: () => void; onSubmit: (dns: NonNullable<NetworkManagementState["managed"]["dns"]>) => void }) {
  const effectiveServers = state.managed.dns?.servers?.length
    ? state.managed.dns.servers
    : state.dns.systemd_resolved.global_servers.length
      ? state.dns.systemd_resolved.global_servers
      : state.dns.resolv_conf.nameservers;
  const [servers, setServers] = useState<string[]>(() => effectiveServers.length ? [...effectiveServers] : [""]);
  const [domains, setDomains] = useState((state.managed.dns?.search_domains || state.dns.resolv_conf.search).join(", "));
  const updateServer = (index: number, value: string) => setServers((current) => current.map((server, currentIndex) => currentIndex === index ? value : server));
  const removeServer = (index: number) => setServers((current) => current.length > 1 ? current.filter((_, currentIndex) => currentIndex !== index) : current);
  const addServer = () => setServers((current) => [...current, ""]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const parsed = [...new Set(servers.map((value) => value.trim()).filter(Boolean))];
    if (!parsed.length) return;
    onSubmit({
      automatic: false,
      servers: parsed,
      search_domains: domains.split(",").map((value) => value.trim()).filter(Boolean),
      routing_domains: [],
      per_interface: Object.fromEntries(state.interfaces.filter((item) => !item.system).map((item) => [item.name, parsed])),
      priority: 100,
      ignore_dhcp: true,
    });
  };
  return <Modal title={networkText("Konfiguracja DNS")} onClose={onClose}><form onSubmit={submit}><div className="network-form-grid">
    <div className="network-form-field"><span>{networkText("Serwery DNS")}</span><div className="network-management-stack">
      {servers.map((server, index) => <div className="network-inline-inputs" key={index}>
        <input aria-label={`Serwer DNS ${index + 1}`} required value={server} onChange={(event) => updateServer(index, event.target.value)} placeholder={index === 0 ? "1.1.1.1" : "8.8.8.8"} />
        <button type="button" aria-label={`${networkText("Usuń serwer DNS")} ${index + 1}`} disabled={servers.length === 1} onClick={() => removeServer(index)}><Trash2 aria-hidden="true" /></button>
      </div>)}
      <button type="button" onClick={addServer}><Plus aria-hidden="true" />{networkText("Dodaj serwer DNS")}</button>
    </div></div>
    <Field label={networkText("Domeny wyszukiwania")}><input value={domains} onChange={(event) => setDomains(event.target.value)} /></Field>
  </div><footer><button type="button" onClick={onClose}>{networkText("Anuluj")}</button><button className="button-primary">{networkText("Przejdź do planu")}</button></footer></form></Modal>;
}

function InterfacesPanel({ state, onChange }: { state: NetworkManagementState; onChange: (change: NetworkChange) => void }) {
  const [selected, setSelected] = useState("");
  const [editing, setEditing] = useState<NetworkInterfaceConfiguration | null | undefined>(undefined);
  const managed = state.managed.interfaces;
  const names = state.interfaces.map((item) => item.name);
  const current = state.interfaces.find((item) => item.name === selected);
  return <div className="network-management-stack">
    <div className="network-actionbar"><button className="button-primary" disabled={!state.provider.writable} onClick={() => setEditing(null)}><Plus />{networkText("Utwórz")}</button><button disabled={!selected || !state.provider.writable} onClick={() => setEditing(managed[selected] || { ...newInterface(), name: selected })}><Edit3 />{networkText("Edytuj")}</button><button disabled={!selected || !managed[selected] || !state.provider.writable} onClick={() => onChange({ operation: "delete_interface", interface_name: selected })}><Trash2 />{networkText("Usuń")}</button><button disabled={!selected || !state.provider.writable} onClick={() => onChange({ operation: "set_link", interface_name: selected, link_up: current?.state !== "up" })}>{current?.state === "up" ? <Unlink /> : <Link2 />}{current?.state === "up" ? networkText("Rozłącz") : networkText("Połącz")}</button></div>
    <section className="network-management-card"><div className="monitor-table-wrap"><table><thead><tr><th>{networkText("Nazwa")}</th><th>{networkText("Stan")}</th><th>{networkText("Rodzaj")}</th><th>{networkText("Adresy")}</th><th>MTU</th><th>{networkText("Konfiguracja")}</th></tr></thead><tbody>{state.interfaces.map((item) => <tr key={item.name} className={selected === item.name ? "selected" : ""} onClick={() => setSelected(item.name)}><td><strong>{item.name}</strong></td><td><span className={`network-status ${item.state}`}>{item.state}</span></td><td>{managed[item.name]?.kind || (item.system ? networkText("systemowy") : networkText("fizyczny"))}</td><td>{item.addresses.map((address) => `${address.address}/${address.prefix_length}`).join(", ") || "—"}</td><td>{item.mtu || "—"}</td><td>{managed[item.name] ? networkText("zarządzana") : networkText("aktywna")}</td></tr>)}</tbody></table></div></section>
    {current && <section className="network-management-card network-selected-details"><header><div><h3>{current.name}</h3><p>{networkText("Szczegóły wybranego interfejsu")}</p></div></header><dl><div><dt>MAC</dt><dd><code>{current.mac_address || "—"}</code></dd></div><div><dt>Carrier</dt><dd>{current.carrier === null ? "—" : current.carrier ? networkText("tak") : networkText("nie")}</dd></div><div><dt>{networkText("Prędkość / duplex")}</dt><dd>{current.speed_mbps ? `${current.speed_mbps} Mb/s` : "—"} / {current.duplex || "—"}</dd></div><div><dt>{networkText("Adresowanie")}</dt><dd>{managed[current.name]?.ipv4.method?.toUpperCase() || networkText("stan aktywny")}</dd></div><div><dt>{networkText("Nadrzędny")}</dt><dd>{managed[current.name]?.parent || "—"}</dd></div><div><dt>{networkText("Członkowie")}</dt><dd>{managed[current.name]?.members.join(", ") || "—"}</dd></div></dl></section>}
    {editing !== undefined && <InterfaceForm initial={editing || undefined} available={names} onClose={() => setEditing(undefined)} onSubmit={(value) => { setEditing(undefined); onChange({ operation: "save_interface", interface: value }); }} />}
  </div>;
}

function RouteForm({ initial, interfaces, onClose, onSubmit }: { initial?: ManagedNetworkRoute; interfaces: string[]; onClose: () => void; onSubmit: (route: ManagedNetworkRoute) => void }) {
  const [value, setValue] = useState(initial || newRoute());
  return <Modal title={initial ? networkText("Edytuj trasę") : networkText("Nowa trasa statyczna")} onClose={onClose}><form onSubmit={(e) => { e.preventDefault(); onSubmit(value); }}><div className="network-form-grid">
    <Field label={networkText("Nazwa")}><input required value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></Field><Field label={networkText("Rodzina")}><select value={value.family} onChange={(e) => setValue({ ...value, family: e.target.value as "ipv4" | "ipv6" })}><option value="ipv4">IPv4</option><option value="ipv6">IPv6</option></select></Field>
    <Field label="Typ"><select value={value.route_type} onChange={(e) => setValue({ ...value, route_type: e.target.value as ManagedNetworkRoute["route_type"] })}>{["unicast", "blackhole", "unreachable", "prohibit"].map((v) => <option key={v}>{v}</option>)}</select></Field><Field label={networkText("Cel")}><input required value={value.destination} onChange={(e) => setValue({ ...value, destination: e.target.value })} placeholder="192.0.2.0/24" /></Field>
    {value.route_type === "unicast" && <><Field label={networkText("Brama")}><input value={value.gateway || ""} onChange={(e) => setValue({ ...value, gateway: e.target.value || null })} /></Field><Field label={networkText("Interfejs")}><select value={value.interface || ""} onChange={(e) => setValue({ ...value, interface: e.target.value || null })}><option value="">{networkText("Automatycznie")}</option>{interfaces.map((name) => <option key={name}>{name}</option>)}</select></Field></>}
    <Field label={networkText("Metryka")}><input type="number" min={0} value={value.metric} onChange={(e) => setValue({ ...value, metric: Number(e.target.value) })} /></Field><Field label={networkText("Tabela")}><input type="number" min={1} value={value.table} onChange={(e) => setValue({ ...value, table: Number(e.target.value) })} /></Field><Field label={networkText("Adres źródłowy")}><input value={value.source || ""} onChange={(e) => setValue({ ...value, source: e.target.value || null })} /></Field><Field label={networkText("Aktywna")}><input type="checkbox" checked={value.enabled} onChange={(e) => setValue({ ...value, enabled: e.target.checked })} /></Field><Field label={networkText("Odtwarzaj po starcie")}><input type="checkbox" checked={value.autostart} onChange={(e) => setValue({ ...value, autostart: e.target.checked })} /></Field>
  </div><footer><button type="button" onClick={onClose}>{networkText("Anuluj")}</button><button className="button-primary">{networkText("Przejdź do planu")}</button></footer></form></Modal>;
}

export function RoutesPanel({ state, onChange }: { state: NetworkManagementState; onChange: (change: NetworkChange) => void }) {
  const [editing, setEditing] = useState<ManagedNetworkRoute | null | undefined>(undefined);
  const [family, setFamily] = useState<"all" | "ipv4" | "ipv6">("all");
  const managed = Object.values(state.managed.routes);
  const visible = managed.filter((route) => family === "all" || route.family === family);
  return <div className="network-management-stack"><div className="network-actionbar"><button className="button-primary" disabled={!state.provider.writable} onClick={() => setEditing(null)}><Plus />{networkText("Dodaj trasę")}</button><label>Rodzina <select value={family} onChange={(e) => setFamily(e.target.value as typeof family)}><option value="all">IPv4 + IPv6</option><option value="ipv4">IPv4</option><option value="ipv6">IPv6</option></select></label></div>
    <section className="network-management-card"><header><div><h3>{networkText("Trasy zarządzane")}</h3><p>{networkText("Trwałe trasy zapisane przez panel.")}</p></div></header><div className="monitor-table-wrap"><table><thead><tr><th>{networkText("Stan")}</th><th>{networkText("Nazwa")}</th><th>{networkText("Rodzina")}</th><th>{networkText("Cel")}</th><th>{networkText("Brama / typ")}</th><th>{networkText("Interfejs")}</th><th>{networkText("Metryka")}</th><th>{networkText("Akcje")}</th></tr></thead><tbody>{visible.length ? visible.map((route) => <tr key={route.id || route.name}><td><input aria-label={`${networkText("Włącz trasę")} ${route.name}`} type="checkbox" checked={route.enabled} onChange={() => onChange({ operation: "save_route", route: { ...route, enabled: !route.enabled } })} /></td><td>{route.name}</td><td>{route.family.toUpperCase()}</td><td><code>{route.destination}</code></td><td>{route.gateway || route.route_type}</td><td>{route.interface || "—"}</td><td>{route.metric}</td><td><button onClick={() => setEditing(route)}><Edit3 /></button><button onClick={() => onChange({ operation: "delete_route", object_id: route.id! })}><Trash2 /></button></td></tr>) : <tr><td colSpan={8}>{networkText("Brak zarządzanych tras.")}</td></tr>}</tbody></table></div></section>
    <details className="network-management-card"><summary>{networkText("Pełna aktywna tablica routingu")} ({state.routing.routes.length})</summary><div className="monitor-table-wrap"><table><thead><tr><th>{networkText("Rodzina")}</th><th>{networkText("Cel")}</th><th>{networkText("Brama")}</th><th>{networkText("Interfejs")}</th><th>{networkText("Tabela")}</th></tr></thead><tbody>{state.routing.routes.map((route, index) => <tr key={`${route.family}-${route.destination}-${index}`}><td>{route.family}</td><td><code>{route.destination}</code></td><td>{route.gateway || "—"}</td><td>{route.device || "—"}</td><td>{route.table}</td></tr>)}</tbody></table></div></details>
    {editing !== undefined && <RouteForm initial={editing || undefined} interfaces={state.interfaces.map((item) => item.name)} onClose={() => setEditing(undefined)} onSubmit={(route) => { setEditing(undefined); onChange({ operation: "save_route", route }); }} />}
  </div>;
}

function TrafficForm({ initial, interfaces, onClose, onSubmit }: { initial?: NetworkTrafficRule; interfaces: string[]; onClose: () => void; onSubmit: (rule: NetworkTrafficRule) => void }) {
  const [value, setValue] = useState(initial || { ...newTraffic(), interface: interfaces[0] || "" });
  return <Modal title={initial ? networkText("Edytuj regułę ruchu") : networkText("Nowa reguła ruchu")} onClose={onClose}><form onSubmit={(e) => { e.preventDefault(); onSubmit(value); }}><div className="network-form-grid">
    <Field label={networkText("Nazwa")}><input required value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></Field><Field label={networkText("Interfejs")}><select required value={value.interface} onChange={(e) => setValue({ ...value, interface: e.target.value })}>{interfaces.map((name) => <option key={name}>{name}</option>)}</select></Field>
    <Field label={networkText("Kierunek")}><select value={value.direction} onChange={(e) => setValue({ ...value, direction: e.target.value as "egress" | "ingress" })}><option value="egress">{networkText("Wychodzący")}</option><option value="ingress">{networkText("Przychodzący")}</option></select></Field><Field label={networkText("Protokół")}><select value={value.protocol} onChange={(e) => setValue({ ...value, protocol: e.target.value as NetworkTrafficRule["protocol"] })}><option value="any">{networkText("Dowolny")}</option><option value="tcp">TCP</option><option value="udp">UDP</option></select></Field>
    <Field label={networkText("Gwarantowane (kbit/s)")}><input type="number" min={1} value={value.guaranteed_kbit} onChange={(e) => setValue({ ...value, guaranteed_kbit: Number(e.target.value) })} /></Field><Field label={networkText("Maksymalne (kbit/s)")}><input type="number" min={1} value={value.maximum_kbit} onChange={(e) => setValue({ ...value, maximum_kbit: Number(e.target.value) })} /></Field>
    <Field label={networkText("Źródło CIDR")}><input value={value.source_cidr || ""} onChange={(e) => setValue({ ...value, source_cidr: e.target.value || null })} /></Field><Field label={networkText("Cel CIDR")}><input value={value.destination_cidr || ""} onChange={(e) => setValue({ ...value, destination_cidr: e.target.value || null })} /></Field>
    {value.protocol !== "any" && <><Field label={networkText("Port źródłowy")}><input type="number" min={1} max={65535} value={value.source_port || ""} onChange={(e) => setValue({ ...value, source_port: Number(e.target.value) || null })} /></Field><Field label={networkText("Port docelowy")}><input type="number" min={1} max={65535} value={value.destination_port || ""} onChange={(e) => setValue({ ...value, destination_port: Number(e.target.value) || null })} /></Field></>}
    <Field label={networkText("Priorytet")}><input type="number" min={1} max={100} value={value.priority} onChange={(e) => setValue({ ...value, priority: Number(e.target.value) })} /></Field><Field label={networkText("Reguła aktywna")}><input type="checkbox" checked={value.enabled} onChange={(e) => setValue({ ...value, enabled: e.target.checked })} /></Field>
  </div><footer><button type="button" onClick={onClose}>{networkText("Anuluj")}</button><button className="button-primary">{networkText("Przejdź do planu")}</button></footer></form></Modal>;
}

export function TrafficPanel({ state, onChange }: { state: NetworkManagementState; onChange: (change: NetworkChange) => void }) {
  const [editing, setEditing] = useState<NetworkTrafficRule | null | undefined>(undefined);
  const rules = Object.values(state.managed.traffic);
  return <div className="network-management-stack"><div className="network-actionbar"><button className="button-primary" disabled={!state.provider.writable || !state.tools.tc} onClick={() => setEditing(null)}><Plus />{networkText("Dodaj regułę")}</button>{!state.tools.tc && <span>{networkText("Brak narzędzia tc.")}</span>}</div>
    <section className="network-management-card"><div className="monitor-table-wrap"><table><thead><tr><th>{networkText("Stan")}</th><th>{networkText("Nazwa")}</th><th>{networkText("Interfejs")}</th><th>{networkText("Kierunek")}</th><th>{networkText("Filtr")}</th><th>{networkText("Minimum")}</th><th>{networkText("Maksimum")}</th><th>{networkText("Priorytet")}</th><th>{networkText("Akcje")}</th></tr></thead><tbody>{rules.length ? rules.map((rule) => <tr key={rule.id || rule.name}><td><input aria-label={`${networkText("Włącz regułę")} ${rule.name}`} type="checkbox" checked={rule.enabled} onChange={() => onChange({ operation: "save_traffic", traffic: { ...rule, enabled: !rule.enabled } })} /></td><td>{rule.name}</td><td>{rule.interface}</td><td>{rule.direction}</td><td>{[rule.protocol, rule.source_cidr, rule.destination_cidr].filter(Boolean).join(" · ")}</td><td>{rule.guaranteed_kbit} kbit/s</td><td>{rule.maximum_kbit} kbit/s</td><td>{rule.priority}</td><td><button onClick={() => setEditing(rule)}><Edit3 /></button><button onClick={() => onChange({ operation: "delete_traffic", object_id: rule.id! })}><Trash2 /></button></td></tr>) : <tr><td colSpan={9}>{networkText("Brak reguł kontroli ruchu.")}</td></tr>}</tbody></table></div></section>
    {editing !== undefined && <TrafficForm initial={editing || undefined} interfaces={state.interfaces.map((item) => item.name)} onClose={() => setEditing(undefined)} onSubmit={(traffic) => { setEditing(undefined); onChange({ operation: "save_traffic", traffic }); }} />}
  </div>;
}

function PlanModal({ plan, busy, error, onClose, onApply }: { plan: NetworkPlan; busy: boolean; error: string; onClose: () => void; onApply: (phrase: string) => void }) {
  const [phrase, setPhrase] = useState("");
  return <Modal title={networkText("Podgląd planu zmian")} onClose={onClose}><div className="network-plan">
    <div className={`network-risk ${plan.high_risk ? "high" : "normal"}`}><ShieldAlert /><div><strong>{plan.high_risk ? networkText("Zmiana wysokiego ryzyka") : networkText("Plan gotowy")}</strong><p>{networkText("Cel")}: {plan.target}. {networkText("Automatyczny rollback po")} {plan.rollback_seconds} s.</p></div></div>
    {!plan.rollback_supported && <p className="error-state" role="alert">{networkText("Brak trwałego mechanizmu rollbacku systemd. Zastosowanie planu jest zablokowane.")}</p>}
    {plan.warnings.length > 0 && <ul>{plan.warnings.map((warning) => <li key={warning}><AlertTriangle />{warning}</li>)}</ul>}
    <details open><summary>{networkText("Polecenia")} ({plan.commands.length})</summary><pre>{plan.commands.map((command) => command.join(" ")).join("\n") || networkText("Zmiana stanu zarządzanego")}</pre></details>
    <details><summary>{networkText("Stan przed i po")}</summary><pre>{JSON.stringify({ before: plan.before, after: plan.after }, null, 2)}</pre></details>
    {plan.high_risk && <Field label={`${networkText("Wpisz dokładnie")}: ${plan.required_phrase}`}><input autoFocus value={phrase} onChange={(e) => setPhrase(e.target.value)} /></Field>}
    {error && <p className="error-state" role="alert">{error}</p>}
  </div><footer><button type="button" onClick={onClose}>{networkText("Anuluj")}</button><button className="button-primary" disabled={busy || !plan.rollback_supported || plan.high_risk && phrase !== plan.required_phrase} onClick={() => onApply(phrase)}>{busy ? networkText("Stosowanie…") : networkText("Zastosuj plan")}</button></footer></Modal>;
}

const NETWORK_TRANSACTION_KEY = "webnas_network_transaction";
type ConnectionState = "connected" | "reconnecting" | "confirming";
type PendingAction = "confirm" | "rollback" | null;

function terminalTransaction(transaction: NetworkTransaction) {
  return ["confirmed", "rolled_back", "failed"].includes(transaction.status || transaction.state);
}

function loadStoredTransaction(): NetworkTransaction | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(NETWORK_TRANSACTION_KEY) || "null") as NetworkTransaction | null;
    return value?.id && value.deadline ? value : null;
  } catch {
    return null;
  }
}

function storeTransaction(transaction: NetworkTransaction | null) {
  try {
    if (transaction && !terminalTransaction(transaction)) sessionStorage.setItem(NETWORK_TRANSACTION_KEY, JSON.stringify(transaction));
    else sessionStorage.removeItem(NETWORK_TRANSACTION_KEY);
  } catch {
    // The system timer remains authoritative when browser storage is unavailable.
  }
}

function reconnectAddresses(transaction: NetworkTransaction) {
  const approved = [
    window.location.origin,
    transaction.predicted_panel_address,
    transaction.previous_panel_address,
    ...(transaction.reachable_addresses || []),
  ].filter((value): value is string => Boolean(value));
  return [...new Set(approved)];
}

function TransactionBanner({ transaction, connection, pendingAction, serverOffset, onConfirm, onRollback }: {
  transaction: NetworkTransaction; connection: ConnectionState; pendingAction: PendingAction; serverOffset: number;
  onConfirm: () => void; onRollback: () => void;
}) {
  const [now, setNow] = useState(transaction.current_server_time || transaction.started_at);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 200);
    return () => window.clearInterval(timer);
  }, []);
  const status = transaction.status || transaction.state;
  const deadline = transaction.deadline_at || transaction.deadline;
  const left = Math.max(0, Math.ceil(deadline - (now + serverOffset)));
  const countdown = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
  const title = status === "confirmed" ? networkText("Konfiguracja zachowana")
    : status === "rolled_back" ? networkText("Przywrócono poprzednią konfigurację")
      : status === "failed" ? networkText("Nie udało się potwierdzić przed upływem czasu")
        : status === "rollback_started" || status === "rollback_pending" || left === 0 ? networkText("Trwa przywracanie poprzedniej konfiguracji")
          : pendingAction === "confirm" ? networkText("Wysyłanie potwierdzenia")
            : connection === "reconnecting" ? networkText("Utracono połączenie — trwa ponowne łączenie")
              : networkText("Oczekiwanie na potwierdzenie");
  const active = !terminalTransaction(transaction);
  return <aside className="network-transaction-banner" role="status"><RefreshCw /><div><strong>{title}</strong>
    <p>{active && left > 0 ? `${networkText("Nowa konfiguracja sieci oczekuje na potwierdzenie. Automatyczne przywrócenie za")} ${countdown}` : title}</p>
  </div>{active && left > 0 && <><button onClick={onRollback}>{networkText("Przywróć teraz")}</button><button className="button-primary" onClick={onConfirm}><CheckCircle2 />{networkText("Zachowaj konfigurację")}</button></>}</aside>;
}

export function NetworkManagementWorkspace({ tab, t, permissions = [], onNavigate }: { tab: "general" | "interfaces" | "traffic" | "routes"; t: Translate; permissions?: string[]; onNavigate: (tab: "interfaces" | "routes" | "connectivity") => void }) {
  const [state, setState] = useState<NetworkManagementState | null>(null);
  const [plan, setPlan] = useState<NetworkPlan | null>(null);
  const [transaction, setTransaction] = useState<NetworkTransaction | null>(loadStoredTransaction);
  const [connection, setConnection] = useState<ConnectionState>("connected");
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [serverOffset, setServerOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const transactionRef = useRef(transaction);
  const pendingActionRef = useRef(pendingAction);
  const transactionId = transaction?.id;
  const refresh = useCallback(async () => {
    setError("");
    try {
      const [next, active] = await Promise.all([api.networkManagement(), api.activeNetworkTransaction()]);
      setState(next);
      setConnection("connected");
      const recovered = active || next.transaction;
      if (recovered) {
        setTransaction(recovered);
        storeTransaction(recovered);
      }
    } catch (reason) {
      setConnection("reconnecting");
      setError(reason instanceof Error ? reason.message : t("error.generic"));
    } finally {
      setLoading(false);
    }
  }, [t]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { transactionRef.current = transaction; }, [transaction]);
  useEffect(() => { pendingActionRef.current = pendingAction; }, [pendingAction]);
  useEffect(() => {
    const initial = transactionRef.current;
    if (!initial || terminalTransaction(initial)) return;
    let stopped = false;
    let timeout: number | undefined;
    let attempts = 0;
    const poll = async () => {
      const current = transactionRef.current;
      if (stopped || !current || terminalTransaction(current)) return;
      let reached = false;
      for (const baseUrl of reconnectAddresses(current)) {
        const controller = new AbortController();
        const abort = window.setTimeout(() => controller.abort(), 1500);
        try {
          const apiBase = baseUrl === window.location.origin ? "" : baseUrl;
          const status = await api.networkTransactionStatus(current.id, apiBase, controller.signal);
          window.clearTimeout(abort);
          if (stopped) return;
          reached = true;
          setApiBaseUrl(apiBase);
          attempts = 0;
          setConnection("connected");
          if (status.current_server_time) setServerOffset(status.current_server_time - Date.now() / 1000);
          setTransaction(status);
          transactionRef.current = status;
          storeTransaction(status);
          if (terminalTransaction(status)) {
            setPendingAction(null);
            return;
          }
          const action = pendingActionRef.current;
          if (action) {
            setConnection(action === "confirm" ? "confirming" : "connected");
            const actionController = new AbortController();
            const actionAbort = window.setTimeout(() => actionController.abort(), 1500);
            const result = action === "confirm"
              ? await api.confirmNetworkTransaction(status.id, apiBase, actionController.signal)
              : await api.rollbackNetworkTransaction(status.id, apiBase, actionController.signal);
            window.clearTimeout(actionAbort);
            if (stopped) return;
            setPendingAction(null);
            pendingActionRef.current = null;
            setTransaction(result);
            transactionRef.current = result;
            storeTransaction(result);
            return;
          }
          break;
        } catch {
          window.clearTimeout(abort);
        }
      }
      if (!reached) setConnection("reconnecting");
      if (!stopped) {
        attempts += 1;
        const delay = attempts < 4 ? 500 : attempts < 8 ? 1000 : 2000;
        timeout = window.setTimeout(() => void poll(), delay);
      }
    };
    void poll();
    return () => {
      stopped = true;
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, [transactionId]);
  async function prepare(change: NetworkChange) {
    setBusy(true); setError("");
    try { setPlan(await api.planNetworkChange(change)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setBusy(false); }
  }
  async function apply(phrase: string) {
    if (!plan) return;
    setBusy(true); setError("");
    try {
      const next = await api.applyNetworkPlan(plan.id, phrase);
      setPlan(null);
      setTransaction(next);
      transactionRef.current = next;
      storeTransaction(next);
      if (next.current_server_time) setServerOffset(next.current_server_time - Date.now() / 1000);
      void refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setBusy(false); }
  }
  async function finish(action: "confirm" | "rollback") {
    if (!transaction) return;
    setPendingAction(action);
    pendingActionRef.current = action;
    setConnection(action === "confirm" ? "confirming" : "connected");
    setError("");
    const controller = new AbortController();
    const abort = window.setTimeout(() => controller.abort(), 1500);
    try {
      const next = action === "confirm"
        ? await api.confirmNetworkTransaction(transaction.id, "", controller.signal)
        : await api.rollbackNetworkTransaction(transaction.id, "", controller.signal);
      setPendingAction(null);
      pendingActionRef.current = null;
      setTransaction(next);
      transactionRef.current = next;
      storeTransaction(next);
      void refresh();
    } catch {
      setConnection("reconnecting");
    } finally {
      window.clearTimeout(abort);
    }
  }
  const banner = transaction && <TransactionBanner transaction={transaction} connection={connection} pendingAction={pendingAction} serverOffset={serverOffset} onConfirm={() => void finish("confirm")} onRollback={() => void finish("rollback")} />;
  if (loading) return <>{banner}<div className="loading-state">{t("status.loading")}</div></>;
  if (!state) return <>{banner}<p className="error-state" role="alert">{error}</p></>;
  const mayMutate = permissions.length === 0 || permissions.some((permission) => permission.startsWith("network.manage_") || permission === "network.confirm" || permission === "network.rollback");
  const visibleState = mayMutate ? state : { ...state, provider: { ...state.provider, writable: false, warnings: [...state.provider.warnings, networkText("Brak uprawnienia do modyfikacji konfiguracji sieci.")] } };
  return <div className="network-management-workspace">
    {banner}
    {error && !plan && <p className="error-state" role="alert">{error}</p>}
    <div className="network-management-heading"><div><Globe2 /><span><strong>{state.hostname}</strong><small>{state.provider.id} · {state.provider.writable ? networkText("zapis dostępny") : networkText("tylko odczyt")}</small></span></div><button onClick={() => void refresh()}><RefreshCw />{networkText("Odśwież")}</button></div>
    {tab === "general" && <GeneralPanel state={visibleState} onChange={(change) => void prepare(change)} onNavigate={onNavigate} />}
    {tab === "interfaces" && <InterfacesPanel state={visibleState} onChange={(change) => void prepare(change)} />}
    {tab === "routes" && <RoutesPanel state={visibleState} onChange={(change) => void prepare(change)} />}
    {tab === "traffic" && <TrafficPanel state={visibleState} onChange={(change) => void prepare(change)} />}
    {plan && <PlanModal plan={plan} busy={busy} error={error} onClose={() => { setPlan(null); setError(""); }} onApply={(phrase) => void apply(phrase)} />}
  </div>;
}
