import { useState } from "react";
import { dcstClient } from "../api/client";
import type { DcstIPSet } from "../api/types";
import { emptyIPSetDraft, parseIPSetEntries, type IPSetDraft } from "../domain/ipset";

export function useDcstIpsets({ refresh, onError, onSuccess }: {
  refresh: () => Promise<void>;
  onError: (error: unknown) => void;
  onSuccess: (message: string) => void;
}) {
  const [draft, setDraft] = useState<IPSetDraft>(emptyIPSetDraft);
  const [editId, setEditId] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [details, setDetails] = useState<DcstIPSet | null>(null);
  function openCreate() { setEditId(""); setDraft(emptyIPSetDraft); setDrawerOpen(true); }
  function edit(item: DcstIPSet) { setEditId(item.id); setDraft({ name: item.name, description: item.description, entries: item.entries.map((entry) => entry.address).join("\n") }); setDrawerOpen(true); }
  function closeDrawer() { if (!saving) setDrawerOpen(false); }
  async function save() {
    setSaving(true);
    try { await dcstClient.saveIPSet({ name: draft.name, description: draft.description, entries: parseIPSetEntries(draft.entries) }, editId); onSuccess(editId ? "IPSet updated" : "IPSet created"); setDrawerOpen(false); setEditId(""); setDraft(emptyIPSetDraft); await refresh(); }
    catch (error) { onError(error); } finally { setSaving(false); }
  }
  async function remove(id: string) { await dcstClient.deleteIPSet(id); await refresh(); }
  async function synchronize(id: string) { try { await dcstClient.syncIPSet(id); await refresh(); } catch (error) { onError(error); } }
  return { draft, setDraft, editId, drawerOpen, saving, details, setDetails, openCreate, edit, closeDrawer, save, remove, synchronize };
}
