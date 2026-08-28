import { ChevronDown, Plus, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  api,
  type HostsManagerCredential,
  type HostsManagerEnvironment,
} from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { confirmDialog } from "../../components/DialogService";
import { Modal } from "../../components/Modal";
import { useRefreshOnConnectionRestored } from "../../features/connection/ConnectionStatusMonitor";
import {
  HostsDataTable,
  type HostsDataColumn,
} from "../../features/modules/hosts/components/HostsDataTable";
import "../../features/modules/hosts/hosts-credential-module-select.css";

type Props = {
  permissions: string[];
  t: Translate;
  toast: ToastFn;
};

type CredentialShareModule = { id: string; name: string };
type CredentialType = HostsManagerCredential["type"];
type CredentialFieldProfile = {
  username?: {
    label: string;
    hint?: string;
    placeholder?: string;
    required?: boolean;
  };
  secret?: {
    label: string;
    hint?: string;
    placeholder?: string;
    multiline?: boolean;
    required?: boolean;
  };
  passphrase?: boolean;
};

function credentialsError(error: unknown, t: Translate): string {
  if (error instanceof ApiError) {
    const message = error.message;
    return error.field && !message.startsWith(`${error.field}:`)
      ? `${error.field}: ${message}`
      : message;
  }
  return error instanceof Error ? error.message : t("error.generic");
}

function CredentialModuleSelect({
  modules,
  selected,
  loading,
  onChange,
  t,
}: {
  modules: CredentialShareModule[];
  selected: string[];
  loading: boolean;
  onChange: (value: string[]) => void;
  t: Translate;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const options = useMemo(() => {
    const known = new Map(modules.map((item) => [item.id, item]));
    selected.forEach((id) => {
      if (!known.has(id)) known.set(id, { id, name: id });
    });
    return [...known.values()].sort(
      (left, right) =>
        left.name.localeCompare(right.name) || left.id.localeCompare(right.id),
    );
  }, [modules, selected]);
  const optionIds = options.map((item) => item.id);
  const allSelected =
    optionIds.length > 0 && optionIds.every((id) => selected.includes(id));
  const summary = loading
    ? t("hosts.credentials.loadingModules")
    : allSelected
      ? t("hosts.credentials.allModules")
      : selected.length === 0
        ? t("hosts.credentials.noModules")
        : `${selected.length}/${options.length} ${t("hosts.credentials.modulesSelected")}`;

  function toggle(id: string, checked: boolean) {
    onChange(
      checked
        ? [...new Set([...selected, id])]
        : selected.filter((value) => value !== id),
    );
  }

  return (
    <div className="hosts-credential-module-select" ref={rootRef}>
      <button
        type="button"
        className="hosts-credential-module-trigger"
        aria-label={t("hosts.credentials.sharedWith")}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span>{summary}</span>
        <ChevronDown aria-hidden="true" />
      </button>
      {open && (
        <div className="hosts-credential-module-menu">
          <div className="hosts-credential-module-actions">
            <button
              type="button"
              disabled={!optionIds.length}
              onClick={() => onChange(optionIds)}
            >
              {t("hosts.credentials.selectAllModules")}
            </button>
            <button
              type="button"
              disabled={!selected.length}
              onClick={() => onChange([])}
            >
              {t("hosts.credentials.clearModules")}
            </button>
          </div>
          <div
            className="hosts-credential-module-options"
            role="group"
            aria-label={t("hosts.credentials.sharedWith")}
          >
            {options.map((item) => (
              <label key={item.id} className="hosts-credential-module-option">
                <input
                  type="checkbox"
                  aria-label={`${item.name} (${item.id})`}
                  checked={selected.includes(item.id)}
                  onChange={(event) => toggle(item.id, event.target.checked)}
                />
                <span>
                  <strong>{item.name}</strong>
                  <small>{item.id}</small>
                </span>
              </label>
            ))}
            {!options.length && (
              <div className="hosts-credential-module-empty">
                {loading
                  ? t("hosts.credentials.loadingModules")
                  : t("hosts.credentials.noModulesAvailable")}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function CredentialsApp({ permissions, t, toast }: Props) {
  const [items, setItems] = useState<HostsManagerCredential[]>([]);
  const [environments, setEnvironments] = useState<HostsManagerEnvironment[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<HostsManagerCredential | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState<CredentialType>("username_password");
  const [username, setUsername] = useState("");
  const [environmentId, setEnvironmentId] = useState("");
  const [description, setDescription] = useState("");
  const [secret, setSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [sharedWith, setSharedWith] = useState<string[]>([]);
  const [shareModules, setShareModules] = useState<CredentialShareModule[]>([]);
  const [shareModulesLoading, setShareModulesLoading] = useState(true);
  const [shareSelectionInitialized, setShareSelectionInitialized] = useState(false);
  const [saving, setSaving] = useState(false);
  const canManage = permissions.includes("hosts-manager.credentials.manage");

  const credentialTypes: CredentialType[] = [
    "username_password",
    "ssh_password",
    "ssh_private_key",
    "become_password",
    "api_token",
    "generic_secret",
    "proxmox_api",
    "redfish",
    "ipmi",
    "git_private_key",
    "wol",
  ];
  const profiles: Partial<Record<CredentialType, CredentialFieldProfile>> = {
    username_password: {
      username: {
        label: t("hosts.credentials.field.login"),
        placeholder: "user@example",
        required: true,
      },
      secret: { label: t("hosts.credentials.field.password"), required: true },
    },
    ssh_password: {
      username: {
        label: t("hosts.credentials.field.sshUser"),
        placeholder: "root",
        required: true,
      },
      secret: {
        label: t("hosts.credentials.field.sshPassword"),
        required: true,
      },
    },
    ssh_private_key: {
      username: {
        label: t("hosts.credentials.field.sshUser"),
        placeholder: "root",
        required: true,
      },
      secret: {
        label: t("hosts.credentials.field.privateKey"),
        placeholder: "-----BEGIN OPENSSH PRIVATE KEY-----",
        multiline: true,
        required: true,
      },
      passphrase: true,
    },
    become_password: {
      secret: {
        label: t("hosts.credentials.field.becomePassword"),
        required: true,
      },
    },
    api_token: {
      secret: { label: t("hosts.credentials.field.apiToken"), required: true },
    },
    generic_secret: {
      secret: {
        label: t("hosts.credentials.field.genericSecret"),
        required: true,
      },
    },
    proxmox_api: {
      username: {
        label: t("hosts.credentials.field.proxmoxTokenId"),
        hint: t("hosts.credentials.field.proxmoxTokenIdHint"),
        placeholder: "automation@pve!algen",
        required: true,
      },
      secret: {
        label: t("hosts.credentials.field.proxmoxTokenSecret"),
        required: true,
      },
    },
    redfish: {
      username: {
        label: t("hosts.credentials.field.redfishUser"),
        required: true,
      },
      secret: {
        label: t("hosts.credentials.field.redfishPassword"),
        required: true,
      },
    },
    ipmi: {
      username: {
        label: t("hosts.credentials.field.ipmiUser"),
        required: true,
      },
      secret: {
        label: t("hosts.credentials.field.ipmiPassword"),
        required: true,
      },
    },
    git_private_key: {
      username: {
        label: t("hosts.credentials.field.gitUser"),
        hint: t("hosts.credentials.field.optional"),
      },
      secret: {
        label: t("hosts.credentials.field.privateKey"),
        placeholder: "-----BEGIN OPENSSH PRIVATE KEY-----",
        multiline: true,
        required: true,
      },
      passphrase: true,
    },
    wol: {},
  };

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [credentials, environmentItems] = await Promise.all([
        api.hostsManagerCredentials(),
        api.hostsManagerEnvironments(),
      ]);
      setItems(credentials);
      setEnvironments(environmentItems);
    } catch (error) {
      toast(credentialsError(error, t), "error", "admin", "hosts-manager");
    } finally {
      setLoading(false);
    }
  }, [t, toast]);

  useRefreshOnConnectionRestored(() => {
    void refresh();
  });
  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    let active = true;
    setShareModulesLoading(true);
    void api
      .modules()
      .then((modules) => {
        if (!active) return;
        setShareModules(
          modules
            .filter((module) => Boolean(module.id))
            .map((module) => ({
              id: module.id,
              name: module.manifest.name || module.id,
            }))
            .sort(
              (left, right) =>
                left.name.localeCompare(right.name) ||
                left.id.localeCompare(right.id),
            ),
        );
      })
      .catch((error: unknown) => {
        if (active) {
          toast(credentialsError(error, t), "error", "admin", "hosts-manager");
        }
      })
      .finally(() => {
        if (active) setShareModulesLoading(false);
      });
    return () => {
      active = false;
    };
  }, [t, toast]);

  const allShareModuleIds = useMemo(
    () => shareModules.map((module) => module.id),
    [shareModules],
  );
  useEffect(() => {
    if (!open || editing || shareSelectionInitialized || shareModulesLoading) return;
    setSharedWith(allShareModuleIds);
    setShareSelectionInitialized(true);
  }, [
    allShareModuleIds,
    editing,
    open,
    shareModulesLoading,
    shareSelectionInitialized,
  ]);

  function setCredentialType(next: CredentialType) {
    setType(next);
    setUsername("");
    setSecret("");
    setPassphrase("");
  }

  function showEditor(item?: HostsManagerCredential) {
    setEditing(item || null);
    setName(item?.name || "");
    setType(item?.type || "username_password");
    setUsername(item?.username || "");
    setEnvironmentId(item?.environment_id || "");
    setDescription(item?.description || "");
    setSecret("");
    setPassphrase("");
    setSharedWith(
      item
        ? [...(item.shared_with || [])]
        : shareModulesLoading
          ? []
          : allShareModuleIds,
    );
    setShareSelectionInitialized(Boolean(item) || !shareModulesLoading);
    setOpen(true);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    try {
      const saved = await api.saveHostsManagerCredential(
        {
          name,
          type,
          username,
          environment_id: environmentId || null,
          secret,
          passphrase,
          description,
          shared_with: [...new Set(sharedWith)],
          confirm: true,
        },
        editing?.id,
      );
      if (!saved?.id) {
        throw new ApiError(
          "Backend zapisał poświadczenie, ale nie zwrócił jego identyfikatora.",
          500,
          "CREDENTIAL_SAVE_INVALID_RESPONSE",
        );
      }
      const normalized = {
        ...saved,
        host_count: saved.host_count ?? editing?.host_count ?? 0,
      };
      setItems((current) =>
        [
          ...current.filter((item) => item.id !== normalized.id),
          normalized,
        ].sort((left, right) => left.name.localeCompare(right.name)),
      );
      setSecret("");
      setPassphrase("");
      setEditing(null);
      setOpen(false);
    } catch (error) {
      toast(credentialsError(error, t), "error", "admin", "hosts-manager");
    } finally {
      setSaving(false);
    }
  }

  async function remove(item: HostsManagerCredential) {
    if (!(await confirmDialog(t("hosts.credentials.deleteConfirm"), t))) return;
    try {
      await api.deleteHostsManagerCredential(item.id);
      setItems((current) => current.filter((candidate) => candidate.id !== item.id));
    } catch (error) {
      toast(credentialsError(error, t), "error", "admin", "hosts-manager");
    }
  }

  const environmentNames = new Map(
    environments.map((item) => [item.id, item.name]),
  );
  const columns: HostsDataColumn<HostsManagerCredential>[] = [
    {
      id: "name",
      label: t("common.name"),
      sortValue: (item) => item.name,
      cell: (item) => <strong>{item.name}</strong>,
    },
    {
      id: "type",
      label: t("hosts.credentials.type"),
      sortValue: (item) => item.type,
      cell: (item) => t(`hosts.credentials.type.${item.type}`),
    },
    {
      id: "username",
      label: t("hosts.credentials.account"),
      sortValue: (item) => item.username,
      cell: (item) => item.username || t("common.none"),
    },
    {
      id: "shared",
      label: t("hosts.credentials.sharedWith"),
      sortValue: (item) => (item.shared_with || []).join(","),
      cell: (item) =>
        item.shared_with?.length
          ? item.shared_with.join(", ")
          : t("hosts.credentials.notShared"),
    },
    {
      id: "environment",
      label: t("hosts.environment.title"),
      sortValue: (item) => environmentNames.get(item.environment_id || "") || "",
      cell: (item) =>
        environmentNames.get(item.environment_id || "") ||
        t("hosts.environment.all"),
    },
    {
      id: "hosts",
      label: t("hosts.credentials.hostCount"),
      sortValue: (item) => item.host_count || 0,
      cell: (item) => item.host_count || 0,
    },
    {
      id: "created",
      label: t("hosts.credentials.createdAt"),
      sortValue: (item) => item.created_at || 0,
      cell: (item) => new Date(item.created_at * 1000).toLocaleString(),
    },
    {
      id: "lastUsed",
      label: t("hosts.credentials.lastUsed"),
      sortValue: (item) => item.last_used_at || 0,
      cell: (item) =>
        item.last_used_at
          ? new Date(item.last_used_at * 1000).toLocaleString()
          : t("common.none"),
    },
    {
      id: "actions",
      label: t("column.actions"),
      cell: (item) =>
        canManage ? (
          <div className="hosts-table-actions">
            <button type="button" onClick={() => showEditor(item)}>
              {t("action.edit")}
            </button>
            <button
              className="button-danger"
              type="button"
              onClick={() => void remove(item)}
            >
              {t("action.delete")}
            </button>
          </div>
        ) : null,
    },
  ];
  const profile = profiles[type] || {};

  return (
    <div className="hosts-manager-app credentials-app">
      <section className="ansible-panel">
        <header>
          <div>
            <h3>{t("hosts.credentials.title")}</h3>
            <p>{t("hosts.credentials.hint")}</p>
          </div>
          <div className="module-section-toolbar">
            <button type="button" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw className={loading ? "spin" : ""} />
              {t("action.refresh")}
            </button>
            {canManage && (
              <button className="button-primary" type="button" onClick={() => showEditor()}>
                <Plus />
                {t("hosts.credentials.add")}
              </button>
            )}
          </div>
        </header>
        <HostsDataTable
          items={items}
          columns={columns}
          rowKey={(item) => item.id}
          loading={loading}
          empty={t("hosts.credentials.empty")}
        />
        {open && (
          <Modal
            title={
              editing
                ? t("hosts.credentials.edit")
                : t("hosts.credentials.add")
            }
            closeLabel={t("action.close")}
            onClose={() => setOpen(false)}
            footer={
              <button
                className="button-primary"
                type="submit"
                form="credential-form"
                disabled={saving}
              >
                {t("action.save")}
              </button>
            }
          >
            <form id="credential-form" className="module-form-grid" onSubmit={save}>
              <label className="module-form-span">
                {t("hosts.credentials.type")}
                <select
                  aria-label={t("hosts.credentials.type")}
                  autoFocus
                  value={type}
                  onChange={(event) =>
                    setCredentialType(event.target.value as CredentialType)
                  }
                  disabled={Boolean(editing)}
                >
                  {credentialTypes.map((value) => (
                    <option key={value} value={value}>
                      {t(`hosts.credentials.type.${value}`)}
                    </option>
                  ))}
                </select>
                <small>
                  {editing
                    ? t("hosts.credentials.typeLocked")
                    : t("hosts.credentials.typeHint")}
                </small>
              </label>
              <label>
                {t("common.name")}
                <input
                  required
                  value={name}
                  placeholder={t("hosts.credentials.namePlaceholder")}
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
              {profile.username && (
                <label>
                  {profile.username.label}
                  <input
                    aria-label={profile.username.label}
                    required={profile.username.required}
                    value={username}
                    placeholder={profile.username.placeholder || ""}
                    onChange={(event) => setUsername(event.target.value)}
                  />
                  <small>{profile.username.hint || ""}</small>
                </label>
              )}
              {profile.secret && (
                <label
                  className={profile.secret.multiline ? "module-form-span" : undefined}
                >
                  {profile.secret.label}
                  {profile.secret.multiline ? (
                    <textarea
                      aria-label={profile.secret.label}
                      rows={7}
                      required={!editing && profile.secret.required}
                      value={secret}
                      onChange={(event) => setSecret(event.target.value)}
                      placeholder={
                        editing
                          ? t("hosts.credentials.keepSecret")
                          : profile.secret.placeholder || ""
                      }
                    />
                  ) : (
                    <input
                      aria-label={profile.secret.label}
                      type="password"
                      required={!editing && profile.secret.required}
                      value={secret}
                      onChange={(event) => setSecret(event.target.value)}
                      autoComplete="new-password"
                      placeholder={
                        editing
                          ? t("hosts.credentials.keepSecret")
                          : profile.secret.placeholder || ""
                      }
                    />
                  )}
                  <small>
                    {editing
                      ? t("hosts.credentials.keepSecret")
                      : profile.secret.hint || ""}
                  </small>
                </label>
              )}
              {profile.passphrase && (
                <label>
                  {t("hosts.credentials.passphrase")}
                  <input
                    aria-label={t("hosts.credentials.passphrase")}
                    type="password"
                    value={passphrase}
                    onChange={(event) => setPassphrase(event.target.value)}
                    autoComplete="new-password"
                  />
                </label>
              )}
              {type === "wol" && (
                <div className="module-form-span module-info">
                  <strong>{t("hosts.credentials.wolNoSecret")}</strong>
                  <p>{t("hosts.credentials.wolNoSecretHint")}</p>
                </div>
              )}
              <label>
                {t("hosts.environment.title")}
                <select
                  value={environmentId}
                  onChange={(event) => setEnvironmentId(event.target.value)}
                >
                  <option value="">{t("hosts.environment.all")}</option>
                  {environments.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="hosts-credential-share-field">
                <span className="hosts-credential-share-label">
                  {t("hosts.credentials.sharedWith")}
                </span>
                <CredentialModuleSelect
                  modules={shareModules}
                  selected={sharedWith}
                  loading={shareModulesLoading}
                  onChange={setSharedWith}
                  t={t}
                />
                <small>{t("hosts.credentials.sharedWithHint")}</small>
              </div>
              <label className="module-form-span">
                {t("common.description")}
                <input
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </label>
            </form>
          </Modal>
        )}
      </section>
    </div>
  );
}
