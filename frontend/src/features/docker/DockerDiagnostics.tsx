import { RefreshCw, Stethoscope } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type ModuleDiagnostic, type ModuleStatus } from "../../api";
import type { Translate } from "../../app/types";
import { LoadState, errorMessage, format } from "./shared";

export function DockerDiagnostics({ t }: { t: Translate }) {
  const [data, setData] = useState<{
    checks: ModuleDiagnostic[];
    status: ModuleStatus;
    config: Record<string, unknown>;
    prune: Record<string, unknown>;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.dockerDiagnostics());
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
  return (
    <section>
      <div className="docker-section-toolbar">
        <button onClick={() => void load()}>
          <RefreshCw />
          {t("docker.runDiagnostics")}
        </button>
      </div>
      <LoadState
        loading={loading}
        error={error}
        retry={() => void load()}
        t={t}
      >
        {data && (
          <>
            <div className="docker-diagnostic-list">
              {data.checks.map((check, index) => (
                <article
                  className={check.severity}
                  key={`${check.title}-${index}`}
                >
                  <Stethoscope />
                  <div>
                    <strong>{check.title}</strong>
                    <p>{check.description}</p>
                    {check.details && <pre>{check.details}</pre>}
                    {check.recommended_action && (
                      <small>{check.recommended_action}</small>
                    )}
                  </div>
                </article>
              ))}
            </div>
            <section className="docker-report">
              <h3>{t("docker.diagnosticReport")}</h3>
              <dl>
                <div>
                  <dt>{t("docker.engine")}</dt>
                  <dd>{data.status.health}</dd>
                </div>
                <div>
                  <dt>{t("docker.daemonConfig")}</dt>
                  <dd>{format(data.config)}</dd>
                </div>
                <div>
                  <dt>{t("docker.prunePreview")}</dt>
                  <dd>{format(data.prune)}</dd>
                </div>
              </dl>
            </section>
          </>
        )}
      </LoadState>
    </section>
  );
}
