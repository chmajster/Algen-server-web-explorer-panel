from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"marker not found: {label}")
    return text.replace(old, new, 1)


root = Path('.')
app_path = root / 'frontend/src/features/modules/hosts/HostsManagerApp.tsx'
text = app_path.read_text()

text = replace_once(
    text,
    'import "./hosts-group-picker.css";\nimport "./hosts-installer.css";',
    'import "./hosts-group-picker.css";\nimport "./hosts-credential-module-select.css";\nimport "./hosts-installer.css";',
    'hosts css import',
)

component = r'''type CredentialShareModule = { id: string; name: string };

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
    return [...known.values()].sort((left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id));
  }, [modules, selected]);
  const optionIds = options.map((item) => item.id);
  const allSelected = optionIds.length > 0 && optionIds.every((id) => selected.includes(id));
  const summary = loading
    ? t("hosts.credentials.loadingModules")
    : allSelected
      ? t("hosts.credentials.allModules")
      : selected.length === 0
        ? t("hosts.credentials.noModules")
        : `${selected.length}/${options.length} ${t("hosts.credentials.modulesSelected")}`;

  function toggle(id: string, checked: boolean) {
    onChange(checked ? [...new Set([...selected, id])] : selected.filter((value) => value !== id));
  }

  return <div className="hosts-credential-module-select" ref={rootRef}>
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
    {open && <div className="hosts-credential-module-menu">
      <div className="hosts-credential-module-actions">
        <button type="button" disabled={!optionIds.length} onClick={() => onChange(optionIds)}>{t("hosts.credentials.selectAllModules")}</button>
        <button type="button" disabled={!selected.length} onClick={() => onChange([])}>{t("hosts.credentials.clearModules")}</button>
      </div>
      <div className="hosts-credential-module-options" role="group" aria-label={t("hosts.credentials.sharedWith")}>
        {options.map((item) => <label key={item.id} className="hosts-credential-module-option">
          <input
            type="checkbox"
            aria-label={`${item.name} (${item.id})`}
            checked={selected.includes(item.id)}
            onChange={(event) => toggle(item.id, event.target.checked)}
          />
          <span><strong>{item.name}</strong><small>{item.id}</small></span>
        </label>)}
        {!options.length && <div className="hosts-credential-module-empty">{loading ? t("hosts.credentials.loadingModules") : t("hosts.credentials.noModulesAvailable")}</div>}
      </div>
    </div>}
  </div>;
}

'''
text = replace_once(text, 'function Credentials({', component + 'function Credentials({', 'credential component insertion')

old_defaults = '''  const defaultShares: Partial<Record<CredentialType, string[]>> = {\n    ssh_password: ["hosts-manager", "ansible-controller"],\n    ssh_private_key: ["hosts-manager", "ansible-controller"],\n    become_password: ["hosts-manager", "ansible-controller"],\n    git_private_key: ["hosts-manager", "ansible-controller"],\n    proxmox_api: ["proxmox-manager"],\n    redfish: ["hosts-manager"], ipmi: ["hosts-manager"], wol: ["hosts-manager"],\n    username_password: ["hosts-manager"], api_token: ["hosts-manager"], generic_secret: ["hosts-manager"],\n  };\n'''
text = replace_once(text, old_defaults, '', 'default credential shares')

old_state = '''  const [description, setDescription] = useState("");\n  const [secret, setSecret] = useState("");\n  const [passphrase, setPassphrase] = useState("");\n  const [sharedWith, setSharedWith] = useState("");\n\n  function setCredentialType(next: CredentialType) {\n    setType(next);\n    setUsername("");\n    setSecret("");\n    setPassphrase("");\n    if (!editing) setSharedWith((defaultShares[next] || []).join(", "));\n  }\n'''
new_state = '''  const [description, setDescription] = useState("");\n  const [secret, setSecret] = useState("");\n  const [passphrase, setPassphrase] = useState("");\n  const [sharedWith, setSharedWith] = useState<string[]>([]);\n  const [shareModules, setShareModules] = useState<CredentialShareModule[]>([]);\n  const [shareModulesLoading, setShareModulesLoading] = useState(true);\n  const [shareSelectionInitialized, setShareSelectionInitialized] = useState(false);\n\n  useEffect(() => {\n    let active = true;\n    setShareModulesLoading(true);\n    void api.modules()\n      .then((modules) => {\n        if (!active) return;\n        setShareModules(modules\n          .filter((module) => Boolean(module.id))\n          .map((module) => ({ id: module.id, name: module.manifest.name || module.id }))\n          .sort((left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id)));\n      })\n      .catch((error: unknown) => {\n        if (active) toast(hostsManagerError(error, t), "error", "admin", "hosts-manager");\n      })\n      .finally(() => {\n        if (active) setShareModulesLoading(false);\n      });\n    return () => { active = false; };\n  }, [t, toast]);\n\n  const allShareModuleIds = useMemo(() => shareModules.map((module) => module.id), [shareModules]);\n  useEffect(() => {\n    if (!open || editing || shareSelectionInitialized || shareModulesLoading) return;\n    setSharedWith(allShareModuleIds);\n    setShareSelectionInitialized(true);\n  }, [allShareModuleIds, editing, open, shareModulesLoading, shareSelectionInitialized]);\n\n  function setCredentialType(next: CredentialType) {\n    setType(next);\n    setUsername("");\n    setSecret("");\n    setPassphrase("");\n  }\n'''
text = replace_once(text, old_state, new_state, 'credential sharing state')

old_editor = '''    setSecret("");\n    setPassphrase("");\n    setSharedWith((item?.shared_with || defaultShares[nextType] || []).join(", "));\n    setOpen(true);\n  }\n\n  async function save(event: React.FormEvent) {\n    event.preventDefault();\n    try {\n      const modules = [...new Set(sharedWith.split(",").map((value) => value.trim()).filter(Boolean))];\n      await api.saveHostsManagerCredential({\n        name, type, username, environment_id: environmentId || null, secret, passphrase, description,\n        shared_with: modules, confirm: true,\n'''
new_editor = '''    setSecret("");\n    setPassphrase("");\n    setSharedWith(item ? [...(item.shared_with || [])] : (shareModulesLoading ? [] : allShareModuleIds));\n    setShareSelectionInitialized(Boolean(item) || !shareModulesLoading);\n    setOpen(true);\n  }\n\n  async function save(event: React.FormEvent) {\n    event.preventDefault();\n    try {\n      await api.saveHostsManagerCredential({\n        name, type, username, environment_id: environmentId || null, secret, passphrase, description,\n        shared_with: [...new Set(sharedWith)], confirm: true,\n'''
text = replace_once(text, old_editor, new_editor, 'credential editor and save')

old_field = '''        <label>{t("hosts.credentials.sharedWith")}<input value={sharedWith} onChange={(event) => setSharedWith(event.target.value)} placeholder={(defaultShares[type] || []).join(", ")} /><small>{t("hosts.credentials.sharedWithHint")}</small></label>'''
new_field = '''        <div className="hosts-credential-share-field"><span className="hosts-credential-share-label">{t("hosts.credentials.sharedWith")}</span><CredentialModuleSelect modules={shareModules} selected={sharedWith} loading={shareModulesLoading} onChange={setSharedWith} t={t} /><small>{t("hosts.credentials.sharedWithHint")}</small></div>'''
text = replace_once(text, old_field, new_field, 'credential module field')
app_path.write_text(text)

css_path = root / 'frontend/src/features/modules/hosts/hosts-credential-module-select.css'
css_path.write_text(r'''.hosts-credential-share-field {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 0.375rem;
}

.hosts-credential-share-label {
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
}

.hosts-credential-module-select {
  position: relative;
  min-width: 0;
}

.hosts-credential-module-trigger {
  width: 100%;
  min-height: var(--control-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);
  padding: var(--control-padding-y) var(--control-padding-x);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-control);
  color: var(--text-primary);
  background: var(--surface-elevated);
  text-align: left;
}

.hosts-credential-module-trigger:hover,
.hosts-credential-module-trigger[aria-expanded="true"] {
  border-color: var(--accent);
  background: var(--surface-hover);
}

.hosts-credential-module-trigger > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hosts-credential-module-trigger svg {
  width: var(--icon-size);
  height: var(--icon-size);
  flex: 0 0 auto;
  transition: transform 120ms ease;
}

.hosts-credential-module-trigger[aria-expanded="true"] svg {
  transform: rotate(180deg);
}

.hosts-credential-module-menu {
  position: absolute;
  z-index: 50;
  top: calc(100% + var(--spacing-xs));
  right: 0;
  left: 0;
  min-width: min(24rem, 82vw);
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-elevated);
  box-shadow: var(--shadow-menu);
}

.hosts-credential-module-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm);
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-secondary);
}

.hosts-credential-module-actions button {
  min-height: 1.875rem;
  padding: 0 var(--spacing-md);
}

.hosts-credential-module-options {
  max-height: 16rem;
  overflow: auto;
  padding: var(--spacing-xs);
}

.hosts-credential-module-option {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-control);
  cursor: pointer;
}

.hosts-credential-module-option:hover {
  background: var(--surface-hover);
}

.hosts-credential-module-option input {
  width: 1rem;
  height: 1rem;
  margin: 0;
  accent-color: var(--accent);
}

.hosts-credential-module-option span {
  min-width: 0;
  display: grid;
}

.hosts-credential-module-option strong,
.hosts-credential-module-option small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hosts-credential-module-option small,
.hosts-credential-share-field > small {
  color: var(--text-muted);
  font-size: var(--font-size-xs);
}

.hosts-credential-module-empty {
  padding: var(--spacing-lg);
  color: var(--text-muted);
  text-align: center;
}
''')

for locale, old_hint, replacements in [
    (
        'pl-PL.json',
        '  "hosts.credentials.sharedWithHint": "Identyfikatory modułów rozdzielone przecinkami. Tylko wskazane moduły backendu mogą odszyfrować to poświadczenie.",',
        '''  "hosts.credentials.sharedWithHint": "Wybierz moduły, które mogą używać tego poświadczenia. Nowe poświadczenie jest domyślnie udostępnione wszystkim dostępnym modułom.",\n  "hosts.credentials.allModules": "Wszystkie moduły",\n  "hosts.credentials.noModules": "Nie wybrano modułów",\n  "hosts.credentials.modulesSelected": "wybranych",\n  "hosts.credentials.selectAllModules": "Zaznacz wszystkie",\n  "hosts.credentials.clearModules": "Odznacz wszystkie",\n  "hosts.credentials.loadingModules": "Ładowanie modułów…",\n  "hosts.credentials.noModulesAvailable": "Brak dostępnych modułów",''',
    ),
    (
        'en-US.json',
        '  "hosts.credentials.sharedWithHint": "Comma-separated module IDs. Only listed backend modules may decrypt this credential.",',
        '''  "hosts.credentials.sharedWithHint": "Choose which modules may use this credential. New credentials are shared with all available modules by default.",\n  "hosts.credentials.allModules": "All modules",\n  "hosts.credentials.noModules": "No modules selected",\n  "hosts.credentials.modulesSelected": "selected",\n  "hosts.credentials.selectAllModules": "Select all",\n  "hosts.credentials.clearModules": "Clear all",\n  "hosts.credentials.loadingModules": "Loading modules…",\n  "hosts.credentials.noModulesAvailable": "No modules available",''',
    ),
]:
    path = root / 'frontend/src/locales' / locale
    value = path.read_text()
    value = replace_once(value, old_hint, replacements, f'{locale} credential sharing translations')
    path.write_text(value)

# Regression coverage: mock module inventory and verify default-all + deselection payload.
test_path = root / 'frontend/src/features/modules/hosts/HostsManagerApp.test.tsx'
test = test_path.read_text()
test = replace_once(
    test,
    'hostsManagerBackups: vi.fn(), hostsManagerCapabilities: vi.fn(), saveHostsManagerHost: vi.fn(),',
    'hostsManagerBackups: vi.fn(), hostsManagerCapabilities: vi.fn(), modules: vi.fn(), saveHostsManagerHost: vi.fn(),',
    'mock modules API',
)
test = replace_once(
    test,
    '    vi.mocked(api.hostsManagerCapabilities).mockResolvedValue([]);',
    '''    vi.mocked(api.hostsManagerCapabilities).mockResolvedValue([]);\n    vi.mocked(api.modules).mockResolvedValue([\n      { id: "hosts-manager", manifest: { name: "Hosts Manager" } },\n      { id: "proxmox-manager", manifest: { name: "Proxmox Manager" } },\n      { id: "dcst", manifest: { name: "DCST" } },\n    ] as never);''',
    'modules fixture',
)
marker = '''  it("keeps APMID selectors for enrollment without duplicating the management form", async () => {'''
new_test = r'''  it("selects every module by default and saves the checked credential shares", async () => {
    vi.mocked(api.saveHostsManagerCredential).mockResolvedValue({} as never);
    render(<HostsManagerApp permissions={[...permissions, "hosts-manager.credentials.view", "hosts-manager.credentials.manage"]} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.credentials/ }));
    fireEvent.click(await screen.findByRole("button", { name: "hosts.credentials.add" }));

    const moduleSelect = await screen.findByRole("button", { name: "hosts.credentials.sharedWith" });
    await waitFor(() => expect(moduleSelect).toHaveTextContent("hosts.credentials.allModules"));
    fireEvent.click(moduleSelect);

    const hostsModule = screen.getByRole("checkbox", { name: "Hosts Manager (hosts-manager)" });
    const proxmoxModule = screen.getByRole("checkbox", { name: "Proxmox Manager (proxmox-manager)" });
    const dcstModule = screen.getByRole("checkbox", { name: "DCST (dcst)" });
    expect(hostsModule).toBeChecked();
    expect(proxmoxModule).toBeChecked();
    expect(dcstModule).toBeChecked();

    fireEvent.click(proxmoxModule);
    fireEvent.change(screen.getByLabelText("common.name"), { target: { value: "Shared credential" } });
    fireEvent.change(screen.getByLabelText("hosts.credentials.field.login"), { target: { value: "automation" } });
    fireEvent.change(screen.getByLabelText("hosts.credentials.field.password"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));

    await waitFor(() => expect(api.saveHostsManagerCredential).toHaveBeenCalled());
    const payload = vi.mocked(api.saveHostsManagerCredential).mock.calls[0][0];
    expect(payload.shared_with).toEqual(["dcst", "hosts-manager"]);
  });

'''
test = replace_once(test, marker, new_test + marker, 'credential sharing regression test')
test_path.write_text(test)
