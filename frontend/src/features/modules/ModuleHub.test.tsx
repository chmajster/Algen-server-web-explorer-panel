import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type ModuleSummary, type PackageModule } from "../../api";
import { ModuleHub } from "./ModuleHub";

vi.mock("../../api", () => ({ api: { apps: vi.fn(), modules: vi.fn(), appPlan: vi.fn(), appAction: vi.fn() } }));

const samba: PackageModule = {
  id: "samba",
  manifest: {
    id: "samba", name: "Samba", description: "SMB/CIFS file sharing", long_description: "Manage Samba shares", category: "file_sharing", version: "1.0.0", maintainer: "WebNAS", homepage: "https://www.samba.org/", icon: "share-2", screenshots: [], license: "GPL-3.0-or-later",
    supported_distributions: ["debian"], supported_architectures: ["x86_64"], apt_packages: ["samba", "smbclient", "cifs-utils"], dnf_packages: ["samba", "samba-client", "cifs-utils"], systemd_services: ["smbd", "nmbd"], ports: ["445/tcp"], dependencies: [], conflicts: [], permissions: ["systemd"], config_paths: ["/etc/samba/smb.conf"], data_paths: ["/var/lib/samba"], backup_paths: ["/etc/samba"], proxmox_safe: true, requires_reboot: false, requires_root: true, configurable: true, removable: true, changelog: [],
  },
  state: { installed: false, installed_version: null, available_version: "1.0.0", update_available: false, requires_reboot: false },
  services: { smbd: "inactive", nmbd: "inactive" },
  status: "available",
  compatible: true,
  blocked_by_proxmox: false,
  distribution: { id: "debian", name: "Debian", architecture: "x86_64", package_manager: "apt-get" },
  jobs: [],
};

const proxmoxManager: PackageModule = {
  ...samba,
  id: "proxmox-manager",
  manifest: {
    ...samba.manifest,
    id: "proxmox-manager",
    name: "Proxmox Manager",
    description: "Proxmox VE API provider",
    apt_packages: [],
    dnf_packages: [],
    systemd_services: [],
    dependencies: ["hosts-manager"],
    capabilities: { install: true, update: true, uninstall: true, configure: true, service_control: false, reload: false, logs: false, diagnostics: false, backups: true, import_export: false, healthcheck: false, resources: ["connections", "virtual-machines", "containers", "shared-hosts"], actions: ["test", "sync", "start", "stop", "shutdown", "reboot"] },
  },
  services: {},
};

describe("ModuleHub", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.apps).mockResolvedValue([samba]);
    vi.mocked(api.modules).mockRejectedValue(new Error("runtime status unavailable"));
    vi.mocked(api.appPlan).mockReturnValue(new Promise(() => {}));
  });

  it("keeps Samba in the shared module catalog when live status is unavailable", async () => {
    const open = vi.fn();
    render(<ModuleHub t={(key) => key} toast={vi.fn()} onOpen={open} />);

    expect(await screen.findByText("Samba")).toBeInTheDocument();
    expect(screen.getByText("SMB/CIFS file sharing")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "managed.openModule" }));
    expect(open).toHaveBeenCalledWith("samba");
  });

  it("renders the fast catalog before runtime status loading finishes", async () => {
    let resolveRuntime!: (value: ModuleSummary[]) => void;
    vi.mocked(api.modules).mockReturnValue(new Promise((resolve) => { resolveRuntime = resolve; }));

    render(<ModuleHub t={(key) => key} toast={vi.fn()} onOpen={vi.fn()} />);

    expect(await screen.findByText("Samba")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "action.refresh" }).querySelector(".spin")).toBeInTheDocument();

    await act(async () => { resolveRuntime([]); });
    expect(screen.getByRole("button", { name: "action.refresh" }).querySelector(".spin")).not.toBeInTheDocument();
  });

  it("offers Proxmox Manager installation to users with module install permission", async () => {
    vi.mocked(api.apps).mockResolvedValue([proxmoxManager]);

    render(<ModuleHub permissions={["modules.install"]} t={(key) => key} toast={vi.fn()} onOpen={vi.fn()} />);

    expect(await screen.findByText("Proxmox Manager")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "store.install" }));

    await waitFor(() => expect(api.appPlan).toHaveBeenCalledWith("proxmox-manager", "install", false));
    expect(screen.getByText("store.install: Proxmox Manager")).toBeInTheDocument();
  });
});
