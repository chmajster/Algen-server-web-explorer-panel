import {
  ArrowLeft,
  Boxes,
  Database,
  FileJson,
  Folder,
  FolderOpen,
  HardDrive,
  Minus,
  Plus,
  RefreshCw,
  ScrollText,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type DockerContainerCreate, type DockerHostResources, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { errorMessage } from "./shared";
import { ConfigRow, ConfigSection, KeyValueRows } from "./create-container/CompactConfig";
import {
  ResourceLimitsSection,
  resourceLimitIssues,
  resourceLimitsFromPayload,
  resourceLimitsPayload,
  resourceSummary,
  type ResourceLimitsDraft,
  type ResourceProfile,
} from "./create-container/ResourceLimitsSection";

function pairs(value: string, invalidMessage: string): Record<string, string> {
  return Object.fromEntries(
    value
      .split("\n")
      .filter((line) => Boolean(line.trim()))
      .map((line) => {
        if (line.endsWith("\r")) line = line.slice(0, -1);
        const index = line.indexOf("=");
        if (index < 1) throw new Error(invalidMessage);
        return [line.slice(0, index), line.slice(index + 1)];
      }),
  );
}

type MountRow = {
  id: number;
  type: "bind" | "volume" | "tmpfs";
  source: string;
  target: string;
  readOnly: boolean;
  tmpfsSizeMb: string;
};

type PortRow = {
  id: number;
  published: string;
  target: string;
  protocol: "tcp" | "udp";
};

type EditablePair = { id: number; key: string; value: string };

function portRows(value: string): PortRow[] {
  return value.split("\n").map((line) => line.trim()).filter(Boolean).map((line, index) => {
    const match = /^(\d*):(\d*)(?:\/(tcp|udp))?$/.exec(line);
    return { id: index + 1, published: match?.[1] || "", target: match?.[2] || "", protocol: (match?.[3] || "tcp") as "tcp" | "udp" };
  });
}

function editablePairs(value: string): EditablePair[] {
  return value.split("\n").map((line) => line.trim()).filter(Boolean).map((line, index) => {
    const separator = line.indexOf("=");
    return { id: index + 1, key: separator < 0 ? line : line.slice(0, separator), value: separator < 0 ? "" : line.slice(separator + 1) };
  });
}

function pairLines(rows: EditablePair[]): string {
  return rows.filter((row) => row.key || row.value).map((row) => `${row.key}=${row.value}`).join("\n");
}

function validEntrypoint(value: string): boolean {
  const normalized = value.trim();
  if (!normalized) return true;
  if (!normalized.startsWith("/")) return /^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$/.test(normalized);
  const segments = normalized.split("/").slice(1);
  return /^\/[A-Za-z0-9._+@%/-]{1,511}$/.test(normalized)
    && segments.every((segment) => segment !== "" && segment !== "." && segment !== "..");
}

type ContainerWizardDraft = {
  step?: number; name?: string; image?: string; network?: string; ports?: string; environment?: string; mounts?: MountRow[];
  memory?: string; memorySwap?: string; cpus?: string; pids?: string; hostname?: string; entrypoint?: string; workingDir?: string; containerUser?: string;
  limitsEnabled?: boolean; resourceProfile?: ResourceProfile; resourceLimits?: ResourceLimitsDraft;
  networkAliases?: string; restartPolicy?: "no" | "always" | "unless-stopped" | "on-failure"; labels?: string;
  healthType?: "none" | "http" | "tcp"; healthPort?: string; healthPath?: string; readOnly?: boolean; init?: boolean; autoStart?: boolean;
  composeMode?: boolean; composeProject?: string; composeContent?: string; composeEnvironment?: string; composeAutoStart?: boolean;
};

function readContainerDraft(key?: string): ContainerWizardDraft {
  if (!key) return {};
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || "{}") as ContainerWizardDraft;
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function DockerPathPicker({ initialPath, t, onClose, onSelect }: { initialPath: string; t: Translate; onClose: () => void; onSelect: (path: string) => void }) {
  const [path, setPath] = useState(initialPath);
  const [parent, setParent] = useState<string | null>(null);
  const [folders, setFolders] = useState<Array<{ name: string; path: string }>>([]);
  const [roots, setRoots] = useState<Array<{ name: string; path: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const open = useCallback(async (next?: string) => {
    setLoading(true);
    try {
      const result = await api.list(next, { page_size: 200, sort: "name", direction: "asc" });
      setPath(result.current_path);
      setParent(result.parent_path);
      setFolders(result.items.filter((item) => item.is_dir).map((item) => ({ name: item.name, path: item.path })));
      setError("");
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void open(initialPath || undefined);
    void Promise.allSettled([api.localDisks(), api.mountRoots()]).then(([disks, mounts]) => {
      setRoots([
        ...(disks.status === "fulfilled" ? disks.value.map((item) => ({ name: item.name, path: item.mount_point })) : []),
        ...(mounts.status === "fulfilled" ? mounts.value.map((item) => ({ name: item.name, path: item.mount_point })) : []),
      ]);
    });
  }, [initialPath, open]);

  return createPortal(
    <div className="modal-backdrop docker-path-picker-backdrop">
      <section className="modal-panel docker-path-picker" role="dialog" aria-modal="true" aria-labelledby="docker-path-picker-title">
        <header className="modal-header"><h2 id="docker-path-picker-title">{t("docker.chooseHostPath")}</h2><button className="icon-button" type="button" aria-label={t("action.close")} onClick={onClose}><X /></button></header>
        <div className="docker-path-picker-toolbar">
          <button type="button" aria-label={t("docker.parentFolder")} disabled={!parent || loading} onClick={() => void open(parent || undefined)}><ArrowLeft /></button>
          <code title={path}>{path || t("status.loading")}</code>
          <button type="button" aria-label={t("action.refresh")} disabled={loading} onClick={() => void open(path || undefined)}><RefreshCw /></button>
        </div>
        <div className="docker-path-picker-body">
          {roots.length > 0 && <div className="docker-path-roots">{roots.map((item) => <button type="button" key={item.path} onClick={() => void open(item.path)}><HardDrive /><span>{item.name}</span><small>{item.path}</small></button>)}</div>}
          {error ? <div className="error-state"><strong>{t("status.error")}</strong><span>{error}</span><button type="button" onClick={() => void open(path || undefined)}>{t("action.retry")}</button></div>
            : loading ? <div className="loading-state">{t("status.loading")}</div>
            : folders.length ? <div className="docker-path-folders">{folders.map((item) => <button type="button" key={item.path} onDoubleClick={() => void open(item.path)} onClick={() => void open(item.path)}><Folder /><span>{item.name}</span></button>)}</div>
            : <div className="empty-state"><FolderOpen /><strong>{t("docker.noSubfolders")}</strong></div>}
        </div>
        <footer className="modal-footer"><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className="button-primary" type="button" disabled={!path || loading} onClick={() => onSelect(path)}>{t("docker.chooseCurrentFolder")}</button></footer>
      </section>
    </div>,
    document.body,
  );
}

export function CreateContainerWizard({
  draftKey,
  t,
  toast,
  onClose,
  onStarted,
  canImportCompose,
  canViewLocalImages,
  canViewLocalNetworks,
}: {
  draftKey?: string;
  t: Translate;
  toast: ToastFn;
  onClose: () => void;
  onStarted: (job: ModuleJob) => void;
  canImportCompose: boolean;
  canViewLocalImages: boolean;
  canViewLocalNetworks: boolean;
}) {
  const [draft] = useState(() => readContainerDraft(draftKey));
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState(draft.name || "");
  const [image, setImage] = useState(draft.image || "");
  const [network, setNetwork] = useState(draft.network || "bridge");
  const [ports, setPorts] = useState(draft.ports || "");
  const [portEntries, setPortEntries] = useState<PortRow[]>(() => portRows(draft.ports || ""));
  const nextPortId = useRef(Math.max(0, ...portRows(draft.ports || "").map((row) => row.id)) + 1);
  const [environment, setEnvironment] = useState(draft.environment || "");
  const [environmentRows, setEnvironmentRows] = useState<EditablePair[]>(() => editablePairs(draft.environment || ""));
  const [environmentTextMode, setEnvironmentTextMode] = useState(false);
  const nextEnvironmentId = useRef(Math.max(0, ...editablePairs(draft.environment || "").map((row) => row.id)) + 1);
  const [secretRows, setSecretRows] = useState<EditablePair[]>([{ id: 1, key: "", value: "" }]);
  const nextSecretId = useRef(2);
  const [mounts, setMounts] = useState<MountRow[]>(() => Array.isArray(draft.mounts) ? draft.mounts : []);
  const [pathPickerMountId, setPathPickerMountId] = useState<number | null>(null);
  const nextMountId = useRef(Math.max(0, ...(draft.mounts || []).map((item) => Number(item.id) || 0)) + 1);
  const [resourceLimits, setResourceLimits] = useState<ResourceLimitsDraft>(() => draft.resourceLimits || resourceLimitsFromPayload({
    memory_mb: draft.memory ? Number(draft.memory) : null, memory_swap_mb: draft.memorySwap ? Number(draft.memorySwap) : null,
    cpus: draft.cpus ? Number(draft.cpus) : null, pids: draft.pids ? Number(draft.pids) : null,
  }));
  const [hostname, setHostname] = useState(draft.hostname || "");
  const [entrypoint, setEntrypoint] = useState(draft.entrypoint || "");
  const [workingDir, setWorkingDir] = useState(draft.workingDir || "");
  const [containerUser, setContainerUser] = useState(draft.containerUser || "");
  const [networkAliases, setNetworkAliases] = useState(draft.networkAliases || "");
  const [restartPolicy, setRestartPolicy] = useState<"no" | "always" | "unless-stopped" | "on-failure">(draft.restartPolicy || "unless-stopped");
  const [labels, setLabels] = useState(draft.labels || "");
  const [labelRows, setLabelRows] = useState<EditablePair[]>(() => editablePairs(draft.labels || ""));
  const [labelsTextMode, setLabelsTextMode] = useState(false);
  const nextLabelId = useRef(Math.max(0, ...editablePairs(draft.labels || "").map((row) => row.id)) + 1);
  const [healthType, setHealthType] = useState<"none" | "http" | "tcp">(draft.healthType || "none");
  const [healthPort, setHealthPort] = useState(draft.healthPort || "");
  const [healthPath, setHealthPath] = useState(draft.healthPath || "/");
  const [readOnly, setReadOnly] = useState(draft.readOnly || false);
  const [init, setInit] = useState(draft.init ?? true);
  const [autoStart, setAutoStart] = useState(draft.autoStart ?? true);
  const [limitsEnabled, setLimitsEnabled] = useState(draft.limitsEnabled ?? Boolean(draft.resourceLimits || draft.memory || draft.memorySwap || draft.cpus || draft.pids));
  const [resourceProfile, setResourceProfile] = useState<ResourceProfile>(draft.resourceProfile || (draft.limitsEnabled === false ? "unlimited" : "custom"));
  const [hostResources, setHostResources] = useState<DockerHostResources | null>(null);
  const resourceLimitsTouched = useRef(false);
  const [composeMode, setComposeMode] = useState(draft.composeMode || false);
  const [composeProject, setComposeProject] = useState(draft.composeProject || "");
  const [composeContent, setComposeContent] = useState(draft.composeContent || "");
  const [composeEnvironment, setComposeEnvironment] = useState(draft.composeEnvironment || "");
  const [composeSecretEnvironment, setComposeSecretEnvironment] = useState("");
  const [composeAutoStart, setComposeAutoStart] = useState(draft.composeAutoStart ?? true);
  const [localImages, setLocalImages] = useState<string[]>([]);
  const [imagesLoading, setImagesLoading] = useState(false);
  const [imagePickerOpen, setImagePickerOpen] = useState(false);
  const [localNetworks, setLocalNetworks] = useState<string[]>(["bridge"]);
  const [networksLoading, setNetworksLoading] = useState(false);
  const [networkPickerOpen, setNetworkPickerOpen] = useState(false);
  const [networkFilterActive, setNetworkFilterActive] = useState(false);
  const configUpload = useRef<HTMLInputElement>(null);
  const composeUpload = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && pathPickerMountId === null) onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose, pathPickerMountId]);

  useEffect(() => {
    let active = true;
    api.dockerContainerDefaultsPolicy()
      .then((policy) => {
        if (!active) return;
        if (resourceLimitsTouched.current || draft.limitsEnabled !== undefined || draft.resourceLimits || draft.memory || draft.memorySwap || draft.cpus || draft.pids) return;
        setLimitsEnabled(policy.resource_limits_enabled);
        setResourceProfile(policy.resource_limits_enabled ? "custom" : "unlimited");
        setResourceLimits(resourceLimitsFromPayload({ memory_mb: policy.memory_mb, memory_swap_mb: policy.memory_swap_mb, cpus: policy.cpus, pids: policy.pids }));
      })
      .catch(() => {
        if (!active || resourceLimitsTouched.current || draft.limitsEnabled !== undefined || draft.resourceLimits || draft.memory || draft.memorySwap || draft.cpus || draft.pids) return;
        const fallback = { resource_limits_enabled: true, memory_mb: 512, memory_swap_mb: 1024, cpus: 1, pids: 128 };
        setLimitsEnabled(true);
        setResourceProfile("custom");
        setResourceLimits(resourceLimitsFromPayload(fallback));
      });
    api.dockerHostResources().then((value) => { if (active) setHostResources(value); }).catch(() => { if (active) setHostResources(null); });
    return () => { active = false; };
  }, [draft.cpus, draft.limitsEnabled, draft.memory, draft.memorySwap, draft.pids, draft.resourceLimits]);

  function addMount(values: Partial<Omit<MountRow, "id">> = {}) {
    setMounts((current) => [...current, {
      id: nextMountId.current++,
      type: values.type || "bind",
      source: values.source || "",
      target: values.target || "",
      readOnly: values.readOnly || false,
      tmpfsSizeMb: values.tmpfsSizeMb || "",
    }]);
  }

  function updateMount(id: number, values: Partial<Omit<MountRow, "id">>) {
    setMounts((current) => current.map((item) => item.id === id ? { ...item, ...values } : item));
  }

  function setPortsFromRows(updater: (rows: PortRow[]) => PortRow[]) {
    setPortEntries((current) => {
      const next = updater(current);
      setPorts(next.map((row) => `${row.published}:${row.target}/${row.protocol}`).join("\n"));
      return next;
    });
  }

  function setEnvironmentFromRows(updater: (rows: EditablePair[]) => EditablePair[]) {
    setEnvironmentRows((current) => {
      const next = updater(current);
      setEnvironment(pairLines(next));
      return next;
    });
  }

  function setLabelsFromRows(updater: (rows: EditablePair[]) => EditablePair[]) {
    setLabelRows((current) => {
      const next = updater(current);
      setLabels(pairLines(next));
      return next;
    });
  }

  useEffect(() => {
    if (!draftKey) return;
    const value: ContainerWizardDraft = {
      step: 0, name, image, network, ports, environment, mounts, limitsEnabled, resourceProfile, resourceLimits, hostname, entrypoint, workingDir,
      containerUser, networkAliases, restartPolicy, labels, healthType, healthPort, healthPath, readOnly, init, autoStart,
      composeMode, composeProject, composeContent, composeEnvironment, composeAutoStart,
    };
    sessionStorage.setItem(draftKey, JSON.stringify(value));
  }, [autoStart, composeAutoStart, composeContent, composeEnvironment, composeMode, composeProject, containerUser, draftKey, entrypoint, environment, healthPath, healthPort, healthType, hostname, image, init, labels, limitsEnabled, mounts, name, network, networkAliases, ports, readOnly, resourceLimits, resourceProfile, restartPolicy, workingDir]);

  useEffect(() => {
    if (!canViewLocalImages) return;
    let active = true;
    const timer = window.setTimeout(() => {
      setImagesLoading(true);
      void api.dockerImages({ search: image.trim(), page_size: 50, sort: "Repository", direction: "asc" })
        .then((result) => {
          if (!active) return;
          const references = result.items
            .map((item) => {
              const repository = String(item.Repository || "");
              const tag = String(item.Tag || "");
              return repository && repository !== "<none>" ? `${repository}:${tag && tag !== "<none>" ? tag : "latest"}` : "";
            })
            .filter(Boolean);
          setLocalImages([...new Set(references)]);
        })
        .catch(() => { if (active) setLocalImages([]); })
        .finally(() => { if (active) setImagesLoading(false); });
    }, 180);
    return () => { active = false; window.clearTimeout(timer); };
  }, [canViewLocalImages, image]);

  const imageSuggestions = useMemo(() => {
    const needle = image.trim().toLowerCase();
    return localImages.filter((item) => !needle || item.toLowerCase().includes(needle)).slice(0, 12);
  }, [image, localImages]);

  useEffect(() => {
    if (!canViewLocalNetworks) return;
    let active = true;
    const timer = window.setTimeout(() => {
      setNetworksLoading(true);
      void api.dockerNetworks("")
        .then((result) => {
          if (!active) return;
          const names = result.items
            .map((item) => String(item.Name || ""))
            .filter((item) => item && item !== "host" && item !== "none");
          setLocalNetworks([...new Set(names)]);
        })
        .catch(() => { if (active) setLocalNetworks(["bridge"]); })
        .finally(() => { if (active) setNetworksLoading(false); });
    }, 180);
    return () => { active = false; window.clearTimeout(timer); };
  }, [canViewLocalNetworks]);

  const networkSuggestions = useMemo(() => {
    const needle = networkFilterActive ? network.trim().toLowerCase() : "";
    return localNetworks.filter((item) => !needle || item.toLowerCase().includes(needle)).slice(0, 12);
  }, [localNetworks, network, networkFilterActive]);

  const portErrors = useMemo(() => {
    const duplicates = new Set<string>();
    const seen = new Set<string>();
    portEntries.forEach((row) => {
      const key = `${row.published}/${row.protocol}`;
      if (seen.has(key)) duplicates.add(key);
      seen.add(key);
    });
    const errors = new Map<number, string>();
    portEntries.forEach((row) => {
      const published = Number(row.published);
      const target = Number(row.target);
      const key = `${row.published}/${row.protocol}`;
      const error = !Number.isInteger(published) || published < 1 || published > 65535 || !Number.isInteger(target) || target < 1 || target > 65535
        ? t("docker.wizard.validation.portRange")
        : duplicates.has(key)
          ? t("docker.wizard.validation.portDuplicate")
          : "";
      if (error) errors.set(row.id, error);
    });
    return errors;
  }, [portEntries, t]);
  const invalidEnvironmentRows = environmentTextMode
    ? environment
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .filter((line) => line.indexOf("=") < 1)
    : environmentRows.filter((row) => !row.key.trim());
  const invalidLabelRows = labelsTextMode
    ? labels
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .filter((line) => line.indexOf("=") < 1)
    : labelRows.filter((row) => !row.key.trim());
  const incompleteMounts = useMemo(
    () => mounts.filter((item) => !item.target.trim() || (item.type !== "tmpfs" && !item.source.trim())),
    [mounts],
  );
  const incompleteSecrets = secretRows.some((row) => Boolean(row.key) !== Boolean(row.value));
  const reviewIssues = [
    !name.trim() ? t("docker.wizard.validation.name") : "",
    !image.trim() ? t("docker.wizard.validation.image") : "",
    portErrors.size ? t("docker.wizard.validation.ports") : "",
    invalidEnvironmentRows.length ? t("docker.wizard.validation.environment") : "",
    invalidLabelRows.length ? t("docker.invalidLabels") : "",
    incompleteSecrets ? t("docker.wizard.validation.secrets") : "",
    incompleteMounts.length ? t("docker.wizard.validation.mounts") : "",
    !validEntrypoint(entrypoint) ? t("docker.wizard.validation.entrypoint") : "",
    ...resourceLimitIssues(resourceLimits, limitsEnabled, hostResources, t),
    healthType !== "none" && (!healthPort || Number(healthPort) < 1 || Number(healthPort) > 65535)
      ? t("docker.wizard.validation.healthPort")
      : "",
  ].filter(Boolean);
  const imageStatus = imagesLoading
    ? t("docker.wizard.imageChecking")
    : localImages.includes(image.trim())
      ? t("docker.wizard.imageLocal")
      : image.trim()
        ? t("docker.wizard.imagePull")
        : "";

  function lines(value: Record<string, string> | undefined) {
    return Object.entries(value || {}).map(([key, item]) => `${key}=${item}`).join("\n");
  }

  async function importConfig(file?: File) {
    if (!file) return;
    try {
      if (file.size > 512 * 1024) throw new Error(t("docker.configTooLarge"));
      const parsed = JSON.parse(await file.text()) as DockerContainerCreate;
      if (!parsed || typeof parsed !== "object" || typeof parsed.name !== "string" || typeof parsed.image !== "string")
        throw new Error(t("docker.invalidContainerConfig"));
      setName(parsed.name);
      setImage(parsed.image);
      setNetwork(parsed.network || "bridge");
      setNetworkAliases((parsed.network_aliases || []).join(", "));
      setHostname(parsed.hostname || "");
      setEntrypoint(parsed.entrypoint || "");
      setWorkingDir(parsed.working_dir || "");
      setContainerUser(parsed.user || "");
      setRestartPolicy(parsed.restart_policy || "unless-stopped");
      const importedEnvironment = lines(parsed.environment);
      const importedEnvironmentRows = editablePairs(importedEnvironment).map((row) => ({ ...row, id: nextEnvironmentId.current++ }));
      setEnvironment(importedEnvironment);
      setEnvironmentRows(importedEnvironmentRows);
      const importedSecrets = Object.entries(parsed.secret_environment || {}).map(([key, value]) => ({ id: nextSecretId.current++, key, value }));
      setSecretRows(importedSecrets.length ? importedSecrets : [{ id: nextSecretId.current++, key: "", value: "" }]);
      const importedPorts = (parsed.ports || []).map((item) => ({ id: nextPortId.current++, published: String(item.published), target: String(item.target), protocol: item.protocol || "tcp" }));
      setPortEntries(importedPorts);
      setPorts(importedPorts.map((row) => `${row.published}:${row.target}/${row.protocol}`).join("\n"));
      setMounts((parsed.mounts || []).map((item) => ({
        id: nextMountId.current++,
        type: item.type,
        source: item.source || "",
        target: item.target,
        readOnly: Boolean(item.read_only),
        tmpfsSizeMb: item.tmpfs_size_mb == null ? "" : String(item.tmpfs_size_mb),
      })));
      const importedLabels = lines(parsed.labels);
      setLabels(importedLabels);
      setLabelRows(editablePairs(importedLabels).map((row) => ({ ...row, id: nextLabelId.current++ })));
      resourceLimitsTouched.current = true;
      setResourceLimits(resourceLimitsFromPayload(parsed.limits));
      const importedLimitsEnabled = Boolean(parsed.limits && Object.entries(parsed.limits).some(([key, value]) => key === "ulimits" ? Array.isArray(value) && value.length > 0 : value !== null && value !== undefined && value !== false));
      setLimitsEnabled(importedLimitsEnabled);
      setResourceProfile(importedLimitsEnabled ? "custom" : "unlimited");
      setHealthType(parsed.healthcheck?.type || "none");
      setHealthPort(parsed.healthcheck?.port == null ? "" : String(parsed.healthcheck.port));
      setHealthPath(parsed.healthcheck?.path || "/");
      setReadOnly(Boolean(parsed.read_only));
      setInit(parsed.init ?? true);
      setAutoStart(parsed.auto_start ?? true);
      toast(t("docker.configImported"), "ok", "admin");
    } catch (error) {
      toast(errorMessage(error, t), "error", "admin");
    } finally {
      if (configUpload.current) configUpload.current.value = "";
    }
  }

  async function importCompose(file?: File) {
    if (!file) return;
    try {
      if (file.size > 512 * 1024) throw new Error(t("docker.composeTooLarge"));
      const base = file.name.replace(/\.(ya?ml)$/i, "").toLowerCase();
      setComposeProject(base.replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 63) || "imported-compose");
      setComposeContent(await file.text());
      setComposeMode(true);
    } catch (error) {
      toast(errorMessage(error, t), "error", "admin");
    } finally {
      if (composeUpload.current) composeUpload.current.value = "";
    }
  }

  async function submitCompose() {
    setBusy(true);
    try {
      const payload = {
        content: composeContent,
        environment: pairs(composeEnvironment, t("docker.invalidEnvironment")),
        secret_environment: composeSecretEnvironment.trim() ? pairs(composeSecretEnvironment, t("docker.invalidEnvironment")) : null,
        description: t("docker.composeImported"),
      };
      await api.validateDockerCompose(composeProject, payload);
      await api.saveDockerComposeProject(composeProject, payload);
      if (composeAutoStart) {
        const result = await api.dockerComposeAction(composeProject, { action: "up", services: [], remove_volumes: false, confirmation: "" });
        if (result.job) onStarted(result.job);
      } else {
        toast(t("docker.composeSaved"), "ok", "admin");
      }
      onClose();
    } catch (error) {
      toast(errorMessage(error, t), "error", "admin");
    } finally {
      setBusy(false);
    }
  }
  async function submit() {
    setBusy(true);
    try {
      if (reviewIssues.length) throw new Error(reviewIssues[0]);
      const mappedPorts = portEntries.map((row) => ({
        published: Number(row.published),
        target: Number(row.target),
        protocol: row.protocol,
      }));
      const result = await api.createDockerContainer({
        name,
        image,
        network,
        pull_policy: "missing",
        network_aliases: networkAliases.split(",").map((item) => item.trim()).filter(Boolean),
        restart_policy: restartPolicy,
        hostname: hostname || null,
        entrypoint: entrypoint.trim() || null,
        working_dir: workingDir || null,
        user: containerUser || null,
        environment: pairs(environment, t("docker.invalidEnvironment")),
        secret_environment: Object.fromEntries(secretRows.filter((row) => row.key || row.value).map((row) => {
          if (!row.key || !row.value) throw new Error(t("docker.invalidEnvironment"));
          return [row.key, row.value];
        })),
        ports: mappedPorts,
        mounts: mounts.map((item) => {
          if (!item.target || (item.type !== "tmpfs" && !item.source)) throw new Error(t("docker.invalidMounts"));
          return item.type === "tmpfs" ? {
            type: item.type,
            source: "",
            target: item.target,
            tmpfs_size_mb: item.tmpfsSizeMb ? Number(item.tmpfsSizeMb) : null,
          } : {
            type: item.type,
            source: item.source,
            target: item.target,
            read_only: item.readOnly,
          };
        }),
        limits: resourceLimitsPayload(resourceLimits, limitsEnabled),
        healthcheck: {
          type: healthType,
          port: healthType === "none" ? null : Number(healthPort),
          path: healthPath,
        },
        labels: pairs(labels, t("docker.invalidLabels")),
        read_only: readOnly,
        init,
        auto_start: autoStart,
        confirmation: name,
      });
      onStarted(result.job);
      onClose();
    } catch (error) {
      toast(errorMessage(error, t), "error", "admin");
    } finally {
      setBusy(false);
    }
  }
  if (composeMode) return createPortal(
    <div className="modal-backdrop docker-wizard-backdrop">
      <section className="modal-panel docker-wizard docker-compose-wizard" role="dialog" aria-modal="true" aria-labelledby="docker-compose-import-title">
        <header>
          <div><ScrollText /><h2 id="docker-compose-import-title">{t("docker.importComposeAndRun")}</h2></div>
          <button aria-label={t("action.close")} onClick={onClose}><X /></button>
        </header>
        <div className="docker-wizard-body docker-compose-import">
          <label>{t("docker.projectName")}<input value={composeProject} onChange={(event) => setComposeProject(event.target.value)} autoFocus required /></label>
          <label>{t("docker.composeYaml")}<textarea className="docker-code-editor" value={composeContent} onChange={(event) => setComposeContent(event.target.value)} required /></label>
          <div className="form-grid">
            <label>{t("docker.publicEnvironment")}<textarea value={composeEnvironment} onChange={(event) => setComposeEnvironment(event.target.value)} placeholder="TZ=Europe/Warsaw" /></label>
            <label>{t("docker.secretEnvironment")}<textarea value={composeSecretEnvironment} onChange={(event) => setComposeSecretEnvironment(event.target.value)} /></label>
          </div>
          <label className="check-row"><input type="checkbox" checked={composeAutoStart} onChange={(event) => setComposeAutoStart(event.target.checked)} />{t("docker.startAfterImport")}</label>
          <p className="field-hint">{t("docker.composeImportHint")}</p>
        </div>
        <footer>
          <button onClick={() => setComposeMode(false)}><ArrowLeft />{t("action.back")}</button><span />
          <button className="button-primary" disabled={busy || !composeProject || !composeContent.trim()} onClick={() => void submitCompose()}><Upload />{t(composeAutoStart ? "docker.importAndRun" : "docker.importCompose")}</button>
        </footer>
      </section>
    </div>,
    document.body,
  );
  return createPortal(
    <div className="modal-backdrop docker-wizard-backdrop">
      <section
        className="modal-panel docker-wizard"
        role="dialog"
        aria-modal="true"
        aria-labelledby="docker-create-title"
      >
        <input ref={configUpload} className="visually-hidden" type="file" accept=".json,application/json" onChange={(event) => void importConfig(event.target.files?.[0])} />
        {canImportCompose && <input ref={composeUpload} className="visually-hidden" type="file" accept=".yaml,.yml,application/yaml,text/yaml" onChange={(event) => void importCompose(event.target.files?.[0])} />}
        <header className="docker-compact-header">
          <div><span><Boxes /></span><h2 id="docker-create-title">{t("docker.createContainer")}</h2></div>
          <div>
            <button type="button" onClick={() => configUpload.current?.click()}><FileJson />{t("docker.importContainerConfig")}</button>
            {canImportCompose && <button type="button" onClick={() => composeUpload.current?.click()}><ScrollText />{t("docker.importCompose")}</button>}
            <button className="icon-button" type="button" aria-label={t("action.close")} onClick={onClose}><X /></button>
          </div>
        </header>
        <div className="docker-wizard-body">
          <form className="docker-compact-form" onSubmit={(event) => { event.preventDefault(); if (!reviewIssues.length) void submit(); }}>
            <ConfigSection title={t("docker.wizard.section.general")} defaultOpen>
              <ConfigRow label={t("docker.field.image")} required description={imageStatus || t("docker.wizard.imageHint")}>
                <div className="docker-resource-picker">
                  <input value={image} onChange={(event) => setImage(event.target.value)} onFocus={() => setImagePickerOpen(true)} onBlur={() => setImagePickerOpen(false)} placeholder="nginx:stable" role="combobox" aria-label={t("docker.field.image")} aria-autocomplete="list" aria-expanded={imagePickerOpen && canViewLocalImages} aria-controls="docker-local-image-options" aria-invalid={!image.trim()} required />
                  {imagePickerOpen && canViewLocalImages && <div id="docker-local-image-options" className="docker-resource-options" role="listbox" aria-label={t("docker.localImages")}>{imageSuggestions.map((item) => <button key={item} type="button" role="option" aria-selected={image === item} onMouseDown={(event) => event.preventDefault()} onClick={() => { setImage(item); setImagePickerOpen(false); }}>{item}</button>)}{!imageSuggestions.length && <span>{imagesLoading ? t("status.loading") : t("docker.noLocalImages")}</span>}</div>}
                </div>
              </ConfigRow>
              <ConfigRow label={t("docker.field.name")} required>
                <input autoFocus aria-label={t("docker.field.name")} aria-invalid={!name.trim()} aria-describedby={!name.trim() ? "docker-name-error" : undefined} value={name} onChange={(event) => setName(event.target.value)} required />
                {!name.trim() && <small className="docker-inline-error" id="docker-name-error">{t("docker.wizard.validation.name")}</small>}
              </ConfigRow>
              <ConfigRow label={t("docker.field.restartPolicy")} description={t("docker.wizard.restartHint")}><select aria-label={t("docker.field.restartPolicy")} value={restartPolicy} onChange={(event) => setRestartPolicy(event.target.value as typeof restartPolicy)}>{(["no", "always", "unless-stopped", "on-failure"] as const).map((value) => <option value={value} key={value}>{value}</option>)}</select></ConfigRow>
              <ConfigRow label={t("docker.field.autoStart")}><label className="docker-compact-check"><input type="checkbox" checked={autoStart} onChange={(event) => setAutoStart(event.target.checked)} />{t("docker.field.autoStart")}</label></ConfigRow>
              <ConfigRow label={t("docker.field.init")}><label className="docker-compact-check"><input type="checkbox" checked={init} onChange={(event) => setInit(event.target.checked)} />{t("docker.field.init")}</label></ConfigRow>
            </ConfigSection>

            <ConfigSection title={t("docker.wizard.section.ports")} defaultOpen>
              <div className="docker-port-table">
                <div className="docker-compact-table-head"><span>{t("docker.wizard.hostPort")}</span><span>{t("docker.wizard.containerPort")}</span><span>{t("docker.wizard.protocol")}</span><span /></div>
                {portEntries.map((row) => <div className={`docker-port-row ${portErrors.has(row.id) ? "invalid" : ""}`} key={row.id}>
                  <input aria-label={t("docker.wizard.hostPort")} inputMode="numeric" value={row.published} onChange={(event) => setPortsFromRows((current) => current.map((item) => item.id === row.id ? { ...item, published: event.target.value } : item))} />
                  <input aria-label={t("docker.wizard.containerPort")} inputMode="numeric" value={row.target} onChange={(event) => setPortsFromRows((current) => current.map((item) => item.id === row.id ? { ...item, target: event.target.value } : item))} />
                  <select aria-label={t("docker.wizard.protocol")} value={row.protocol} onChange={(event) => setPortsFromRows((current) => current.map((item) => item.id === row.id ? { ...item, protocol: event.target.value as "tcp" | "udp" } : item))}><option value="tcp">TCP</option><option value="udp">UDP</option></select>
                  <button type="button" aria-label={t("docker.wizard.removePort")} onClick={() => setPortsFromRows((current) => current.filter((item) => item.id !== row.id))}><Minus /></button>
                  {portErrors.get(row.id) && <small role="alert">{portErrors.get(row.id)}</small>}
                </div>)}
                <button className="docker-compact-add" type="button" onClick={() => setPortsFromRows((current) => [...current, { id: nextPortId.current++, published: "", target: "", protocol: "tcp" }])}><Plus />{t("docker.wizard.addPort")}</button>
              </div>
            </ConfigSection>

            <ConfigSection title={t("docker.wizard.section.volumes")} defaultOpen>
              <div className="docker-volume-table">
                {mounts.length === 0 && <p className="docker-compact-empty">{t("docker.noMounts")}</p>}
                {mounts.map((item) => <div className={`docker-volume-row ${incompleteMounts.some((mount) => mount.id === item.id) ? "invalid" : ""}`} key={item.id}>
                  <span className="docker-volume-icon">{item.type === "bind" ? <FolderOpen /> : item.type === "volume" ? <HardDrive /> : <Database />}</span>
                  <select aria-label={t("docker.mountType")} value={item.type} onChange={(event) => updateMount(item.id, { type: event.target.value as MountRow["type"], source: event.target.value === "tmpfs" ? "" : item.source })}><option value="bind">bind</option><option value="volume">volume</option><option value="tmpfs">tmpfs</option></select>
                  {item.type !== "tmpfs" ? <div className="docker-mount-source"><input aria-label={t("docker.mountSource")} value={item.source} onChange={(event) => updateMount(item.id, { source: event.target.value })} onDoubleClick={() => item.type === "bind" && setPathPickerMountId(item.id)} placeholder={item.type === "bind" ? "/srv/data" : "app-data"} />{item.type === "bind" && <button type="button" aria-label={t("docker.chooseHostPath")} onClick={() => setPathPickerMountId(item.id)}><FolderOpen /></button>}</div> : <input aria-label={t("docker.tmpfsSizeMb")} type="number" min="1" value={item.tmpfsSizeMb} onChange={(event) => updateMount(item.id, { tmpfsSizeMb: event.target.value })} placeholder="MB" />}
                  <input aria-label={t("docker.mountTarget")} value={item.target} onChange={(event) => updateMount(item.id, { target: event.target.value })} placeholder="/data" />
                  {item.type !== "tmpfs" && <select aria-label={t("docker.wizard.accessMode")} value={item.readOnly ? "ro" : "rw"} onChange={(event) => updateMount(item.id, { readOnly: event.target.value === "ro" })}><option value="rw">{t("docker.wizard.readWrite")}</option><option value="ro">{t("files.readOnly")}</option></select>}
                  <button type="button" aria-label={t("docker.removeMount")} onClick={() => setMounts((current) => current.filter((mount) => mount.id !== item.id))}><Minus /></button>
                </div>)}
                <button className="docker-compact-add" type="button" onClick={() => addMount()}><Plus />{t("docker.wizard.addVolume")}</button>
              </div>
            </ConfigSection>

            <ConfigSection title={t("docker.wizard.section.environment")} defaultOpen>
              <button className="docker-text-mode-toggle" type="button" onClick={() => { if (environmentTextMode) setEnvironmentRows(editablePairs(environment).map((row) => ({ ...row, id: nextEnvironmentId.current++ }))); setEnvironmentTextMode((value) => !value); }}>{t(environmentTextMode ? "docker.wizard.editAsRows" : "docker.wizard.editAsText")}</button>
              {environmentTextMode ? <textarea className="docker-config-textarea" aria-label={t("docker.field.environment")} value={environment} onChange={(event) => setEnvironment(event.target.value)} placeholder="TZ=Europe/Warsaw" /> : <KeyValueRows rows={environmentRows} keyLabel={t("docker.wizard.variableName")} valueLabel={t("docker.wizard.variableValue")} addLabel={t("docker.wizard.addVariable")} t={t} onAdd={() => setEnvironmentFromRows((current) => [...current, { id: nextEnvironmentId.current++, key: "", value: "" }])} onRemove={(id) => setEnvironmentFromRows((current) => current.filter((row) => row.id !== id))} onUpdate={(id, values) => setEnvironmentFromRows((current) => current.map((row) => row.id === id ? { ...row, ...values } : row))} />}
            </ConfigSection>

            <ConfigSection title={t("docker.wizard.section.secrets")}>
              <p className="docker-compact-hint">{t("docker.wizard.secretsDraftHint")}</p>
              <KeyValueRows secret rows={secretRows} keyLabel={t("docker.secretName")} valueLabel={t("docker.secretValue")} addLabel={t("docker.addSecret")} t={t} onAdd={() => setSecretRows((current) => [...current, { id: nextSecretId.current++, key: "", value: "" }])} onRemove={(id) => setSecretRows((current) => current.filter((row) => row.id !== id))} onUpdate={(id, values) => setSecretRows((current) => current.map((row) => row.id === id ? { ...row, ...values } : row))} />
            </ConfigSection>

            <ConfigSection title={t("docker.wizard.section.security")}>
              <ConfigRow label={t("docker.field.readOnly")}><label className="docker-compact-check"><input type="checkbox" checked={readOnly} onChange={(event) => setReadOnly(event.target.checked)} />{t("docker.field.readOnly")}</label></ConfigRow>
              <p className="docker-compact-hint">{t("docker.highRiskBlocked")}</p>
            </ConfigSection>

            <ConfigSection title={t("docker.wizard.section.network")} defaultOpen>
              <ConfigRow label={t("docker.field.network")}>
                <div className="docker-resource-picker">
                  <input value={network} onChange={(event) => { setNetwork(event.target.value); setNetworkFilterActive(true); }} onFocus={(event) => { setNetworkFilterActive(false); setNetworkPickerOpen(true); event.currentTarget.select(); }} onBlur={() => setNetworkPickerOpen(false)} role="combobox" aria-label={t("docker.field.network")} aria-autocomplete="list" aria-expanded={networkPickerOpen && canViewLocalNetworks} aria-controls="docker-local-network-options" required />
                  {networkPickerOpen && canViewLocalNetworks && <div id="docker-local-network-options" className="docker-resource-options" role="listbox" aria-label={t("docker.localNetworks")}>{networkSuggestions.map((item) => <button key={item} type="button" role="option" aria-selected={network === item} onMouseDown={(event) => event.preventDefault()} onClick={() => { setNetwork(item); setNetworkFilterActive(false); setNetworkPickerOpen(false); }}>{item}</button>)}{!networkSuggestions.length && <span>{networksLoading ? t("status.loading") : t("docker.noLocalNetworks")}</span>}</div>}
                </div>
              </ConfigRow>
              <ConfigRow label={t("docker.field.networkAliases")}><input aria-label={t("docker.field.networkAliases")} value={networkAliases} onChange={(event) => setNetworkAliases(event.target.value)} placeholder={t("docker.networkAliasesHint")} /></ConfigRow>
              <ConfigRow label={t("docker.field.hostname")}><input aria-label={t("docker.field.hostname")} value={hostname} onChange={(event) => setHostname(event.target.value)} /></ConfigRow>
            </ConfigSection>

            <ConfigSection title={t("docker.wizard.section.process")}>
              <ConfigRow label={t("docker.field.entrypoint")} description={t("docker.wizard.entrypointHint")}><input aria-label={t("docker.field.entrypoint")} aria-invalid={!validEntrypoint(entrypoint)} value={entrypoint} onChange={(event) => setEntrypoint(event.target.value)} placeholder="/usr/local/bin/start" /></ConfigRow>
              <ConfigRow label={t("docker.field.workingDir")}><input aria-label={t("docker.field.workingDir")} value={workingDir} onChange={(event) => setWorkingDir(event.target.value)} placeholder="/app" /></ConfigRow>
              <ConfigRow label={t("docker.field.userUidGid")}><input aria-label={t("docker.field.userUidGid")} value={containerUser} onChange={(event) => setContainerUser(event.target.value)} placeholder="1000:1000" /></ConfigRow>
            </ConfigSection>

            <ConfigSection title={t("docker.wizard.section.resources")}>
              <ResourceLimitsSection enabled={limitsEnabled} host={hostResources} profile={resourceProfile} t={t} value={resourceLimits}
                onEnabled={(value) => { resourceLimitsTouched.current = true; setLimitsEnabled(value); }}
                onProfile={setResourceProfile}
                onValue={(value) => { resourceLimitsTouched.current = true; setResourceLimits(value); }} />
            </ConfigSection>

            <ConfigSection title={t("docker.wizard.section.health")}>
              <ConfigRow label={t("docker.field.healthcheck")}><select aria-label={t("docker.field.healthcheck")} value={healthType} onChange={(event) => setHealthType(event.target.value as typeof healthType)}><option value="none">{t("common.none")}</option><option value="http">HTTP</option><option value="tcp">TCP</option></select></ConfigRow>
              {healthType !== "none" && <ConfigRow label={t("docker.field.healthPort")}><input aria-label={t("docker.field.healthPort")} aria-invalid={!healthPort || Number(healthPort) < 1 || Number(healthPort) > 65535} type="number" min="1" max="65535" value={healthPort} onChange={(event) => setHealthPort(event.target.value)} /></ConfigRow>}
              {healthType === "http" && <ConfigRow label={t("docker.field.healthPath")}><input aria-label={t("docker.field.healthPath")} value={healthPath} onChange={(event) => setHealthPath(event.target.value)} /></ConfigRow>}
            </ConfigSection>

            <ConfigSection title={t("docker.wizard.section.labels")}>
              <button className="docker-text-mode-toggle" type="button" onClick={() => { if (labelsTextMode) setLabelRows(editablePairs(labels).map((row) => ({ ...row, id: nextLabelId.current++ }))); setLabelsTextMode((value) => !value); }}>{t(labelsTextMode ? "docker.wizard.editAsRows" : "docker.wizard.editAsText")}</button>
              {labelsTextMode ? <textarea className="docker-config-textarea" aria-label={t("docker.field.labels")} value={labels} onChange={(event) => setLabels(event.target.value)} placeholder={t("docker.labelsHint")} /> : <KeyValueRows rows={labelRows} keyLabel={t("docker.wizard.labelName")} valueLabel={t("docker.wizard.labelValue")} addLabel={t("docker.wizard.addLabel")} t={t} onAdd={() => setLabelsFromRows((current) => [...current, { id: nextLabelId.current++, key: "", value: "" }])} onRemove={(id) => setLabelsFromRows((current) => current.filter((row) => row.id !== id))} onUpdate={(id, values) => setLabelsFromRows((current) => current.map((row) => row.id === id ? { ...row, ...values } : row))} />}
            </ConfigSection>

            <ConfigSection title={t("docker.wizard.section.summary")}>
              {reviewIssues.length > 0 && <div className="docker-compact-errors" role="alert"><ul>{reviewIssues.map((issue) => <li key={issue}>{issue}</li>)}</ul></div>}
              <dl className="docker-compact-summary">
                <div><dt>{t("docker.field.image")}</dt><dd>{image || "—"}</dd></div><div><dt>{t("docker.field.name")}</dt><dd>{name || "—"}</dd></div>
                <div><dt>{t("docker.field.network")}</dt><dd>{network || "—"}</dd></div><div><dt>{t("docker.field.ports")}</dt><dd>{portEntries.length || t("common.none")}</dd></div>
                <div><dt>{t("docker.field.mounts")}</dt><dd>{mounts.length}</dd></div><div><dt>{t("docker.field.environment")}</dt><dd>{editablePairs(environment).length}</dd></div>
                {resourceSummary(resourceLimits, limitsEnabled, t).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
                <div><dt>{t("docker.field.entrypoint")}</dt><dd>{entrypoint.trim() || t("docker.wizard.imageDefault")}</dd></div>
                <div><dt>{t("docker.field.restartPolicy")}</dt><dd>{restartPolicy}</dd></div><div><dt>{t("docker.field.autoStart")}</dt><dd>{t(autoStart ? "common.yes" : "common.no")}</dd></div>
              </dl>
            </ConfigSection>
          </form>
        </div>
        <footer className="docker-compact-footer">
          <button type="button" onClick={onClose}>{t("action.cancel")}</button>
          <span>{reviewIssues[0] || ""}</span>
          <button className="button-primary" type="button" disabled={busy || reviewIssues.length > 0} onClick={() => void submit()}>{busy ? <RefreshCw className="docker-spin" /> : <Boxes />}{t("docker.createContainer")}</button>
        </footer>
      </section>
      {pathPickerMountId !== null && <DockerPathPicker
        initialPath={mounts.find((item) => item.id === pathPickerMountId)?.source || ""}
        t={t}
        onClose={() => setPathPickerMountId(null)}
        onSelect={(path) => { updateMount(pathPickerMountId, { source: path }); setPathPickerMountId(null); }}
      />}
    </div>,
    document.body,
  );
}
