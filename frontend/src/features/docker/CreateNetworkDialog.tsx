import { Plus, Trash2 } from "lucide-react";
import { useId, useRef, useState } from "react";
import { api, type DockerNetworkCreate, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import {
  addressInNetwork,
  isUsableIpv4Gateway,
  networkInNetwork,
  parseAddress,
  parseNetwork,
  validDockerName,
  validLabel,
} from "./networkValidation";
import { errorMessage } from "./shared";

type LabelRow = { id: number; key: string; value: string };

export function CreateNetworkDialog({
  existingNames,
  t,
  toast,
  onClose,
  onJob,
}: {
  existingNames: string[];
  t: Translate;
  toast: ToastFn;
  onClose: () => void;
  onJob: (job: ModuleJob) => void;
}) {
  const formId = `create-network-${useId().replace(/:/g, "")}`;
  const nextLabelId = useRef(1);
  const [name, setName] = useState("");
  const [ipv4Mode, setIpv4Mode] = useState<"auto" | "manual">("auto");
  const [ipv4Subnet, setIpv4Subnet] = useState("");
  const [ipv4Range, setIpv4Range] = useState("");
  const [ipv4Gateway, setIpv4Gateway] = useState("");
  const [ipv6Mode, setIpv6Mode] = useState<"none" | "manual">("none");
  const [ipv6Subnet, setIpv6Subnet] = useState("");
  const [ipv6Range, setIpv6Range] = useState("");
  const [ipv6Gateway, setIpv6Gateway] = useState("");
  const [disableMasquerade, setDisableMasquerade] = useState(false);
  const [internal, setInternal] = useState(false);
  const [labels, setLabels] = useState<LabelRow[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  function validate(): Record<string, string> {
    const next: Record<string, string> = {};
    const normalizedName = name.trim();
    if (!normalizedName) next.name = t("docker.networkValidation.nameRequired");
    else if (!validDockerName(normalizedName)) next.name = t("docker.networkValidation.nameInvalid");
    else if (["bridge", "host", "none"].includes(normalizedName) || existingNames.includes(normalizedName))
      next.name = t("docker.networkValidation.nameDuplicate");

    if (ipv4Mode === "manual") {
      const subnet = parseNetwork(ipv4Subnet);
      if (!subnet || subnet.version !== 4) next.ipv4_subnet = t("docker.networkValidation.ipv4Subnet");
      if (ipv4Range && (!subnet || !networkInNetwork(ipv4Range, ipv4Subnet) || parseNetwork(ipv4Range)?.version !== 4))
        next.ipv4_ip_range = t("docker.networkValidation.ipv4Range");
      if (ipv4Gateway && (!subnet || !isUsableIpv4Gateway(ipv4Gateway, ipv4Subnet)))
        next.ipv4_gateway = t("docker.networkValidation.ipv4Gateway");
    }
    if (ipv6Mode === "manual") {
      const subnet = parseNetwork(ipv6Subnet);
      if (!subnet || subnet.version !== 6) next.ipv6_subnet = t("docker.networkValidation.ipv6Subnet");
      if (ipv6Range && (!subnet || !networkInNetwork(ipv6Range, ipv6Subnet) || parseNetwork(ipv6Range)?.version !== 6))
        next.ipv6_ip_range = t("docker.networkValidation.ipv6Range");
      const gateway = ipv6Gateway ? parseAddress(ipv6Gateway) : null;
      if (ipv6Gateway && (!subnet || gateway?.version !== 6 || !addressInNetwork(ipv6Gateway, ipv6Subnet)))
        next.ipv6_gateway = t("docker.networkValidation.ipv6Gateway");
    }
    const seen = new Set<string>();
    labels.forEach((label) => {
      const key = label.key.trim();
      if (!key || !validLabel(key, label.value) || seen.has(key))
        next[`label-${label.id}`] = t("docker.networkValidation.label");
      seen.add(key);
    });
    return next;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (saving) return;
    const nextErrors = validate();
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    const clean = (value: string) => value.trim() || null;
    const payload: DockerNetworkCreate = {
      name: name.trim(),
      driver: "bridge",
      ipv4_mode: ipv4Mode,
      ipv4_subnet: ipv4Mode === "manual" ? clean(ipv4Subnet) : null,
      ipv4_ip_range: ipv4Mode === "manual" ? clean(ipv4Range) : null,
      ipv4_gateway: ipv4Mode === "manual" ? clean(ipv4Gateway) : null,
      ipv6_mode: ipv6Mode,
      ipv6_subnet: ipv6Mode === "manual" ? clean(ipv6Subnet) : null,
      ipv6_ip_range: ipv6Mode === "manual" ? clean(ipv6Range) : null,
      ipv6_gateway: ipv6Mode === "manual" ? clean(ipv6Gateway) : null,
      internal,
      disable_ip_masquerade: disableMasquerade,
      labels: Object.fromEntries(labels.map((label) => [label.key.trim(), label.value])),
    };
    setSaving(true);
    try {
      const result = await api.createDockerNetwork(payload);
      onJob(result.job);
      onClose();
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    } finally {
      setSaving(false);
    }
  }

  function fieldError(key: string) {
    return errors[key] ? <span className="docker-field-error" role="alert">{errors[key]}</span> : null;
  }

  return (
    <Modal
      title={t("docker.networkAction.create")}
      closeLabel={t("action.close")}
      onClose={saving ? () => undefined : onClose}
      wide
      footer={
        <>
          <button type="button" disabled={saving} onClick={onClose}>{t("action.cancel")}</button>
          <button className="button-primary" type="submit" form={formId} disabled={saving}>
            {saving ? t("status.loading") : t("action.add")}
          </button>
        </>
      }
    >
      <form id={formId} className="docker-network-form" onSubmit={(event) => void submit(event)}>
        <div className="docker-network-basics">
          <label className="field-label" htmlFor={`${formId}-name`}>
            {t("docker.field.name")}
            <input
              id={`${formId}-name`}
              autoFocus
              maxLength={128}
              disabled={saving}
              value={name}
              onChange={(event) => setName(event.target.value)}
              aria-invalid={Boolean(errors.name)}
            />
            {fieldError("name")}
          </label>
          <label className="field-label" htmlFor={`${formId}-driver`}>
            {t("docker.field.driver")}
            <input id={`${formId}-driver`} value="bridge" readOnly disabled />
          </label>
        </div>

        <fieldset>
          <legend>{t("docker.ipv4Configuration")}</legend>
          <div className="docker-network-modes">
            <label><input type="radio" name={`${formId}-ipv4`} checked={ipv4Mode === "auto"} disabled={saving} onChange={() => setIpv4Mode("auto")} />{t("docker.ipMode.auto")}</label>
            <label><input type="radio" name={`${formId}-ipv4`} checked={ipv4Mode === "manual"} disabled={saving} onChange={() => setIpv4Mode("manual")} />{t("docker.ipMode.manual")}</label>
          </div>
          {ipv4Mode === "auto" ? (
            <p className="docker-form-hint">{t("docker.ipv4AutoHint")}</p>
          ) : (
            <div className="docker-network-ipam">
              <label>{t("docker.field.subnet")}<input disabled={saving} placeholder="172.20.0.0/16" value={ipv4Subnet} onChange={(event) => setIpv4Subnet(event.target.value)} aria-invalid={Boolean(errors.ipv4_subnet)} />{fieldError("ipv4_subnet")}</label>
              <label>{t("docker.field.ipRange")}<input disabled={saving} placeholder="172.20.10.0/24" value={ipv4Range} onChange={(event) => setIpv4Range(event.target.value)} aria-invalid={Boolean(errors.ipv4_ip_range)} />{fieldError("ipv4_ip_range")}</label>
              <label>{t("docker.field.gateway")}<input disabled={saving} placeholder="172.20.0.1" value={ipv4Gateway} onChange={(event) => setIpv4Gateway(event.target.value)} aria-invalid={Boolean(errors.ipv4_gateway)} />{fieldError("ipv4_gateway")}</label>
            </div>
          )}
        </fieldset>

        <fieldset>
          <legend>{t("docker.ipv6Configuration")}</legend>
          <div className="docker-network-modes">
            <label><input type="radio" name={`${formId}-ipv6`} checked={ipv6Mode === "none"} disabled={saving} onChange={() => setIpv6Mode("none")} />{t("docker.ipMode.none")}</label>
            <label><input type="radio" name={`${formId}-ipv6`} checked={ipv6Mode === "manual"} disabled={saving} onChange={() => setIpv6Mode("manual")} />{t("docker.ipMode.manual")}</label>
          </div>
          {ipv6Mode === "manual" && (
            <div className="docker-network-ipam">
              <label>{t("docker.field.ipv6Subnet")}<input disabled={saving} placeholder="fd42:20::/64" value={ipv6Subnet} onChange={(event) => setIpv6Subnet(event.target.value)} aria-invalid={Boolean(errors.ipv6_subnet)} />{fieldError("ipv6_subnet")}</label>
              <label>{t("docker.field.ipv6Range")}<input disabled={saving} placeholder="fd42:20:0:0:10::/80" value={ipv6Range} onChange={(event) => setIpv6Range(event.target.value)} aria-invalid={Boolean(errors.ipv6_ip_range)} />{fieldError("ipv6_ip_range")}</label>
              <label>{t("docker.field.ipv6Gateway")}<input disabled={saving} placeholder="fd42:20::1" value={ipv6Gateway} onChange={(event) => setIpv6Gateway(event.target.value)} aria-invalid={Boolean(errors.ipv6_gateway)} />{fieldError("ipv6_gateway")}</label>
            </div>
          )}
        </fieldset>

        <label className="check-row">
          <input type="checkbox" checked={disableMasquerade} disabled={saving} onChange={(event) => setDisableMasquerade(event.target.checked)} />
          {t("docker.disableIpMasquerade")}
        </label>

        <details className="docker-network-advanced">
          <summary>{t("docker.advanced")}</summary>
          <label className="check-row">
            <input type="checkbox" checked={internal} disabled={saving} onChange={(event) => setInternal(event.target.checked)} />
            {t("docker.internalNetwork")}
          </label>
          <div className="docker-network-labels">
            <div>
              <strong>{t("docker.field.labels")}</strong>
              <button
                type="button"
                disabled={saving || labels.length >= 100}
                onClick={() => setLabels((current) => [...current, { id: nextLabelId.current++, key: "", value: "" }])}
              >
                <Plus />{t("docker.addLabel")}
              </button>
            </div>
            {labels.map((label) => (
              <div className="docker-network-label-row" key={label.id}>
                <label>{t("docker.labelKey")}<input disabled={saving} value={label.key} onChange={(event) => setLabels((current) => current.map((item) => item.id === label.id ? { ...item, key: event.target.value } : item))} aria-invalid={Boolean(errors[`label-${label.id}`])} /></label>
                <label>{t("docker.labelValue")}<input disabled={saving} maxLength={512} value={label.value} onChange={(event) => setLabels((current) => current.map((item) => item.id === label.id ? { ...item, value: event.target.value } : item))} /></label>
                <button type="button" className="danger-icon" title={t("action.delete")} disabled={saving} onClick={() => setLabels((current) => current.filter((item) => item.id !== label.id))}><Trash2 /></button>
                {fieldError(`label-${label.id}`)}
              </div>
            ))}
          </div>
        </details>
      </form>
    </Modal>
  );
}
