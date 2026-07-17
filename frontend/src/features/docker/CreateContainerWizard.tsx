import { ArrowLeft, ArrowRight, Boxes, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { api, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { errorMessage } from "./shared";

function pairs(value: string, invalidMessage: string): Record<string, string> {
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

function mountLines(value: string, invalidMessage: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(":");
      const type = parts[0];
      if (type === "tmpfs" && parts.length >= 2)
        return {
          type: "tmpfs" as const,
          source: "",
          target: parts[1],
          tmpfs_size_mb: parts[2] ? Number(parts[2]) : null,
        };
      if ((type === "bind" || type === "volume") && parts.length >= 3)
        return {
          type: type as "bind" | "volume",
          source: parts[1],
          target: parts[2],
          read_only: parts[3] === "ro",
        };
      throw new Error(invalidMessage);
    });
}

export function CreateContainerWizard({
  t,
  toast,
  onClose,
  onStarted,
}: {
  t: Translate;
  toast: ToastFn;
  onClose: () => void;
  onStarted: (job: ModuleJob) => void;
}) {
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [image, setImage] = useState("");
  const [network, setNetwork] = useState("bridge");
  const [ports, setPorts] = useState("");
  const [environment, setEnvironment] = useState("");
  const [secretRows, setSecretRows] = useState([{ key: "", value: "" }]);
  const [mounts, setMounts] = useState("");
  const [memory, setMemory] = useState("");
  const [memorySwap, setMemorySwap] = useState("");
  const [cpus, setCpus] = useState("");
  const [pids, setPids] = useState("");
  const [hostname, setHostname] = useState("");
  const [workingDir, setWorkingDir] = useState("");
  const [containerUser, setContainerUser] = useState("");
  const [networkAliases, setNetworkAliases] = useState("");
  const [restartPolicy, setRestartPolicy] = useState<"no" | "always" | "unless-stopped" | "on-failure">("unless-stopped");
  const [labels, setLabels] = useState("");
  const [healthType, setHealthType] = useState<"none" | "http" | "tcp">("none");
  const [healthPort, setHealthPort] = useState("");
  const [healthPath, setHealthPath] = useState("/");
  const [readOnly, setReadOnly] = useState(false);
  const [init, setInit] = useState(true);
  const [autoStart, setAutoStart] = useState(true);
  async function submit() {
    setBusy(true);
    try {
      const mappedPorts = ports
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const match = /^(\d+):(\d+)(?:\/(tcp|udp))?$/.exec(line);
          if (!match) throw new Error(t("docker.invalidPorts"));
          return {
            published: Number(match[1]),
            target: Number(match[2]),
            protocol: (match[3] || "tcp") as "tcp" | "udp",
          };
        });
      const result = await api.createDockerContainer({
        name,
        image,
        network,
        pull_policy: "missing",
        network_aliases: networkAliases.split(",").map((item) => item.trim()).filter(Boolean),
        restart_policy: restartPolicy,
        hostname: hostname || null,
        working_dir: workingDir || null,
        user: containerUser || null,
        environment: pairs(environment, t("docker.invalidEnvironment")),
        secret_environment: Object.fromEntries(secretRows.filter((row) => row.key || row.value).map((row) => {
          if (!row.key || !row.value) throw new Error(t("docker.invalidEnvironment"));
          return [row.key, row.value];
        })),
        ports: mappedPorts,
        mounts: mountLines(mounts, t("docker.invalidMounts")),
        limits: {
          memory_mb: memory ? Number(memory) : null,
          memory_swap_mb: memorySwap ? Number(memorySwap) : null,
          cpus: cpus ? Number(cpus) : null,
          pids: pids ? Number(pids) : null,
        },
        healthcheck: {
          type: healthType,
          port: healthType === "none" ? null : Number(healthPort),
          path: healthPath,
        },
        labels: pairs(labels, t("docker.invalidLabels")),
        read_only: readOnly,
        init,
        auto_start: autoStart,
        confirmation: name,
      });
      onStarted(result.job);
      onClose();
    } catch (error) {
      toast(errorMessage(error, t), "error", "admin");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="dialog-backdrop">
      <section
        className="dialog docker-wizard"
        role="dialog"
        aria-modal="true"
        aria-labelledby="docker-create-title"
      >
        <header>
          <div>
            <Boxes />
            <h2 id="docker-create-title">{t("docker.createContainer")}</h2>
          </div>
          <button aria-label={t("action.close")} onClick={onClose}>
            <X />
          </button>
        </header>
        <ol className="docker-wizard-steps">
          {["basic", "connectivity", "resources", "review"].map(
            (key, index) => (
              <li
                className={
                  step === index ? "active" : step > index ? "done" : ""
                }
                key={key}
              >
                {t(`docker.wizard.${key}`)}
              </li>
            ),
          )}
        </ol>
        <div className="docker-wizard-body">
          {step === 0 && (
            <div className="form-grid">
              <label>
                {t("docker.field.name")}
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  autoFocus
                  required
                />
              </label>
              <label>
                {t("docker.field.image")}
                <input
                  value={image}
                  onChange={(event) => setImage(event.target.value)}
                  placeholder="nginx:stable"
                  required
                />
              </label>
              <label>
                {t("docker.field.network")}
                <input
                  value={network}
                  onChange={(event) => setNetwork(event.target.value)}
                />
              </label>
              <label>
                {t("docker.field.networkAliases")}
                <input value={networkAliases} onChange={(event) => setNetworkAliases(event.target.value)} placeholder={t("docker.networkAliasesHint")} />
              </label>
              <label>
                {t("docker.field.hostname")}
                <input value={hostname} onChange={(event) => setHostname(event.target.value)} />
              </label>
              <label>
                {t("docker.field.restartPolicy")}
                <select value={restartPolicy} onChange={(event) => setRestartPolicy(event.target.value as typeof restartPolicy)}>
                  {(["no", "always", "unless-stopped", "on-failure"] as const).map((value) => <option value={value} key={value}>{value}</option>)}
                </select>
              </label>
              <label className="check-row">
                <input type="checkbox" checked={autoStart} onChange={(event) => setAutoStart(event.target.checked)} />
                {t("docker.field.autoStart")}
              </label>
            </div>
          )}
          {step === 1 && (
            <div className="form-grid">
              <label>
                {t("docker.field.ports")}
                <textarea
                  value={ports}
                  onChange={(event) => setPorts(event.target.value)}
                  placeholder="8080:80/tcp"
                />
              </label>
              <label>
                {t("docker.field.environment")}
                <textarea
                  value={environment}
                  onChange={(event) => setEnvironment(event.target.value)}
                  placeholder="TZ=Europe/Warsaw"
                />
              </label>
              <fieldset className="docker-secret-fields">
                <legend>{t("docker.field.secrets")}</legend>
                {secretRows.map((row, index) => (
                  <div className="docker-secret-row" key={index}>
                    <input aria-label={index === 0 ? t("docker.secretName") : undefined} value={row.key} onChange={(event) => setSecretRows((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, key: event.target.value } : item))} placeholder={t("docker.secretName")} />
                    <input aria-label={index === 0 ? t("docker.secretValue") : undefined} type="password" autoComplete="new-password" value={row.value} onChange={(event) => setSecretRows((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, value: event.target.value } : item))} placeholder={t("docker.secretValue")} />
                    <button type="button" aria-label={t("action.delete")} disabled={secretRows.length === 1} onClick={() => setSecretRows((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Trash2 /></button>
                  </div>
                ))}
                <button type="button" onClick={() => setSecretRows((current) => [...current, { key: "", value: "" }])}><Plus />{t("docker.addSecret")}</button>
              </fieldset>
              <p className="field-hint">{t("docker.secretsHint")}</p>
              <label>
                {t("docker.field.mounts")}
                <textarea value={mounts} onChange={(event) => setMounts(event.target.value)} placeholder={t("docker.mountsHint")} />
              </label>
              <label>
                {t("docker.field.labels")}
                <textarea value={labels} onChange={(event) => setLabels(event.target.value)} placeholder={t("docker.labelsHint")} />
              </label>
            </div>
          )}
          {step === 2 && (
            <div className="form-grid">
              <label>
                {t("docker.field.memoryMb")}
                <input
                  type="number"
                  min="16"
                  value={memory}
                  onChange={(event) => setMemory(event.target.value)}
                />
              </label>
              <label>
                {t("docker.field.cpus")}
                <input
                  type="number"
                  min="0.1"
                  step="0.1"
                  value={cpus}
                  onChange={(event) => setCpus(event.target.value)}
                />
              </label>
              <label>
                {t("docker.field.memorySwapMb")}
                <input type="number" min="16" value={memorySwap} onChange={(event) => setMemorySwap(event.target.value)} />
              </label>
              <label>
                {t("docker.field.pids")}
                <input type="number" min="16" value={pids} onChange={(event) => setPids(event.target.value)} />
              </label>
              <label>
                {t("docker.field.userUidGid")}
                <input value={containerUser} onChange={(event) => setContainerUser(event.target.value)} placeholder="1000:1000" />
              </label>
              <label>
                {t("docker.field.workingDir")}
                <input value={workingDir} onChange={(event) => setWorkingDir(event.target.value)} placeholder="/app" />
              </label>
              <label>
                {t("docker.field.healthcheck")}
                <select value={healthType} onChange={(event) => setHealthType(event.target.value as typeof healthType)}>
                  <option value="none">{t("common.none")}</option>
                  <option value="http">HTTP</option>
                  <option value="tcp">TCP</option>
                </select>
              </label>
              {healthType !== "none" && (
                <>
                  <label>
                    {t("docker.field.healthPort")}
                    <input type="number" min="1" max="65535" value={healthPort} onChange={(event) => setHealthPort(event.target.value)} required />
                  </label>
                  {healthType === "http" && <label>{t("docker.field.healthPath")}<input value={healthPath} onChange={(event) => setHealthPath(event.target.value)} /></label>}
                </>
              )}
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={readOnly}
                  onChange={(event) => setReadOnly(event.target.checked)}
                />
                {t("docker.field.readOnly")}
              </label>
              <label className="check-row">
                <input type="checkbox" checked={init} onChange={(event) => setInit(event.target.checked)} />
                {t("docker.field.init")}
              </label>
              <p className="docker-notice info">
                {t("docker.highRiskBlocked")}
              </p>
            </div>
          )}
          {step === 3 && (
            <dl className="docker-review">
              <div>
                <dt>{t("docker.field.name")}</dt>
                <dd>{name}</dd>
              </div>
              <div>
                <dt>{t("docker.field.image")}</dt>
                <dd>{image}</dd>
              </div>
              <div>
                <dt>{t("docker.field.network")}</dt>
                <dd>{network}</dd>
              </div>
              <div>
                <dt>{t("docker.field.ports")}</dt>
                <dd>{ports || "—"}</dd>
              </div>
              <div>
                <dt>{t("docker.field.secrets")}</dt>
                <dd>{secretRows.some((row) => row.value) ? t("docker.secretValuesHidden") : "—"}</dd>
              </div>
              <div>
                <dt>{t("docker.field.mounts")}</dt>
                <dd>{mounts || "—"}</dd>
              </div>
              <div>
                <dt>{t("docker.field.limits")}</dt>
                <dd>{[cpus && `${cpus} CPU`, memory && `${memory} MiB`, pids && `${pids} PID`].filter(Boolean).join(", ") || "—"}</dd>
              </div>
            </dl>
          )}
        </div>
        <footer>
          {step > 0 && (
            <button onClick={() => setStep((value) => value - 1)}>
              <ArrowLeft />
              {t("action.back")}
            </button>
          )}
          <span />
          {step < 3 ? (
            <button
              className="button-primary"
              disabled={step === 0 && (!name || !image)}
              onClick={() => setStep((value) => value + 1)}
            >
              {t("action.next")}
              <ArrowRight />
            </button>
          ) : (
            <button
              className="button-primary"
              disabled={busy || !name || !image}
              onClick={() => void submit()}
            >
              <Boxes />
              {t("docker.createContainer")}
            </button>
          )}
        </footer>
      </section>
    </div>
  );
}
