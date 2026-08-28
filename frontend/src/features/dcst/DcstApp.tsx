import { useCallback, useState } from "react";
import type { ToastFn, Translate } from "../../app/types";
import { dcstClient } from "./api/client";
import type { DcstIPSet, DcstPort, DcstService } from "./api/types";
import { DcstConfirmDialog, type DcstConfirmAction } from "./components/DcstConfirmDialog";
import { DcstHeader } from "./components/DcstHeader";
import { DcstIPSetDrawer, DcstPortDrawer } from "./components/DcstObjectDrawers";
import { DcstObjectDetails } from "./components/DcstObjectDetails";
import { DcstServiceDetails } from "./components/DcstServiceDetails";
import { DcstServiceDrawer } from "./components/DcstServiceDrawer";
import { DcstTabs, type DcstTab } from "./components/DcstTabs";
import { exactTime, relativeTime, syncTimestamp } from "./domain/firewallLog";
import { useDcstIpsets } from "./hooks/useDcstIpsets";
import { useDcstOverview } from "./hooks/useDcstOverview";
import { useDcstPorts } from "./hooks/useDcstPorts";
import { useDcstServices } from "./hooks/useDcstServices";
import { useDcstTags } from "./hooks/useDcstTags";
import { useDcstUtilities } from "./hooks/useDcstUtilities";
import { IpsetsPage } from "./pages/IpsetsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PortsPage } from "./pages/PortsPage";
import { ServicesPage } from "./pages/ServicesPage";
import { TagsPage } from "./pages/TagsPage";
import { UtilitiesPage } from "./pages/UtilitiesPage";

export { normalizeFirewallLog } from "./domain/firewallLog";

export function DcstApp({ permissions, t, toast }: { permissions: string[]; t: Translate; toast: ToastFn }) {
  const [tab, setTab] = useState<DcstTab>("overview");
  const [confirm, setConfirm] = useState<DcstConfirmAction>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [synchronizing, setSynchronizing] = useState(false);
  const can = useCallback((permission: string) => permissions.includes(permission), [permissions]);
  const notifyError = useCallback((error: unknown) => toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"), [t, toast]);
  const success = useCallback((message: string) => toast(message, "ok", "admin"), [toast]);

  const data = useDcstOverview(notifyError);
  const refresh = useCallback(() => data.refresh(false), [data.refresh]);
  const services = useDcstServices({ services: data.services, refresh, onError: notifyError, onSuccess: success });
  const ports = useDcstPorts({ services: data.services, refresh, onError: notifyError, onSuccess: success });
  const ipsets = useDcstIpsets({ refresh, onError: notifyError, onSuccess: success });
  const tags = useDcstTags({ refresh, onError: notifyError, onSuccess: success });
  const utilities = useDcstUtilities(notifyError, success);
  const overview = data.overview as unknown as Record<string, unknown> || {};
  const inventoryReady = data.tags.length > 0 || Boolean(syncTimestamp(overview.last_inventory_sync));
  const lastSyncLabel = relativeTime(overview.last_firewall_sync);
  const lastSyncExact = exactTime(overview.last_firewall_sync);
  const managedObjectCount = data.services.length + data.tags.length + data.ipsets.length + data.ports.length;

  async function runConfirmation() {
    if (!confirm || confirmBusy) return;
    setConfirmBusy(true);
    try { await confirm.run(); setConfirm(null); } catch (error) { notifyError(error); } finally { setConfirmBusy(false); }
  }

  function confirmBulkBlock() {
    const ids = [...services.selected];
    if (!ids.length) return;
    setConfirm({ title: `Block ${ids.length} communication service${ids.length === 1 ? "" : "s"}?`, message: "Blocking these services applies traffic-blocking firewall rules and can interrupt live communication. Confirm only if this disruption is intended.", confirmLabel: "Block selected", destructive: true, run: async () => { await dcstClient.bulk("block", ids); success("Bulk block completed"); services.setSelected(new Set()); await refresh(); } });
  }

  function confirmDeleteService(item: DcstService) {
    setConfirm({ title: "Delete communication service?", subject: item.name, message: "Deleting this service removes its managed firewall rules immediately. Live traffic may change as soon as deletion succeeds.", confirmLabel: "Delete", destructive: true, run: async () => { await dcstClient.deleteService(item.id); await refresh(); success("Communication service deleted"); } });
  }

  function confirmDeleteIPSet(item: DcstIPSet) {
    setConfirm({ title: "Delete IP Set?", subject: item.name, message: "This object will be removed if it is not referenced by communication services.", confirmLabel: "Delete", destructive: true, run: async () => { await ipsets.remove(item.id); } });
  }

  function confirmDeletePort(item: DcstPort) {
    setConfirm({ title: "Delete port object?", subject: item.name, message: "Services using this object will prevent deletion.", confirmLabel: "Delete", destructive: true, run: async () => { await ports.remove(item.id); } });
  }

  function confirmFirewallSync() {
    setConfirm({ title: "Synchronize firewall policies?", message: "DCST will apply the current desired state to managed Proxmox Firewall objects. External unmanaged rules will be preserved.", confirmLabel: "Synchronize", run: async () => {
      setSynchronizing(true);
      try { await dcstClient.firewallSync(false); await refresh(); success("Firewall synchronized"); } finally { setSynchronizing(false); }
    } });
  }

  function renderPage() {
    if (tab === "overview") return <OverviewPage overview={overview} services={data.services} tags={data.tags} ports={data.ports} ipsetCount={data.ipsets.length} />;
    if (tab === "services") return <ServicesPage services={data.services} visible={services.visible} ports={data.ports} tags={data.tags} ipsets={data.ipsets} selected={services.selected} loading={data.loading} inventoryReady={inventoryReady} filters={services.filters} canManage={can("dcst.manage_services")} canBlock={can("dcst.block_traffic")} canSync={can("dcst.sync")} canInventorySync={can("dcst.manage_tags")} onFilter={services.setFilter} onSelectionChange={services.setSelected} onCreate={services.openCreate} onView={services.view} onEdit={services.edit} onDuplicate={(item) => void services.duplicate(item)} onAction={(item, operation) => void services.action(item, operation)} onSynchronize={(item) => void services.synchronize(item)} onDelete={confirmDeleteService} onInventorySync={() => void tags.synchronize()} onBulk={(operation) => void services.bulk(operation)} onBulkBlock={confirmBulkBlock} />;
    if (tab === "tags") return <TagsPage tags={data.tags} loading={data.loading} canManage={can("dcst.manage_tags")} refreshing={data.refreshing} onSynchronize={() => void tags.synchronize()} onView={tags.setDetails} />;
    if (tab === "ipsets") return <IpsetsPage ipsets={data.ipsets} loading={data.loading} canManage={can("dcst.manage_ipsets")} canSync={can("dcst.sync")} onCreate={ipsets.openCreate} onView={ipsets.setDetails} onEdit={ipsets.edit} onDelete={confirmDeleteIPSet} onSynchronize={(item) => void ipsets.synchronize(item.id)} />;
    if (tab === "ports") return <PortsPage ports={data.ports} loading={data.loading} canManage={can("dcst.manage_ports")} usage={ports.usage} onCreate={ports.openCreate} onView={ports.setDetails} onEdit={ports.edit} onDelete={confirmDeletePort} />;
    return <UtilitiesPage overview={overview} loading={utilities.loading} diagnostics={utilities.diagnostics} filters={utilities.filters} nodes={utilities.nodes} logs={utilities.filtered} canSync={can("dcst.sync")} canViewLogs={can("dcst.view_logs")} onFilter={utilities.setFilter} onRefresh={() => void utilities.load()} onTest={() => void utilities.testConnection()} onDryRun={() => void utilities.dryRun()} onDrift={() => void utilities.detectDrift()} />;
  }

  return <section className="system-app module-app dcst-app">
    <DcstHeader managedObjectCount={managedObjectCount} lastSyncLabel={lastSyncLabel} inventorySynchronized={inventoryReady} refreshing={data.refreshing} synchronizing={synchronizing} canSync={can("dcst.sync")} onRefresh={() => void refresh()} onSynchronize={confirmFirewallSync} />
    <DcstTabs active={tab} counts={{ services: data.services.length, tags: data.tags.length, ipsets: data.ipsets.length, ports: data.ports.length }} onChange={(nextTab) => { setTab(nextTab); if (nextTab === "utilities") void utilities.load(); }} />
    {renderPage()}
    <DcstServiceDrawer open={services.drawerOpen} editId={services.editId} draft={services.draft} tags={data.tags} ipsets={data.ipsets} ports={data.ports} errors={services.errors} saving={services.saving} onDraftChange={services.setDraft} onClose={services.closeDrawer} onSubmit={() => void services.save()} />
    <DcstServiceDetails service={services.details} preview={services.preview} ports={data.ports} tags={data.tags} ipsets={data.ipsets} lastSyncLabel={lastSyncExact} onClose={services.closeDetails} />
    <DcstIPSetDrawer open={ipsets.drawerOpen} editId={ipsets.editId} draft={ipsets.draft} saving={ipsets.saving} onDraftChange={ipsets.setDraft} onClose={ipsets.closeDrawer} onSubmit={() => void ipsets.save()} />
    <DcstPortDrawer open={ports.drawerOpen} editId={ports.editId} draft={ports.draft} saving={ports.saving} onDraftChange={ports.setDraft} onClose={ports.closeDrawer} onSubmit={() => void ports.save()} />
    <DcstObjectDetails tag={tags.details} ipset={ipsets.details} port={ports.details} portUsage={ports.usage} onCloseTag={() => tags.setDetails(null)} onCloseIPSet={() => ipsets.setDetails(null)} onClosePort={() => ports.setDetails(null)} />
    <DcstConfirmDialog action={confirm} busy={confirmBusy} onCancel={() => { if (!confirmBusy) setConfirm(null); }} onConfirm={() => void runConfirmation()} />
  </section>;
}
