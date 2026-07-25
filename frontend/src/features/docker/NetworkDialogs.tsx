import { useEffect, useId, useMemo, useState } from "react";
import {
  api,
  type DockerDefaultBridgeConfig,
  type DockerNetwork,
  type DockerNetworkContainer,
  type DockerPrunePlan,
  type ModuleJob,
} from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import {
  addressInNetwork,
  isUsableIpv4Gateway,
  networkInNetwork,
  parseAddress,
  parseNetwork,
} from "./networkValidation";
import { errorMessage } from "./shared";

type CommonProps = {
  t: Translate;
  toast: ToastFn;
  onClose: () => void;
  onJob: (job: ModuleJob) => void;
};

export function NetworkContainerDialog({
  network,
  action,
  t,
  toast,
  onClose,
  onJob,
}: CommonProps & { network: DockerNetwork; action: "connect" | "disconnect" }) {
  const formId = `network-${action}-${useId().replace(/:/g, "")}`;
  const [items, setItems] = useState<DockerNetworkContainer[]>([]);
  const [container, setContainer] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void api.dockerNetworkContainers(network.Name)
      .then((result) => {
        if (!active) return;
        setItems(result.items);
        setError("");
      })
      .catch((reason) => active && setError(errorMessage(reason, t)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [network.Name, t]);

  const options = useMemo(
    () => items.filter((item) => action === "disconnect" ? item.connected : !item.connected),
    [action, items],
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!container || saving) return;
    setSaving(true);
    try {
      const result = await api.dockerNetworkAction(network.Name, {
        action,
        container,
        confirmation: "",
        pam_password: null,
      });
      onJob(result.job);
      onClose();
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={t(`docker.networkAction.${action}`)}
      closeLabel={t("action.close")}
      onClose={saving ? () => undefined : onClose}
      footer={
        <>
          <button type="button" disabled={saving} onClick={onClose}>{t("action.cancel")}</button>
          <button className="button-primary" type="submit" form={formId} disabled={saving || loading || !container}>
            {saving ? t("status.loading") : t("action.apply")}
          </button>
        </>
      }
    >
      <form id={formId} className="docker-network-action-form" onSubmit={(event) => void submit(event)}>
        <p>{t("docker.networkContainerHint").replace("{network}", network.Name)}</p>
        <label className="field-label">
          {t("docker.field.container")}
          <select disabled={saving || loading} value={container} onChange={(event) => setContainer(event.target.value)}>
            <option value="">{loading ? t("status.loading") : t("docker.selectContainer")}</option>
            {options.map((item) => <option key={item.id} value={item.name}>{item.name} ({item.state})</option>)}
          </select>
        </label>
        {!loading && !error && !options.length && <p className="docker-form-hint">{t(`docker.noContainersTo.${action}`)}</p>}
        {error && <p className="error-state compact-error" role="alert">{error}</p>}
      </form>
    </Modal>
  );
}

export function RemoveNetworkDialog({
  network,
  t,
  toast,
  onClose,
  onJob,
}: CommonProps & { network: DockerNetwork }) {
  const formId = `remove-network-${useId().replace(/:/g, "")}`;
  const [confirmation, setConfirmation] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const blocked = Number(network.container_count || 0) > 0;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (saving || blocked || confirmation !== network.Name || !password) return;
    setSaving(true);
    try {
      const result = await api.dockerNetworkAction(network.Name, {
        action: "remove",
        confirmation,
        pam_password: password,
      });
      onJob(result.job);
      onClose();
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={t("docker.networkAction.remove")}
      closeLabel={t("action.close")}
      onClose={saving ? () => undefined : onClose}
      footer={
        <>
          <button type="button" disabled={saving} onClick={onClose}>{t("action.cancel")}</button>
          <button className="button-danger" type="submit" form={formId} disabled={saving || blocked || confirmation !== network.Name || !password}>
            {saving ? t("status.loading") : t("action.delete")}
          </button>
        </>
      }
    >
      <form id={formId} className="docker-network-action-form" onSubmit={(event) => void submit(event)}>
        {blocked ? (
          <p className="docker-notice error" role="alert">
            {t("docker.networkInUse").replace("{count}", String(network.container_count))}
          </p>
        ) : (
          <p className="danger-note">{t("admin.destructiveWarning")}</p>
        )}
        <label className="field-label">
          {t("docker.confirmNetworkName").replace("{name}", network.Name)}
          <input disabled={saving || blocked} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" />
        </label>
        <label className="field-label">
          {t("docker.currentPassword")}
          <input disabled={saving || blocked} type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
      </form>
    </Modal>
  );
}

export function PruneNetworksDialog({ t, toast, onClose, onJob }: CommonProps) {
  const formId = `prune-networks-${useId().replace(/:/g, "")}`;
  const [plan, setPlan] = useState<DockerPrunePlan | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void api.dockerPrunePlan(["networks"])
      .then((result) => active && setPlan(result))
      .catch((reason) => active && setError(errorMessage(reason, t)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [t]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (saving || confirmation !== "networks" || !password) return;
    setSaving(true);
    try {
      const result = await api.dockerNetworkAction("networks", {
        action: "prune",
        confirmation,
        pam_password: password,
      });
      onJob(result.job);
      onClose();
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={t("docker.networkAction.prune")}
      closeLabel={t("action.close")}
      onClose={saving ? () => undefined : onClose}
      wide
      footer={
        <>
          <button type="button" disabled={saving} onClick={onClose}>{t("action.cancel")}</button>
          <button className="button-danger" type="submit" form={formId} disabled={saving || loading || confirmation !== "networks" || !password}>
            {saving ? t("status.loading") : t("docker.pruneNetworks")}
          </button>
        </>
      }
    >
      <form id={formId} className="docker-network-action-form" onSubmit={(event) => void submit(event)}>
        <p className="danger-note">{t("admin.destructiveWarning")}</p>
        <section className="docker-prune-preview" aria-busy={loading}>
          <h3>{t("docker.prunePreview")}</h3>
          {loading && <p>{t("status.loading")}</p>}
          {error && <p className="error-state compact-error" role="alert">{error}</p>}
          {plan && (
            plan.items.length ? (
              <ul>{plan.items.map((item) => <li key={`${item.id}-${item.name}`}><strong>{item.name || item.id}</strong><code>{item.id}</code></li>)}</ul>
            ) : <p>{t("docker.noUnusedNetworks")}</p>
          )}
        </section>
        <label className="field-label">
          {t("docker.confirmNetworksPrune")}
          <input disabled={saving} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" />
        </label>
        <label className="field-label">
          {t("docker.currentPassword")}
          <input disabled={saving} type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
      </form>
    </Modal>
  );
}

export function DefaultBridgeNetworkDialog({ t, toast, onClose, onJob }: CommonProps) {
  const formId = `default-bridge-${useId().replace(/:/g, "")}`;
  const [value, setValue] = useState<DockerDefaultBridgeConfig | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    let active = true;
    void api.dockerDefaultBridge()
      .then((result) => active && setValue(result))
      .catch((reason) => active && setError(errorMessage(reason, t)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [t]);

  function patch(next: Partial<DockerDefaultBridgeConfig>) {
    setValue((current) => current ? { ...current, ...next } : current);
  }

  function validate(current: DockerDefaultBridgeConfig) {
    const errors: Record<string, string> = {};
    if (current.ipv4_mode === "manual") {
      const subnet = current.ipv4_subnet ? parseNetwork(current.ipv4_subnet) : null;
      if (!subnet || subnet.version !== 4) errors.ipv4_subnet = t("docker.networkValidation.ipv4Subnet");
      if (!current.ipv4_gateway || !current.ipv4_subnet || !isUsableIpv4Gateway(current.ipv4_gateway, current.ipv4_subnet))
        errors.ipv4_gateway = t("docker.networkValidation.ipv4GatewayRequired");
      if (current.ipv4_ip_range && (!current.ipv4_subnet || !networkInNetwork(current.ipv4_ip_range, current.ipv4_subnet)))
        errors.ipv4_ip_range = t("docker.networkValidation.ipv4Range");
    }
    if (current.ipv6_mode === "manual") {
      const subnet = current.ipv6_subnet ? parseNetwork(current.ipv6_subnet) : null;
      if (!subnet || subnet.version !== 6) errors.ipv6_subnet = t("docker.networkValidation.ipv6Subnet");
      if (current.ipv6_gateway) {
        const gateway = parseAddress(current.ipv6_gateway);
        if (!current.ipv6_subnet || gateway?.version !== 6 || !addressInNetwork(current.ipv6_gateway, current.ipv6_subnet))
          errors.ipv6_gateway = t("docker.networkValidation.ipv6Gateway");
      }
    }
    return errors;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!value || saving) return;
    const nextErrors = validate(value);
    setFieldErrors(nextErrors);
    if (Object.keys(nextErrors).length || confirmation !== "bridge" || !password) return;
    setSaving(true);
    try {
      const clean = (item: string | null) => item?.trim() || null;
      const result = await api.saveDockerDefaultBridge({
        ...value,
        ipv4_subnet: value.ipv4_mode === "manual" ? clean(value.ipv4_subnet) : null,
        ipv4_ip_range: value.ipv4_mode === "manual" ? clean(value.ipv4_ip_range) : null,
        ipv4_gateway: value.ipv4_mode === "manual" ? clean(value.ipv4_gateway) : null,
        ipv6_subnet: value.ipv6_mode === "manual" ? clean(value.ipv6_subnet) : null,
        ipv6_gateway: value.ipv6_mode === "manual" ? clean(value.ipv6_gateway) : null,
        confirmation,
        pam_password: password,
      });
      onJob(result.job);
      onClose();
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    } finally {
      setSaving(false);
    }
  }

  const fieldError = (key: string) => fieldErrors[key] ? <span className="docker-field-error" role="alert">{fieldErrors[key]}</span> : null;
  return (
    <Modal
      title={t("docker.configureDefaultBridge")}
      closeLabel={t("action.close")}
      onClose={saving ? () => undefined : onClose}
      wide
      footer={
        <>
          <button type="button" disabled={saving} onClick={onClose}>{t("action.cancel")}</button>
          <button className="button-danger" type="submit" form={formId} disabled={saving || loading || !value || confirmation !== "bridge" || !password}>
            {saving ? t("status.loading") : t("action.save")}
          </button>
        </>
      }
    >
      {loading && <p>{t("status.loading")}</p>}
      {error && <p className="error-state compact-error" role="alert">{error}</p>}
      {value && (
        <form id={formId} className="docker-network-form" onSubmit={(event) => void submit(event)}>
          <p className="docker-notice warning">{t("docker.defaultBridgeWarning")}</p>
          <fieldset>
            <legend>{t("docker.ipv4Configuration")}</legend>
            <div className="docker-network-modes">
              <label><input type="radio" checked={value.ipv4_mode === "auto"} onChange={() => patch({ ipv4_mode: "auto", ipv4_subnet: null, ipv4_ip_range: null, ipv4_gateway: null })} />{t("docker.ipMode.auto")}</label>
              <label><input type="radio" checked={value.ipv4_mode === "manual"} onChange={() => patch({ ipv4_mode: "manual" })} />{t("docker.ipMode.manual")}</label>
            </div>
            {value.ipv4_mode === "manual" && <div className="docker-network-ipam">
              <label>{t("docker.field.subnet")}<input value={value.ipv4_subnet || ""} placeholder="172.30.0.0/16" onChange={(event) => patch({ ipv4_subnet: event.target.value })} />{fieldError("ipv4_subnet")}</label>
              <label>{t("docker.field.ipRange")}<input value={value.ipv4_ip_range || ""} placeholder="172.30.10.0/24" onChange={(event) => patch({ ipv4_ip_range: event.target.value })} />{fieldError("ipv4_ip_range")}</label>
              <label>{t("docker.field.gateway")}<input value={value.ipv4_gateway || ""} placeholder="172.30.0.1" onChange={(event) => patch({ ipv4_gateway: event.target.value })} />{fieldError("ipv4_gateway")}</label>
            </div>}
          </fieldset>
          <fieldset>
            <legend>{t("docker.ipv6Configuration")}</legend>
            <div className="docker-network-modes">
              <label><input type="radio" checked={value.ipv6_mode === "none"} onChange={() => patch({ ipv6_mode: "none", ipv6_subnet: null, ipv6_gateway: null })} />{t("docker.ipMode.none")}</label>
              <label><input type="radio" checked={value.ipv6_mode === "manual"} onChange={() => patch({ ipv6_mode: "manual" })} />{t("docker.ipMode.manual")}</label>
            </div>
            {value.ipv6_mode === "manual" && <div className="docker-network-ipam">
              <label>{t("docker.field.ipv6Subnet")}<input value={value.ipv6_subnet || ""} placeholder="fd42:30::/64" onChange={(event) => patch({ ipv6_subnet: event.target.value })} />{fieldError("ipv6_subnet")}</label>
              <label>{t("docker.field.ipv6Gateway")}<input value={value.ipv6_gateway || ""} placeholder="fd42:30::1" onChange={(event) => patch({ ipv6_gateway: event.target.value })} />{fieldError("ipv6_gateway")}</label>
            </div>}
          </fieldset>
          <label className="check-row"><input type="checkbox" checked={value.disable_ip_masquerade} onChange={(event) => patch({ disable_ip_masquerade: event.target.checked })} />{t("docker.disableIpMasquerade")}</label>
          <label className="field-label">{t("docker.confirmBridge")}<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" /></label>
          <label className="field-label">{t("docker.currentPassword")}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" /></label>
        </form>
      )}
    </Modal>
  );
}
