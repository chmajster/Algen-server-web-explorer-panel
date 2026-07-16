import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type PackageModule } from "../../api";
import { ModuleHub } from "./ModuleHub";

vi.mock("../../api", () => ({ api: { apps: vi.fn(), modules: vi.fn() } }));

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

describe("ModuleHub", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.apps).mockResolvedValue([samba]);
    vi.mocked(api.modules).mockRejectedValue(new Error("runtime status unavailable"));
  });

  it("keeps Samba in the shared module catalog when live status is unavailable", async () => {
    const open = vi.fn();
    render(<ModuleHub t={(key) => key} toast={vi.fn()} onOpen={open} />);

    expect(await screen.findByText("Samba")).toBeInTheDocument();
    expect(screen.getByText("SMB/CIFS file sharing")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "managed.openModule" }));
    expect(open).toHaveBeenCalledWith("samba");
  });
});
