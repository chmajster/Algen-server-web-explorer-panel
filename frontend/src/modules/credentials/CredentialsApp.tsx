import {
  ChevronDown,
  KeyRound,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
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
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", keyboard);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", keyboard);
    };
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

function CredentialShareChips({
  ids,
  names,
  empty,
}: {
  ids: string[];
  names: Map<string, string>;
  empty: string;
}) {
  if (!ids.length) return <span className="credentials-muted">{empty}</span>;
  const visible = ids.slice(0, 3);
  const remaining = ids.length - visible.length;
  return (
    <div className="credentials-share-chips">
      {visible.map((id) => (
        <span key={id} className="credentials-chip" title={id}>
          {names.get(id) || id}
        </span>
      ))}
      {remaining > 0 && (
        <span className="credentials-chip credentials-chip-more">+{remaining}</span>
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
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [environmentFilter, setEnvironmentFilter] = useState("");
  const [moduleFilter, setModuleFilter] = useState("");
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

  const environmentNames = useMemo(
    () => new Map(environments.map((item) => [item.id, item.name])),
    [environments],
  );
  const moduleNames = useMemo(
    () => new Map(shareModules.map((item) => [item.id, item.name])),
    [shareModules],
  );

  const filteredItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return items.filter((item) => {
      if (typeFilter && item.type !== typeFilter) return false;
      if (environmentFilter && (item.environment_id || "") !== environmentFilter)
        return false;
      if (moduleFilter && !(item.shared_with || []).includes(moduleFilter)) return false;
      if (!normalizedQuery) return true;
      return [item.name, item.username, item.description, item.type]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalizedQuery));
    });
  }, [environmentFilter, items, moduleFilter, query, typeFilter]);

  function setCredentialType(next: CredentialType) {
    setType(next);
    setUsername("");
    setSecret("");
    setPassphrase("");
  }

  function closeEditor() {
    setSecret("");
    setPassphrase("");
    setEditing(null);
    setOpen(false);
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
      closeEditor();
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

  const columns: HostsDataColumn<HostsManagerCredential>[] = [
    {
      id: "name",
      label: t("common.name"),
      sortValue: (item) => item.name,
      cell: (item) => (
        <div className="credentials-name-cell">
          <strong>{item.name}</strong>
          {item.description && <small>{item.description}</small>}
        </div>
      ),
    },
    {
      id: "type",
      label: t("hosts.credentials.type"),
      sortValue: (item) => item.type,
      cell: (item) => (
        <span className="credentials-type-badge">
          {t(`hosts.credentials.type.${item.type}`)}
        </span>
      ),
    },
    {
      id: "username",
      label: t("hosts.credentials.account"),
      sortValue: (item) => item.username,
      cell: (item) => (
        <span className={item.username ? "credentials-account" : "credentials-muted"}>
          {item.username || t("common.none")}
        </span>
      ),
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
      id: "shared",
      label: t("hosts.credentials.sharedWith"),
      sortValue: (item) => (item.shared_with || []).join(","),
      cell: (item) => (
        <CredentialShareChips
          ids={item.shared_with || []}
          names={moduleNames}
          empty={t("hosts.credentials.notShared")}
        />
      ),
    },
    {
      id: "hosts",
      label: t("hosts.credentials.hostCount"),
      sortValue: (item) => item.host_count || 0,
      align: "center",
      cell: (item) => item.host_count || 0,
    },
    {
      id: "actions",
      label: t("column.actions"),
      cell: (item) =>
        canManage ? (
          <div className="hosts-table-actions credentials-row-actions">
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
    <div className="credentials-app">
      <section className="credentials-workspace">
        <header className="credentials-header">
          <div className="credentials-heading">
            <span className="credentials-heading-icon" aria-hidden="true">
              <KeyRound />
            </span>
            <div>
              <h2>{t("hosts.credentials.title")}</h2>
              <p>{t("hosts.credentials.hint")}</p>
            </div>
          </div>
          <div className="credentials-header-actions">
            <button type="button" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw className={loading ? "spin" : ""} aria-hidden="true" />
              {t("action.refresh")}
            </button>
            {canManage && (
              <button
                className="button-primary"
                type="button"
                onClick={() => showEditor()}
              >
                <Plus aria-hidden="true" />
                {t("hosts.credentials.add")}
              </button>
            )}
          </div>
        </header>

        <div className="credentials-security-note" role="note">
          <ShieldCheck aria-hidden="true" />
          <span>{t("hosts.credentials.hint")}</span>
        </div>

        <div className="credentials-toolbar">
          <label className="credentials-search-field">
            <span className="credentials-visually-hidden">{t("action.search")}</span>
            <Search aria-hidden="true" />
            <input
              aria-label={t("action.search")}
              type="search"
              value={query}
              placeholder={`${t("action.search")}…`}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <label>
            <span>{t("hosts.credentials.type")}</span>
            <select
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
            >
              <option value="">{t("filter.all")}</option>
              {credentialTypes.map((value) => (
                <option key={value} value={value}>
                  {t(`hosts.credentials.type.${value}`)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t("hosts.environment.title")}</span>
            <select
              value={environmentFilter}
              onChange={(event) => setEnvironmentFilter(event.target.value)}
            >
              <option value="">{t("filter.all")}</option>
              {environments.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t("hosts.credentials.sharedWith")}</span>
            <select
              value={moduleFilter}
              onChange={(event) => setModuleFilter(event.target.value)}
            >
              <option value="">{t("filter.all")}</option>
              {shareModules.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <output className="credentials-count" aria-live="polite">
            {filteredItems.length} / {items.length}
          </output>
        </div>

        <HostsDataTable
          items={filteredItems}
          columns={columns}
          rowKey={(item) => item.id}
          loading={loading}
          empty={
            <div className="credentials-empty-state">
              <KeyRound aria-hidden="true" />
              <strong>{t("hosts.credentials.empty")}</strong>
              <small>{t("hosts.credentials.hint")}</small>
            </div>
          }
        />

        {open && (
          <Modal
            title={
              editing
                ? t("hosts.credentials.edit")
                : t("hosts.credentials.add")
            }
            closeLabel={t("action.close")}
            onClose={closeEditor}
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
            <form
              id="credential-form"
              className="credentials-form"
              onSubmit={save}
            >
              <div className="credentials-form-section credentials-form-grid">
                <label>
                  {t("common.name")}
                  <input
                    autoFocus
                    required
                    value={name}
                    placeholder={t("hosts.credentials.namePlaceholder")}
                    onChange={(event) => setName(event.target.value)}
                  />
                </label>
                <label>
                  {t("hosts.credentials.type")}
                  <select
                    aria-label={t("hosts.credentials.type")}
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
                <label className="credentials-form-span">
                  {t("common.description")}
                  <input
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </label>
              </div>

              <div className="credentials-form-section credentials-form-grid">
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
                    {profile.username.hint && <small>{profile.username.hint}</small>}
                  </label>
                )}
                {profile.secret && (
                  <label
                    className={
                      profile.secret.multiline ? "credentials-form-span" : undefined
                    }
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
                  <div className="credentials-form-span module-info">
                    <strong>{t("hosts.credentials.wolNoSecret")}</strong>
                    <p>{t("hosts.credentials.wolNoSecretHint")}</p>
                  </div>
                )}
              </div>

              <div className="credentials-form-section credentials-form-grid">
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
                <div className="hosts-credential-share-field credentials-form-span">
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
              </div>
            </form>
          </Modal>
        )}
      </section>
    </div>
  );
}
