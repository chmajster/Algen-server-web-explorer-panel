import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type LocalDisk } from "../../api";
import { DirectoryTree } from "./DirectoryTree";

vi.mock("../../api", () => ({ api: { tree: vi.fn() } }));

const t = (key: string) => key;
const disks: LocalDisk[] = [
  { device: "/dev/sdb1", mount_point: "/mnt/storage", name: "storage", fs_type: "ext4", read_only: false, removable: false, total: 100, used: 50, free: 50 },
  { device: "/dev/sdc1", mount_point: "/media/archive", name: "archive", fs_type: "xfs", read_only: true, removable: false, total: 200, used: 100, free: 100 },
];

describe("local disks in directory tree", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.mocked(api.tree).mockResolvedValue({ path: "/home/alice", items: [] });
  });

  it("renders a separate section with multiple disks and read-only status", () => {
    render(<DirectoryTree currentPath="/home/alice" homePath="/home/alice" localDisks={disks} mounts={[]} t={t} onOpen={vi.fn()} onDropItems={vi.fn()} />);

    expect(screen.getByText("files.localDisks")).toBeInTheDocument();
    expect(screen.getByText("storage")).toBeInTheDocument();
    expect(screen.getByText("archive")).toBeInTheDocument();
    expect(screen.getByText(/xfs.*files.readOnly/)).toBeInTheDocument();
    expect(screen.queryByText("files.networkResources")).not.toBeInTheDocument();
  });

  it("does not render the section when no disks are visible", () => {
    render(<DirectoryTree currentPath="/home/alice" homePath="/home/alice" localDisks={[]} mounts={[]} t={t} onOpen={vi.fn()} onDropItems={vi.fn()} />);

    expect(screen.queryByText("files.localDisks")).not.toBeInTheDocument();
  });

  it("renders removable filesystems in a separate USB section", () => {
    const usbDisk: LocalDisk = { device: "/dev/sdd1", mount_point: "/media/webnas-usb/BACKUP-1234", name: "BACKUP", fs_type: "exfat", read_only: false, removable: true, total: 300, used: 10, free: 290 };

    render(<DirectoryTree currentPath="/home/alice" homePath="/home/alice" localDisks={[usbDisk]} mounts={[]} t={t} onOpen={vi.fn()} onDropItems={vi.fn()} />);

    expect(screen.getByText("files.usbDevices")).toBeInTheDocument();
    expect(screen.getByText("BACKUP")).toBeInTheDocument();
    expect(screen.queryByText("files.localDisks")).not.toBeInTheDocument();
  });

  it("opens a local disk and blocks drops on a read-only disk", () => {
    const onOpen = vi.fn();
    const onDrop = vi.fn();
    render(<DirectoryTree currentPath="/home/alice" homePath="/home/alice" localDisks={disks} mounts={[]} t={t} onOpen={onOpen} onDropItems={onDrop} />);

    const archive = screen.getByRole("button", { name: /archive/ });
    fireEvent.click(archive);
    fireEvent.drop(archive, { dataTransfer: { getData: () => "/home/alice/file.txt" } });

    expect(onOpen).toHaveBeenCalledWith("/media/archive");
    expect(onDrop).not.toHaveBeenCalled();
  });
});
