import {
  BookOpen,
  Download,
  ExternalLink,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Square,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type DockerApp, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { LoadState, StatusPill, errorMessage } from "./shared";

export function ContainerAppsCatalog({
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
  const [items, setItems] = useState<DockerApp[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<{
    app: DockerApp;
    action: "install" | "remove" | "update";
  } | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems((await api.dockerApps(search)).items);
      setError("");
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setLoading(false);
    }
  }, [search, t]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 180);
    return () => window.clearTimeout(timer);
  }, [load]);
  async function quick(app: DockerApp, action: "start" | "stop" | "restart") {
    try {
      onJob((await api.dockerAppAction(app.id, action)).job);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  async function submit(values: Record<string, string>) {
    if (!dialog) return;
    try {
      if (dialog.action === "install") {
        const secret_environment = Object.fromEntries(
          dialog.app.required_secrets.map((key) => [key, values[key]]),
        );
        onJob(
          (
            await api.installDockerApp(dialog.app.id, {
              secret_environment,
              ...(dialog.app.id === "pihole"
                ? {
                    timezone: values.timezone,
                    hostname: values.hostname,
                    panel_port: Number(values.panel_port),
                    dns_port: Number(values.dns_port),
                    network: values.network,
                  }
                : {}),
              confirmation: dialog.app.id,
            })
          ).job,
        );
      } else
        onJob(
          (
            await api.dockerAppAction(
              dialog.app.id,
              dialog.action,
              {
                confirmation: dialog.app.id,
                pam_password: values.pam_password || null,
              },
            )
          ).job,
        );
      setDialog(null);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  function panelUrl(app: DockerApp) {
    const hostname = window.location.hostname.replace(/^\[|\]$/g, "");
    return app.panel_port
      ? `http://${hostname.includes(":") ? `[${hostname}]` : hostname}:${app.panel_port}`
      : "";
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
        </div>
        <LoadState
          loading={loading}
          error={error}
          retry={() => void load()}
          t={t}
        >
          <div className="docker-app-grid">
            {items.map((app) => (
              <article className="docker-app-card" key={app.id}>
                <header>
                  <div>
                    <strong>{app.name}</strong>
                    <small>{t(`package.category.${app.category}`)}</small>
                  </div>
                  <StatusPill value={app.status} t={t} />
                </header>
                <p>{t(`docker.appDescription.${app.id}`)}</p>
                {app.id === "pihole" && (
                  <p className="docker-notice warning">{t("docker.piholePortWarning")}</p>
                )}
                <dl>
                  <div>
                    <dt>{t("docker.field.image")}</dt>
                    <dd>{app.image}</dd>
                  </div>
                  <div>
                    <dt>{t("docker.field.ports")}</dt>
                    <dd>{app.ports.join(", ")}</dd>
                  </div>
                  <div>
                    <dt>{t("module.version")}</dt>
                    <dd>{app.version}</dd>
                  </div>
                  <div>
                    <dt>{t("docker.field.architectures")}</dt>
                    <dd>{app.architectures.join(", ")}</dd>
                  </div>
                  <div>
                    <dt>{t("docker.field.minimumMemory")}</dt>
                    <dd>{app.minimum_memory_mb} MiB</dd>
                  </div>
                  <div>
                    <dt>{t("docker.field.healthcheck")}</dt>
                    <dd>{app.healthcheck}</dd>
                  </div>
                </dl>
                {app.installed && !app.managed && (
                  <p className="docker-notice warning">
                    {t("docker.unmanagedContainer")}
                  </p>
                )}
                <footer>
                  {app.documentation_url && (
                    <a className="button" href={app.documentation_url} target="_blank" rel="noreferrer">
                      <BookOpen />
                      {t("docker.documentation")}
                    </a>
                  )}
                  {app.running && (
                    <a
                      className="button"
                      href={panelUrl(app)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink />
                      {t("docker.openPanel")}
                    </a>
                  )}
                  {!app.installed &&
                    permissions.includes("docker.create_container") && (
                      <button
                        className="button-primary"
                        onClick={() => setDialog({ app, action: "install" })}
                      >
                        <Download />
                        {t("store.install")}
                      </button>
                    )}
                  {app.installed && app.managed && (
                    <>
                      {app.running &&
                        permissions.includes("docker.stop_container") && (
                        <button onClick={() => void quick(app, "stop")}>
                          <Square />
                          {t("module.stop")}
                        </button>
                      )}
                      {!app.running &&
                        permissions.includes("docker.start_container") && (
                        <button onClick={() => void quick(app, "start")}>
                          <Play />
                          {t("module.start")}
                        </button>
                      )}
                      {app.running &&
                        permissions.includes("docker.restart_container") && (
                          <button onClick={() => void quick(app, "restart")}>
                            <RotateCcw />
                            {t("module.restart")}
                          </button>
                        )}
                      {permissions.includes("docker.pull_image") && (
                        <button
                          onClick={() => setDialog({ app, action: "update" })}
                        >
                          <RefreshCw />
                          {t("store.update")}
                        </button>
                      )}
                      {permissions.includes("docker.remove_container") &&
                        permissions.includes("docker.high_risk") && (
                          <button
                            className="button-danger"
                            onClick={() => setDialog({ app, action: "remove" })}
                          >
                            <Trash2 />
                            {t("action.delete")}
                          </button>
                        )}
                    </>
                  )}
                </footer>
              </article>
            ))}
          </div>
        </LoadState>
      </section>
      {dialog && (
        <AdminActionDialog
          title={t(`docker.appAction.${dialog.action}`)}
          danger={dialog.action === "remove"}
          fields={
            dialog.action === "install"
              ? [
                  ...dialog.app.required_secrets.map((key) => ({
                    name: key,
                    label: key === "WEBPASSWORD" ? t("managed.piholePassword") : key,
                    type: "password" as const,
                    required: true,
                  })),
                  ...(dialog.app.id === "pihole"
                    ? [
                        { name: "hostname", label: t("docker.field.hostname"), value: "pihole", required: true },
                        { name: "timezone", label: t("managed.timezone"), value: "Europe/Warsaw", required: true },
                        { name: "panel_port", label: t("docker.field.panelPort"), type: "number" as const, value: "8080", required: true },
                        { name: "dns_port", label: t("docker.field.dnsPort"), type: "number" as const, value: "53", required: true },
                        { name: "network", label: t("docker.field.network"), value: "bridge", required: true },
                      ]
                    : []),
                ]
              : dialog.action === "remove"
                ? [
                    {
                      name: "pam_password",
                      label: t("docker.currentPassword"),
                      type: "password" as const,
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
