import {
  ChevronDown,
  ChevronUp,
  Eye,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Square,
  Upload,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api, type DockerContainer, type DockerContainerAction, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { ContainerDetails } from "./ContainerDetails";
import { CreateContainerWizard } from "./CreateContainerWizard";
import { LoadState, StatusPill, errorMessage, format } from "./shared";

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
  const [selected, setSelected] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [wizard, setWizard] = useState(() => Boolean(draftKey && sessionStorage.getItem(draftKey)));
  const [importFile, setImportFile] = useState<File | null>(null);
  const importInput = useRef<HTMLInputElement>(null);
  const [dialog, setDialog] = useState<{
    target: string;
    action: "remove" | "backup" | "export" | "rename" | "duplicate" | "import" | "stop" | "kill";
  } | null>(null);
  function openWizard() { if (draftKey && !sessionStorage.getItem(draftKey)) sessionStorage.setItem(draftKey, "{}"); setWizard(true); }
  function closeWizard() { if (draftKey) sessionStorage.removeItem(draftKey); setWizard(false); }
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await api.dockerContainers({ search, state, page, page_size: 50, sort, direction });
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
                  image: values.image || null,
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
  if (selected)
    return (
      <ContainerDetails
        target={selected}
        t={t}
        onBack={() => setSelected("")}
        permissions={permissions}
        toast={toast}
        onJob={onJob}
      />
    );
  return (
    <>
      <section>
        <div className="docker-section-toolbar">
          <label className="docker-search">
            <Search />
            <span className="visually-hidden">{t("action.search")}</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("action.search")}
            />
          </label>
          <select
            aria-label={t("docker.filterState")}
            value={state}
            onChange={(event) => setState(event.target.value)}
          >
            {["all", "running", "exited", "paused", "dead"].map((value) => (
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
          <select aria-label={t("docker.sortDirection")} value={direction} onChange={(event) => setDirection(event.target.value as "asc" | "desc")}>
            <option value="asc">{t("docker.sortAscending")}</option>
            <option value="desc">{t("docker.sortDescending")}</option>
          </select>
          <button onClick={() => void load()}>
            <RefreshCw />
            {t("action.refresh")}
          </button>
          {permissions.includes("docker.create_container") && (
            <button className="button-primary" onClick={openWizard}>
              <Plus />
              {t("docker.createContainer")}
            </button>
          )}
          {permissions.includes("docker.restore_backup") && (
            <>
              <input ref={importInput} className="visually-hidden" type="file" accept=".tar,.tar.gz,.tgz" onChange={(event) => {
                const file = event.target.files?.[0] || null;
                setImportFile(file);
                if (file) setDialog({ action: "import", target: "" });
              }} />
              <button onClick={() => importInput.current?.click()}><Upload />{t("docker.importContainerFilesystem")}</button>
            </>
          )}
        </div>
        <LoadState
          loading={loading}
          error={error}
          retry={() => void load()}
          t={t}
        >
          {items.length ? <div className="docker-table-wrap docker-containers-table-wrap">
            <table className="docker-table docker-containers-table">
              <thead><tr>
                <th>{t("docker.field.name")}</th>
                <th>{t("docker.field.status")}</th>
                <th>{t("docker.field.actions")}</th>
              </tr></thead>
              <tbody>{items.map((row) => {
                const target = String(row.ID || row.Names || "unknown-container");
                const stateValue = String(row.State || "unknown").toLowerCase();
                const knownStates = ["created", "running", "paused", "restarting", "removing", "exited", "dead", "stopped"];
                const displayedState = knownStates.includes(stateValue) ? stateValue : "unknown";
                const running = stateValue === "running";
                const paused = stateValue === "paused";
                const isExpanded = expanded.has(target);
                const detailsId = `docker-container-details-${target.replace(/[^A-Za-z0-9_-]/g, "-")}`;
                const detailFields: Array<[string, unknown]> = [
                  ["docker.field.id", row.ID], ["docker.field.image", row.Image], ["docker.field.digest", row.Digest],
                  ["docker.field.status", row.Status], ["docker.field.health", row.Health], ["docker.field.created", row.CreatedAt],
                  ["docker.field.restart_policy", row.RestartPolicy], ["docker.field.ports", row.Ports], ["docker.field.networks", row.Networks],
                  ["docker.field.mounts", Array.isArray(row.Mounts) ? row.Mounts.length : row.Mounts],
                  ["docker.statsCpu", `${Number(row.CpuPercent || 0).toFixed(2)}%`],
                  ["docker.statsMemory", `${Math.round(Number(row.MemoryBytes || 0) / 1024 / 1024)} MiB`],
                  ["docker.field.networkIo", `${bytes(row.NetworkInputBytes)} / ${bytes(row.NetworkOutputBytes)}`],
                  ["docker.field.blockIo", `${bytes(row.BlockReadBytes)} / ${bytes(row.BlockWriteBytes)}`],
                  ["docker.field.management", row.Management ? t(`docker.management.${String(row.Management)}`) : ""],
                  ["docker.field.size", row.Size],
                ];
                return <Fragment key={target}>
                  <tr className="docker-container-row">
                    <td className="docker-container-name"><strong>{format(row.Names)}</strong>{Boolean(row.Image) && <small>{String(row.Image)}</small>}</td>
                    <td className="docker-container-status"><StatusPill value={displayedState} t={t} />{Boolean(row.Health) && <small>{String(row.Health)}</small>}</td>
                    <td><div className="docker-row-actions docker-container-actions">
                      <button type="button" title={t("docker.inspect")} onClick={() => setSelected(target)}><Eye /></button>
                      {running ? <button type="button" title={t("module.stop")} disabled={!permissions.includes("docker.stop_container")} onClick={() => setDialog({ target, action: "stop" })}><Square /></button>
                        : paused ? <button type="button" title={t("docker.unpause")} disabled={!permissions.includes("docker.start_container")} onClick={() => void action(target, "unpause")}><Play /></button>
                          : <button type="button" title={t("module.start")} disabled={!permissions.includes("docker.start_container")} onClick={() => void action(target, "start")}><Play /></button>}
                      <button type="button" title={t("module.restart")} disabled={!permissions.includes("docker.restart_container")} onClick={() => void action(target, "restart")}><RotateCcw /></button>
                      <select aria-label={t("docker.moreActions")} defaultValue="" onChange={(event) => {
                        const next = event.target.value;
                        event.target.value = "";
                        if (["rename", "duplicate", "kill", "backup", "export", "remove"].includes(next)) setDialog({ target, action: next as "rename" | "duplicate" | "kill" | "backup" | "export" | "remove" });
                        else if (next === "compose") void exportCompose(target);
                        else if (next) void action(target, next as DockerContainerAction["action"]);
                      }}>
                        <option value="">{t("docker.moreActions")}</option>
                        {running && permissions.includes("docker.stop_container") && <option value="pause">{t("docker.pause")}</option>}
                        {permissions.includes("docker.stop_container") && <option value="kill">{t("docker.kill")}</option>}
                        {permissions.includes("docker.create_container") && <option value="rename">{t("docker.rename")}</option>}
                        {permissions.includes("docker.create_container") && <option value="duplicate">{t("docker.duplicate")}</option>}
                        {permissions.includes("docker.create_container") && <option value="recreate">{t("docker.recreate")}</option>}
                        {permissions.includes("docker.inspect_container") && <option value="compose">{t("docker.generateCompose")}</option>}
                        {permissions.includes("docker.pull_image") && <option value="check_update">{t("docker.checkUpdate")}</option>}
                        {permissions.includes("docker.pull_image") && <option value="update">{t("store.update")}</option>}
                        {permissions.includes("docker.export_backup") && <option value="export">{t("docker.exportContainer")}</option>}
                        {permissions.includes("docker.export_backup") && <option value="backup">{t("docker.backup")}</option>}
                        {permissions.includes("docker.remove_container") && <option value="remove">{t("action.delete")}</option>}
                      </select>
                      <button type="button" className="docker-details-toggle" aria-expanded={isExpanded} aria-controls={detailsId} onClick={() => setExpanded((current) => {
                        const next = new Set(current); if (next.has(target)) next.delete(target); else next.add(target); return next;
                      })}>{isExpanded ? <ChevronUp /> : <ChevronDown />}<span>{t(isExpanded ? "docker.showLess" : "docker.showMore")}</span></button>
                    </div></td>
                  </tr>
                  {isExpanded && <tr id={detailsId} className="docker-container-details-row"><td colSpan={3}>
                    <table className="docker-container-detail-table">
                      <thead><tr><th>{t("docker.details.parameter")}</th><th>{t("docker.details.status")}</th></tr></thead>
                      <tbody>{detailFields.map(([label, value]) => <tr key={label}>
                        <th scope="row">{t(label)}</th>
                        <td className={label === "docker.field.digest" ? "docker-container-detail-long" : undefined}>{detailValue(value, t)}</td>
                      </tr>)}</tbody>
                    </table>
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
      {wizard && (
        <CreateContainerWizard
          t={t}
          toast={toast}
          draftKey={draftKey}
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
              : dialog.action === "rename" || dialog.action === "duplicate"
                ? [
                    {
                      name: "new_name",
                      label: t("docker.newContainerName"),
                      required: true,
                    },
                    ...(dialog.action === "duplicate"
                      ? [
                          {
                            name: "image",
                            label: t("docker.optionalImage"),
                          },
                        ]
                      : []),
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
