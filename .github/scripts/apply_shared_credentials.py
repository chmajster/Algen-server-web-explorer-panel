from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def append_before_closing_brace(path: str, entries: list[tuple[str, str]]) -> None:
    text = read(path)
    if entries[0][0] in text:
        return
    stripped = text.rstrip()
    if not stripped.endswith("}"):
        raise RuntimeError(f"{path}: JSON object does not end with }}")
    body = stripped[:-1].rstrip()
    if body and not body.endswith(","):
        body += ","
    lines = [f'  "{key}": "{value}"' for key, value in entries]
    write(path, body + "\n" + ",\n".join(lines) + "\n}\n")


# Hosts Manager credential model: generic secret types + explicit module ACL.
models = "backend/app/modules/hosts_manager/models.py"
replace_once(
    models,
    '''class CredentialType(StrEnum):\n    ssh_private_key = "ssh_private_key"\n    ssh_password = "ssh_password"\n    become_password = "become_password"\n    redfish = "redfish"\n    ipmi = "ipmi"\n    proxmox_api = "proxmox_api"\n    wol = "wol"\n    git_private_key = "git_private_key"\n''',
    '''class CredentialType(StrEnum):\n    ssh_private_key = "ssh_private_key"\n    ssh_password = "ssh_password"\n    become_password = "become_password"\n    username_password = "username_password"\n    api_token = "api_token"\n    generic_secret = "generic_secret"\n    redfish = "redfish"\n    ipmi = "ipmi"\n    proxmox_api = "proxmox_api"\n    wol = "wol"\n    git_private_key = "git_private_key"\n\n\nDEFAULT_CREDENTIAL_SHARES: dict[CredentialType, tuple[str, ...]] = {\n    CredentialType.ssh_private_key: ("hosts-manager", "ansible-controller"),\n    CredentialType.ssh_password: ("hosts-manager", "ansible-controller"),\n    CredentialType.become_password: ("hosts-manager", "ansible-controller"),\n    CredentialType.git_private_key: ("hosts-manager", "ansible-controller"),\n    CredentialType.redfish: ("hosts-manager",),\n    CredentialType.ipmi: ("hosts-manager",),\n    CredentialType.proxmox_api: ("proxmox-manager",),\n    CredentialType.wol: ("hosts-manager",),\n    CredentialType.username_password: ("hosts-manager",),\n    CredentialType.api_token: ("hosts-manager",),\n    CredentialType.generic_secret: ("hosts-manager",),\n}\n''',
)
replace_once(
    models,
    '''    description: str = Field(default="", max_length=500)\n    environment_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)\n    confirm: bool = False\n\n    @model_validator(mode="after")\n    def valid_secret(self) -> "CredentialInput":\n        if self.type != CredentialType.wol and not self.secret:\n            raise ValueError("credential secret is required")\n        if self.type in {CredentialType.ssh_private_key, CredentialType.git_private_key} and "PRIVATE KEY-----" not in self.secret:\n            raise ValueError("private-key credential is invalid")\n        if self.type not in {CredentialType.ssh_private_key, CredentialType.git_private_key} and ("\\n" in self.secret or "\\r" in self.secret):\n            raise ValueError("credential secret must be a single line")\n        return self\n''',
    '''    description: str = Field(default="", max_length=500)\n    environment_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)\n    shared_with: list[str] | None = Field(default=None, max_length=64)\n    confirm: bool = False\n\n    @model_validator(mode="after")\n    def valid_secret(self) -> "CredentialInput":\n        if self.secret and self.type in {CredentialType.ssh_private_key, CredentialType.git_private_key} and "PRIVATE KEY-----" not in self.secret:\n            raise ValueError("private-key credential is invalid")\n        if self.secret and self.type not in {CredentialType.ssh_private_key, CredentialType.git_private_key} and ("\\n" in self.secret or "\\r" in self.secret):\n            raise ValueError("credential secret must be a single line")\n        shares = list(DEFAULT_CREDENTIAL_SHARES.get(self.type, ())) if self.shared_with is None else self.shared_with\n        if any(not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", module_id) for module_id in shares):\n            raise ValueError("shared module identifier is invalid")\n        self.shared_with = list(dict.fromkeys(shares))\n        return self\n''',
)

# Hosts Manager storage: schema v6, migration/default ACLs, secret-preserving edits, ACL enforcement.
service = "backend/app/modules/hosts_manager/service.py"
replace_once(service, "SCHEMA_VERSION = 5", "SCHEMA_VERSION = 6")
replace_once(
    service,
    '''    "report_json": "report",\n}''',
    '''    "report_json": "report", "shared_with_json": "shared_with",\n}''',
)
replace_once(
    service,
    '''                    description TEXT NOT NULL DEFAULT '', encrypted_secret TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,\n                    environment_id TEXT, last_used_at REAL,\n                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);''',
    '''                    description TEXT NOT NULL DEFAULT '', encrypted_secret TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,\n                    environment_id TEXT, last_used_at REAL, shared_with_json TEXT NOT NULL DEFAULT '[]',\n                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);''',
)
replace_once(
    service,
    '''            token_columns = {row[1] for row in connection.execute("PRAGMA table_info(enrollment_tokens)")}''',
    '''            credential_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(credentials)").fetchall()}\n            if "shared_with_json" not in credential_columns:\n                connection.execute("ALTER TABLE credentials ADD COLUMN shared_with_json TEXT NOT NULL DEFAULT '[]'")\n            connection.execute(\n                """UPDATE credentials SET shared_with_json=CASE\n                    WHEN type IN ('ssh_private_key','ssh_password','become_password','git_private_key') THEN '[\\"hosts-manager\\",\\"ansible-controller\\"]'\n                    WHEN type='proxmox_api' THEN '[\\"proxmox-manager\\"]'\n                    ELSE '[\\"hosts-manager\\"]' END\n                   WHERE shared_with_json IS NULL OR shared_with_json='' OR shared_with_json='[]'"""\n            )\n            token_columns = {row[1] for row in connection.execute("PRAGMA table_info(enrollment_tokens)")}''',
)
replace_once(
    service,
    '''    @staticmethod\n    def _credential_metadata(item: dict[str, Any]) -> dict[str, Any]:\n        return {key: value for key, value in item.items() if key != "encrypted_secret"} | {"secret_configured": bool(item.get("encrypted_secret"))}\n\n    def save_credential(self, payload: CredentialInput, actor: str, credential_id: str | None = None) -> dict[str, Any]:\n        now, item_id = time.time(), credential_id or stable_id()\n        envelope = self.cipher.encrypt(json.dumps({"secret": payload.secret, "passphrase": payload.passphrase}), associated_data=item_id) if payload.secret else ""\n        with self.connect() as connection:\n            old = connection.execute("SELECT created_at,created_by FROM credentials WHERE id=?", (item_id,)).fetchone()\n            created_at, created_by = (old["created_at"], old["created_by"]) if old else (now, actor)\n            connection.execute("""INSERT INTO credentials(id,name,type,username,description,encrypted_secret,active,environment_id,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,1,?,?,?,?,?)\n                ON CONFLICT(id) DO UPDATE SET name=excluded.name,type=excluded.type,username=excluded.username,description=excluded.description,encrypted_secret=excluded.encrypted_secret,active=1,environment_id=excluded.environment_id,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",\n                (item_id, payload.name, payload.type.value, payload.username, payload.description, envelope, payload.environment_id, created_at, now, created_by, actor))\n        return self._credential_metadata(self._get("credentials", item_id) or {})\n\n    def verified_credential(self, credential_id: str, *, module_id: str, purpose: str) -> dict[str, str]:\n        if not module_id or not purpose:\n            raise PermissionError("a controlled backend credential context is required")\n        item = self._get("credentials", credential_id)\n        if not item or not item.get("active") or not item.get("encrypted_secret"):\n            raise KeyError("credential not found")\n        value = json.loads(self.cipher.decrypt(str(item["encrypted_secret"]), associated_data=credential_id))\n''',
    '''    @staticmethod\n    def _credential_metadata(item: dict[str, Any]) -> dict[str, Any]:\n        return {key: value for key, value in item.items() if key != "encrypted_secret"} | {"secret_configured": bool(item.get("encrypted_secret"))}\n\n    def save_credential(self, payload: CredentialInput, actor: str, credential_id: str | None = None) -> dict[str, Any]:\n        now, item_id = time.time(), credential_id or stable_id()\n        with self.connect() as connection:\n            old = connection.execute("SELECT created_at,created_by,encrypted_secret FROM credentials WHERE id=?", (item_id,)).fetchone()\n            if payload.secret:\n                envelope = self.cipher.encrypt(json.dumps({"secret": payload.secret, "passphrase": payload.passphrase}), associated_data=item_id)\n            elif old:\n                envelope = str(old["encrypted_secret"] or "")\n            elif payload.type.value != "wol":\n                raise ValueError("credential secret is required")\n            else:\n                envelope = ""\n            created_at, created_by = (old["created_at"], old["created_by"]) if old else (now, actor)\n            shares = json.dumps(payload.shared_with or [], ensure_ascii=False, separators=(",", ":"))\n            connection.execute("""INSERT INTO credentials(id,name,type,username,description,encrypted_secret,active,environment_id,shared_with_json,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?)\n                ON CONFLICT(id) DO UPDATE SET name=excluded.name,type=excluded.type,username=excluded.username,description=excluded.description,encrypted_secret=excluded.encrypted_secret,active=1,environment_id=excluded.environment_id,shared_with_json=excluded.shared_with_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",\n                (item_id, payload.name, payload.type.value, payload.username, payload.description, envelope, payload.environment_id, shares, created_at, now, created_by, actor))\n        return self._credential_metadata(self._get("credentials", item_id) or {})\n\n    def verified_credential(self, credential_id: str, *, module_id: str, purpose: str) -> dict[str, str]:\n        if not module_id or not purpose:\n            raise PermissionError("a controlled backend credential context is required")\n        item = self._get("credentials", credential_id)\n        if not item or not item.get("active") or not item.get("encrypted_secret"):\n            raise KeyError("credential not found")\n        if module_id not in set(item.get("shared_with") or []):\n            raise PermissionError(f"credential is not shared with module {module_id}")\n        value = json.loads(self.cipher.decrypt(str(item["encrypted_secret"]), associated_data=credential_id))\n''',
)

# Frontend contract exposes the expanded types and ACL metadata.
contracts = "frontend/src/core/api/contracts.ts"
replace_once(
    contracts,
    '''export type HostsManagerCredential = Omit<AnsibleCredential, "type"> & {\n  type: AnsibleCredential["type"] | "redfish" | "ipmi" | "proxmox_api" | "wol";\n  environment_id?: string | null; last_used_at?: number | null; host_count?: number;\n};''',
    '''export type HostsManagerCredentialType = AnsibleCredential["type"] | "username_password" | "api_token" | "generic_secret" | "redfish" | "ipmi" | "proxmox_api" | "wol";\nexport type HostsManagerCredential = Omit<AnsibleCredential, "type"> & {\n  type: HostsManagerCredentialType;\n  environment_id?: string | null; last_used_at?: number | null; host_count?: number; shared_with: string[];\n};''',
)

# Replace only the Credentials workspace so the rest of the large Hosts Manager UI stays untouched.
hosts_app = "frontend/src/features/modules/hosts/HostsManagerApp.tsx"
text = read(hosts_app)
start = text.index("function Credentials({")
end = text.index("function Repositories({", start)
new_credentials = r'''function Credentials({
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
  const credentialTypes: CredentialType[] = [
    "ssh_password", "ssh_private_key", "become_password", "username_password", "api_token", "generic_secret",
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
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<HostsManagerCredential | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState<CredentialType>("ssh_password");
  const [username, setUsername] = useState("");
  const [environmentId, setEnvironmentId] = useState("");
  const [description, setDescription] = useState("");
  const [secret, setSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [sharedWith, setSharedWith] = useState("");

  function setCredentialType(next: CredentialType) {
    setType(next);
    if (!editing) setSharedWith((defaultShares[next] || []).join(", "));
  }
  function showEditor(item?: HostsManagerCredential) {
    setEditing(item || null);
    setName(item?.name || "");
    setType(item?.type || "ssh_password");
    setUsername(item?.username || "");
    setEnvironmentId(item?.environment_id || "");
    setDescription(item?.description || "");
    setSecret("");
    setPassphrase("");
    setSharedWith((item?.shared_with || defaultShares[item?.type || "ssh_password"] || []).join(", "));
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
      setOpen(false);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }

  async function remove(item: HostsManagerCredential) {
    if (!(await confirmDialog(t("hosts.credentials.deleteConfirm"), t))) return;
    try { await api.deleteHostsManagerCredential(item.id); await refresh(); }
    catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); }
  }

  const environmentNames = new Map(environments.map((item) => [item.id, item.name]));
  const columns: HostsDataColumn<HostsManagerCredential>[] = [
    { id: "name", label: t("common.name"), sortValue: (item) => item.name, cell: (item) => <strong>{item.name}</strong> },
    { id: "type", label: t("hosts.credentials.type"), sortValue: (item) => item.type, cell: (item) => t(`hosts.credentials.type.${item.type}`) },
    { id: "username", label: t("hosts.host.user"), sortValue: (item) => item.username, cell: (item) => item.username || t("common.none") },
    { id: "shared", label: t("hosts.credentials.sharedWith"), sortValue: (item) => (item.shared_with || []).join(","), cell: (item) => item.shared_with?.length ? item.shared_with.join(", ") : t("hosts.credentials.notShared") },
    { id: "environment", label: t("hosts.environment.title"), sortValue: (item) => environmentNames.get(item.environment_id || "") || "", cell: (item) => environmentNames.get(item.environment_id || "") || t("hosts.environment.all") },
    { id: "hosts", label: t("hosts.credentials.hostCount"), sortValue: (item) => item.host_count || 0, cell: (item) => item.host_count || 0 },
    { id: "created", label: t("hosts.credentials.createdAt"), sortValue: (item) => item.created_at || 0, cell: (item) => new Date(item.created_at * 1000).toLocaleString() },
    { id: "lastUsed", label: t("hosts.credentials.lastUsed"), sortValue: (item) => item.last_used_at || 0, cell: (item) => item.last_used_at ? new Date(item.last_used_at * 1000).toLocaleString() : t("common.none") },
    { id: "actions", label: t("common.actions"), cell: (item) => canManage ? <div className="hosts-table-actions"><button type="button" onClick={() => showEditor(item)}>{t("action.edit")}</button><button className="button-danger" type="button" onClick={() => void remove(item)}>{t("action.delete")}</button></div> : null },
  ];
  const keyType = type === "ssh_private_key" || type === "git_private_key";
  const usernameRequired = ["ssh_password", "ssh_private_key", "username_password", "proxmox_api", "redfish", "ipmi"].includes(type);

  return <section className="ansible-panel"><header><div><h3>{t("hosts.credentials.title")}</h3><p>{t("hosts.credentials.hint")}</p></div>{canManage && <button onClick={() => showEditor()}><Plus />{t("hosts.credentials.add")}</button>}</header>
    <HostsDataTable items={items} columns={columns} rowKey={(item) => item.id} empty={t("hosts.credentials.empty")} />
    {open && <Modal title={editing ? t("hosts.credentials.edit") : t("hosts.credentials.add")} closeLabel={t("action.close")} onClose={() => setOpen(false)} footer={<button className="button-primary" type="submit" form="credential-form">{t("action.save")}</button>}>
      <form id="credential-form" className="module-form-grid" onSubmit={save}>
        <label>{t("common.name")}<input required value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label>{t("hosts.credentials.type")}<select value={type} onChange={(event) => setCredentialType(event.target.value as CredentialType)}>{credentialTypes.map((value) => <option key={value} value={value}>{t(`hosts.credentials.type.${value}`)}</option>)}</select></label>
        <label>{t("hosts.host.user")}<input required={usernameRequired} value={username} onChange={(event) => setUsername(event.target.value)} /><small>{t("hosts.credentials.usernameHint")}</small></label>
        <label>{t("hosts.environment.title")}<select value={environmentId} onChange={(event) => setEnvironmentId(event.target.value)}><option value="">{t("hosts.environment.all")}</option>{environments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="module-form-span">{t("common.description")}<input value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        <label className="module-form-span">{t("hosts.credentials.sharedWith")}<input value={sharedWith} onChange={(event) => setSharedWith(event.target.value)} placeholder="hosts-manager, proxmox-manager" /><small>{t("hosts.credentials.sharedWithHint")}</small></label>
        <label className={keyType ? "module-form-span" : undefined}>{t("hosts.credentials.secret")}{keyType ? <textarea rows={7} required={!editing} value={secret} onChange={(event) => setSecret(event.target.value)} placeholder={editing ? t("hosts.credentials.keepSecret") : "-----BEGIN PRIVATE KEY-----"} /> : <input type="password" required={!editing && type !== "wol"} value={secret} onChange={(event) => setSecret(event.target.value)} autoComplete="new-password" placeholder={editing ? t("hosts.credentials.keepSecret") : ""} />}<small>{editing ? t("hosts.credentials.keepSecret") : ""}</small></label>
        {keyType && <label>{t("hosts.credentials.passphrase")}<input type="password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} autoComplete="new-password" /></label>}
      </form>
    </Modal>}
  </section>;
}
'''
write(hosts_app, text[:start] + new_credentials + text[end:])

# Proxmox Manager consumes only explicitly shared central credentials and supports API token or username/password.
proxmox_ui = "frontend/src/features/modules/proxmox/ProxmoxManagerApp.tsx"
replace_once(
    proxmox_ui,
    'setCredentials(credentialItems.filter((item) => item.type === "proxmox_api"));',
    'setCredentials(credentialItems.filter((item) => ["proxmox_api", "username_password"].includes(item.type) && (item.shared_with || []).includes("proxmox-manager")));',
)
replace_once(
    proxmox_ui,
    '<p>API tokens are referenced from Hosts Manager credentials and are never copied into this module.</p>',
    '<p>Credentials are referenced from Hosts Manager and are never copied into this module. API tokens and Proxmox username/password credentials are supported.</p>',
)
replace_once(
    proxmox_ui,
    'if (!form.credential_id) { toast("Create a Hosts Manager credential of type proxmox_api first.", "error", "admin", "proxmox-manager"); return; }',
    'if (!form.credential_id) { toast("Create a Hosts Manager credential shared with proxmox-manager first.", "error", "admin", "proxmox-manager"); return; }',
)
replace_once(
    proxmox_ui,
    '<form id="proxmox-connection-form" onSubmit={submit}><p>Store the API token in Hosts Manager → Credentials as type <code>proxmox_api</code>. Set username to <code>user@realm!tokenid</code> and secret to the token secret.</p>',
    '<form id="proxmox-connection-form" onSubmit={submit}><p>Use a Hosts Manager credential shared with <code>proxmox-manager</code>: <code>proxmox_api</code> for API tokens, or <code>username_password</code> for a Proxmox <code>user@realm</code> login.</p>',
)
replace_once(proxmox_ui, '<option value="">Select proxmox_api credential</option>', '<option value="">Select shared Proxmox credential</option>')

# Proxmox API client: token auth remains unchanged; username/password obtains a ticket + CSRF token.
proxmox_service = "backend/app/modules/proxmox_manager/service.py"
replace_once(
    proxmox_service,
    '''        token_secret: str,\n        *,\n        verify_tls: bool = True,''',
    '''        token_secret: str,\n        *,\n        credential_type: str = "proxmox_api",\n        verify_tls: bool = True,''',
)
replace_once(
    proxmox_service,
    '''        if not token_id or "!" not in token_id or not token_secret:\n            raise ValueError("Proxmox API credential requires username user@realm!tokenid and token secret")\n        self.endpoint = endpoint.rstrip("/")\n        self.authorization = f"PVEAPIToken={token_id}={token_secret}"\n        self.timeout = timeout\n''',
    '''        self.endpoint = endpoint.rstrip("/")\n        self.credential_type = credential_type\n        self.username = token_id\n        self.secret = token_secret\n        self.authorization = ""\n        self.ticket = ""\n        self.csrf_token = ""\n        if credential_type == "proxmox_api":\n            if not token_id or "!" not in token_id or not token_secret:\n                raise ValueError("Proxmox API credential requires username user@realm!tokenid and token secret")\n            self.authorization = f"PVEAPIToken={token_id}={token_secret}"\n        elif credential_type == "username_password":\n            if not token_id or "@" not in token_id or not token_secret:\n                raise ValueError("Proxmox username/password credential requires user@realm and password")\n        else:\n            raise ValueError("unsupported Proxmox credential type")\n        self.timeout = timeout\n''',
)
replace_once(
    proxmox_service,
    '''    def request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:\n        encoded = urllib.parse.urlencode(data or {}, doseq=True).encode() if method != "GET" else None\n        url = f"{self.endpoint}/api2/json/{path.lstrip('/')}"\n        request = urllib.request.Request(\n            url,\n            data=encoded,\n            method=method,\n            headers={\n                "Authorization": self.authorization,\n                "Accept": "application/json",\n                "Content-Type": "application/x-www-form-urlencoded",\n            },\n        )\n''',
    '''    def _login(self) -> None:\n        encoded = urllib.parse.urlencode({"username": self.username, "password": self.secret}).encode()\n        request = urllib.request.Request(\n            f"{self.endpoint}/api2/json/access/ticket",\n            data=encoded,\n            method="POST",\n            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},\n        )\n        try:\n            with urllib.request.urlopen(request, timeout=self.timeout, context=self.ssl_context) as response:  # nosec B310\n                payload = json.loads(response.read(1024 * 1024).decode("utf-8"))\n        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ssl.SSLError, ValueError, UnicodeDecodeError) as error:\n            raise ProxmoxApiError(f"Proxmox login failed: {type(error).__name__}") from error\n        data = payload.get("data") if isinstance(payload, dict) else None\n        if not isinstance(data, dict) or not data.get("ticket") or not data.get("CSRFPreventionToken"):\n            raise ProxmoxApiError("Proxmox login returned an invalid response")\n        self.ticket = str(data["ticket"])\n        self.csrf_token = str(data["CSRFPreventionToken"])\n\n    def request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:\n        encoded = urllib.parse.urlencode(data or {}, doseq=True).encode() if method != "GET" else None\n        url = f"{self.endpoint}/api2/json/{path.lstrip('/')}"\n        headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}\n        if self.credential_type == "proxmox_api":\n            headers["Authorization"] = self.authorization\n        else:\n            if not self.ticket:\n                self._login()\n            headers["Cookie"] = f"PVEAuthCookie={self.ticket}"\n            if method != "GET":\n                headers["CSRFPreventionToken"] = self.csrf_token\n        request = urllib.request.Request(url, data=encoded, method=method, headers=headers)\n''',
)
replace_once(
    proxmox_service,
    '''        if not credential or credential.get("type") != "proxmox_api":\n            raise KeyError("Proxmox API credential not found")''',
    '''        if not credential or credential.get("type") not in {"proxmox_api", "username_password"}:\n            raise KeyError("Proxmox credential not found")\n        if "proxmox-manager" not in set(credential.get("shared_with") or ["proxmox-manager"] if credential.get("type") == "proxmox_api" else []):\n            raise PermissionError("credential is not shared with Proxmox Manager")''',
)
replace_once(
    proxmox_service,
    '''        if credential["type"] != "proxmox_api":\n            raise ValueError("configured credential is not a Proxmox API credential")\n        return ProxmoxApiClient(\n            str(item["endpoint"]),\n            credential["username"],\n            credential["secret"],\n            verify_tls=bool(item["verify_tls"]),''',
    '''        if credential["type"] not in {"proxmox_api", "username_password"}:\n            raise ValueError("configured credential is not supported by Proxmox Manager")\n        return ProxmoxApiClient(\n            str(item["endpoint"]),\n            credential["username"],\n            credential["secret"],\n            credential_type=credential["type"],\n            verify_tls=bool(item["verify_tls"]),''',
)

# Tests: explicit ACL, generic username/password, secret-preserving edit, and Proxmox password acceptance.
hosts_tests = "backend/tests/test_hosts_manager.py"
text = read(hosts_tests)
marker = "\ndef test_enrollment_token_is_hashed_one_time_bounded_and_hostname_scoped"
assert marker in text
new_test = '''\n\ndef test_generic_credentials_are_module_scoped_and_secret_preserving(tmp_path: Path):\n    store = service(tmp_path)\n    credential = store.save_credential(\n        CredentialInput(\n            name="PVE Login", type=CredentialType.username_password, username="automation@pve",\n            secret="s3cret", shared_with=["proxmox-manager"],\n        ),\n        "admin",\n    )\n    assert credential["shared_with"] == ["proxmox-manager"]\n    assert credential["secret_configured"] is True\n    with pytest.raises(PermissionError, match="not shared"):\n        store.verified_credential(credential["id"], module_id="ansible-controller", purpose="ssh")\n    assert store.verified_credential(credential["id"], module_id="proxmox-manager", purpose="proxmox-api")["secret"] == "s3cret"\n\n    updated = store.save_credential(\n        CredentialInput(\n            name="PVE Login", type=CredentialType.username_password, username="automation@pve",\n            secret="", shared_with=["proxmox-manager", "dcst"],\n        ),\n        "admin", credential["id"],\n    )\n    assert updated["shared_with"] == ["proxmox-manager", "dcst"]\n    assert store.verified_credential(credential["id"], module_id="proxmox-manager", purpose="proxmox-api")["secret"] == "s3cret"\n'''
write(hosts_tests, text.replace(marker, new_test + marker, 1))

proxmox_tests = "backend/tests/test_proxmox_manager.py"
text = read(proxmox_tests)
marker = "\ndef test_sync_uses_one_shared_host_identity_and_disables_missing"
assert marker in text
new_test = '''\n\ndef test_connection_accepts_shared_username_password_credential(monkeypatch, tmp_path):\n    registry = FakeHostRegistry()\n    registry._credentials = [{\n        "id": "proxmox-credential", "name": "PVE Login", "type": "username_password",\n        "username": "automation@pve", "secret_configured": True, "active": True,\n        "shared_with": ["proxmox-manager"],\n    }]\n    patch_registry(monkeypatch, registry)\n    manager = ProxmoxManagerService(tmp_path / "proxmox.sqlite3")\n    saved = manager.save_connection(connection_input(), "admin")\n    assert saved["credential"]["type"] == "username_password"\n'''
write(proxmox_tests, text.replace(marker, new_test + marker, 1))

# Add translations without reformatting the large locale files.
append_before_closing_brace("frontend/src/locales/en-US.json", [
    ("hosts.credentials.type.username_password", "Username and password"),
    ("hosts.credentials.type.api_token", "API token"),
    ("hosts.credentials.type.generic_secret", "Generic secret"),
    ("hosts.credentials.type.proxmox_api", "Proxmox API token"),
    ("hosts.credentials.type.redfish", "Redfish login"),
    ("hosts.credentials.type.ipmi", "IPMI login"),
    ("hosts.credentials.type.wol", "Wake-on-LAN"),
    ("hosts.credentials.type.git_private_key", "Git private key"),
    ("hosts.credentials.sharedWith", "Shared with modules"),
    ("hosts.credentials.sharedWithHint", "Comma-separated module IDs. Only listed backend modules may decrypt this credential."),
    ("hosts.credentials.notShared", "Not shared"),
    ("hosts.credentials.usernameHint", "Login/user name where the credential type requires one."),
    ("hosts.credentials.keepSecret", "Leave empty while editing to keep the existing secret."),
])
append_before_closing_brace("frontend/src/locales/pl-PL.json", [
    ("hosts.credentials.type.username_password", "Login i hasło"),
    ("hosts.credentials.type.api_token", "Token API"),
    ("hosts.credentials.type.generic_secret", "Sekret ogólny"),
    ("hosts.credentials.type.proxmox_api", "Token API Proxmox"),
    ("hosts.credentials.type.redfish", "Login Redfish"),
    ("hosts.credentials.type.ipmi", "Login IPMI"),
    ("hosts.credentials.type.wol", "Wake-on-LAN"),
    ("hosts.credentials.type.git_private_key", "Klucz prywatny Git"),
    ("hosts.credentials.sharedWith", "Udostępnione modułom"),
    ("hosts.credentials.sharedWithHint", "Identyfikatory modułów rozdzielone przecinkami. Tylko wskazane moduły backendu mogą odszyfrować to poświadczenie."),
    ("hosts.credentials.notShared", "Nieudostępnione"),
    ("hosts.credentials.usernameHint", "Login/nazwa użytkownika, jeśli wymaga tego typ poświadczenia."),
    ("hosts.credentials.keepSecret", "Podczas edycji pozostaw puste, aby zachować obecny sekret."),
])

# Document central sharing semantics.
hosts_doc = "HOSTS_MANAGER.md"
text = read(hosts_doc)
if "## Shared credentials" not in text:
    text += '''\n\n## Shared credentials\n\nHosts Manager is the central encrypted credential vault for infrastructure modules. Credentials may be SSH passwords/keys, privilege passwords, generic username/password pairs, API tokens, generic secrets, Proxmox API tokens, Redfish/IPMI credentials, Wake-on-LAN data, or Git private keys.\n\nEach credential has an explicit `shared_with` module allowlist. The browser only receives metadata and never secret material. A backend module must identify itself and its purpose when requesting a credential; Hosts Manager rejects access unless that module is present in the credential allowlist and records the use in the operation audit trail. Existing credentials are migrated with compatibility-safe defaults (for example SSH → Hosts Manager/Ansible and Proxmox API → Proxmox Manager).\n\nProxmox Manager accepts either a `proxmox_api` token (`user@realm!tokenid` + token secret) or a `username_password` credential (`user@realm` + password) that is shared with `proxmox-manager`. Password authentication is exchanged server-side for a Proxmox ticket and CSRF token; the password is never copied into the Proxmox Manager database.\n'''
    write(hosts_doc, text)

# Remove this one-shot patch machinery from the final branch diff.
(ROOT / ".github/scripts/apply_shared_credentials.py").unlink(missing_ok=True)
(ROOT / ".github/workflows/apply-shared-credentials.yml").unlink(missing_ok=True)
