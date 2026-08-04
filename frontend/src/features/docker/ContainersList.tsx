import {
  ArrowDown,
  ArrowUp,
  Archive,
  Boxes,
  ChevronDown,
  ChevronUp,
  Copy,
  Eye,
  FileText,
  MoreVertical,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Square,
  TerminalSquare,
  Trash2,
  Upload,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type DockerContainer, type DockerContainerAction, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { ContextMenu, type ContextMenuItem } from "../../components/ContextMenu";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { ContainerDetails, type DetailTab } from "./ContainerDetails";
import { CreateContainerWizard } from "./CreateContainerWizard";
import { LoadState, errorMessage, format } from "./shared";

function detailValue(value: unknown, t: Translate): string {
  if (value === null || value === undefined || value === "") return t("common.none");
  if (Array.isArray(value)) return value.length ? value.map(String).join(", ") : t("common.none");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function bytes(value: unknown): string {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount) || amount <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const unit = Math.min(units.length - 1, Math.floor(Math.log(amount) / Math.log(1024)));
  const precision = unit > 0 && amount / 1024 ** unit < 10 ? 1 : 0;
  return `${(amount / 1024 ** unit).toFixed(precision)} ${units[unit]}`;
}

function cpu(value: unknown): string {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
}

function ports(value: unknown): { visible: string; full: string; more: number } {
  const values = (Array.isArray(value) ? value.map(String) : String(value || "").split(",")).map((item) => item.trim()).filter(Boolean);
  return { visible: values.slice(0, 2).join(", ") || "—", full: values.join(", "), more: Math.max(0, values.length - 2) };
}

function stateOf(row: DockerContainer): string { return String(row.State || "unknown").toLowerCase(); }
function healthOf(row: DockerContainer): string { return String(row.Health || "").toLowerCase(); }
function isProblem(row: DockerContainer): boolean { return ["dead", "restarting"].includes(stateOf(row)) || healthOf(row) === "unhealthy"; }


type ContainerWizardMountDraft = {
  id: number;
  type: "bind" | "volume" | "tmpfs";
  source: string;
  target: string;
  readOnly: boolean;
  tmpfsSizeMb: string;
};

type ContainerWizardDraft = {
  step: number;
  name: string;
  image: string;
  network: string;
  ports: string;
  environment: string;
  mounts: ContainerWizardMountDraft[];
  memory: string;
  memorySwap: string;
  cpus: string;
  pids: string;
  hostname: string;
  workingDir: string;
  containerUser: string;
  limitsEnabled: boolean;
  networkAliases: string;
  restartPolicy: "no" | "always" | "unless-stopped" | "on-failure";
  labels: string;
  healthType: "none" | "http" | "tcp";
  healthPort: string;
  healthPath: string;
  readOnly: boolean;
  init: boolean;
  autoStart: boolean;
};

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function positiveNumber(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function duplicateContainerName(value: unknown): string {
  const base = String(value || "container").replace(/^\/+/, "").trim() || "container";
  return `${base.slice(0, 240)}-copy`;
}

function duplicatePorts(value: unknown): string {
  const result: string[] = [];
  for (const [rawTarget, rawBindings] of Object.entries(recordValue(value))) {
    const [target, rawProtocol = "tcp"] = rawTarget.split("/", 2);
    const protocol = rawProtocol === "udp" ? "udp" : "tcp";
    if (!/^\d+$/.test(target)) continue;
    for (const rawBinding of arrayValue(rawBindings)) {
      const binding = recordValue(rawBinding);
      const published = String(binding.HostPort || "").trim();
      if (/^\d+$/.test(published)) result.push(`${published}:${target}/${protocol}`);
    }
  }
  return result.join("\n");
}

function duplicateMounts(value: unknown): ContainerWizardMountDraft[] {
  return arrayValue(value).flatMap((rawMount, index) => {
    const mount = recordValue(rawMount);
    const type = String(mount.Type || "").toLowerCase();
    if (type !== "bind" && type !== "volume" && type !== "tmpfs") return [];
    const source = type === "tmpfs" ? "" : String(type === "volume" ? mount.Name || mount.Source || "" : mount.Source || "");
    const target = String(mount.Destination || "");
    if (!target || (type !== "tmpfs" && !source)) return [];
    return [{
      id: index + 1,
      type,
      source,
      target,
      readOnly: mount.RW === false,
      tmpfsSizeMb: "",
    }];
  });
}

function duplicateLabels(value: unknown): string {
  return Object.entries(recordValue(value))
    .filter(([key, item]) =>
      !key.startsWith("com.docker.compose.")
      && !key.startsWith("io.webnas.")
      && item !== null
      && item !== undefined
      && !String(item).includes("\n"),
    )
    .map(([key, item]) => `${key}=${String(item)}`)
    .join("\n");
}

function duplicateNetwork(details: Record<string, unknown>): { network: string; aliases: string } {
  const networks = recordValue(details.networks);
  const network = Object.keys(networks)[0] || "bridge";
  const sourceName = String(details.name || "").replace(/^\/+/, "");
  const sourceId = String(details.id || "");
  const selected = recordValue(networks[network]);
  const aliases = [...new Set(
    arrayValue(selected.Aliases)
      .map(String)
      .map((item) => item.trim())
      .filter((item) => item && item !== sourceName && item !== sourceId && !sourceId.startsWith(item)),
  )];
  return { network, aliases: aliases.join(", ") };
}

function yamlScalar(value: string): string {
  const trimmed = value.trim();
  if (trimmed === "null" || trimmed === "~") return "";
  if (trimmed.startsWith("'") && trimmed.endsWith("'")) return trimmed.slice(1, -1).replace(/''/g, "'");
  if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
    try { return JSON.parse(trimmed) as string; } catch { return trimmed.slice(1, -1); }
  }
  return trimmed;
}

function duplicateComposeFields(content: string): Pick<ContainerWizardDraft, "hostname" | "workingDir" | "containerUser"> {
  const result = { hostname: "", workingDir: "", containerUser: "" };
  for (const line of content.split("\n")) {
    const match = /^\s{4}(hostname|working_dir|user):\s*(.*)$/.exec(line);
    if (!match) continue;
    const value = yamlScalar(match[2]);
    if (match[1] === "hostname") result.hostname = value;
    else if (match[1] === "working_dir") result.workingDir = value;
    else result.containerUser = value;
  }
  return result;
}

function duplicateDraft(details: Record<string, unknown>, row: DockerContainer): ContainerWizardDraft {
  const limits = recordValue(details.limits);
  const state = recordValue(details.state);
  const memoryBytes = positiveNumber(limits.memory);
  const memorySwapBytes = positiveNumber(limits.memory_swap);
  const nanoCpus = positiveNumber(limits.nano_cpus);
  const pids = positiveNumber(limits.pids);
  const memory = memoryBytes ? String(Math.max(1, Math.round(memoryBytes / 1024 / 1024))) : "";
  const memorySwap = memorySwapBytes ? String(Math.max(1, Math.round(memorySwapBytes / 1024 / 1024))) : "";
  const cpus = nanoCpus ? String(nanoCpus / 1_000_000_000) : "";
  const restart = String(details.restart_policy || "no");
  const restartPolicy: ContainerWizardDraft["restartPolicy"] = ["no", "always", "unless-stopped", "on-failure"].includes(restart)
    ? restart as ContainerWizardDraft["restartPolicy"]
    : "no";
  const network = duplicateNetwork(details);
  return {
    step: 0,
    name: duplicateContainerName(details.name || row.Names),
    image: String(details.image || row.Image || ""),
    network: network.network,
    ports: duplicatePorts(details.ports),
    environment: "",
    mounts: duplicateMounts(details.mounts),
    memory,
    memorySwap,
    cpus,
    pids: pids ? String(pids) : "",
    hostname: "",
    workingDir: "",
    containerUser: "",
    limitsEnabled: Boolean(memory || memorySwap || cpus || pids),
    networkAliases: network.aliases,
    restartPolicy,
    labels: duplicateLabels(details.labels),
    healthType: "none",
    healthPort: "",
    healthPath: "/",
    readOnly: Boolean(details.read_only),
    init: true,
    autoStart: state.Running === undefined ? true : Boolean(state.Running),
  };
}

type SelectedContainer = { target: string; tab: DetailTab };
type ContainerMenu = { x: number; y: number; target: string; row: DockerContainer; portalTarget: Element | null };

export function ContainersList({
  draftKey,
  permissions,
  t,
  toast,
  onJob,
}: {
  draftKey?: string;
  permissions: string[];
  t: Translate;
  toast: ToastFn;
  onJob: (job: ModuleJob) => void;
}) {
  const [items, setItems] = useState<DockerContainer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [state, setState] = useState("all");
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [sort, setSort] = useState("Names");
  const [direction, setDirection] = useState<"asc" | "desc">("asc");
  const [selected, setSelected] = useState<SelectedContainer | null>(null);
  const [menu, setMenu] = useState<ContainerMenu | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const fallbackDraftKey = useRef(`docker:create-container:${Math.random().toString(36).slice(2)}`);
  const wizardDraftKey = draftKey || fallbackDraftKey.current;
  const [wizard, setWizard] = useState(() => Boolean(sessionStorage.getItem(wizardDraftKey)));
  const [importFile, setImportFile] = useState<File | null>(null);
  const importInput = useRef<HTMLInputElement>(null);
  const [dialog, setDialog] = useState<{
    target: string;
    action: "remove" | "backup" | "export" | "rename" | "import" | "stop" | "kill";
  } | null>(null);
  function openWizard() { if (!sessionStorage.getItem(wizardDraftKey)) sessionStorage.setItem(wizardDraftKey, "{}"); setWizard(true); }
  function closeWizard() { sessionStorage.removeItem(wizardDraftKey); setWizard(false); }
  async function openDuplicateWizard(row: DockerContainer, target: string) {
    setMenu(null);
    try {
      const [details, compose] = await Promise.all([
        api.dockerContainer(target),
        api.dockerContainerCompose(target).catch(() => null),
      ]);
      const draft = duplicateDraft(details, row);
      if (compose) Object.assign(draft, duplicateComposeFields(compose.content));
      sessionStorage.setItem(wizardDraftKey, JSON.stringify(draft));
      setWizard(true);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await api.dockerContainers({ search, state: state === "problems" ? "all" : state, page, page_size: 50, sort, direction });
      setItems(result.items);
      setPages(result.pages);
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setLoading(false);
    }
  }, [direction, page, search, sort, state, t]);
  useEffect(() => setPage(1), [direction, search, sort, state]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 180);
    return () => window.clearTimeout(timer);
  }, [load]);
  async function action(target: string, name: DockerContainerAction["action"]) {
    try {
      onJob(
        (
          await api.dockerContainerAction(target, {
            action: name,
            confirmation: ["remove", "kill", "recreate", "update"].includes(
              name,
            )
              ? target
              : "",
          })
        ).job,
      );
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  async function exportCompose(target: string) {
    try {
      const result = await api.dockerContainerCompose(target);
      const url = URL.createObjectURL(new Blob([result.content], { type: "application/yaml;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${target}-compose.yaml`;
      anchor.click();
      URL.revokeObjectURL(url);
      if (result.secrets_omitted) toast(t("docker.composeSecretsOmitted"), "ok", "admin");
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  async function submit(values: Record<string, string>) {
    if (!dialog) return;
    try {
      if (dialog.action === "import" && !importFile) throw new Error(t("docker.importFileMissing"));
      const result = dialog.action === "import"
        ? await api.importDockerContainerFilesystem(importFile as File, values.repository)
        : dialog.action === "export"
          ? await api.dockerContainerExport(dialog.target)
        : dialog.action === "backup"
        ? await api.dockerContainerBackup(dialog.target)
        : await api.dockerContainerAction(dialog.target,
            dialog.action === "stop" || dialog.action === "kill"
              ? {
                  action: dialog.action,
                  timeout: Number(values.timeout || 10),
                  signal: (values.signal || "KILL") as DockerContainerAction["signal"],
                  confirmation: dialog.action === "kill" ? values.confirmation : "",
                }
              : dialog.action === "remove"
              ? {
              action: "remove",
              force: values.force === "true",
              confirmation: values.confirmation,
              pam_password: values.pam_password,
                }
              : {
                  action: dialog.action,
                  new_name: values.new_name,
                  confirmation: "",
                },
          );
      onJob(result.job);
      setDialog(null);
      setImportFile(null);
      if (importInput.current) importInput.current.value = "";
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  function openDetails(target: string, tab: DetailTab = "overview") { setMenu(null); setSelected({ target, tab }); }
  function menuItems(row: DockerContainer, target: string): ContextMenuItem[] {
    const running = stateOf(row) === "running";
    const paused = stateOf(row) === "paused";
    const regular: ContextMenuItem[] = [];
    if (permissions.includes("docker.inspect_container")) {
      regular.push(
        { label: t("docker.details"), icon: <Eye />, action: () => openDetails(target) },
        { label: t("docker.detail.logs"), icon: <FileText />, action: () => openDetails(target, "logs") },
        { label: t("docker.console"), icon: <TerminalSquare />, action: () => openDetails(target, "processes") },
      );
    }
    if (!running && !paused && permissions.includes("docker.start_container")) regular.push({ label: t("module.start"), icon: <Play />, action: () => void action(target, "start") });
    if (running && permissions.includes("docker.stop_container")) regular.push({ label: t("module.stop"), icon: <Square />, action: () => setDialog({ target, action: "stop" }) });
    if (permissions.includes("docker.restart_container")) regular.push({ label: t("module.restart"), icon: <RotateCcw />, action: () => void action(target, "restart") });
    if (running && permissions.includes("docker.stop_container")) regular.push({ label: t("docker.pause"), action: () => void action(target, "pause") });
    if (paused && permissions.includes("docker.start_container")) regular.push({ label: t("docker.unpause"), icon: <Play />, action: () => void action(target, "unpause") });
    if (permissions.includes("docker.create_container")) regular.push(
      { label: t("docker.rename"), icon: <Pencil />, action: () => setDialog({ target, action: "rename" }) },
      { label: t("docker.duplicate"), icon: <Copy />, action: () => void openDuplicateWizard(row, target) },
      { label: t("docker.recreate"), icon: <RefreshCw />, action: () => void action(target, "recreate") },
    );
    if (permissions.includes("docker.inspect_container")) regular.push({ label: t("docker.generateCompose"), icon: <FileText />, action: () => void exportCompose(target) });
    if (permissions.includes("docker.pull_image")) regular.push(
      { label: t("docker.checkUpdate"), icon: <RefreshCw />, action: () => void action(target, "check_update") },
      { label: t("store.update"), icon: <RefreshCw />, action: () => void action(target, "update") },
    );
    if (permissions.includes("docker.export_backup")) regular.push(
      { label: t("docker.exportContainer"), icon: <Upload />, action: () => setDialog({ target, action: "export" }) },
      { label: t("docker.backup"), icon: <Archive />, action: () => setDialog({ target, action: "backup" }) },
    );
    const danger: ContextMenuItem[] = [];
    if (permissions.includes("docker.stop_container")) danger.push({ label: t("docker.kill"), danger: true, separator: true, action: () => setDialog({ target, action: "kill" }) });
    if (permissions.includes("docker.remove_container")) danger.push({ label: t("action.delete"), icon: <Trash2 />, danger: true, separator: danger.length === 0, action: () => setDialog({ target, action: "remove" }) });
    return [...regular, ...danger];
  }
  const visibleItems = useMemo(() => state === "problems" ? items.filter(isProblem) : items, [items, state]);
  const counts = useMemo(() => ({
    all: items.length,
    running: items.filter((row) => stateOf(row) === "running").length,
    exited: items.filter((row) => ["exited", "stopped"].includes(stateOf(row))).length,
    paused: items.filter((row) => stateOf(row) === "paused").length,
    problems: items.filter(isProblem).length,
  }), [items]);

  if (selected)
    return (
      <ContainerDetails
        target={selected.target}
        initialTab={selected.tab}
        t={t}
        onBack={() => setSelected(null)}
        permissions={permissions}
        toast={toast}
        onJob={onJob}
      />
    );
  return (
    <>
      <section>
        <header className="docker-containers-header">
          <div><h2>{t("docker.section.containers")}</h2><p>{t("docker.containersSubtitle")}</p></div>
          <div className="docker-containers-header-actions">
            {permissions.includes("docker.restore_backup") && <>
              <input ref={importInput} className="visually-hidden" type="file" accept=".tar,.tar.gz,.tgz" onChange={(event) => {
                const file = event.target.files?.[0] || null;
                setImportFile(file);
                if (file) setDialog({ action: "import", target: "" });
              }} />
              <button title={t("docker.importContainerFilesystem")} onClick={() => importInput.current?.click()}><Upload />{t("docker.importContainer")}</button>
            </>}
            {permissions.includes("docker.create_container") && <button className="button-primary" onClick={openWizard}><Plus />{t("docker.createContainer")}</button>}
          </div>
        </header>
        <div className="docker-container-summary" aria-label={t("docker.currentResults")}>
          {(["all", "running", "exited", "paused", "problems"] as const).map((value) => <button type="button" className={state === value ? "active summary-" + value : "summary-" + value} aria-pressed={state === value} onClick={() => setState(value)} key={value}><span>{t("docker.summary." + value)}</span><strong>{counts[value]}</strong></button>)}
          <small>{t("docker.currentResults")}</small>
        </div>
        <div className="docker-section-toolbar docker-containers-toolbar">
          <label className="docker-search">
            <Search />
            <span className="visually-hidden">{t("action.search")}</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("docker.searchContainers")}
            />
          </label>
          <div className="docker-toolbar-filters" aria-label={t("docker.filters")}>
          <select
            aria-label={t("docker.filterState")}
            value={state}
            onChange={(event) => setState(event.target.value)}
          >
            {["all", "running", "exited", "paused", "dead", "problems"].map((value) => (
              <option value={value} key={value}>
                {t(`docker.state.${value}`)}
              </option>
            ))}
          </select>
          <select aria-label={t("docker.sortBy")} value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="Names">{t("docker.field.name")}</option>
            <option value="Image">{t("docker.field.image")}</option>
            <option value="State">{t("docker.field.state")}</option>
            <option value="CreatedAt">{t("docker.field.created")}</option>
          </select>
          </div>
          <div className="docker-toolbar-actions">
          <button className="docker-sort-direction" aria-label={t("docker.sortDirection")} title={t(direction === "asc" ? "docker.sortAscending" : "docker.sortDescending")} aria-pressed={direction === "desc"} onClick={() => setDirection((value) => value === "asc" ? "desc" : "asc")}>{direction === "asc" ? <ArrowUp /> : <ArrowDown />}</button>
          <button className="docker-refresh-icon" aria-label={t("action.refresh")} title={t("action.refresh")} onClick={() => void load()}><RefreshCw /></button>
          </div>
        </div>
        <LoadState
          loading={loading}
          error={error}
          retry={() => void load()}
          t={t}
        >
          {visibleItems.length ? <div className="docker-table-wrap docker-containers-table-wrap">
            <table className="docker-table docker-containers-table">
              <thead><tr>
                <th>{t("docker.container")}</th>
                <th>{t("docker.field.status")}</th>
                <th>{t("docker.cpu")}</th>
                <th>{t("docker.memory")}</th>
                <th>{t("docker.field.ports")}</th>
                <th>{t("docker.field.actions")}</th>
              </tr></thead>
              <tbody>{visibleItems.map((row) => {
                const target = String(row.ID || row.Names || "unknown-container");
                const stateValue = String(row.State || "unknown").toLowerCase();
                const knownStates = ["created", "running", "paused", "restarting", "removing", "exited", "dead", "stopped"];
                const displayedState = knownStates.includes(stateValue) ? stateValue : "unknown";
                const running = stateValue === "running";
                const paused = stateValue === "paused";
                const health = healthOf(row);
                const statusTone = health === "unhealthy" || stateValue === "dead" ? "danger" : stateValue === "restarting" || health === "starting" ? "warning" : stateValue === "running" ? "success" : stateValue === "paused" ? "paused" : "neutral";
                const portList = ports(row.Ports);
                const isExpanded = expanded.has(target);
                const detailsId = `docker-container-details-${target.replace(/[^A-Za-z0-9_-]/g, "-")}`;
                const detailFields: Array<[string, unknown]> = [
                  ["docker.field.id", row.ID], ["docker.field.image", row.Image], ["docker.field.digest", row.Digest],
                  ["docker.field.ports", row.Ports], ["docker.field.networks", row.Networks],
                  ["docker.field.mounts", Array.isArray(row.Mounts) ? row.Mounts.length : row.Mounts],
                  ["docker.field.restart_policy", row.RestartPolicy], ["docker.field.created", row.CreatedAt],
                  ["docker.field.networkIo", `${bytes(row.NetworkInputBytes)} / ${bytes(row.NetworkOutputBytes)}`],
                  ["docker.field.blockIo", `${bytes(row.BlockReadBytes)} / ${bytes(row.BlockWriteBytes)}`],
                  ["docker.field.management", row.Management ? t(`docker.management.${String(row.Management)}`) : ""],
                  ["docker.field.size", row.Size],
                ];
                return <Fragment key={target}>
                  <tr
                    className="docker-container-row"
                    onContextMenu={(event) => {
                      const items = menuItems(row, target);
                      if (!items.length) return;
                      event.preventDefault();
                      event.stopPropagation();
                      setMenu({
                        x: event.clientX,
                        y: event.clientY,
                        target,
                        row,
                        portalTarget: event.currentTarget.closest(".desktop"),
                      });
                    }}
                  >
                    <td className="docker-container-name"><div className="docker-container-identity"><span className="docker-container-icon" aria-hidden="true"><Boxes /></span><span>{permissions.includes("docker.inspect_container") ? <button type="button" className="docker-container-link" onClick={() => openDetails(target)}>{format(row.Names)}</button> : <strong>{format(row.Names)}</strong>}{Boolean(row.Image) && <small>{String(row.Image)}</small>}{Boolean(row.ID) && <code>{String(row.ID).slice(0, 12)}</code>}</span></div><button type="button" className="docker-details-toggle" aria-expanded={isExpanded} aria-controls={detailsId} onClick={() => setExpanded((current) => {
                      const next = new Set(current); if (next.has(target)) next.delete(target); else next.add(target); return next;
                    })}>{isExpanded ? <ChevronUp /> : <ChevronDown />}<span>{t(isExpanded ? "docker.hideTechnicalDetails" : "docker.showTechnicalDetails")}</span></button></td>
                    <td className={`docker-container-status status-${statusTone}`}><span><i aria-hidden="true" />{t(`docker.state.${displayedState}`)}</span><small>{health || String(row.Status || "—")}</small></td>
                    <td className="docker-container-metric">{cpu(row.CpuPercent)}</td>
                    <td className="docker-container-metric">{row.MemoryBytes === null || row.MemoryBytes === undefined ? "—" : bytes(row.MemoryBytes)}</td>
                    <td className="docker-container-ports" title={portList.full || undefined}><span>{portList.visible}</span>{portList.more > 0 && <b>+{portList.more}</b>}</td>
                    <td><div className="docker-row-actions docker-container-actions">
                      {running && permissions.includes("docker.stop_container") ? <button type="button" aria-label={t("module.stop")} title={t("module.stop")} onClick={() => setDialog({ target, action: "stop" })}><Square /></button>
                        : paused && permissions.includes("docker.start_container") ? <button type="button" aria-label={t("docker.unpause")} title={t("docker.unpause")} onClick={() => void action(target, "unpause")}><Play /></button>
                          : !running && permissions.includes("docker.start_container") && <button type="button" aria-label={t("module.start")} title={t("module.start")} onClick={() => void action(target, "start")}><Play /></button>}
                      {permissions.includes("docker.restart_container") && <button type="button" aria-label={t("module.restart")} title={t("module.restart")} onClick={() => void action(target, "restart")}><RotateCcw /></button>}
                      {menuItems(row, target).length > 0 && <button type="button" className="docker-more-actions" aria-label={t("docker.moreActions")} title={t("docker.moreActions")} aria-haspopup="menu" aria-expanded={menu?.target === target} onClick={(event) => { const rect = event.currentTarget.getBoundingClientRect(); setMenu({ x: rect.right - 224, y: rect.bottom + 4, target, row, portalTarget: event.currentTarget.closest(".desktop") }); }}><MoreVertical /></button>}
                    </div></td>
                  </tr>
                  {isExpanded && <tr id={detailsId} className="docker-container-details-row"><td colSpan={6}>
                    <dl className="docker-container-detail-grid">{detailFields.map(([label, value]) => <div key={label}><dt>{t(label)}</dt><dd className={label === "docker.field.digest" ? "docker-container-detail-long" : undefined}>{detailValue(value, t)}</dd></div>)}</dl>
                  </td></tr>}
                </Fragment>;
              })}</tbody>
            </table>
          </div> : <div className="empty-state"><strong>{t("docker.noContainers")}</strong></div>}
          {pages > 1 && (
            <div className="docker-pagination">
              <button disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>{t("action.previous")}</button>
              <span>{page} / {pages}</span>
              <button disabled={page >= pages} onClick={() => setPage((value) => Math.min(pages, value + 1))}>{t("action.next")}</button>
            </div>
          )}
        </LoadState>
      </section>
      {menu && <ContextMenu className="docker-container-context-menu" portalTarget={menu.portalTarget} x={menu.x} y={menu.y} items={menuItems(menu.row, menu.target)} onClose={() => setMenu(null)} />}
      {wizard && (
        <CreateContainerWizard
          t={t}
          toast={toast}
          draftKey={wizardDraftKey}
          onClose={closeWizard}
          onStarted={onJob}
          canImportCompose={permissions.includes("docker.manage_compose")}
          canViewLocalImages={permissions.includes("docker.view_images")}
          canViewLocalNetworks={permissions.includes("docker.manage_networks") || permissions.includes("docker.create_container")}
        />
      )}
      {dialog && (
        <AdminActionDialog
          title={t(
            dialog.action === "backup"
              ? "docker.backup"
              : dialog.action === "export"
                ? "docker.exportContainer"
              : dialog.action === "import"
                ? "docker.importContainerFilesystem"
              : dialog.action === "stop"
                ? "module.stop"
              : dialog.action === "kill"
                ? "docker.kill"
              : dialog.action === "remove"
                ? "docker.removeContainer"
                : `docker.${dialog.action}`,
          )}
          danger={dialog.action === "remove" || dialog.action === "import"}
          fields={
            dialog.action === "import"
              ? [
                  { name: "repository", label: t("docker.importTargetImage"), required: true },
                ]
              : dialog.action === "stop"
                ? [{ name: "timeout", label: t("docker.stopTimeout"), type: "number", value: "10", required: true }]
              : dialog.action === "kill"
                ? [
                    { name: "signal", label: t("docker.killSignal"), type: "select", value: "KILL", options: ["KILL", "TERM", "HUP", "INT", "QUIT", "USR1", "USR2"].map((value) => ({ value, label: value })) },
                    { name: "confirmation", label: t("docker.exactConfirmation"), value: dialog.target, required: true },
                  ]
              : dialog.action === "remove"
              ? [
                  {
                    name: "confirmation",
                    label: t("docker.exactConfirmation"),
                    value: dialog.target,
                    required: true,
                  },
                  {
                    name: "force",
                    label: t("docker.forceRemove"),
                    type: "select",
                    value: "false",
                    options: [
                      { value: "false", label: t("common.no") },
                      { value: "true", label: t("common.yes") },
                    ],
                  },
                  {
                    name: "pam_password",
                    label: t("docker.currentPassword"),
                    type: "password",
                  },
                ]
              : dialog.action === "rename"
                ? [
                    {
                      name: "new_name",
                      label: t("docker.newContainerName"),
                      required: true,
                    },
                  ]
                : []
          }
          t={t}
          onClose={() => setDialog(null)}
          onSubmit={submit}
        />
      )}
    </>
  );
}
