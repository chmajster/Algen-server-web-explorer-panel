import {
  Download,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Square,
  Trash2,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DockerComposeAction, type DockerComposeSave, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { DockerTable, LoadState, errorMessage } from "./shared";

const TEMPLATE =
  "services:\n  app:\n    image: nginx:stable\n    restart: unless-stopped\n    ports:\n      - 8080:80/tcp\n";

function environmentPairs(value: string, invalidMessage: string) {
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

export function ComposeManager({
  permissions,
  t,
  toast,
  onJob,
  onDirtyChange,
}: {
  permissions: string[];
  t: Translate;
  toast: ToastFn;
  onJob: (job: ModuleJob) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [project, setProject] = useState("");
  const [content, setContent] = useState(TEMPLATE);
  const [environment, setEnvironment] = useState("");
  const [secretEnvironment, setSecretEnvironment] = useState("");
  const [secretsConfigured, setSecretsConfigured] = useState(false);
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([]);
  const [validation, setValidation] = useState("");
  const [runtimeStatus, setRuntimeStatus] = useState<Array<Record<string, unknown>>>([]);
  const [runtimeLogs, setRuntimeLogs] = useState<string[]>([]);
  const [logService, setLogService] = useState("");
  const [dialog, setDialog] = useState<{
    action: "delete" | "scale" | "rollback";
    project: string;
    revision?: string;
  } | null>(null);
  const composeUpload = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems((await api.dockerComposeProjects()).items);
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
  async function edit(name: string) {
    try {
      const value = await api.dockerComposeProject(name);
      setProject(name);
      setContent(value.content);
      setEnvironment(
        Object.entries(value.environment || {})
          .map(([key, item]) => `${key}=${item}`)
          .join("\n"),
      );
      setHistory(value.history || []);
      setSecretEnvironment("");
      setSecretsConfigured(Boolean(value.secrets_configured));
      const [status, logs] = await Promise.all([
        api.dockerComposeStatus(name).catch(() => ({ items: [], total: 0 })),
        api.dockerComposeLogs(name).catch(() => ({ lines: [], total: 0, truncated: false })),
      ]);
      setRuntimeStatus(status.items);
      setRuntimeLogs(logs.lines);
      onDirtyChange(false);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  async function refreshRuntime() {
    try {
      const [status, logs] = await Promise.all([
        api.dockerComposeStatus(project),
        api.dockerComposeLogs(project, logService),
      ]);
      setRuntimeStatus(status.items);
      setRuntimeLogs(logs.lines);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  async function save() {
    try {
      const payload: DockerComposeSave = {
        content,
        environment: environmentPairs(environment, t("docker.invalidEnvironment")),
        description: t("docker.composeSaved"),
      };
      if (secretEnvironment.trim())
        payload.secret_environment = environmentPairs(
          secretEnvironment,
          t("docker.invalidEnvironment"),
        );
      const saved = await api.saveDockerComposeProject(project, payload);
      setSecretEnvironment("");
      setSecretsConfigured(Boolean(saved.secrets_configured));
      onDirtyChange(false);
      toast(t("docker.composeSaved"), "ok", "admin");
      await load();
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  async function validate() {
    try {
      await api.validateDockerCompose(project || "preview", {
        content,
        environment: environmentPairs(environment, t("docker.invalidEnvironment")),
        secret_environment: secretEnvironment.trim() ? environmentPairs(secretEnvironment, t("docker.invalidEnvironment")) : null,
        description: "",
      });
      setValidation(t("docker.composeValid"));
    } catch (reason) {
      setValidation(errorMessage(reason, t));
    }
  }
  async function action(name: string, verb: DockerComposeAction["action"]) {
    try {
      const result = await api.dockerComposeAction(name, {
        action: verb,
        services: [],
        remove_volumes: false,
        confirmation: "",
      });
      if (result.job) onJob(result.job);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  async function submitDialog(values: Record<string, string>) {
    if (!dialog) return;
    try {
      if (dialog.action === "scale") {
        const replicas = Number(values.replicas);
        if (!Number.isInteger(replicas) || replicas < 0 || replicas > 1000)
          throw new Error(t("docker.invalidReplicas"));
        const result = await api.dockerComposeAction(dialog.project, {
          action: "scale",
          services: [],
          scale: { [values.service]: replicas },
          remove_volumes: false,
          confirmation: "",
        });
        if (result.job) onJob(result.job);
        setDialog(null);
        return;
      }
      if (dialog.action === "rollback") {
        await api.rollbackDockerCompose(
          dialog.project,
          dialog.revision || "",
          values.confirmation,
        );
        setDialog(null);
        await edit(dialog.project);
        toast(t("docker.composeRolledBack"), "ok", "admin");
        return;
      }
      const result = await api.dockerComposeAction(dialog.project, {
        action: "delete",
        services: [],
        remove_volumes: values.remove_volumes === "true",
        confirmation: values.confirmation,
        pam_password: values.pam_password,
      });
      if (result.job) onJob(result.job);
      setDialog(null);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  function exportCompose() {
    const url = URL.createObjectURL(
      new Blob([content], { type: "application/yaml;charset=utf-8" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${project || "compose"}.yaml`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  async function importCompose(file?: File) {
    if (!file) return;
    try {
      if (file.size > 512 * 1024) throw new Error(t("docker.composeTooLarge"));
      const base = file.name.replace(/\.(ya?ml)$/i, "").toLowerCase();
      const safeName = base
        .replace(/[^a-z0-9_-]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 63) || "imported-compose";
      setProject(safeName);
      setContent(await file.text());
      setEnvironment("");
      setSecretEnvironment("");
      setSecretsConfigured(false);
      setHistory([]);
      onDirtyChange(true);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    } finally {
      if (composeUpload.current) composeUpload.current.value = "";
    }
  }
  if (project)
    return (
      <section className="docker-compose-editor">
        <div className="docker-section-toolbar">
          <button
            onClick={() => {
              setProject("");
              onDirtyChange(false);
            }}
          >
            {t("action.back")}
          </button>
          <input
            aria-label={t("docker.projectName")}
            value={project}
            onChange={(event) => {
              setProject(event.target.value);
              onDirtyChange(true);
            }}
          />
          <button onClick={() => void validate()}>
            {t("docker.validate")}
          </button>
          <button onClick={exportCompose}>
            <Download />
            {t("docker.exportCompose")}
          </button>
          <button className="button-primary" onClick={() => void save()}>
            <Save />
            {t("action.save")}
          </button>
        </div>
        <label>
          {t("docker.composeYaml")}
          <textarea
            className="docker-code-editor"
            value={content}
            onChange={(event) => {
              setContent(event.target.value);
              onDirtyChange(true);
            }}
          />
        </label>
        <label>
          {t("docker.publicEnvironment")}
          <textarea
            value={environment}
            onChange={(event) => {
              setEnvironment(event.target.value);
              onDirtyChange(true);
            }}
          />
        </label>
        <label>
          {t("docker.secretEnvironment")}
          <textarea
            value={secretEnvironment}
            placeholder={
              secretsConfigured ? t("docker.secretValuesHidden") : undefined
            }
            onChange={(event) => {
              setSecretEnvironment(event.target.value);
              onDirtyChange(true);
            }}
          />
          <small>{t("docker.secretsHint")}</small>
        </label>
        {validation && (
          <p className="docker-notice info" role="status">
            {validation}
          </p>
        )}
        <section>
          <div className="docker-section-toolbar">
            <h3>{t("docker.composeServices")}</h3>
            <input value={logService} onChange={(event) => setLogService(event.target.value)} placeholder={t("docker.optionalService")} />
            <button onClick={() => void refreshRuntime()}><RefreshCw />{t("action.refresh")}</button>
          </div>
          <DockerTable
            items={runtimeStatus}
            empty={t("docker.noComposeServices")}
            columns={[
              { key: "Service", label: t("docker.field.service") },
              { key: "Name", label: t("docker.field.name") },
              { key: "State", label: t("docker.field.state") },
              { key: "Health", label: t("docker.field.health") },
              { key: "Publishers", label: t("docker.field.ports") },
            ]}
          />
          <h3>{t("docker.composeLogs")}</h3>
          <pre className="docker-log-view">{runtimeLogs.join("\n")}</pre>
        </section>
        <section>
          <h3>{t("docker.history")}</h3>
          <DockerTable
            items={history}
            empty={t("docker.noHistory")}
            columns={[
              { key: "id", label: t("docker.field.revision") },
              { key: "created_at", label: t("docker.field.created") },
              { key: "created_by", label: t("docker.field.actor") },
              { key: "description", label: t("docker.field.description") },
            ]}
            actions={(row) => (
              <button
                title={t("docker.rollbackCompose")}
                onClick={() =>
                  setDialog({
                    action: "rollback",
                    project,
                    revision: String(row.id || ""),
                  })
                }
              >
                <RotateCcw />
              </button>
            )}
          />
        </section>
      </section>
    );
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
            onClick={() => {
              setProject("new-project");
              setContent(TEMPLATE);
              setEnvironment("");
              setSecretEnvironment("");
              setSecretsConfigured(false);
              setHistory([]);
              onDirtyChange(true);
            }}
          >
            <Plus />
            {t("docker.newCompose")}
          </button>
          <input
            ref={composeUpload}
            className="visually-hidden"
            type="file"
            accept=".yaml,.yml,application/yaml,text/yaml"
            onChange={(event) => void importCompose(event.target.files?.[0])}
          />
          <button onClick={() => composeUpload.current?.click()}>
            <Upload />
            {t("docker.importCompose")}
          </button>
        </div>
        <LoadState
          loading={loading}
          error={error}
          retry={() => void load()}
          t={t}
        >
          <DockerTable
            items={items}
            empty={t("docker.noComposeProjects")}
            columns={[
              { key: "name", label: t("docker.field.name") },
              { key: "updated_at", label: t("docker.field.updated") },
              { key: "size", label: t("docker.field.size") },
            ]}
            actions={(row) => {
              const name = String(row.name || "");
              return (
                <>
                  <button
                    title={t("action.edit")}
                    onClick={() => void edit(name)}
                  >
                    <Save />
                  </button>
                  <button
                    title={t("docker.up")}
                    onClick={() => void action(name, "up")}
                  >
                    <Play />
                  </button>
                  <button
                    title={t("docker.stop")}
                    onClick={() => void action(name, "stop")}
                  >
                    <Square />
                  </button>
                  <button
                    title={t("docker.pull")}
                    onClick={() => void action(name, "pull")}
                  >
                    <Download />
                  </button>
                  <button
                    title={t("docker.restart")}
                    onClick={() => void action(name, "restart")}
                  >
                    <RotateCcw />
                  </button>
                  <button
                    title={t("docker.scale")}
                    onClick={() =>
                      setDialog({ action: "scale", project: name })
                    }
                  >
                    {t("docker.scale")}
                  </button>
                  {permissions.includes("docker.high_risk") && (
                    <button
                      className="danger-icon"
                      title={t("action.delete")}
                      onClick={() =>
                        setDialog({ action: "delete", project: name })
                      }
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
          title={
            dialog.action === "delete"
              ? t("docker.deleteCompose")
              : dialog.action === "scale"
                ? t("docker.scaleCompose")
                : t("docker.rollbackCompose")
          }
          danger={dialog.action === "delete" || dialog.action === "rollback"}
          fields={
            dialog.action === "delete"
              ? [
                  {
                    name: "confirmation",
                    label: t("docker.exactConfirmation"),
                    value: dialog.project,
                    required: true,
                  },
                  {
                    name: "pam_password",
                    label: t("docker.currentPassword"),
                    type: "password" as const,
                    required: true,
                  },
                  {
                    name: "remove_volumes",
                    label: t("docker.removeVolumes"),
                    type: "select" as const,
                    value: "false",
                    options: [
                      { value: "false", label: t("common.no") },
                      { value: "true", label: t("common.yes") },
                    ],
                  },
                ]
              : dialog.action === "scale"
                ? [
                    {
                      name: "service",
                      label: t("docker.serviceName"),
                      required: true,
                    },
                    {
                      name: "replicas",
                      label: t("docker.replicas"),
                      type: "number" as const,
                      value: "1",
                      required: true,
                    },
                  ]
                : [
                    {
                      name: "confirmation",
                      label: t("docker.exactConfirmation"),
                      value: dialog.project,
                      required: true,
                    },
                  ]
          }
          t={t}
          onClose={() => setDialog(null)}
          onSubmit={submitDialog}
        />
      )}
    </>
  );
}
