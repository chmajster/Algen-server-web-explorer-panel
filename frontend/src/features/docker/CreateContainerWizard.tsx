import {
  ArrowLeft,
  Box,
  Boxes,
  CircleAlert,
  CircleCheck,
  Cpu,
  Database,
  Folder,
  FolderOpen,
  Gauge,
  HardDrive,
  HeartPulse,
  KeyRound,
  Minus,
  Network,
  Plus,
  RefreshCw,
  RotateCw,
  ScrollText,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type DockerContainerCreate, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { errorMessage } from "./shared";
import {
  FormSection,
  SummaryCard,
  SwitchField,
  WizardFooter,
  WizardHeader,
  WizardHelpPanel,
  WizardStepper,
  type WizardStep,
} from "./create-container/WizardChrome";

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

type ContainerWizardDraft = {
  step?: number; name?: string; image?: string; network?: string; ports?: string; environment?: string; mounts?: MountRow[];
  memory?: string; memorySwap?: string; cpus?: string; pids?: string; hostname?: string; workingDir?: string; containerUser?: string;
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
  const [memory, setMemory] = useState(draft.memory || "");
  const [memorySwap, setMemorySwap] = useState(draft.memorySwap || "");
  const [cpus, setCpus] = useState(draft.cpus || "");
  const [pids, setPids] = useState(draft.pids || "");
  const [hostname, setHostname] = useState(draft.hostname || "");
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
  const [limitsEnabled, setLimitsEnabled] = useState(Boolean(draft.memory || draft.memorySwap || draft.cpus || draft.pids));
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

  useEffect(() => {
    if (!draftKey) return;
    const value: ContainerWizardDraft = {
      step, name, image, network, ports, environment, mounts, memory, memorySwap, cpus, pids, hostname, workingDir,
      containerUser, networkAliases, restartPolicy, labels, healthType, healthPort, healthPath, readOnly, init, autoStart,
      composeMode, composeProject, composeContent, composeEnvironment, composeAutoStart,
    };
    sessionStorage.setItem(draftKey, JSON.stringify(value));
  }, [autoStart, composeAutoStart, composeContent, composeEnvironment, composeMode, composeProject, containerUser, cpus, draftKey, environment, healthPath, healthPort, healthType, hostname, image, init, labels, memory, memorySwap, mounts, name, network, networkAliases, pids, ports, readOnly, restartPolicy, step, workingDir]);

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

  const portAnalysis = useMemo(() => {
    const entered = ports.split("\n").map((line) => line.trim()).filter(Boolean);
    const valid = entered.filter((line) => /^(\d+):(\d+)(?:\/(tcp|udp))?$/.test(line));
    return { total: entered.length, valid: valid.length, invalid: entered.filter((line) => !valid.includes(line)) };
  }, [ports]);
  const invalidEnvironmentLines = useMemo(
    () => environment.split("\n").map((line) => line.trim()).filter(Boolean).filter((line) => line.indexOf("=") < 1),
    [environment],
  );
  const incompleteMounts = useMemo(
    () => mounts.filter((item) => !item.target.trim() || (item.type !== "tmpfs" && !item.source.trim())),
    [mounts],
  );
  const incompleteSecrets = secretRows.some((row) => Boolean(row.key) !== Boolean(row.value));
  const basicIssues = [
    !name.trim() ? t("docker.wizard.validation.name") : "",
    !image.trim() ? t("docker.wizard.validation.image") : "",
  ].filter(Boolean);
  const connectivityIssues = [
    portAnalysis.invalid.length ? t("docker.wizard.validation.ports") : "",
    invalidEnvironmentLines.length ? t("docker.wizard.validation.environment") : "",
    incompleteSecrets ? t("docker.wizard.validation.secrets") : "",
    incompleteMounts.length ? t("docker.wizard.validation.mounts") : "",
  ].filter(Boolean);
  const resourceIssues = [
    healthType !== "none" && (!healthPort || Number(healthPort) < 1 || Number(healthPort) > 65535)
      ? t("docker.wizard.validation.healthPort")
      : "",
  ].filter(Boolean);
  const reviewIssues = [...basicIssues, ...connectivityIssues, ...resourceIssues];
  const currentIssues = step === 0 ? basicIssues : step === 1 ? connectivityIssues : step === 2 ? resourceIssues : reviewIssues;
  const imageStatus = imagesLoading
    ? t("docker.wizard.imageChecking")
    : localImages.includes(image.trim())
      ? t("docker.wizard.imageLocal")
      : image.trim()
        ? t("docker.wizard.imagePull")
        : "";
  const wizardSteps: WizardStep[] = [
    { key: "basic", label: t("docker.wizard.basic"), description: t("docker.wizard.basicDescription") },
    { key: "connectivity", label: t("docker.wizard.connectivity"), description: t("docker.wizard.connectivityDescription") },
    { key: "resources", label: t("docker.wizard.resources"), description: t("docker.wizard.resourcesDescription") },
    { key: "review", label: t("docker.wizard.review"), description: t("docker.wizard.reviewDescription") },
  ];

  function goToStep(target: number) {
    if (target <= furthestStep) {
      setStep(target);
      setShowValidation(false);
    }
  }

  function nextStep() {
    if (currentIssues.length) {
      setShowValidation(true);
      return;
    }
    const next = Math.min(step + 1, 3);
    setFurthestStep((current) => Math.max(current, next));
    setStep(next);
    setShowValidation(false);
  }

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
      setWorkingDir(parsed.working_dir || "");
      setContainerUser(parsed.user || "");
      setRestartPolicy(parsed.restart_policy || "unless-stopped");
      setEnvironment(lines(parsed.environment));
      setSecretRows(Object.entries(parsed.secret_environment || {}).map(([key, value]) => ({ key, value })).concat(Object.keys(parsed.secret_environment || {}).length ? [] : [{ key: "", value: "" }]));
      setPorts((parsed.ports || []).map((item) => `${item.published}:${item.target}/${item.protocol || "tcp"}`).join("\n"));
      setMounts((parsed.mounts || []).map((item) => ({
        id: nextMountId.current++,
        type: item.type,
        source: item.source || "",
        target: item.target,
        readOnly: Boolean(item.read_only),
        tmpfsSizeMb: item.tmpfs_size_mb == null ? "" : String(item.tmpfs_size_mb),
      })));
      setLabels(lines(parsed.labels));
      setMemory(parsed.limits?.memory_mb == null ? "" : String(parsed.limits.memory_mb));
      setMemorySwap(parsed.limits?.memory_swap_mb == null ? "" : String(parsed.limits.memory_swap_mb));
      setCpus(parsed.limits?.cpus == null ? "" : String(parsed.limits.cpus));
      setPids(parsed.limits?.pids == null ? "" : String(parsed.limits.pids));
      setHealthType(parsed.healthcheck?.type || "none");
      setHealthPort(parsed.healthcheck?.port == null ? "" : String(parsed.healthcheck.port));
      setHealthPath(parsed.healthcheck?.path || "/");
      setReadOnly(Boolean(parsed.read_only));
      setInit(parsed.init ?? true);
      setAutoStart(parsed.auto_start ?? true);
      setStep(0);
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
      const mappedPorts = ports
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const match = /^(\d+):(\d+)(?:\/(tcp|udp))?$/.exec(line);
          if (!match) throw new Error(t("docker.invalidPorts"));
          return {
            published: Number(match[1]),
            target: Number(match[2]),
            protocol: (match[3] || "tcp") as "tcp" | "udp",
          };
        });
      const result = await api.createDockerContainer({
        name,
        image,
        network,
        pull_policy: "missing",
        network_aliases: networkAliases.split(",").map((item) => item.trim()).filter(Boolean),
        restart_policy: restartPolicy,
        hostname: hostname || null,
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
        limits: {
          memory_mb: memory ? Number(memory) : null,
          memory_swap_mb: memorySwap ? Number(memorySwap) : null,
          cpus: cpus ? Number(cpus) : null,
          pids: pids ? Number(pids) : null,
        },
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
        <WizardHeader
          canImportCompose={canImportCompose}
          t={t}
          onClose={onClose}
          onImportConfig={() => configUpload.current?.click()}
          onImportCompose={() => composeUpload.current?.click()}
        />
        <WizardStepper current={step} furthest={furthestStep} steps={wizardSteps} t={t} onStep={goToStep} />
        <div className="docker-wizard-body">
          <div className="docker-wizard-workspace">
            <main className="docker-wizard-form">
          {step === 0 && (
            <div className="docker-wizard-step">
              <FormSection title={t("docker.wizard.identification")} description={t("docker.wizard.identificationHint")} icon={Box}>
                <div className="docker-wizard-fields single">
                  <label>
                    <span>{t("docker.field.name")}</span>
                    <input
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      autoFocus
                      required
                      aria-label={t("docker.field.name")}
                      aria-invalid={showValidation && !name.trim()}
                      aria-describedby="docker-container-name-hint"
                    />
                    <small id="docker-container-name-hint">{t("docker.wizard.nameHint")}</small>
                  </label>
                  <label>
                    <span>{t("docker.field.image")}</span>
                    <div className="docker-resource-picker">
                      <input
                        value={image}
                        onChange={(event) => setImage(event.target.value)}
                        onFocus={() => setImagePickerOpen(true)}
                        onBlur={() => setImagePickerOpen(false)}
                        placeholder="nginx:stable"
                        role="combobox"
                        aria-label={t("docker.field.image")}
                        aria-autocomplete="list"
                        aria-expanded={imagePickerOpen && canViewLocalImages}
                        aria-controls="docker-local-image-options"
                        aria-invalid={showValidation && !image.trim()}
                        aria-describedby="docker-container-image-hint"
                        required
                      />
                      {imagePickerOpen && canViewLocalImages && (
                        <div id="docker-local-image-options" className="docker-resource-options" role="listbox" aria-label={t("docker.localImages")}>
                          {imageSuggestions.map((item) => <button key={item} type="button" role="option" aria-selected={image === item} onMouseDown={(event) => event.preventDefault()} onClick={() => { setImage(item); setImagePickerOpen(false); }}>{item}</button>)}
                          {!imageSuggestions.length && <span>{imagesLoading ? t("status.loading") : t("docker.noLocalImages")}</span>}
                        </div>
                      )}
                    </div>
                    <span className="docker-field-meta"><small id="docker-container-image-hint">{t("docker.wizard.imageHint")}</small>{imageStatus && <em className={localImages.includes(image.trim()) ? "success" : ""}>{imageStatus}</em>}</span>
                  </label>
                </div>
              </FormSection>
              <FormSection title={t("docker.wizard.startup")} description={t("docker.wizard.startupHint")} icon={RotateCw}>
                <div className="docker-wizard-fields">
                  <label><span>{t("docker.field.restartPolicy")}</span><select value={restartPolicy} onChange={(event) => setRestartPolicy(event.target.value as typeof restartPolicy)}>{(["no", "always", "unless-stopped", "on-failure"] as const).map((value) => <option value={value} key={value}>{value}</option>)}</select><small>{t("docker.wizard.restartHint")}</small></label>
                  <label><span>{t("docker.field.hostname")}</span><input value={hostname} onChange={(event) => setHostname(event.target.value)} placeholder="app-host" /></label>
                  <SwitchField checked={autoStart} label={t("docker.field.autoStart")} description={t("docker.wizard.autoStartHint")} onChange={setAutoStart} />
                </div>
              </FormSection>
              <FormSection title={t("docker.wizard.basicNetwork")} description={t("docker.wizard.basicNetworkHint")} icon={Network}>
                <div className="docker-wizard-fields">
                  <label>
                    <span>{t("docker.field.network")}</span>
                    <div className="docker-resource-picker">
                      <input value={network} onChange={(event) => { setNetwork(event.target.value); setNetworkFilterActive(true); }} onFocus={(event) => { setNetworkFilterActive(false); setNetworkPickerOpen(true); event.currentTarget.select(); }} onBlur={() => setNetworkPickerOpen(false)} role="combobox" aria-label={t("docker.field.network")} aria-autocomplete="list" aria-expanded={networkPickerOpen && canViewLocalNetworks} aria-controls="docker-local-network-options" required />
                      {networkPickerOpen && canViewLocalNetworks && <div id="docker-local-network-options" className="docker-resource-options" role="listbox" aria-label={t("docker.localNetworks")}>{networkSuggestions.map((item) => <button key={item} type="button" role="option" aria-selected={network === item} onMouseDown={(event) => event.preventDefault()} onClick={() => { setNetwork(item); setNetworkFilterActive(false); setNetworkPickerOpen(false); }}>{item}</button>)}{!networkSuggestions.length && <span>{networksLoading ? t("status.loading") : t("docker.noLocalNetworks")}</span>}</div>}
                    </div>
                  </label>
                  <label><span>{t("docker.field.networkAliases")}</span><input value={networkAliases} onChange={(event) => setNetworkAliases(event.target.value)} placeholder={t("docker.networkAliasesHint")} /></label>
                </div>
              </FormSection>
              {showValidation && basicIssues.length > 0 && <div className="docker-wizard-validation" role="alert"><CircleAlert />{basicIssues.join(" ")}</div>}
            </div>
          )}
          {step === 1 && (
            <div className="docker-wizard-step">
              <FormSection title={t("docker.field.ports")} description={t("docker.wizard.portsHint")} icon={Network}>
                <label>
                  <span>{t("docker.field.ports")}</span>
                  <textarea className="docker-config-textarea" value={ports} onChange={(event) => setPorts(event.target.value)} placeholder="8080:80/tcp" aria-label={t("docker.field.ports")} aria-invalid={showValidation && portAnalysis.invalid.length > 0} aria-describedby="docker-port-analysis" />
                  <span id="docker-port-analysis" className={`docker-field-counter ${portAnalysis.invalid.length ? "invalid" : ""}`}>{t("docker.wizard.validPorts").replace("{valid}", String(portAnalysis.valid)).replace("{total}", String(portAnalysis.total))}</span>
                  {portAnalysis.invalid.map((line) => <code className="docker-invalid-line" key={line}>{line}</code>)}
                </label>
              </FormSection>
              <FormSection title={t("docker.wizard.environment")} description={t("docker.wizard.environmentHint")} icon={KeyRound}>
                <div className="docker-wizard-fields single">
                  <label>
                    <span>{t("docker.field.environment")}</span>
                    <textarea className="docker-config-textarea" value={environment} onChange={(event) => setEnvironment(event.target.value)} placeholder="TZ=Europe/Warsaw" aria-label={t("docker.field.environment")} aria-invalid={showValidation && invalidEnvironmentLines.length > 0} />
                    <small>{t("docker.wizard.publicEnvironmentHint")}</small>
                  </label>
              <fieldset className="docker-secret-fields">
                <legend>{t("docker.field.secrets")}</legend>
                {secretRows.map((row, index) => (
                  <div className="docker-secret-row" key={index}>
                    <input aria-label={index === 0 ? t("docker.secretName") : undefined} value={row.key} onChange={(event) => setSecretRows((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, key: event.target.value } : item))} placeholder={t("docker.secretName")} />
                    <input aria-label={index === 0 ? t("docker.secretValue") : undefined} type="password" autoComplete="new-password" value={row.value} onChange={(event) => setSecretRows((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, value: event.target.value } : item))} placeholder={t("docker.secretValue")} />
                    <button type="button" aria-label={t("action.delete")} disabled={secretRows.length === 1} onClick={() => setSecretRows((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Trash2 /></button>
                  </div>
                ))}
                <button type="button" onClick={() => setSecretRows((current) => [...current, { key: "", value: "" }])}><Plus />{t("docker.addSecret")}</button>
              </fieldset>
              <p className="field-hint">{t("docker.secretsHint")}</p>
                </div>
              </FormSection>
              <FormSection title={t("docker.field.mounts")} description={t("docker.wizard.mountsHint")} icon={Database}>
              <fieldset className="docker-mount-fields">
                {mounts.length === 0 && <p className="field-hint">{t("docker.noMounts")}</p>}
                {mounts.map((item) => <div className={`docker-mount-row ${showValidation && incompleteMounts.some((mount) => mount.id === item.id) ? "invalid" : ""}`} key={item.id}>
                  <label>{t("docker.mountType")}<select aria-label={t("docker.mountType")} value={item.type} onChange={(event) => updateMount(item.id, { type: event.target.value as MountRow["type"], source: event.target.value === "tmpfs" ? "" : item.source })}><option value="bind">bind</option><option value="volume">volume</option><option value="tmpfs">tmpfs</option></select></label>
                  {item.type !== "tmpfs" && <label className="docker-mount-source">{t(item.type === "bind" ? "docker.hostPath" : "docker.volumeName")}<span><input aria-label={t("docker.mountSource")} value={item.source} onChange={(event) => updateMount(item.id, { source: event.target.value })} placeholder={item.type === "bind" ? "/srv/data" : "app-data"} />{item.type === "bind" && <button type="button" title={t("docker.chooseHostPath")} aria-label={t("docker.chooseHostPath")} onClick={() => setPathPickerMountId(item.id)}><FolderOpen /></button>}</span></label>}
                  <label>{t("docker.mountTarget")}<input aria-label={t("docker.mountTarget")} value={item.target} onChange={(event) => updateMount(item.id, { target: event.target.value })} placeholder="/data" /></label>
                  {item.type === "tmpfs" ? <label>{t("docker.tmpfsSizeMb")}<input aria-label={t("docker.tmpfsSizeMb")} type="number" min="1" value={item.tmpfsSizeMb} onChange={(event) => updateMount(item.id, { tmpfsSizeMb: event.target.value })} /></label>
                    : <label className="check-row docker-mount-readonly"><input aria-label={t("files.readOnly")} type="checkbox" checked={item.readOnly} onChange={(event) => updateMount(item.id, { readOnly: event.target.checked })} />{t("files.readOnly")}</label>}
                  <button className="docker-mount-remove" type="button" title={t("docker.removeMount")} aria-label={t("docker.removeMount")} onClick={() => setMounts((current) => current.filter((mount) => mount.id !== item.id))}><Minus /></button>
                </div>)}
                <button className="docker-add-mount" type="button" onClick={() => addMount()}><Plus />{t("docker.addMount")}</button>
              </fieldset>
              </FormSection>
              <FormSection title={t("docker.field.labels")} description={t("docker.labelsHint")} icon={Gauge}>
                <label><span>{t("docker.field.labels")}</span><textarea className="docker-config-textarea" value={labels} onChange={(event) => setLabels(event.target.value)} placeholder={t("docker.labelsHint")} /></label>
              </FormSection>
              {showValidation && connectivityIssues.length > 0 && <div className="docker-wizard-validation" role="alert"><CircleAlert />{connectivityIssues.join(" ")}</div>}
            </div>
          )}
          {step === 2 && (
            <div className="docker-wizard-step">
              <FormSection title={t("docker.wizard.limits")} description={t("docker.wizard.limitsHint")} icon={Cpu}>
                <div className="docker-wizard-fields">
                  <label><span>{t("docker.field.memoryMb")}</span><div className="docker-unit-field"><input type="number" min="16" value={memory} onChange={(event) => setMemory(event.target.value)} /><span>MB</span></div></label>
                  <label><span>{t("docker.field.memorySwapMb")}</span><div className="docker-unit-field"><input type="number" min="16" value={memorySwap} onChange={(event) => setMemorySwap(event.target.value)} /><span>MB</span></div></label>
                  <label><span>{t("docker.field.cpus")}</span><div className="docker-unit-field"><input type="number" min="0.1" step="0.1" value={cpus} onChange={(event) => setCpus(event.target.value)} /><span>CPU</span></div></label>
                  <label><span>{t("docker.field.pids")}</span><div className="docker-unit-field"><input type="number" min="16" value={pids} onChange={(event) => setPids(event.target.value)} /><span>{t("docker.wizard.processesUnit")}</span></div></label>
                </div>
              </FormSection>
              <FormSection title={t("docker.wizard.processConfig")} description={t("docker.wizard.processConfigHint")} icon={Gauge}>
                <div className="docker-wizard-fields">
                  <label><span>{t("docker.field.userUidGid")}</span><input value={containerUser} onChange={(event) => setContainerUser(event.target.value)} placeholder="1000:1000" /></label>
                  <label><span>{t("docker.field.workingDir")}</span><input value={workingDir} onChange={(event) => setWorkingDir(event.target.value)} placeholder="/app" /></label>
                  <SwitchField checked={init} label={t("docker.field.init")} description={t("docker.wizard.initHint")} onChange={setInit} />
                </div>
              </FormSection>
              <FormSection title={t("docker.wizard.security")} description={t("docker.wizard.securityHint")} icon={ShieldCheck}>
                <SwitchField checked={readOnly} label={t("docker.field.readOnly")} description={t("docker.wizard.readOnlyHint")} onChange={setReadOnly} />
                <p className="docker-notice info">{t("docker.highRiskBlocked")}</p>
              </FormSection>
              <FormSection title={t("docker.field.healthcheck")} description={t("docker.wizard.healthHint")} icon={HeartPulse}>
                <div className="docker-wizard-fields">
                  <label><span>{t("docker.field.healthcheck")}</span><select value={healthType} onChange={(event) => setHealthType(event.target.value as typeof healthType)}><option value="none">{t("common.none")}</option><option value="http">HTTP</option><option value="tcp">TCP</option></select></label>
                  {healthType !== "none" && <label><span>{t("docker.field.healthPort")}</span><input type="number" min="1" max="65535" value={healthPort} onChange={(event) => setHealthPort(event.target.value)} aria-invalid={showValidation && resourceIssues.length > 0} required /></label>}
                  {healthType === "http" && <label><span>{t("docker.field.healthPath")}</span><input value={healthPath} onChange={(event) => setHealthPath(event.target.value)} placeholder="/health" /></label>}
                </div>
              </FormSection>
              {showValidation && resourceIssues.length > 0 && <div className="docker-wizard-validation" role="alert"><CircleAlert />{resourceIssues.join(" ")}</div>}
            </div>
          )}
          {step === 3 && (
            <div className="docker-wizard-step docker-review">
              <div className="docker-summary-grid">
                <SummaryCard icon={Box} title={t("docker.wizard.summary.container")} t={t} onEdit={() => goToStep(0)} rows={[[t("docker.field.name"), name], [t("docker.field.hostname"), hostname || "—"]]} />
                <SummaryCard icon={Boxes} title={t("docker.wizard.summary.image")} t={t} onEdit={() => goToStep(0)} rows={[[t("docker.field.image"), image], [t("docker.wizard.imageStatus"), imageStatus || "—"]]} />
                <SummaryCard icon={Network} title={t("docker.wizard.summary.network")} t={t} onEdit={() => goToStep(1)} rows={[[t("docker.field.network"), network], [t("docker.field.ports"), ports || "—"]]} />
                <SummaryCard icon={Database} title={t("docker.wizard.summary.volumes")} t={t} onEdit={() => goToStep(1)} rows={[[t("docker.field.mounts"), mounts.length ? mounts.map((item) => `${item.type}: ${item.type === "tmpfs" ? "" : `${item.source} → `}${item.target}`).join(", ") : "—"], [t("docker.field.secrets"), secretRows.some((row) => row.value) ? t("docker.secretValuesHidden") : "—"]]} />
                <SummaryCard icon={Cpu} title={t("docker.wizard.summary.resources")} t={t} onEdit={() => goToStep(2)} rows={[[t("docker.field.limits"), [cpus && `${cpus} CPU`, memory && `${memory} MB`, memorySwap && `${memorySwap} MB + swap`, pids && `${pids} PID`].filter(Boolean).join(", ") || "—"]]} />
                <SummaryCard icon={HeartPulse} title={t("docker.wizard.summary.lifecycle")} t={t} onEdit={() => goToStep(2)} rows={[[t("docker.field.restartPolicy"), restartPolicy], [t("docker.field.healthcheck"), healthType === "none" ? t("common.none") : `${healthType.toUpperCase()} :${healthPort}${healthType === "http" ? healthPath : ""}`]]} />
                <SummaryCard icon={ShieldCheck} title={t("docker.wizard.summary.security")} t={t} onEdit={() => goToStep(2)} rows={[[t("docker.field.readOnly"), t(readOnly ? "common.yes" : "common.no")], [t("docker.field.init"), t(init ? "common.yes" : "common.no")]]} />
              </div>
              <section className={`docker-preflight ${reviewIssues.length ? "invalid" : "valid"}`}>
                <header>{reviewIssues.length ? <CircleAlert /> : <CircleCheck />}<div><h3>{t("docker.wizard.preflight")}</h3><p>{t(reviewIssues.length ? "docker.wizard.preflightFailed" : "docker.wizard.preflightPassed")}</p></div></header>
                {reviewIssues.length > 0 && <ul>{reviewIssues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
              </section>
            </div>
          )}
            </main>
            <WizardHelpPanel
              t={t}
              title={t(`docker.wizard.help.${wizardSteps[step].key}.title`)}
              text={t(`docker.wizard.help.${wizardSteps[step].key}.text`)}
              issues={currentIssues}
              examples={step === 0 ? ["nginx:stable", "registry.example.com/team/app:1.2"] : step === 1 ? ["8080:80/tcp", "/srv/app → /data"] : step === 2 ? ["512 MB", "0.5 CPU"] : undefined}
              summary={[
                [t("docker.field.name"), name || "—"],
                [t("docker.field.image"), image || "—"],
                [t("docker.field.network"), network || "—"],
                [t("docker.field.mounts"), String(mounts.length)],
              ]}
            />
          </div>
        </div>
        <WizardFooter busy={busy} createBlockedReason={reviewIssues[0]} current={step} total={wizardSteps.length} t={t} onBack={() => goToStep(step - 1)} onNext={nextStep} onSubmit={() => void submit()} />
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
