from pathlib import Path
import json

app = Path("frontend/src/features/modules/hosts/HostsManagerApp.tsx")
text = app.read_text()
start = text.index("function Credentials({")
end = text.index("\nfunction SettingsWorkspace", start)
replacement = r'''function Credentials({
  items,
  environments,
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerCredential[];
  environments: HostsManagerEnvironment[];
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  type CredentialType = HostsManagerCredential["type"];
  type CredentialFieldProfile = {
    username?: { label: string; hint?: string; placeholder?: string; required?: boolean };
    secret?: { label: string; hint?: string; placeholder?: string; multiline?: boolean; required?: boolean };
    passphrase?: boolean;
  };

  const credentialTypes: CredentialType[] = [
    "username_password", "ssh_password", "ssh_private_key", "become_password", "api_token", "generic_secret",
    "proxmox_api", "redfish", "ipmi", "git_private_key", "wol",
  ];
  const defaultShares: Partial<Record<CredentialType, string[]>> = {
    ssh_password: ["hosts-manager", "ansible-controller"],
    ssh_private_key: ["hosts-manager", "ansible-controller"],
    become_password: ["hosts-manager", "ansible-controller"],
    git_private_key: ["hosts-manager", "ansible-controller"],
    proxmox_api: ["proxmox-manager"],
    redfish: ["hosts-manager"], ipmi: ["hosts-manager"], wol: ["hosts-manager"],
    username_password: ["hosts-manager"], api_token: ["hosts-manager"], generic_secret: ["hosts-manager"],
  };
  const profiles: Record<CredentialType, CredentialFieldProfile> = {
    username_password: {
      username: { label: t("hosts.credentials.field.login"), placeholder: "user@example", required: true },
      secret: { label: t("hosts.credentials.field.password"), required: true },
    },
    ssh_password: {
      username: { label: t("hosts.credentials.field.sshUser"), placeholder: "root", required: true },
      secret: { label: t("hosts.credentials.field.sshPassword"), required: true },
    },
    ssh_private_key: {
      username: { label: t("hosts.credentials.field.sshUser"), placeholder: "root", required: true },
      secret: { label: t("hosts.credentials.field.privateKey"), placeholder: "-----BEGIN OPENSSH PRIVATE KEY-----", multiline: true, required: true },
      passphrase: true,
    },
    become_password: {
      secret: { label: t("hosts.credentials.field.becomePassword"), required: true },
    },
    api_token: {
      secret: { label: t("hosts.credentials.field.apiToken"), required: true },
    },
    generic_secret: {
      secret: { label: t("hosts.credentials.field.genericSecret"), required: true },
    },
    proxmox_api: {
      username: { label: t("hosts.credentials.field.proxmoxTokenId"), hint: t("hosts.credentials.field.proxmoxTokenIdHint"), placeholder: "automation@pve!algen", required: true },
      secret: { label: t("hosts.credentials.field.proxmoxTokenSecret"), required: true },
    },
    redfish: {
      username: { label: t("hosts.credentials.field.redfishUser"), required: true },
      secret: { label: t("hosts.credentials.field.redfishPassword"), required: true },
    },
    ipmi: {
      username: { label: t("hosts.credentials.field.ipmiUser"), required: true },
      secret: { label: t("hosts.credentials.field.ipmiPassword"), required: true },
    },
    git_private_key: {
      username: { label: t("hosts.credentials.field.gitUser"), hint: t("hosts.credentials.field.optional") },
      secret: { label: t("hosts.credentials.field.privateKey"), placeholder: "-----BEGIN OPENSSH PRIVATE KEY-----", multiline: true, required: true },
      passphrase: true,
    },
    wol: {},
  };

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<HostsManagerCredential | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState<CredentialType>("username_password");
  const [username, setUsername] = useState("");
  const [environmentId, setEnvironmentId] = useState("");
  const [description, setDescription] = useState("");
  const [secret, setSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [sharedWith, setSharedWith] = useState("");

  function setCredentialType(next: CredentialType) {
    setType(next);
    setUsername("");
    setSecret("");
    setPassphrase("");
    if (!editing) setSharedWith((defaultShares[next] || []).join(", "));
  }

  function showEditor(item?: HostsManagerCredential) {
    const nextType = item?.type || "username_password";
    setEditing(item || null);
    setName(item?.name || "");
    setType(nextType);
    setUsername(item?.username || "");
    setEnvironmentId(item?.environment_id || "");
    setDescription(item?.description || "");
    setSecret("");
    setPassphrase("");
    setSharedWith((item?.shared_with || defaultShares[nextType] || []).join(", "));
    setOpen(true);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      const modules = [...new Set(sharedWith.split(",").map((value) => value.trim()).filter(Boolean))];
      await api.saveHostsManagerCredential({
        name, type, username, environment_id: environmentId || null, secret, passphrase, description,
        shared_with: modules, confirm: true,
      }, editing?.id);
      setSecret("");
      setPassphrase("");
      setOpen(false);
      await refresh();
    } catch (error) {
      toast(hostsManagerError(error, t), "error", "admin", "hosts-manager");
    }
  }

  async function remove(item: HostsManagerCredential) {
    if (!window.confirm(t("hosts.credentials.deleteConfirm"))) return;
    try {
      await api.deleteHostsManagerCredential(item.id);
      await refresh();
    } catch (error) {
      toast(hostsManagerError(error, t), "error", "admin", "hosts-manager");
    }
  }

  const environmentNames = new Map(environments.map((item) => [item.id, item.name]));
  const columns: HostsDataColumn<HostsManagerCredential>[] = [
    { id: "name", label: t("common.name"), sortValue: (item) => item.name, cell: (item) => <strong>{item.name}</strong> },
    { id: "type", label: t("hosts.credentials.type"), sortValue: (item) => item.type, cell: (item) => t(`hosts.credentials.type.${item.type}`) },
    { id: "username", label: t("hosts.credentials.account"), sortValue: (item) => item.username, cell: (item) => item.username || t("common.none") },
    { id: "shared", label: t("hosts.credentials.sharedWith"), sortValue: (item) => (item.shared_with || []).join(","), cell: (item) => item.shared_with?.length ? item.shared_with.join(", ") : t("hosts.credentials.notShared") },
    { id: "environment", label: t("hosts.environment.title"), sortValue: (item) => environmentNames.get(item.environment_id || "") || "", cell: (item) => environmentNames.get(item.environment_id || "") || t("hosts.environment.all") },
    { id: "hosts", label: t("hosts.credentials.hostCount"), sortValue: (item) => item.host_count || 0, cell: (item) => item.host_count || 0 },
    { id: "created", label: t("hosts.credentials.createdAt"), sortValue: (item) => item.created_at || 0, cell: (item) => new Date(item.created_at * 1000).toLocaleString() },
    { id: "lastUsed", label: t("hosts.credentials.lastUsed"), sortValue: (item) => item.last_used_at || 0, cell: (item) => item.last_used_at ? new Date(item.last_used_at * 1000).toLocaleString() : t("common.none") },
    { id: "actions", label: t("column.actions"), cell: (item) => canManage ? <div className="hosts-table-actions"><button type="button" onClick={() => showEditor(item)}>{t("action.edit")}</button><button className="button-danger" type="button" onClick={() => void remove(item)}>{t("action.delete")}</button></div> : null },
  ];
  const profile = profiles[type];

  return <section className="ansible-panel"><header><div><h3>{t("hosts.credentials.title")}</h3><p>{t("hosts.credentials.hint")}</p></div>{canManage && <button onClick={() => showEditor()}><Plus />{t("hosts.credentials.add")}</button>}</header>
    <HostsDataTable items={items} columns={columns} rowKey={(item) => item.id} empty={t("hosts.credentials.empty")} />
    {open && <Modal title={editing ? t("hosts.credentials.edit") : t("hosts.credentials.add")} closeLabel={t("action.close")} onClose={() => setOpen(false)} footer={<button className="button-primary" type="submit" form="credential-form">{t("action.save")}</button>}>
      <form id="credential-form" className="module-form-grid" onSubmit={save}>
        <label className="module-form-span">{t("hosts.credentials.type")}<select autoFocus value={type} onChange={(event) => setCredentialType(event.target.value as CredentialType)} disabled={Boolean(editing)}>{credentialTypes.map((value) => <option key={value} value={value}>{t(`hosts.credentials.type.${value}`)}</option>)}</select><small>{editing ? t("hosts.credentials.typeLocked") : t("hosts.credentials.typeHint")}</small></label>
        <label>{t("common.name")}<input required value={name} placeholder={t("hosts.credentials.namePlaceholder")} onChange={(event) => setName(event.target.value)} /></label>
        {profile.username && <label>{profile.username.label}<input required={profile.username.required} value={username} placeholder={profile.username.placeholder || ""} onChange={(event) => setUsername(event.target.value)} /><small>{profile.username.hint || ""}</small></label>}
        {profile.secret && <label className={profile.secret.multiline ? "module-form-span" : undefined}>{profile.secret.label}{profile.secret.multiline ? <textarea rows={7} required={!editing && profile.secret.required} value={secret} onChange={(event) => setSecret(event.target.value)} placeholder={editing ? t("hosts.credentials.keepSecret") : profile.secret.placeholder || ""} /> : <input type="password" required={!editing && profile.secret.required} value={secret} onChange={(event) => setSecret(event.target.value)} autoComplete="new-password" placeholder={editing ? t("hosts.credentials.keepSecret") : profile.secret.placeholder || ""} />}<small>{editing ? t("hosts.credentials.keepSecret") : profile.secret.hint || ""}</small></label>}
        {profile.passphrase && <label>{t("hosts.credentials.passphrase")}<input type="password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} autoComplete="new-password" /></label>}
        {type === "wol" && <div className="module-form-span module-info"><strong>{t("hosts.credentials.wolNoSecret")}</strong><p>{t("hosts.credentials.wolNoSecretHint")}</p></div>}
        <label>{t("hosts.environment.title")}<select value={environmentId} onChange={(event) => setEnvironmentId(event.target.value)}><option value="">{t("hosts.environment.all")}</option>{environments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>{t("hosts.credentials.sharedWith")}<input value={sharedWith} onChange={(event) => setSharedWith(event.target.value)} placeholder={(defaultShares[type] || []).join(", ")} /><small>{t("hosts.credentials.sharedWithHint")}</small></label>
        <label className="module-form-span">{t("common.description")}<input value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      </form>
    </Modal>}
  </section>;
}
'''
app.write_text(text[:start] + replacement + text[end:])

pl = {
    "common.description": "Opis",
    "hosts.credentials.add": "Dodaj poświadczenie",
    "hosts.credentials.account": "Konto / użytkownik",
    "hosts.credentials.typeHint": "Najpierw wybierz typ poświadczenia. Formularz pokaże tylko pola wymagane dla tego typu.",
    "hosts.credentials.typeLocked": "Typ istniejącego poświadczenia jest zablokowany. Utwórz nowe poświadczenie, aby użyć innego typu.",
    "hosts.credentials.namePlaceholder": "np. Proxmox Lab, SSH root, Git deploy key",
    "hosts.credentials.field.login": "Login / nazwa użytkownika",
    "hosts.credentials.field.password": "Hasło",
    "hosts.credentials.field.sshUser": "Użytkownik SSH",
    "hosts.credentials.field.sshPassword": "Hasło SSH",
    "hosts.credentials.field.privateKey": "Klucz prywatny",
    "hosts.credentials.field.becomePassword": "Hasło sudo / root",
    "hosts.credentials.field.apiToken": "Token API",
    "hosts.credentials.field.genericSecret": "Sekret",
    "hosts.credentials.field.proxmoxTokenId": "ID tokenu Proxmox",
    "hosts.credentials.field.proxmoxTokenIdHint": "Format: user@realm!tokenid, np. automation@pve!algen.",
    "hosts.credentials.field.proxmoxTokenSecret": "Sekret tokenu Proxmox",
    "hosts.credentials.field.redfishUser": "Login Redfish",
    "hosts.credentials.field.redfishPassword": "Hasło Redfish",
    "hosts.credentials.field.ipmiUser": "Login IPMI",
    "hosts.credentials.field.ipmiPassword": "Hasło IPMI",
    "hosts.credentials.field.gitUser": "Użytkownik Git",
    "hosts.credentials.field.optional": "Pole opcjonalne.",
    "hosts.credentials.wolNoSecret": "Wake-on-LAN nie wymaga sekretu.",
    "hosts.credentials.wolNoSecretHint": "Adres MAC i parametry WOL są konfigurowane w profilu zasilania hosta.",
}
en = {
    "common.description": "Description",
    "hosts.credentials.add": "Add credential",
    "hosts.credentials.account": "Account / username",
    "hosts.credentials.typeHint": "Choose the credential type first. The form will show only fields required for that type.",
    "hosts.credentials.typeLocked": "The type of an existing credential is locked. Create a new credential to use another type.",
    "hosts.credentials.namePlaceholder": "e.g. Proxmox Lab, SSH root, Git deploy key",
    "hosts.credentials.field.login": "Login / username",
    "hosts.credentials.field.password": "Password",
    "hosts.credentials.field.sshUser": "SSH user",
    "hosts.credentials.field.sshPassword": "SSH password",
    "hosts.credentials.field.privateKey": "Private key",
    "hosts.credentials.field.becomePassword": "sudo / root password",
    "hosts.credentials.field.apiToken": "API token",
    "hosts.credentials.field.genericSecret": "Secret",
    "hosts.credentials.field.proxmoxTokenId": "Proxmox token ID",
    "hosts.credentials.field.proxmoxTokenIdHint": "Format: user@realm!tokenid, for example automation@pve!algen.",
    "hosts.credentials.field.proxmoxTokenSecret": "Proxmox token secret",
    "hosts.credentials.field.redfishUser": "Redfish login",
    "hosts.credentials.field.redfishPassword": "Redfish password",
    "hosts.credentials.field.ipmiUser": "IPMI login",
    "hosts.credentials.field.ipmiPassword": "IPMI password",
    "hosts.credentials.field.gitUser": "Git username",
    "hosts.credentials.field.optional": "Optional field.",
    "hosts.credentials.wolNoSecret": "Wake-on-LAN does not require a secret.",
    "hosts.credentials.wolNoSecretHint": "The MAC address and WOL parameters are configured in the host power profile.",
}
for path, extra in [(Path("frontend/src/locales/pl-PL.json"), pl), (Path("frontend/src/locales/en-US.json"), en)]:
    data = json.loads(path.read_text())
    data.update(extra)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

test = Path("frontend/src/features/modules/hosts/HostsManagerApp.test.tsx")
source = test.read_text()
source = source.replace(
    "hostsManagerCredentials: vi.fn(),",
    "hostsManagerCredentials: vi.fn(), saveHostsManagerCredential: vi.fn(), deleteHostsManagerCredential: vi.fn(),",
)
marker = '  it("keeps APMID selectors for enrollment without duplicating the management form", async () => {'
if marker not in source:
    raise SystemExit("test insertion marker not found")
new_test = r'''  it("shows credential fields dynamically for the selected type", async () => {
    vi.mocked(api.saveHostsManagerCredential).mockResolvedValue({} as never);
    render(<HostsManagerApp permissions={[...permissions, "hosts-manager.credentials.view", "hosts-manager.credentials.manage"]} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.credentials/ }));
    fireEvent.click(await screen.findByRole("button", { name: "hosts.credentials.add" }));

    const typeSelect = screen.getByLabelText("hosts.credentials.type");
    expect(typeSelect).toHaveValue("username_password");
    expect(screen.getByLabelText("hosts.credentials.field.login")).toBeInTheDocument();
    expect(screen.getByLabelText("hosts.credentials.field.password")).toBeInTheDocument();
    expect(screen.queryByLabelText("hosts.credentials.field.sshUser")).not.toBeInTheDocument();

    fireEvent.change(typeSelect, { target: { value: "proxmox_api" } });
    expect(screen.getByLabelText("hosts.credentials.field.proxmoxTokenId")).toBeInTheDocument();
    expect(screen.getByLabelText("hosts.credentials.field.proxmoxTokenSecret")).toBeInTheDocument();
    expect(screen.queryByLabelText("hosts.credentials.field.password")).not.toBeInTheDocument();

    fireEvent.change(typeSelect, { target: { value: "ssh_private_key" } });
    expect(screen.getByLabelText("hosts.credentials.field.sshUser")).toBeInTheDocument();
    expect(screen.getByLabelText("hosts.credentials.field.privateKey")).toBeInTheDocument();
    expect(screen.getByLabelText("hosts.credentials.passphrase")).toBeInTheDocument();

    fireEvent.change(typeSelect, { target: { value: "wol" } });
    expect(screen.getByText("hosts.credentials.wolNoSecret")).toBeInTheDocument();
    expect(screen.queryByLabelText("hosts.credentials.field.privateKey")).not.toBeInTheDocument();
  });

'''
source = source.replace(marker, new_test + marker)
test.write_text(source)
