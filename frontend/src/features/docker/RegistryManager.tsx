import { LogOut, Pencil, Plus, RefreshCw, TestTube2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type DockerRegistry, type DockerRegistrySave, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { DockerTable, LoadState, errorMessage } from "./shared";

type RegistryDialog =
  | { kind: "create" }
  | { kind: "edit"; item: DockerRegistry }
  | { kind: "delete"; item: DockerRegistry };

export function RegistryManager({
  t,
  toast,
  onJob,
}: {
  t: Translate;
  toast: ToastFn;
  onJob: (job: ModuleJob) => void;
}) {
  const [items, setItems] = useState<DockerRegistry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<RegistryDialog | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems((await api.dockerRegistries()).items);
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
    if (!dialog) return;
    try {
      if (dialog.kind === "delete")
        await api.deleteDockerRegistry(dialog.item.id, values.confirmation);
      else {
        const result = await api.saveDockerRegistry({
          name: values.name,
          provider: values.provider as DockerRegistrySave["provider"],
          server: values.server,
          username: values.username,
          password: values.password || null,
          tls: values.tls === "true",
          ca_certificate: values.ca_certificate || null,
        }, dialog.kind === "edit" ? dialog.item.id : "");
        onJob(result.job);
      }
      setDialog(null);
      await load();
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
          <button
            className="button-primary"
            onClick={() => setDialog({ kind: "create" })}
          >
            <Plus />
            {t("docker.addRegistry")}
          </button>
        </div>
        <p className="docker-notice info">{t("docker.registrySecretHint")}</p>
        <LoadState
          loading={loading}
          error={error}
          retry={() => void load()}
          t={t}
        >
          <DockerTable
            items={items}
            empty={t("docker.noRegistries")}
            columns={[
              {
                key: "name",
                label: t("docker.field.name"),
                render: (value, row) => <span className="docker-registry-name">{String(value)}{Boolean(row.built_in) && <small>{t("docker.builtIn")}</small>}</span>,
              },
              { key: "provider", label: t("docker.field.provider") },
              { key: "server", label: t("docker.field.server") },
              {
                key: "username",
                label: t("settings.username"),
                render: (value, row) => row.public_access ? t("docker.publicAnonymous") : String(value || "—"),
              },
              {
                key: "secret_configured",
                label: t("docker.field.secretConfigured"),
                render: (value, row) => row.public_access ? t("docker.notRequired") : t(value ? "common.yes" : "common.no"),
              },
              { key: "tls", label: t("docker.field.tls") },
              {
                key: "ca_certificate_configured",
                label: t("docker.field.caCertificate"),
              },
            ]}
            actions={(row) => {
              const item = row as unknown as DockerRegistry;
              if (item.built_in) return <span className="status-badge">{t("docker.defaultRegistry")}</span>;
              return (
                <>
                  <button title={t("action.edit")} onClick={() => setDialog({ kind: "edit", item })}>
                    <Pencil />
                  </button>
                  <button
                    title={t("docker.testRegistry")}
                    onClick={() => void api.testDockerRegistry(item.id).then((result) => onJob(result.job)).catch((reason) => toast(errorMessage(reason, t), "error", "admin"))}
                  >
                    <TestTube2 />
                  </button>
                  <button
                    title={t("docker.logoutRegistry")}
                    onClick={() => void api.logoutDockerRegistry(item.id).then((result) => onJob(result.job)).catch((reason) => toast(errorMessage(reason, t), "error", "admin"))}
                  >
                    <LogOut />
                  </button>
                  <button className="danger-icon" title={t("action.delete")} onClick={() => setDialog({ kind: "delete", item })}>
                    <Trash2 />
                  </button>
                </>
              );
            }}
          />
        </LoadState>
      </section>
      {dialog && (
        <AdminActionDialog
          title={t(
            dialog.kind !== "delete"
              ? dialog.kind === "create" ? "docker.addRegistry" : "docker.editRegistry"
              : "docker.removeRegistry",
          )}
          danger={dialog.kind === "delete"}
          fields={
            dialog.kind === "delete"
              ? [
                  {
                    name: "confirmation",
                    label: t("docker.exactConfirmation"),
                    value: dialog.item.name,
                    required: true,
                  },
                ]
              : [
                  {
                    name: "name",
                    label: t("docker.field.name"),
                    value: dialog.kind === "edit" ? dialog.item.name : "",
                    required: true,
                  },
                  {
                    name: "provider",
                    label: t("docker.field.provider"),
                    type: "select",
                    value: dialog.kind === "edit" ? dialog.item.provider : "docker_hub",
                    options: [
                      "docker_hub",
                      "ghcr",
                      "gitlab",
                      "quay",
                      "custom",
                    ].map((value) => ({ value, label: value })),
                  },
                  {
                    name: "server",
                    label: t("docker.field.server"),
                    value: dialog.kind === "edit" ? dialog.item.server : "registry-1.docker.io",
                    required: true,
                  },
                  {
                    name: "username",
                    label: t("settings.username"),
                    value: dialog.kind === "edit" ? dialog.item.username : "",
                    required: true,
                  },
                  {
                    name: "password",
                    label: t("docker.field.passwordToken"),
                    type: "password",
                    required: dialog.kind === "create",
                  },
                  {
                    name: "tls",
                    label: t("docker.field.tls"),
                    type: "select",
                    value: dialog.kind === "edit" ? String(dialog.item.tls) : "true",
                    options: [
                      { value: "true", label: t("common.yes") },
                      { value: "false", label: t("common.no") },
                    ],
                  },
                  {
                    name: "ca_certificate",
                    label: t("docker.field.caCertificate"),
                    type: "textarea",
                  },
                ]
          }
          t={t}
          onClose={() => setDialog(null)}
          onSubmit={submit}
        />
      )}
    </>
  );
}
