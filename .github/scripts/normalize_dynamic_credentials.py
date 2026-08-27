from pathlib import Path
import subprocess

BASE_SHA = "244613630b59ae496962ac4c88014a36bc29258b"
APP_PATH = "frontend/src/features/modules/hosts/HostsManagerApp.tsx"
TEST_PATH = "frontend/src/features/modules/hosts/HostsManagerApp.test.tsx"

app = Path(APP_PATH)
text = app.read_text()
text = text.replace(
    'const profiles: Record<CredentialType, CredentialFieldProfile> = {',
    'const profiles: Partial<Record<CredentialType, CredentialFieldProfile>> = {',
)
text = text.replace('if (!window.confirm(t("hosts.credentials.deleteConfirm"))) return;', 'if (!(await confirmDialog(t("hosts.credentials.deleteConfirm"), t))) return;')
text = text.replace('const profile = profiles[type];', 'const profile = profiles[type] || {};')
app.write_text(text)

source = subprocess.check_output(["git", "show", f"{BASE_SHA}:{TEST_PATH}"], text=True)
source = source.replace(
    "hostsManagerCredentials: vi.fn(),",
    "hostsManagerCredentials: vi.fn(), saveHostsManagerCredential: vi.fn(), deleteHostsManagerCredential: vi.fn(),",
    1,
)
marker = '  it("keeps APMID selectors for enrollment without duplicating the management form", async () => {'
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
if marker not in source:
    raise SystemExit("test insertion marker not found")
source = source.replace(marker, new_test + marker, 1)
Path(TEST_PATH).write_text(source)
