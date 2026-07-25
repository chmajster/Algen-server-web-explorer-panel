import { Archive, Copy, Plus, RefreshCw, RotateCcw, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { DockerTable, LoadState, errorMessage } from "./shared";

export function VolumesManager({
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
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<{
    action: "create" | "remove" | "clone" | "backup" | "restore" | "prune";
    target?: string;
  } | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems((await api.dockerVolumes(search)).items);
      setError("");
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setLoading(false);
    }
  }, [search, t]);
  useEffect(() => {
    void load();
  }, [load]);
  async function submit(values: Record<string, string>) {
    if (!dialog) return;
    try {
      const result =
        dialog.action === "create"
          ? await api.createDockerVolume({ name: values.name.trim(), labels: {} })
          : await api.dockerVolumeAction(dialog.target || "all", {
              action: dialog.action,
              target_name: values.target_name?.trim() || null,
              backup_id: values.backup_id || null,
              confirmation: dialog.action === "prune" ? "volumes" : dialog.target || "",
              pam_password: values.pam_password || null,
            });
      onJob(result.job);
      setDialog(null);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  return (
    <>
      <section>
        <div className="docker-section-toolbar">
          <label className="docker-search">
            <Search />
            <input
              aria-label={t("action.search")}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <button onClick={() => void load()}>
            <RefreshCw />
            {t("action.refresh")}
          </button>
          <button
            className="button-primary"
            onClick={() => setDialog({ action: "create" })}
          >
            <Plus />
            {t("docker.createVolume")}
          </button>
          {permissions.includes("docker.prune") && (
            <button className="button-danger" onClick={() => setDialog({ action: "prune", target: "volumes" })}>
              <Trash2 />{t("docker.pruneVolumes")}
            </button>
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
            empty={t("docker.noVolumes")}
            columns={[
              { key: "Name", label: t("docker.field.name") },
              { key: "Driver", label: t("docker.field.driver") },
              { key: "Scope", label: t("docker.field.scope") },
              { key: "consumers", label: t("docker.field.consumers") },
            ]}
            actions={(row) => {
              const target = String(row.Name || "");
              return (
                <>
                  {permissions.includes("docker.export_backup") && (
                    <button
                      title={t("docker.backup")}
                      onClick={() => setDialog({ action: "backup", target })}
                    >
                      <Archive />
                    </button>
                  )}
                  <button
                    title={t("docker.clone")}
                    onClick={() => setDialog({ action: "clone", target })}
                  >
                    <Copy />
                  </button>
                  {permissions.includes("docker.restore_backup") && (
                    <button title={t("module.restore")} onClick={() => setDialog({ action: "restore", target })}>
                      <RotateCcw />
                    </button>
                  )}
                  {permissions.includes("docker.high_risk") && (
                    <button
                      className="danger-icon"
                      title={t("action.delete")}
                      onClick={() => setDialog({ action: "remove", target })}
                    >
                      <Trash2 />
                    </button>
                  )}
                </>
              );
            }}
          />
        </LoadState>
      </section>
      {dialog && (
        <AdminActionDialog
          title={t(`docker.volumeAction.${dialog.action}`)}
          danger={["remove", "restore", "prune"].includes(dialog.action)}
          fields={
            dialog.action === "create"
              ? [
                  {
                    name: "name",
                    label: t("docker.field.name"),
                    required: true,
                    minLength: 2,
                    maxLength: 128,
                    pattern: "[A-Za-z0-9][A-Za-z0-9_.-]+",
                    validate: (value) => {
                      const name = value.trim();
                      if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{1,127}$/.test(name))
                        return t("docker.volumeValidation.nameInvalid");
                      if (items.some((item) => String(item.Name || "") === name))
                        return t("docker.volumeValidation.nameDuplicate");
                      return "";
                    },
                  },
                ]
              : dialog.action === "clone"
                ? [
                    {
                      name: "target_name",
                      label: t("docker.cloneName"),
                      required: true,
                      minLength: 2,
                      maxLength: 128,
                      pattern: "[A-Za-z0-9][A-Za-z0-9_.-]+",
                      validate: (value) => {
                        const name = value.trim();
                        if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{1,127}$/.test(name))
                          return t("docker.volumeValidation.nameInvalid");
                        if (items.some((item) => String(item.Name || "") === name))
                          return t("docker.volumeValidation.nameDuplicate");
                        return "";
                      },
                    },
                  ]
                : dialog.action === "restore"
                  ? [
                      { name: "backup_id", label: t("docker.volumeBackupId"), required: true },
                      { name: "pam_password", label: t("docker.currentPassword"), type: "password" as const, required: true },
                    ]
                : dialog.action === "remove" || dialog.action === "prune"
                  ? [
                      {
                        name: "pam_password",
                        label: t("docker.currentPassword"),
                        type: "password",
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
