import { RefreshCw, Save, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { LoadState, errorMessage } from "./shared";

export function DockerEngineSettings({
  canEdit,
  t,
  toast,
  onJob,
}: {
  canEdit: boolean;
  t: Translate;
  toast: ToastFn;
  onJob: (job: ModuleJob) => void;
}) {
  const [content, setContent] = useState("{}");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [validation, setValidation] = useState("");
  const [confirm, setConfirm] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const value = await api.dockerDaemonConfig();
      setContent(JSON.stringify(value.config, null, 2));
      setError(value.error || "");
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setLoading(false);
    }
  }, [t]);
  useEffect(() => {
    void load();
  }, [load]);
  function parsed(): Record<string, unknown> {
    const value = JSON.parse(content) as unknown;
    if (!value || Array.isArray(value) || typeof value !== "object")
      throw new Error(t("docker.invalidDaemonJson"));
    return value as Record<string, unknown>;
  }
  async function validate() {
    try {
      const result = await api.validateDockerDaemonConfig(parsed());
      setValidation(
        result.ok ? t("docker.daemonConfigValid") : result.errors.join("\n"),
      );
    } catch (reason) {
      setValidation(errorMessage(reason, t));
    }
  }
  async function save(values: Record<string, string>) {
    try {
      onJob(
        (await api.saveDockerDaemonConfig(parsed(), values.pam_password)).job,
      );
      setConfirm(false);
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
          {canEdit && (
            <button onClick={() => void validate()}>
              <ShieldCheck />
              {t("docker.validate")}
            </button>
          )}
          {canEdit && (
            <button className="button-primary" onClick={() => setConfirm(true)}>
              <Save />
              {t("action.save")}
            </button>
          )}
        </div>
        <p className="docker-notice warning">
          {t("docker.daemonConfigWarning")}
        </p>
        <LoadState
          loading={loading}
          error={error}
          retry={() => void load()}
          t={t}
        >
          <textarea
            className="docker-code-editor daemon"
            aria-label={t("docker.daemonConfig")}
            value={content}
            readOnly={!canEdit}
            onChange={(event) => setContent(event.target.value)}
          />
          {validation && (
            <pre className="docker-validation-result">{validation}</pre>
          )}
        </LoadState>
      </section>
      {confirm && (
        <AdminActionDialog
          title={t("docker.applyDaemonConfig")}
          danger
          fields={[
            {
              name: "pam_password",
              label: t("docker.currentPassword"),
              type: "password",
              required: true,
            },
          ]}
          t={t}
          onClose={() => setConfirm(false)}
          onSubmit={save}
        />
      )}
    </>
  );
}
