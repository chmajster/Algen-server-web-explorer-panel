import { useMemo, useState } from "react";
import { dcstClient } from "../api/client";
import type { DcstPort, DcstService } from "../api/types";
import { emptyPortDraft, type PortDraft } from "../domain/port";

export function useDcstPorts({ services, refresh, onError, onSuccess }: {
  services: DcstService[];
  refresh: () => Promise<void>;
  onError: (error: unknown) => void;
  onSuccess: (message: string) => void;
}) {
  const [draft, setDraft] = useState<PortDraft>(emptyPortDraft);
  const [editId, setEditId] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [details, setDetails] = useState<DcstPort | null>(null);
  const usage = useMemo(() => {
    const counts = new Map<string, number>();
    services.forEach((service) => service.port_ids.forEach((portId) => counts.set(portId, (counts.get(portId) || 0) + 1)));
    return counts;
  }, [services]);

  function openCreate() { setEditId(""); setDraft(emptyPortDraft); setDrawerOpen(true); }
  function edit(port: DcstPort) {
    setEditId(port.id);
    setDraft({ name: port.name, protocol: port.protocol, port_from: port.port_from ?? null, port_to: port.port_to ?? null, description: port.description });
    setDrawerOpen(true);
  }
  function closeDrawer() { if (!saving) setDrawerOpen(false); }
  async function save() {
    setSaving(true);
    try { await dcstClient.savePort(draft, editId); onSuccess(editId ? "Port object updated" : "Port object created"); setDrawerOpen(false); setEditId(""); setDraft(emptyPortDraft); await refresh(); }
    catch (error) { onError(error); } finally { setSaving(false); }
  }
  async function remove(id: string) { await dcstClient.deletePort(id); await refresh(); }
  return { draft, setDraft, editId, drawerOpen, saving, details, setDetails, usage, openCreate, edit, closeDrawer, save, remove };
}
