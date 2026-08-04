import {
  Download,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  type DockerArtifact,
  type ModuleJob,
} from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import {
  DockerTable,
  LoadState,
  errorMessage,
} from "./shared";

function safeArtifacts(value: unknown): DockerArtifact[] {
  return Array.isArray(value) ? value as DockerArtifact[] : [];
}

function artifactEnvironmentKeys(
  artifact: DockerArtifact | null,
): string[] {
  if (
    !artifact ||
    artifact.metadata === null ||
    typeof artifact.metadata !== "object" ||
    Array.isArray(artifact.metadata)
  ) {
    return [];
  }
  const value = artifact.metadata.environment_keys;
  return Array.isArray(value)
    ? value
        .filter((item): item is string => typeof item === "string")
        .filter(Boolean)
    : [];
}

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
      const value = await api.dockerBackups();
      setItems(safeArtifacts(value?.artifacts));
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
    const environmentKeys = artifactEnvironmentKeys(restore);
    try {
      const result = await api.restoreDockerBackup(restore.id, {
        new_name: values.new_name,
        secret_environment: Object.fromEntries(
          environmentKeys.map((key) => [
            key,
            values[`secret:${key}`] || "",
          ]),
        ),
        confirmation: values.new_name,
        pam_password: values.pam_password,
      });
      if (result?.job) onJob(result.job);
      setRestore(null);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }

  const restoreEnvironmentKeys = artifactEnvironmentKeys(restore);

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
              {
                key: "display_name",
                label: t("docker.field.name"),
              },
              {
                key: "kind",
                label: t("docker.field.type"),
              },
              {
                key: "size",
                label: t("docker.field.size"),
              },
              {
                key: "checksum",
                label: t("docker.field.checksum"),
              },
              {
                key: "created_at",
                label: t("docker.field.created"),
              },
              {
                key: "created_by",
                label: t("docker.field.actor"),
              },
            ]}
            actions={(row) => {
              const item = row as unknown as DockerArtifact;
              const id =
                typeof item?.id === "string" ? item.id : "";
              return (
                <>
                  <a
                    className="button icon-button"
                    href={
                      id
                        ? `/api/modules/docker/artifacts/${encodeURIComponent(id)}`
                        : undefined
                    }
                    aria-disabled={!id}
                    title={t("action.download")}
                  >
                    <Download />
                  </a>
                  {item?.kind === "container_backup" &&
                    permissions.includes(
                      "docker.restore_backup",
                    ) && (
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
            ...restoreEnvironmentKeys.map((key) => ({
              name: `secret:${key}`,
              label: key,
              type: "password" as const,
              required: true,
            })),
          ]}
          t={t}
          onClose={() => setRestore(null)}
          onSubmit={submit}
        />
      )}
    </>
  );
}
