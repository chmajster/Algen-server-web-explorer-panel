import { Download, RefreshCw, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type DockerArtifact, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { DockerTable, LoadState, errorMessage } from "./shared";

export function DockerBackups({
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
  const [items, setItems] = useState<DockerArtifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [restore, setRestore] = useState<DockerArtifact | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems((await api.dockerBackups()).artifacts);
      setError("");
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setLoading(false);
    }
  }, [t]);
  useEffect(() => {
    void load();
  }, [load]);
  async function submit(values: Record<string, string>) {
    if (!restore) return;
    try {
      onJob(
        (
          await api.restoreDockerBackup(restore.id, {
            new_name: values.new_name,
            secret_environment: Object.fromEntries(((restore.metadata.environment_keys as string[] | undefined) || []).map((key) => [key, values[`secret:${key}`]])),
            confirmation: values.new_name,
            pam_password: values.pam_password,
          })
        ).job,
      );
      setRestore(null);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  return (
    <>
      <section>
        <div className="docker-section-toolbar">
          <button onClick={() => void load()}>
            <RefreshCw />
            {t("action.refresh")}
          </button>
        </div>
        <p className="docker-notice warning">
          {t("docker.backupSecretsOmitted")}
        </p>
        <LoadState
          loading={loading}
          error={error}
          retry={() => void load()}
          t={t}
        >
          <DockerTable
            items={items}
            empty={t("docker.noBackups")}
            columns={[
              { key: "display_name", label: t("docker.field.name") },
              { key: "kind", label: t("docker.field.type") },
              { key: "size", label: t("docker.field.size") },
              { key: "checksum", label: t("docker.field.checksum") },
              { key: "created_at", label: t("docker.field.created") },
              { key: "created_by", label: t("docker.field.actor") },
            ]}
            actions={(row) => {
              const item = row as unknown as DockerArtifact;
              return (
                <>
                  <a
                    className="button icon-button"
                    href={`/api/modules/docker/artifacts/${encodeURIComponent(item.id)}`}
                    title={t("action.download")}
                  >
                    <Download />
                  </a>
                  {item.kind === "container_backup" &&
                    permissions.includes("docker.restore_backup") && (
                    <button
                      title={t("module.restore")}
                      onClick={() => setRestore(item)}
                    >
                      <RotateCcw />
                    </button>
                  )}
                </>
              );
            }}
          />
        </LoadState>
      </section>
      {restore && (
        <AdminActionDialog
          title={t("module.restore")}
          danger
          fields={[
            {
              name: "new_name",
              label: t("docker.restoreName"),
              required: true,
            },
            {
              name: "pam_password",
              label: t("docker.currentPassword"),
              type: "password",
              required: true,
            },
            ...(((restore.metadata.environment_keys as string[] | undefined) || []).map((key) => ({
              name: `secret:${key}`,
              label: key,
              type: "password" as const,
              required: true,
            }))),
          ]}
          t={t}
          onClose={() => setRestore(null)}
          onSubmit={submit}
        />
      )}
    </>
  );
}
