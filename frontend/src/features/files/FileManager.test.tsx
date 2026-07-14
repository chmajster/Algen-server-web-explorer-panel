import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { FileManager } from "./FileManager";

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

  it("uses a local disk as the breadcrumb root", async () => {
    vi.mocked(api.localDisks).mockResolvedValue([
      { device: "/dev/sdb1", mount_point: "/mnt/storage", name: "storage", fs_type: "ext4", read_only: false, total: 100, used: 50, free: 50 },
    ]);
    vi.mocked(api.list).mockResolvedValue({ path: "/mnt/storage/Films", current_path: "/mnt/storage/Films", parent_path: "/mnt/storage", items: [], page: 1, page_size: 100, total_items: 0, total_pages: 1, sort: "name", direction: "asc", can_write: true, can_upload: true, can_delete: true });

    const { container } = render(<FileManager homePath="/home/test" initialPath="/mnt/storage/Films" tasks={[]} isAdmin={false} t={t} toast={vi.fn()} onUpload={vi.fn()} onOpenFolderWindow={vi.fn()} onShareSamba={vi.fn()} />);

    await waitFor(() => expect(container.querySelector(".breadcrumbs")?.textContent).toContain("storageFilms"));
    expect(container.querySelector(".breadcrumbs")?.textContent).not.toContain("files.home");
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
