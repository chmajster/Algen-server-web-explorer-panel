import {
  Archive,
  Download,
  Eye,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Square,
  Trash2,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DockerContainer, type DockerContainerAction, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { ContainerDetails } from "./ContainerDetails";
import { CreateContainerWizard } from "./CreateContainerWizard";
import { DockerTable, LoadState, StatusPill, errorMessage } from "./shared";

export function ContainersList({
  permissions,
  t,
  toast,
  onJob,
}: {
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
  const [wizard, setWizard] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const importInput = useRef<HTMLInputElement>(null);
  const [dialog, setDialog] = useState<{
    target: string;
    action: "remove" | "backup" | "export" | "rename" | "duplicate" | "import" | "stop" | "kill";
  } | null>(null);
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
            <button className="button-primary" onClick={() => setWizard(true)}>
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
          <DockerTable
            items={items}
            empty={t("docker.noContainers")}
            columns={[
              { key: "Names", label: t("docker.field.name") },
              { key: "Image", label: t("docker.field.image") },
              { key: "Digest", label: t("docker.field.digest") },
              {
                key: "State",
                label: t("docker.field.state"),
                render: (value) => <StatusPill value={String(value)} t={t} />,
              },
              { key: "Status", label: t("docker.field.status") },
              { key: "Health", label: t("docker.field.health") },
              { key: "CreatedAt", label: t("docker.field.created") },
              { key: "RestartPolicy", label: t("docker.field.restart_policy") },
              { key: "Ports", label: t("docker.field.ports") },
              { key: "Networks", label: t("docker.field.networks") },
              { key: "Mounts", label: t("docker.field.mounts"), render: (value) => String(Array.isArray(value) ? value.length : 0) },
              { key: "CpuPercent", label: t("docker.statsCpu"), render: (value) => `${Number(value || 0).toFixed(2)}%` },
              { key: "MemoryBytes", label: t("docker.statsMemory"), render: (value) => `${Math.round(Number(value || 0) / 1024 / 1024)} MiB` },
              { key: "NetworkInputBytes", label: t("docker.field.networkIo"), render: (value, row) => `${Number(value || 0)} / ${Number(row.NetworkOutputBytes || 0)}` },
              { key: "BlockReadBytes", label: t("docker.field.blockIo"), render: (value, row) => `${Number(value || 0)} / ${Number(row.BlockWriteBytes || 0)}` },
              { key: "Management", label: t("docker.field.management"), render: (value) => t(`docker.management.${String(value)}`) },
              { key: "Size", label: t("docker.field.size") },
            ]}
            actions={(row) => {
              const target = String(row.ID || row.Names || "");
              const running = String(row.State).toLowerCase() === "running";
              const paused = String(row.State).toLowerCase() === "paused";
              return (
                <>
                  <button
                    title={t("docker.inspect")}
                    onClick={() => setSelected(target)}
                  >
                    <Eye />
                  </button>
                  {running ? (
                    <button
                      title={t("module.stop")}
                      disabled={!permissions.includes("docker.stop_container")}
                      onClick={() => setDialog({ target, action: "stop" })}
                    >
                      <Square />
                    </button>
                  ) : paused ? (
                    <button
                      title={t("docker.unpause")}
                      disabled={!permissions.includes("docker.start_container")}
                      onClick={() => void action(target, "unpause")}
                    >
                      <Play />
                    </button>
                  ) : (
                    <button
                      title={t("module.start")}
                      disabled={!permissions.includes("docker.start_container")}
                      onClick={() => void action(target, "start")}
                    >
                      <Play />
                    </button>
                  )}
                  <button
                    title={t("module.restart")}
                    disabled={!permissions.includes("docker.restart_container")}
                    onClick={() => void action(target, "restart")}
                  >
                    <RotateCcw />
                  </button>
                  <select
                    aria-label={t("docker.moreActions")}
                    defaultValue=""
                    onChange={(event) => {
                      const next = event.target.value;
                      event.target.value = "";
                      if (next === "rename" || next === "duplicate" || next === "kill")
                        setDialog({ target, action: next });
                      else if (next === "compose") void exportCompose(target);
                      else if (next)
                        void action(
                          target,
                          next as DockerContainerAction["action"],
                        );
                    }}
                  >
                    <option value="">{t("docker.moreActions")}</option>
                    {running && permissions.includes("docker.stop_container") && (
                      <option value="pause">{t("docker.pause")}</option>
                    )}
                    {permissions.includes("docker.stop_container") && (
                      <option value="kill">{t("docker.kill")}</option>
                    )}
                    {permissions.includes("docker.create_container") && (
                      <option value="rename">{t("docker.rename")}</option>
                    )}
                    {permissions.includes("docker.create_container") && (
                      <option value="duplicate">{t("docker.duplicate")}</option>
                    )}
                    {permissions.includes("docker.create_container") && (
                      <option value="recreate">{t("docker.recreate")}</option>
                    )}
                    {permissions.includes("docker.inspect_container") && (
                      <option value="compose">{t("docker.generateCompose")}</option>
                    )}
                    {permissions.includes("docker.pull_image") && (
                      <option value="check_update">{t("docker.checkUpdate")}</option>
                    )}
                    {permissions.includes("docker.pull_image") && (
                      <option value="update">{t("store.update")}</option>
                    )}
                  </select>
                  <button
                    title={t("docker.exportContainer")}
                    disabled={!permissions.includes("docker.export_backup")}
                    onClick={() => setDialog({ target, action: "export" })}
                  >
                    <Download />
                  </button>
                  <button
                    title={t("docker.backup")}
                    disabled={!permissions.includes("docker.export_backup")}
                    onClick={() => setDialog({ target, action: "backup" })}
                  >
                    <Archive />
                  </button>
                  <button
                    title={t("action.delete")}
                    className="danger-icon"
                    disabled={!permissions.includes("docker.remove_container")}
                    onClick={() => setDialog({ target, action: "remove" })}
                  >
                    <Trash2 />
                  </button>
                </>
              );
            }}
          />
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
          onClose={() => setWizard(false)}
          onStarted={onJob}
          canImportCompose={permissions.includes("docker.manage_compose")}
          canViewLocalImages={permissions.includes("docker.view_images")}
          canViewLocalNetworks={permissions.includes("docker.view_networks")}
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
