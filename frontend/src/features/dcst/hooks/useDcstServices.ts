import { useMemo, useRef, useState } from "react";
import { dcstClient } from "../api/client";
import type { DcstService, DcstServiceInput } from "../api/types";
import { emptyServiceDraft, emptyServiceFilters, filterServices, validateServiceDraft, type ServiceFilters, type ServiceValidationErrors } from "../domain/service";

export function useDcstServices({ services, refresh, onError, onSuccess }: {
  services: DcstService[];
  refresh: () => Promise<void>;
  onError: (error: unknown) => void;
  onSuccess: (message: string) => void;
}) {
  const [filters, setFilters] = useState<ServiceFilters>(emptyServiceFilters);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState<DcstServiceInput>(emptyServiceDraft);
  const [editId, setEditId] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [errors, setErrors] = useState<ServiceValidationErrors>({});
  const [saving, setSaving] = useState(false);
  const [details, setDetails] = useState<DcstService | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const previewRequest = useRef(0);

  const visible = useMemo(() => filterServices(services, filters), [services, filters]);

  function setFilter<K extends keyof ServiceFilters>(key: K, value: ServiceFilters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function openCreate() {
    setEditId(""); setDraft(emptyServiceDraft); setErrors({}); setDrawerOpen(true);
  }

  function edit(item: DcstService) {
    setEditId(item.id);
    setDraft({
      name: item.name, description: item.description, direction: item.direction, action: item.action,
      source_type: item.source_type, source_value: item.source_value, destination_type: item.destination_type,
      destination_value: item.destination_value, port_ids: item.port_ids, enabled: item.enabled,
      logging: item.logging, comment: item.comment,
    });
    setErrors({}); setDrawerOpen(true);
  }

  function closeDrawer() {
    if (saving) return;
    setDrawerOpen(false); setErrors({});
  }

  async function save() {
    const nextErrors = validateServiceDraft(draft);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    setSaving(true);
    try {
      await dcstClient.saveService(draft, editId);
      onSuccess(editId ? "Service updated" : "Service created");
      setDrawerOpen(false); setEditId(""); setDraft(emptyServiceDraft);
      await refresh();
    } catch (error) { onError(error); } finally { setSaving(false); }
  }

  async function action(item: DcstService, operation: "block" | "unblock" | "enable" | "disable") {
    try { await dcstClient.serviceAction(item.id, operation); onSuccess(`${item.name}: ${operation} completed`); await refresh(); } catch (error) { onError(error); }
  }

  async function bulk(operation: "block" | "unblock" | "enable" | "disable" | "sync") {
    if (!selected.size) return;
    try { await dcstClient.bulk(operation, [...selected]); onSuccess(`Bulk ${operation} completed`); setSelected(new Set()); await refresh(); } catch (error) { onError(error); }
  }

  async function duplicate(item: DcstService) {
    try { await dcstClient.cloneService(item.id); await refresh(); onSuccess("Service duplicated"); } catch (error) { onError(error); }
  }

  async function synchronize(item: DcstService) {
    try { await dcstClient.syncService(item.id); await refresh(); onSuccess(`${item.name} synchronized`); } catch (error) { onError(error); }
  }

  function view(item: DcstService) {
    const requestId = ++previewRequest.current;
    setDetails(item); setPreview(null);
    void dcstClient.previewService(item.id).then((value) => {
      if (previewRequest.current === requestId) setPreview(value);
    }).catch((error) => { if (previewRequest.current === requestId) onError(error); });
  }

  function closeDetails() {
    previewRequest.current += 1; setDetails(null); setPreview(null);
  }

  return {
    filters, setFilter, selected, setSelected, visible,
    draft, setDraft, editId, drawerOpen, errors, saving, openCreate, edit, closeDrawer, save,
    details, preview, view, closeDetails, action, bulk, duplicate, synchronize,
  };
}
