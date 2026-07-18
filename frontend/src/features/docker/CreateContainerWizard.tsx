import { ArrowLeft, ArrowRight, Boxes, FileJson, Folder, FolderOpen, HardDrive, Minus, Plus, RefreshCw, ScrollText, Trash2, Upload, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type DockerContainerCreate, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { errorMessage } from "./shared";

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
  const [step, setStep] = useState(() => Math.max(0, Math.min(3, Number(draft.step) || 0)));
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState(draft.name || "");
  const [image, setImage] = useState(draft.image || "");
  const [network, setNetwork] = useState(draft.network || "bridge");
  const [ports, setPorts] = useState(draft.ports || "");
  const [environment, setEnvironment] = useState(draft.environment || "");
  const [secretRows, setSecretRows] = useState([{ key: "", value: "" }]);
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
  const [healthType, setHealthType] = useState<"none" | "http" | "tcp">(draft.healthType || "none");
  const [healthPort, setHealthPort] = useState(draft.healthPort || "");
  const [healthPath, setHealthPath] = useState(draft.healthPath || "/");
  const [readOnly, setReadOnly] = useState(draft.readOnly || false);
  const [init, setInit] = useState(draft.init ?? true);
  const [autoStart, setAutoStart] = useState(draft.autoStart ?? true);
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
      <section className="modal-panel docker-wizard" role="dialog" aria-modal="true" aria-labelledby="docker-compose-import-title">
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
        <header>
          <div>
            <Boxes />
            <h2 id="docker-create-title">{t("docker.createContainer")}</h2>
          </div>
          <div className="docker-wizard-imports">
            <input ref={configUpload} className="visually-hidden" type="file" accept=".json,application/json" onChange={(event) => void importConfig(event.target.files?.[0])} />
            <button type="button" onClick={() => configUpload.current?.click()}><FileJson />{t("docker.importContainerConfig")}</button>
            {canImportCompose && <>
              <input ref={composeUpload} className="visually-hidden" type="file" accept=".yaml,.yml,application/yaml,text/yaml" onChange={(event) => void importCompose(event.target.files?.[0])} />
              <button type="button" onClick={() => composeUpload.current?.click()}><ScrollText />{t("docker.importCompose")}</button>
            </>}
          </div>
          <button aria-label={t("action.close")} onClick={onClose}>
            <X />
          </button>
        </header>
        <ol className="docker-wizard-steps">
          {["basic", "connectivity", "resources", "review"].map(
            (key, index) => (
              <li
                className={
                  step === index ? "active" : step > index ? "done" : ""
                }
                key={key}
              >
                {t(`docker.wizard.${key}`)}
              </li>
            ),
          )}
        </ol>
        <div className="docker-wizard-body">
          {step === 0 && (
            <div className="form-grid">
              <label>
                {t("docker.field.name")}
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  autoFocus
                  required
                />
              </label>
              <label>
                {t("docker.field.image")}
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
                    required
                  />
                  {imagePickerOpen && canViewLocalImages && (
                    <div id="docker-local-image-options" className="docker-resource-options" role="listbox" aria-label={t("docker.localImages")}>
                      {imageSuggestions.map((item) => <button key={item} type="button" role="option" aria-selected={image === item} onMouseDown={(event) => event.preventDefault()} onClick={() => { setImage(item); setImagePickerOpen(false); }}>{item}</button>)}
                      {!imageSuggestions.length && <span>{imagesLoading ? t("status.loading") : t("docker.noLocalImages")}</span>}
                    </div>
                  )}
                </div>
                {canViewLocalImages && <small className="field-hint">{t("docker.localImageSearchHint")}</small>}
              </label>
              <label>
                {t("docker.field.network")}
                <div className="docker-resource-picker">
                  <input
                    value={network}
                    onChange={(event) => { setNetwork(event.target.value); setNetworkFilterActive(true); }}
                    onFocus={(event) => { setNetworkFilterActive(false); setNetworkPickerOpen(true); event.currentTarget.select(); }}
                    onBlur={() => setNetworkPickerOpen(false)}
                    role="combobox"
                    aria-label={t("docker.field.network")}
                    aria-autocomplete="list"
                    aria-expanded={networkPickerOpen && canViewLocalNetworks}
                    aria-controls="docker-local-network-options"
                    required
                  />
                  {networkPickerOpen && canViewLocalNetworks && (
                    <div id="docker-local-network-options" className="docker-resource-options" role="listbox" aria-label={t("docker.localNetworks")}>
                      {networkSuggestions.map((item) => <button key={item} type="button" role="option" aria-selected={network === item} onMouseDown={(event) => event.preventDefault()} onClick={() => { setNetwork(item); setNetworkFilterActive(false); setNetworkPickerOpen(false); }}>{item}</button>)}
                      {!networkSuggestions.length && <span>{networksLoading ? t("status.loading") : t("docker.noLocalNetworks")}</span>}
                    </div>
                  )}
                </div>
                {canViewLocalNetworks && <small className="field-hint">{t("docker.localNetworkSearchHint")}</small>}
              </label>
              <label>
                {t("docker.field.networkAliases")}
                <input value={networkAliases} onChange={(event) => setNetworkAliases(event.target.value)} placeholder={t("docker.networkAliasesHint")} />
              </label>
              <label>
                {t("docker.field.hostname")}
                <input value={hostname} onChange={(event) => setHostname(event.target.value)} />
              </label>
              <label>
                {t("docker.field.restartPolicy")}
                <select value={restartPolicy} onChange={(event) => setRestartPolicy(event.target.value as typeof restartPolicy)}>
                  {(["no", "always", "unless-stopped", "on-failure"] as const).map((value) => <option value={value} key={value}>{value}</option>)}
                </select>
              </label>
              <label className="check-row">
                <input type="checkbox" checked={autoStart} onChange={(event) => setAutoStart(event.target.checked)} />
                {t("docker.field.autoStart")}
              </label>
            </div>
          )}
          {step === 1 && (
            <div className="form-grid">
              <label>
                {t("docker.field.ports")}
                <textarea
                  value={ports}
                  onChange={(event) => setPorts(event.target.value)}
                  placeholder="8080:80/tcp"
                />
              </label>
              <label>
                {t("docker.field.environment")}
                <textarea
                  value={environment}
                  onChange={(event) => setEnvironment(event.target.value)}
                  placeholder="TZ=Europe/Warsaw"
                />
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
              <fieldset className="docker-mount-fields">
                <legend>{t("docker.field.mounts")}</legend>
                {mounts.length === 0 && <p className="field-hint">{t("docker.noMounts")}</p>}
                {mounts.map((item) => <div className="docker-mount-row" key={item.id}>
                  <label>{t("docker.mountType")}<select aria-label={t("docker.mountType")} value={item.type} onChange={(event) => updateMount(item.id, { type: event.target.value as MountRow["type"], source: event.target.value === "tmpfs" ? "" : item.source })}><option value="bind">bind</option><option value="volume">volume</option><option value="tmpfs">tmpfs</option></select></label>
                  {item.type !== "tmpfs" && <label className="docker-mount-source">{t(item.type === "bind" ? "docker.hostPath" : "docker.volumeName")}<span><input aria-label={t("docker.mountSource")} value={item.source} onChange={(event) => updateMount(item.id, { source: event.target.value })} placeholder={item.type === "bind" ? "/srv/data" : "app-data"} />{item.type === "bind" && <button type="button" title={t("docker.chooseHostPath")} aria-label={t("docker.chooseHostPath")} onClick={() => setPathPickerMountId(item.id)}><FolderOpen /></button>}</span></label>}
                  <label>{t("docker.mountTarget")}<input aria-label={t("docker.mountTarget")} value={item.target} onChange={(event) => updateMount(item.id, { target: event.target.value })} placeholder="/data" /></label>
                  {item.type === "tmpfs" ? <label>{t("docker.tmpfsSizeMb")}<input aria-label={t("docker.tmpfsSizeMb")} type="number" min="1" value={item.tmpfsSizeMb} onChange={(event) => updateMount(item.id, { tmpfsSizeMb: event.target.value })} /></label>
                    : <label className="check-row docker-mount-readonly"><input aria-label={t("files.readOnly")} type="checkbox" checked={item.readOnly} onChange={(event) => updateMount(item.id, { readOnly: event.target.checked })} />{t("files.readOnly")}</label>}
                  <button className="docker-mount-remove" type="button" title={t("docker.removeMount")} aria-label={t("docker.removeMount")} onClick={() => setMounts((current) => current.filter((mount) => mount.id !== item.id))}><Minus /></button>
                </div>)}
                <button className="docker-add-mount" type="button" onClick={() => addMount()}><Plus />{t("docker.addMount")}</button>
              </fieldset>
              <label>
                {t("docker.field.labels")}
                <textarea value={labels} onChange={(event) => setLabels(event.target.value)} placeholder={t("docker.labelsHint")} />
              </label>
            </div>
          )}
          {step === 2 && (
            <div className="form-grid">
              <label>
                {t("docker.field.memoryMb")}
                <input
                  type="number"
                  min="16"
                  value={memory}
                  onChange={(event) => setMemory(event.target.value)}
                />
              </label>
              <label>
                {t("docker.field.cpus")}
                <input
                  type="number"
                  min="0.1"
                  step="0.1"
                  value={cpus}
                  onChange={(event) => setCpus(event.target.value)}
                />
              </label>
              <label>
                {t("docker.field.memorySwapMb")}
                <input type="number" min="16" value={memorySwap} onChange={(event) => setMemorySwap(event.target.value)} />
              </label>
              <label>
                {t("docker.field.pids")}
                <input type="number" min="16" value={pids} onChange={(event) => setPids(event.target.value)} />
              </label>
              <label>
                {t("docker.field.userUidGid")}
                <input value={containerUser} onChange={(event) => setContainerUser(event.target.value)} placeholder="1000:1000" />
              </label>
              <label>
                {t("docker.field.workingDir")}
                <input value={workingDir} onChange={(event) => setWorkingDir(event.target.value)} placeholder="/app" />
              </label>
              <label>
                {t("docker.field.healthcheck")}
                <select value={healthType} onChange={(event) => setHealthType(event.target.value as typeof healthType)}>
                  <option value="none">{t("common.none")}</option>
                  <option value="http">HTTP</option>
                  <option value="tcp">TCP</option>
                </select>
              </label>
              {healthType !== "none" && (
                <>
                  <label>
                    {t("docker.field.healthPort")}
                    <input type="number" min="1" max="65535" value={healthPort} onChange={(event) => setHealthPort(event.target.value)} required />
                  </label>
                  {healthType === "http" && <label>{t("docker.field.healthPath")}<input value={healthPath} onChange={(event) => setHealthPath(event.target.value)} /></label>}
                </>
              )}
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={readOnly}
                  onChange={(event) => setReadOnly(event.target.checked)}
                />
                {t("docker.field.readOnly")}
              </label>
              <label className="check-row">
                <input type="checkbox" checked={init} onChange={(event) => setInit(event.target.checked)} />
                {t("docker.field.init")}
              </label>
              <p className="docker-notice info">
                {t("docker.highRiskBlocked")}
              </p>
            </div>
          )}
          {step === 3 && (
            <dl className="docker-review">
              <div>
                <dt>{t("docker.field.name")}</dt>
                <dd>{name}</dd>
              </div>
              <div>
                <dt>{t("docker.field.image")}</dt>
                <dd>{image}</dd>
              </div>
              <div>
                <dt>{t("docker.field.network")}</dt>
                <dd>{network}</dd>
              </div>
              <div>
                <dt>{t("docker.field.ports")}</dt>
                <dd>{ports || "—"}</dd>
              </div>
              <div>
                <dt>{t("docker.field.secrets")}</dt>
                <dd>{secretRows.some((row) => row.value) ? t("docker.secretValuesHidden") : "—"}</dd>
              </div>
              <div>
                <dt>{t("docker.field.mounts")}</dt>
                <dd>{mounts.length ? mounts.map((item) => `${item.type}: ${item.type === "tmpfs" ? "" : `${item.source} → `}${item.target}${item.readOnly ? ` (${t("files.readOnly")})` : ""}`).join(", ") : "—"}</dd>
              </div>
              <div>
                <dt>{t("docker.field.limits")}</dt>
                <dd>{[cpus && `${cpus} CPU`, memory && `${memory} MiB`, pids && `${pids} PID`].filter(Boolean).join(", ") || "—"}</dd>
              </div>
            </dl>
          )}
        </div>
        <footer>
          {step > 0 && (
            <button onClick={() => setStep((value) => value - 1)}>
              <ArrowLeft />
              {t("action.back")}
            </button>
          )}
          <span />
          {step < 3 ? (
            <button
              className="button-primary"
              disabled={step === 0 && (!name || !image)}
              onClick={() => setStep((value) => value + 1)}
            >
              {t("action.next")}
              <ArrowRight />
            </button>
          ) : (
            <button
              className="button-primary"
              disabled={busy || !name || !image}
              onClick={() => void submit()}
            >
              <Boxes />
              {t("docker.createContainer")}
            </button>
          )}
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
