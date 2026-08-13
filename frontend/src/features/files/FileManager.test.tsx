import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { FileManager, isExternalFileTransfer } from "./FileManager";
import { settingsFixture } from "../../test/settings";

vi.mock("../../api", () => ({
  ApiError: class ApiError extends Error {},
  downloadUrl: (path: string) => `/download?path=${path}`,
  api: {
    list: vi.fn(), tree: vi.fn(), mounts: vi.fn(), mountRoots: vi.fn(), localDisks: vi.fn(), appConfig: vi.fn(), stat: vi.fn(),
    copy: vi.fn(), move: vi.fn(), mkdir: vi.fn(), create: vi.fn(), rename: vi.fn(), delete: vi.fn(), upload: vi.fn(), preview: vi.fn(),
    readText: vi.fn(), writeText: vi.fn(), chmod: vi.fn(), chown: vi.fn()
  }
}));

const files = [
  { name: "Documents", path: "/home/test/Documents", type: "directory", is_dir: true, size: 0, owner: "test", group: "users", mode: "0755", permissions: "drwxr-xr-x", modified: 1, mtime: 1, mime: "inode/directory", can_read: true, can_write: true, can_delete: true, can_rename: true, is_symlink: false },
  { name: "alpha.txt", path: "/home/test/alpha.txt", type: "text", is_dir: false, size: 20, owner: "test", group: "users", mode: "0644", permissions: "-rw-r--r--", modified: 2, mtime: 2, mime: "text/plain", can_read: true, can_write: true, can_delete: true, can_rename: true, is_symlink: false }
];

const labels: Record<string, string> = { "status.items": "{count} items", "status.selected": "{count} selected", "status.operations": "{count} operations" };
const t = (key: string) => labels[key] || key;

function dragTransfer(files: File[] = [], types: string[] = files.length ? ["Files"] : []) {
  return {
    files,
    types,
    dropEffect: "none",
    effectAllowed: "all",
    getData: vi.fn(() => ""),
    setData: vi.fn(),
    setDragImage: vi.fn(),
  } as unknown as DataTransfer;
}

describe("file manager behavior", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.mocked(api.list).mockResolvedValue({ path: "/home/test", current_path: "/home/test", parent_path: "/home", items: files, page: 1, page_size: 100, total_items: 2, total_pages: 1, sort: "name", direction: "asc", can_write: true, can_upload: true, can_delete: true });
    vi.mocked(api.tree).mockResolvedValue({ path: "/home/test", items: [files[0]] });
    vi.mocked(api.mounts).mockResolvedValue([]);
    vi.mocked(api.mountRoots).mockResolvedValue([]);
    vi.mocked(api.localDisks).mockResolvedValue([]);
    vi.mocked(api.appConfig).mockResolvedValue({ shares: [] });
    vi.mocked(api.readText).mockResolvedValue({ path: "/home/test/alpha.txt", content: "alpha", encoding: "utf-8", size: 5, mtime_ns: "100" });
    vi.mocked(api.writeText).mockResolvedValue({ path: "/home/test/alpha.txt", encoding: "utf-8", size: 5, mtime_ns: "200", ok: true });
  });

  it("selects multiple items and changes the persisted view", async () => {
    render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("alpha.txt");
    fireEvent.click(screen.getByLabelText("action.select Documents"));
    fireEvent.click(screen.getByLabelText("action.select alpha.txt"));
    expect(screen.getByText(/2 selected/)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("view.medium"));
    expect(localStorage.getItem("webnas_file_explorer_view")).toBe("medium");
  });

  it("sorts from a column header and opens the context menu", async () => {
    const { container } = render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("alpha.txt");
    fireEvent.click(screen.getByRole("columnheader", { name: /column.size/ }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith("/home/test", expect.objectContaining({ sort: "size" })));
    const row = container.querySelectorAll(".file-row")[1];
    fireEvent.contextMenu(row, { clientX: 40, clientY: 40 });
    expect(screen.getByRole("menuitem", { name: "action.open" })).toBeInTheDocument();
  });

  it("loads child directories lazily", async () => {
    render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await waitFor(() => expect(api.tree).toHaveBeenCalledWith("/home/test"));
    expect(await screen.findAllByText("Documents")).not.toHaveLength(0);
  });

  it("expands a tree folder after a drag hover delay", async () => {
    vi.mocked(api.tree).mockImplementation(async (path?: string) => ({ path: path || "/home/test", items: path === "/home/test" ? [files[0]] : [] }));
    const { container } = render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("alpha.txt");
    const treeRow = [...container.querySelectorAll<HTMLButtonElement>(".tree-row")].find((element) => element.textContent?.includes("Documents"));
    expect(treeRow).toBeDefined();
    fireEvent.dragEnter(treeRow!, { dataTransfer: { getData: () => "/home/test/alpha.txt" } });
    await waitFor(() => expect(api.tree).toHaveBeenCalledWith("/home/test/Documents"), { timeout: 1200 });
  });

  it("uses the home folder instead of an inaccessible filesystem root", async () => {
    localStorage.setItem("webnas_file_explorer_path", "/");
    render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);

    await waitFor(() => expect(api.list).toHaveBeenCalledWith("/home/test", expect.any(Object)));
    expect(screen.getAllByTitle("files.goHome").length).toBeGreaterThan(0);
  });

  it("navigates to home from a nested directory", async () => {
    render(<FileManager homePath="/home/test" initialPath="/home/test/Documents" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await waitFor(() => expect(api.list).toHaveBeenCalledWith("/home/test/Documents", expect.any(Object)));

    fireEvent.click(screen.getAllByTitle("files.goHome")[0]);
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith("/home/test", expect.any(Object)));
  });

  it("does not send a create request when the name already exists", async () => {
    const toast = vi.fn();
    render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={toast} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("alpha.txt");

    fireEvent.click(screen.getByTitle("action.newFolder"));
    fireEvent.change(screen.getByLabelText("files.folderName"), { target: { value: "Documents" } });
    fireEvent.click(screen.getByRole("button", { name: "action.create" }));

    expect(api.mkdir).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith("files.alreadyExists", "error");
  });

  it("disables write actions in a read-only destination", async () => {
    vi.mocked(api.list).mockResolvedValue({ path: "/home/test", current_path: "/home/test", parent_path: "/home", items: [], page: 1, page_size: 100, total_items: 0, total_pages: 1, sort: "name", direction: "asc", can_write: false, can_upload: false, can_delete: false });
    const { container } = render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await waitFor(() => expect(api.list).toHaveBeenCalled());

    fireEvent.contextMenu(container.querySelector(".file-content")!);

    expect(screen.getByRole("menuitem", { name: "action.newFolder" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "action.newFile" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "action.upload" })).toBeDisabled();
  });

  it("loads local disks without blocking the explorer when the API fails", async () => {
    vi.mocked(api.localDisks).mockRejectedValue(new Error("disks unavailable"));

    render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);

    await screen.findByText("alpha.txt");
    expect(api.localDisks).toHaveBeenCalledWith();
    expect(screen.queryByText("disks unavailable")).not.toBeInTheDocument();
  });

  it("returns home when the active managed USB filesystem disappears", async () => {
    const toast = vi.fn();
    vi.mocked(api.localDisks).mockResolvedValue([]);

    render(<FileManager homePath="/home/test" initialPath="/media/webnas-usb/BACKUP-1234/Films" tasks={[]} isAdmin={false} t={t} toast={toast} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);

    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith("/home/test", expect.any(Object)));
    expect(toast).toHaveBeenCalledWith("files.usbUnavailable", "error");
  });

  it("refreshes removable USB devices when the page becomes visible", async () => {
    const usbDisk = { device: "/dev/sdd1", mount_point: "/media/webnas-usb/BACKUP-1234", name: "BACKUP", fs_type: "exfat", read_only: false, removable: true, total: 300, used: 10, free: 290 };
    vi.mocked(api.localDisks).mockResolvedValueOnce([]).mockResolvedValue([usbDisk]);

    render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await waitFor(() => expect(api.localDisks).toHaveBeenCalledTimes(1));

    fireEvent(document, new Event("visibilitychange"));

    expect(await screen.findByText("BACKUP")).toBeInTheDocument();
    expect(screen.getByText("files.usbDevices")).toBeInTheDocument();
  });

  it("uses a local disk as the breadcrumb root", async () => {
    vi.mocked(api.localDisks).mockResolvedValue([
      { device: "/dev/sdb1", mount_point: "/mnt/storage", name: "storage", fs_type: "ext4", read_only: false, removable: false, total: 100, used: 50, free: 50 },
    ]);
    vi.mocked(api.list).mockResolvedValue({ path: "/mnt/storage/Films", current_path: "/mnt/storage/Films", parent_path: "/mnt/storage", items: [], page: 1, page_size: 100, total_items: 0, total_pages: 1, sort: "name", direction: "asc", can_write: true, can_upload: true, can_delete: true });

    const { container } = render(<FileManager homePath="/home/test" initialPath="/mnt/storage/Films" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);

    await waitFor(() => expect(container.querySelector(".breadcrumbs")?.textContent).toContain("storageFilms"));
    expect(container.querySelector(".breadcrumbs")?.textContent).not.toContain("files.home");
  });

  it("applies server-backed file manager preferences", async () => {
    const { container } = render(<FileManager homePath="/home/test" settings={settingsFixture({ file_default_view: "large", file_compact_rows: true, file_show_hidden: true, file_page_size: 25, file_default_sort: "modified", file_sort_direction: "desc" })} tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);

    await waitFor(() => expect(api.list).toHaveBeenCalledWith("/home/test", expect.objectContaining({ page_size: 25, show_hidden: true, sort: "modified", direction: "desc" })));
    expect(container.querySelector(".file-grid.large")).toBeInTheDocument();
    expect(container.querySelector(".file-content")).toHaveClass("compact");
  });

  it("recognizes an external file transfer from its Files type before files are exposed", () => {
    expect(isExternalFileTransfer(dragTransfer([], ["Files"]))).toBe(true);
    expect(isExternalFileTransfer(dragTransfer([], ["text/plain"]))).toBe(false);
  });

  it("uploads every externally dropped file to the current path and clears the overlay", async () => {
    vi.mocked(api.list).mockResolvedValue({ path: "/home/test/Empty", current_path: "/home/test/Empty", parent_path: "/home/test", items: [], page: 1, page_size: 100, total_items: 0, total_pages: 1, sort: "name", direction: "asc", can_write: true, can_upload: true, can_delete: true });
    const onUpload = vi.fn(() => []);
    const { container } = render(<FileManager homePath="/home/test" initialPath="/home/test/Empty" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={onUpload} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("files.empty");
    const content = container.querySelector<HTMLElement>(".file-content")!;
    const dropped = [new File(["one"], "one.txt"), new File(["two"], "two.txt")];
    const dataTransfer = dragTransfer(dropped);

    fireEvent.dragEnter(content, { dataTransfer });
    expect(screen.getByRole("status")).toHaveTextContent("files.dropUpload");
    expect(content).toHaveClass("external-drag-active");

    fireEvent.dragOver(content, { dataTransfer });
    expect(dataTransfer.dropEffect).toBe("copy");
    expect(fireEvent.drop(content, { dataTransfer })).toBe(false);

    expect(onUpload).toHaveBeenCalledWith(dropped, "/home/test/Empty");
    expect(screen.queryByText("files.dropUpload")).not.toBeInTheDocument();
    expect(content).not.toHaveClass("external-drag-active");
  });

  it("uses the same upload path for the file picker", async () => {
    const onUpload = vi.fn(() => []);
    render(<FileManager homePath="/home/test" settings={settingsFixture({ file_confirm_overwrite: false })} tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={onUpload} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("alpha.txt");
    const selected = [new File(["picked"], "picked.txt")];

    fireEvent.change(document.getElementById("file-manager-upload")!, { target: { files: selected } });

    expect(onUpload).toHaveBeenCalledWith(selected, "/home/test");
  });

  it("does not activate or upload an external drop in a read-only directory", async () => {
    vi.mocked(api.list).mockResolvedValue({ path: "/home/test", current_path: "/home/test", parent_path: "/home", items: [], page: 1, page_size: 100, total_items: 0, total_pages: 1, sort: "name", direction: "asc", can_write: false, can_upload: false, can_delete: false });
    const onUpload = vi.fn(() => []);
    const { container } = render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={onUpload} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("files.empty");
    const content = container.querySelector<HTMLElement>(".file-content")!;
    const dataTransfer = dragTransfer([new File(["blocked"], "blocked.txt")]);

    fireEvent.dragEnter(content, { dataTransfer });
    fireEvent.dragOver(content, { dataTransfer });
    expect(fireEvent.drop(content, { dataTransfer })).toBe(false);

    expect(dataTransfer.dropEffect).toBe("none");
    expect(onUpload).not.toHaveBeenCalled();
    expect(screen.queryByText("files.dropUpload")).not.toBeInTheDocument();
  });

  it("keeps internal file dragging on the existing move path without uploading", async () => {
    const onUpload = vi.fn(() => []);
    const { container } = render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={onUpload} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("alpha.txt");
    const rows = [...container.querySelectorAll<HTMLElement>(".file-row")];
    const source = rows.find((row) => row.textContent?.includes("alpha.txt"))!;
    const destination = rows.find((row) => row.textContent?.includes("Documents"))!;
    const dataTransfer = dragTransfer([], ["text/plain"]);

    fireEvent.dragStart(source, { dataTransfer });
    fireEvent.dragOver(destination, { dataTransfer });
    fireEvent.drop(destination, { dataTransfer });

    expect(onUpload).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "files.confirmMove" })).toBeInTheDocument();
  });

  it("does not upload dragged text or URLs", async () => {
    const onUpload = vi.fn(() => []);
    const { container } = render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={onUpload} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("alpha.txt");
    const content = container.querySelector<HTMLElement>(".file-content")!;

    fireEvent.dragEnter(content, { dataTransfer: dragTransfer([], ["text/plain"]) });
    fireEvent.drop(content, { dataTransfer: dragTransfer([], ["text/uri-list"]) });

    expect(onUpload).not.toHaveBeenCalled();
    expect(screen.queryByText("files.dropUpload")).not.toBeInTheDocument();
  });

  it("preserves overwrite confirmation for externally dropped files", async () => {
    const onUpload = vi.fn(() => []);
    const { container } = render(<FileManager homePath="/home/test" settings={settingsFixture({ file_confirm_overwrite: true })} tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={onUpload} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("alpha.txt");
    const dropped = [new File(["replacement"], "alpha.txt"), new File(["new"], "new.txt")];

    fireEvent.drop(container.querySelector(".file-row")!, { dataTransfer: dragTransfer(dropped) });

    expect(onUpload).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "files.confirmOverwriteTitle" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.overwrite" }));
    expect(onUpload).toHaveBeenCalledWith(dropped, "/home/test");
  });

  it("keeps the drop-zone stable across children and clears it on leave or cancellation", async () => {
    const { container } = render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn(() => [])} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("alpha.txt");
    const content = container.querySelector<HTMLElement>(".file-content")!;
    const child = container.querySelector<HTMLElement>(".file-row")!;
    const dataTransfer = dragTransfer([new File(["one"], "one.txt")]);

    fireEvent.dragEnter(content, { dataTransfer });
    fireEvent.dragEnter(child, { dataTransfer });
    fireEvent.dragLeave(child, { dataTransfer, relatedTarget: content });
    expect(screen.getByText("files.dropUpload")).toBeInTheDocument();

    fireEvent.dragLeave(content, { dataTransfer, relatedTarget: document.body });
    expect(screen.queryByText("files.dropUpload")).not.toBeInTheDocument();

    fireEvent.dragEnter(content, { dataTransfer });
    expect(screen.getByText("files.dropUpload")).toBeInTheDocument();
    fireEvent.dragEnd(window, { dataTransfer });
    expect(screen.queryByText("files.dropUpload")).not.toBeInTheDocument();
  });

  it("opens a file in the text editor from its context menu", async () => {
    const { container } = render(<FileManager homePath="/home/test" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);
    await screen.findByText("alpha.txt");
    const row = [...container.querySelectorAll<HTMLElement>(".file-row")].find((entry) => entry.textContent?.includes("alpha.txt"));
    fireEvent.contextMenu(row!);

    fireEvent.click(screen.getByRole("menuitem", { name: "files.editText" }));

    await waitFor(() => expect(api.readText).toHaveBeenCalledWith("/home/test/alpha.txt"));
    expect(screen.getByRole("dialog", { name: /files.textEditor/ })).toBeInTheDocument();
  });
});
