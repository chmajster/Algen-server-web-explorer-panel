import { useCallback, useEffect, useMemo, useState } from "react";
import { FileCode2, Play, Plus, RefreshCw, Save, ShieldCheck, Trash2 } from "lucide-react";
import type { ToastFn, Translate } from "../../app/types";
import { confirmDialog } from "../../components/DialogService";
import { policyAsCodeClient, type PolicyEvaluation, type PolicyFormat, type PolicyListItem, type PolicySummary } from "./api/client";
import "../security-tools.css";
import "./policy-as-code.css";

const DEFAULT_POLICY = `apiVersion: webnas/v1
kind: PolicySet
metadata:
  name: linux-baseline
  description: Declarative Linux security baseline
spec:
  enabled: true
  rules:
    - id: ssh.root-login
      severity: high
      message: Root SSH login must be disabled
      assert:
        path: ssh.permit_root_login
        operator: eq
        value: "no"
    - id: firewall.enabled
      severity: critical
      message: Firewall must be enabled with a restrictive default policy
      assert:
        all:
          - path: firewall.enabled
            operator: eq
            value: true
          - path: firewall.default_policy
            operator: in
            value: [drop, reject]
`;

const DEFAULT_FACTS = JSON.stringify({
  ssh: { permit_root_login: "no" },
  firewall: { enabled: true, default_policy: "drop" },
}, null, 2);

export function PolicyAsCodeApp({ permissions, language, toast, t, setDirty }: {
  permissions: readonly string[];
  language: string;
  toast: ToastFn;
  t: Translate;
  setDirty: (dirty: boolean) => void;
}) {
  const pl = language.toLowerCase().startsWith("pl");
  const tx = {
    title: "Policy-as-Code Engine",
    eyebrow: pl ? "Deklaratywne polityki YAML/JSON" : "Declarative YAML/JSON policies",
    subtitle: pl
      ? "Twórz i przechowuj polityki jako pliki YAML lub JSON. Walidator i evaluator obsługują wyłącznie bezpieczny, deklaratywny DSL bez eval, shella i wykonywania kodu."
      : "Create and store policies as YAML or JSON files. Validation and evaluation use a safe declarative DSL without eval, shell or embedded code execution.",
    policies: pl ? "Polityki" : "Policies",
    rules: pl ? "Reguły" : "Rules",
    enabled: pl ? "Aktywne" : "Enabled",
    invalid: pl ? "Niepoprawne" : "Invalid",
    newPolicy: pl ? "Nowa polityka" : "New policy",
    refresh: pl ? "Odśwież" : "Refresh",
    save: pl ? "Zapisz" : "Save",
    remove: pl ? "Usuń" : "Delete",
    validate: pl ? "Waliduj" : "Validate",
    evaluate: pl ? "Testuj bieżącą" : "Evaluate current",
    evaluateAll: pl ? "Testuj aktywne" : "Evaluate enabled",
    source: pl ? "Źródło polityki" : "Policy source",
    facts: pl ? "Dane wejściowe do testu (JSON)" : "Evaluation input facts (JSON)",
    result: pl ? "Wynik ewaluacji" : "Evaluation result",
    noPolicies: pl ? "Brak zapisanych polityk" : "No saved policies",
    saved: pl ? "Polityka została zapisana" : "Policy saved",
    deleted: pl ? "Polityka została usunięta" : "Policy deleted",
    valid: pl ? "Polityka jest poprawna" : "Policy is valid",
    confirmDelete: pl ? "Usunąć wybraną politykę?" : "Delete the selected policy?",
    compliant: pl ? "ZGODNA" : "COMPLIANT",
    nonCompliant: pl ? "NIEZGODNA" : "NON-COMPLIANT",
    selectPolicy: pl ? "Wybierz politykę lub utwórz nową." : "Select a policy or create a new one.",
  };
  const can = (permission: string) => permissions.includes(permission);
  const [summary, setSummary] = useState<PolicySummary | null>(null);
  const [items, setItems] = useState<PolicyListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [format, setFormat] = useState<PolicyFormat>("yaml");
  const [source, setSource] = useState(DEFAULT_POLICY);
  const [facts, setFacts] = useState(DEFAULT_FACTS);
  const [evaluation, setEvaluation] = useState<PolicyEvaluation | null>(null);
  const [loading, setLoading] = useState(false);
  const [dirty, setLocalDirty] = useState(false);

  useEffect(() => setDirty(dirty), [dirty, setDirty]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextSummary, nextPolicies] = await Promise.all([policyAsCodeClient.summary(), policyAsCodeClient.list()]);
      setSummary(nextSummary);
      setItems(nextPolicies.items);
      if (selectedId && !nextPolicies.items.some((item) => item.id === selectedId)) setSelectedId(null);
    } catch (error) {
      toast(String(error), "error");
    } finally {
      setLoading(false);
    }
  }, [selectedId, toast]);

  useEffect(() => { void load(); }, [load]);

  async function openPolicy(id: string) {
    try {
      const record = await policyAsCodeClient.get(id);
      setSelectedId(record.id);
      setFormat(record.format);
      setSource(record.source);
      setEvaluation(null);
      setLocalDirty(false);
    } catch (error) {
      toast(String(error), "error");
    }
  }

  function newPolicy() {
    setSelectedId(null);
    setFormat("yaml");
    setSource(DEFAULT_POLICY);
    setEvaluation(null);
    setLocalDirty(false);
  }

  async function savePolicy() {
    try {
      const record = selectedId
        ? await policyAsCodeClient.update(selectedId, format, source)
        : await policyAsCodeClient.create(format, source);
      setSelectedId(record.id);
      setFormat(record.format);
      setSource(record.source);
      setLocalDirty(false);
      toast(tx.saved, "ok");
      await load();
    } catch (error) {
      toast(String(error), "error");
    }
  }

  async function deletePolicy() {
    if (!selectedId || !await confirmDialog(tx.confirmDelete, t, true)) return;
    try {
      await policyAsCodeClient.remove(selectedId);
      setSelectedId(null);
      setSource(DEFAULT_POLICY);
      setFormat("yaml");
      setEvaluation(null);
      setLocalDirty(false);
      toast(tx.deleted, "ok");
      await load();
    } catch (error) {
      toast(String(error), "error");
    }
  }

  async function validatePolicy() {
    try {
      const result = await policyAsCodeClient.validate(format, source);
      toast(`${tx.valid}: ${result.id} (${result.rule_count})`, "ok");
    } catch (error) {
      toast(String(error), "error");
    }
  }

  function parsedFacts(): Record<string, unknown> {
    const value = JSON.parse(facts) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Facts must be a JSON object");
    return value as Record<string, unknown>;
  }

  async function evaluateCurrent() {
    try {
      setEvaluation(await policyAsCodeClient.evaluateSource(format, source, parsedFacts()));
    } catch (error) {
      toast(String(error), "error");
    }
  }

  async function evaluateEnabled() {
    try {
      setEvaluation(await policyAsCodeClient.evaluateEnabled(parsedFacts()));
    } catch (error) {
      toast(String(error), "error");
    }
  }

  const selected = useMemo(() => items.find((item) => item.id === selectedId) || null, [items, selectedId]);
  const resultRows = evaluation?.results || evaluation?.policies?.flatMap((policy) => policy.results || []) || [];

  return <section className="security-tool-app policy-code-app">
    <header className="security-tool-header">
      <div><span className="security-tool-eyebrow">{tx.eyebrow}</span><h2><FileCode2 /> {tx.title}</h2><p>{tx.subtitle}</p></div>
      <div className="security-actions">
        <button className="security-action" onClick={() => void load()} disabled={loading}><RefreshCw /> {tx.refresh}</button>
        {can("policy.manage") && <button className="security-action" onClick={newPolicy}><Plus /> {tx.newPolicy}</button>}
      </div>
    </header>

    <div className="security-stat-grid">
      <article><span>{tx.policies}</span><strong>{summary?.total ?? "—"}</strong><small>YAML {summary?.formats.yaml ?? 0} · JSON {summary?.formats.json ?? 0}</small></article>
      <article><span>{tx.enabled}</span><strong>{summary?.enabled ?? "—"}</strong><small>{summary?.disabled ?? 0} disabled</small></article>
      <article><span>{tx.rules}</span><strong>{summary?.rules ?? "—"}</strong><small>{tx.invalid}: {summary?.invalid ?? 0}</small></article>
    </div>

    <div className="policy-code-grid">
      <aside className="security-panel policy-code-list">
        <h3>{tx.policies}</h3>
        {items.length === 0 && <p>{tx.noPolicies}</p>}
        {items.map((item) => <button key={`${item.id}-${item.format}`} className={selectedId === item.id ? "active" : ""} onClick={() => void openPolicy(item.id)}>
          <span><strong>{item.name}</strong><small>{item.format.toUpperCase()} · {item.rule_count} {tx.rules.toLowerCase()}</small></span>
          <em className={item.valid ? (item.enabled ? "security-tone-ok" : "") : "security-tone-danger"}>{item.valid ? (item.enabled ? "ON" : "OFF") : "ERR"}</em>
        </button>)}
      </aside>

      <div className="policy-code-workspace">
        <div className="security-panel policy-code-editor">
          <div className="policy-code-toolbar">
            <h3>{selected ? selected.name : tx.newPolicy}</h3>
            <select value={format} onChange={(event) => { setFormat(event.target.value as PolicyFormat); setLocalDirty(true); }} aria-label="Policy format"><option value="yaml">YAML</option><option value="json">JSON</option></select>
            {can("policy.evaluate") && <button className="security-action" onClick={() => void validatePolicy()}><ShieldCheck /> {tx.validate}</button>}
            {can("policy.manage") && <button className="security-action" onClick={() => void savePolicy()}><Save /> {tx.save}</button>}
            {can("policy.manage") && selectedId && <button className="security-action danger" onClick={() => void deletePolicy()}><Trash2 /> {tx.remove}</button>}
          </div>
          <label>{tx.source}<textarea spellCheck={false} value={source} onChange={(event) => { setSource(event.target.value); setLocalDirty(true); }} /></label>
        </div>

        {can("policy.evaluate") && <div className="security-panel policy-code-evaluate">
          <div className="policy-code-toolbar"><h3>{tx.facts}</h3><button className="security-action" onClick={() => void evaluateCurrent()}><Play /> {tx.evaluate}</button><button className="security-action" onClick={() => void evaluateEnabled()}><Play /> {tx.evaluateAll}</button></div>
          <textarea spellCheck={false} value={facts} onChange={(event) => setFacts(event.target.value)} />
        </div>}
      </div>
    </div>

    {evaluation && <div className="security-panel policy-code-results">
      <div className="policy-code-result-head"><h3>{tx.result}</h3><strong className={evaluation.compliant ? "security-tone-ok" : "security-tone-danger"}>{evaluation.compliant ? tx.compliant : tx.nonCompliant} · {evaluation.score}/100</strong><span>{evaluation.passed} pass · {evaluation.failed} fail · {evaluation.errors} error</span></div>
      {resultRows.length === 0 ? <p>{tx.selectPolicy}</p> : <div className="policy-code-result-list">{resultRows.map((row, index) => <article key={`${row.id}-${index}`}><strong>{row.id}</strong><span className={row.status === "pass" ? "security-tone-ok" : "security-tone-danger"}>{row.status.toUpperCase()}</span><small>{row.message || row.description || row.error || "—"}</small></article>)}</div>}
    </div>}
  </section>;
}
