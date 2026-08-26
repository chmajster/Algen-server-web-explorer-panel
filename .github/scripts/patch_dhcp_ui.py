from pathlib import Path

dns = Path("backend/app/modules/providers/dns.py")
text = dns.read_text(encoding="utf-8")
if "from urllib.parse import quote\n" not in text:
    text = text.replace("from typing import Any\n", "from typing import Any\nfrom urllib.parse import quote\n", 1)
dns.write_text(text, encoding="utf-8")

hosts = Path("frontend/src/features/modules/hosts/HostsManagerApp.tsx")
text = hosts.read_text(encoding="utf-8")
state_marker = '  const [agentToken, setAgentToken] = useState("");\n'
state_insert = '''  const [agentToken, setAgentToken] = useState("");
  const [dhcpReservationOpen, setDhcpReservationOpen] = useState(false);
  const [dhcpSubnets, setDhcpSubnets] = useState<Array<{ id: string; name: string; cidr: string }>>([]);
  const [dhcpSubnetId, setDhcpSubnetId] = useState("");
  const [dhcpMac, setDhcpMac] = useState("");
  const [dhcpHostname, setDhcpHostname] = useState("");
  const [dhcpCreateDns, setDhcpCreateDns] = useState(false);
  const [dhcpDnsProvider, setDhcpDnsProvider] = useState<"auto" | "pihole" | "adguard-home">("auto");
  const [dhcpPamPassword, setDhcpPamPassword] = useState("");
  const [dhcpSaving, setDhcpSaving] = useState(false);
'''
if state_marker not in text:
    raise SystemExit("HostDetails state marker not found")
text = text.replace(state_marker, state_insert, 1)

function_marker = '''  async function invalidateIdentity() {
    if (!window.confirm(t("hosts.agent.invalidateConfirm"))) return;
    try {
      await api.invalidateHostsManagerAgentIdentity(value.id);
      toast(t("hosts.agent.identityInvalidated"), "ok");
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
'''
function_insert = function_marker + '''  async function openDhcpReservation() {
    try {
      const result = await api.dhcpSubnets();
      setDhcpSubnets(result.items.map((item) => ({ id: item.id, name: item.name, cidr: item.cidr })));
      setDhcpSubnetId(String(value.variables?.dhcp_subnet_id || result.items[0]?.id || ""));
      setDhcpMac(String(value.variables?.dhcp_mac || ""));
      setDhcpHostname(value.hostname || value.name);
      setDhcpCreateDns(false);
      setDhcpDnsProvider("auto");
      setDhcpPamPassword("");
      setDhcpReservationOpen(true);
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  async function createDhcpReservation(event: React.FormEvent) {
    event.preventDefault();
    if (!dhcpSubnetId || !dhcpMac || !dhcpPamPassword) return;
    setDhcpSaving(true);
    try {
      await api.createDhcpReservationFromHost(value.id, {
        subnet_id: dhcpSubnetId,
        mac_address: dhcpMac,
        hostname: dhcpHostname,
        create_dns_record: dhcpCreateDns,
        dns_provider: dhcpDnsProvider,
        confirmation: value.id,
        pam_password: dhcpPamPassword,
      });
      toast("DHCP reservation queued", "ok");
      setDhcpReservationOpen(false);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    } finally {
      setDhcpSaving(false);
    }
  }
'''
if function_marker not in text:
    raise SystemExit("HostDetails identity marker not found")
text = text.replace(function_marker, function_insert, 1)

summary_marker = '''            <dt>{t("hosts.host.approval")}</dt><dd>{t(value.approved ? "common.yes" : "common.no")}</dd>
          </dl></section>
'''
summary_insert = '''            <dt>{t("hosts.host.approval")}</dt><dd>{t(value.approved ? "common.yes" : "common.no")}</dd>
            {Boolean(value.variables?.dhcp_source) && <>
              <dt>DHCP IP</dt><dd>{String(value.variables?.dhcp_ip || t("common.none"))}</dd>
              <dt>DHCP MAC</dt><dd>{String(value.variables?.dhcp_mac || t("common.none"))}</dd>
              <dt>DHCP subnet</dt><dd>{String(value.variables?.dhcp_subnet || t("common.none"))}</dd>
              <dt>DHCP lease</dt><dd>{String(value.variables?.dhcp_lease_state || t("common.none"))}</dd>
              <dt>DHCP reservation</dt><dd>{String(value.variables?.dhcp_reservation_state || t("common.none"))}</dd>
              <dt>Source</dt><dd>{String(value.variables?.dhcp_source || "DHCP")}</dd>
            </>}
          </dl></section>
'''
if summary_marker not in text:
    raise SystemExit("HostDetails summary marker not found")
text = text.replace(summary_marker, summary_insert, 1)

action_marker = '''          {!value.approved &&
            permissions.includes("hosts-manager.hosts.approve") && (
'''
action_insert = '''          {permissions.includes("dhcp.reservations.manage") && (
            <button type="button" onClick={() => void openDhcpReservation()}>
              <Network />
              Create DHCP Reservation
            </button>
          )}
          {!value.approved &&
            permissions.includes("hosts-manager.hosts.approve") && (
'''
if action_marker not in text:
    raise SystemExit("HostDetails action marker not found")
text = text.replace(action_marker, action_insert, 1)

modal_marker = '''      {agentToken && <Modal title={t("hosts.agent.newToken")} closeLabel={t("action.close")} onClose={() => setAgentToken("")}><p>{t("hosts.agent.newTokenHint")}</p><code className="hosts-secret-once">{agentToken}</code><button type="button" onClick={() => void navigator.clipboard.writeText(agentToken)}><Copy />{t("action.copy")}</button></Modal>}
    </Modal>
'''
modal_insert = '''      {agentToken && <Modal title={t("hosts.agent.newToken")} closeLabel={t("action.close")} onClose={() => setAgentToken("")}><p>{t("hosts.agent.newTokenHint")}</p><code className="hosts-secret-once">{agentToken}</code><button type="button" onClick={() => void navigator.clipboard.writeText(agentToken)}><Copy />{t("action.copy")}</button></Modal>}
      {dhcpReservationOpen && <Modal
        title="Create DHCP Reservation"
        closeLabel={t("action.close")}
        onClose={() => setDhcpReservationOpen(false)}
        footer={<><button type="button" onClick={() => setDhcpReservationOpen(false)}>{t("action.cancel")}</button><button className="button-primary" type="submit" form="hosts-dhcp-reservation" disabled={dhcpSaving}>{dhcpSaving ? t("status.loading") : t("action.save")}</button></>}
      >
        <form id="hosts-dhcp-reservation" className="module-form-grid" onSubmit={(event) => void createDhcpReservation(event)}>
          <label>Subnet<select required value={dhcpSubnetId} onChange={(event) => setDhcpSubnetId(event.target.value)}><option value="">Select subnet</option>{dhcpSubnets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.cidr}</option>)}</select></label>
          <label>MAC address<input required value={dhcpMac} onChange={(event) => setDhcpMac(event.target.value)} placeholder="02:00:00:00:00:01" /></label>
          <label>Hostname<input required value={dhcpHostname} onChange={(event) => setDhcpHostname(event.target.value)} /></label>
          <label className="checkbox-line"><input type="checkbox" checked={dhcpCreateDns} onChange={(event) => setDhcpCreateDns(event.target.checked)} />Create / update DNS record</label>
          {dhcpCreateDns && <label>DNS provider<select value={dhcpDnsProvider} onChange={(event) => setDhcpDnsProvider(event.target.value as "auto" | "pihole" | "adguard-home")}><option value="auto">Auto</option><option value="pihole">Pi-hole</option><option value="adguard-home">AdGuard Home</option></select></label>}
          <label className="wide">PAM password<input required type="password" autoComplete="current-password" value={dhcpPamPassword} onChange={(event) => setDhcpPamPassword(event.target.value)} /></label>
          <p className="wide">Confirmation is bound to host ID <code>{value.id}</code>. The backend validates RBAC, CSRF, PAM and Proxmox Safe Mode before enqueueing the DHCP job.</p>
        </form>
      </Modal>}
    </Modal>
'''
if modal_marker not in text:
    raise SystemExit("HostDetails modal marker not found")
text = text.replace(modal_marker, modal_insert, 1)
hosts.write_text(text, encoding="utf-8")
