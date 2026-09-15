import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type FileItem, type FileSearchResponse } from "../../api";
import { FileSearchDialog } from "./FileSearchDialog";

vi.mock("../../api", () => ({ api: { search: vi.fn() } }));

const file: FileItem = {
  name: "Report.TXT", path: "/home/test/Reports/Report.TXT", type: "txt", is_dir: false, size: 20,
  owner: "test", group: "users", mode: "0644", permissions: "-rw-r--r--", modified: 2, mtime: 2,
  mime: "text/plain", can_read: true, can_write: true, can_delete: true, can_rename: true, is_symlink: false,
};
const labels: Record<string, string> = { "files.searchResults": "{count} results for {query}", "files.searchSkipped": "Skipped {count} entries" };
function setup(initialQuery = "") {
  const props = { path: "/home/test", initialQuery, showHidden: false, t: (key: string) => labels[key] || key, toast: vi.fn(), onClose: vi.fn(), onOpenItem: vi.fn(), onOpenFolder: vi.fn() };
  return { ...render(<FileSearchDialog {...props} />), ...props };
}

describe("recursive file search", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(api.search).mockResolvedValue({ items: [file], scanned: 5, skipped: 0, truncated: false, reason: null });
  });

  it("searches with name, type, case and hidden filters, then opens a result or its parent", async () => {
    const props = setup();
    expect(screen.getByLabelText("files.searchName")).toHaveFocus();
    expect(screen.getByRole("button", { name: "files.runSearch" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("files.searchName"), { target: { value: " *.TXT " } });
    fireEvent.change(screen.getByLabelText("files.searchMatchMode"), { target: { value: "glob" } });
    fireEvent.change(screen.getByLabelText("files.searchType"), { target: { value: "files" } });
    fireEvent.click(screen.getByLabelText("files.searchCaseSensitive"));
    fireEvent.click(screen.getByLabelText("files.searchHidden"));
    expect(screen.getByText("files.searchGlobHint")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "files.runSearch" }));
    expect(await screen.findByText(file.path)).toBeInTheDocument();
    expect(api.search).toHaveBeenCalledWith("/home/test", "*.TXT", { match_mode: "glob", item_type: "files", case_sensitive: true, show_hidden: true }, expect.any(AbortSignal));
    expect(screen.getByText("1 results for *.TXT")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.open Report.TXT" }));
    expect(props.onOpenItem).toHaveBeenCalledWith(file);
    fireEvent.click(screen.getByRole("button", { name: "files.openContainingFolder Report.TXT" }));
    expect(props.onOpenFolder).toHaveBeenCalledWith("/home/test/Reports");
  });

  it.each(["limit", "entries", "timeout"] as const)("reports partial results caused by %s and skipped entries", async (reason) => {
    vi.mocked(api.search).mockResolvedValue({ items: [file], truncated: true, reason, skipped: 2 });
    setup("Report");
    fireEvent.click(screen.getByRole("button", { name: "files.runSearch" }));
    expect(await screen.findByText(`files.searchPartial.${reason}`)).toBeInTheDocument();
    expect(screen.getByText("Skipped 2 entries")).toBeInTheDocument();
    expect(screen.getByText(file.path)).toBeInTheDocument();
  });

  it("shows request failures and allows a retry without presenting them as empty results", async () => {
    vi.mocked(api.search).mockRejectedValueOnce(new Error("Permission denied")).mockResolvedValueOnce({ items: [] });
    setup("Report");
    fireEvent.click(screen.getByRole("button", { name: "files.runSearch" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Permission denied");
    expect(screen.queryByText("files.searchNoResults")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "files.runSearch" }));
    expect(await screen.findByText("files.searchNoResults")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("cancels an outstanding search on unmount and prevents duplicate submissions", async () => {
    let resolve!: (value: FileSearchResponse) => void;
    vi.mocked(api.search).mockReturnValue(new Promise((done) => { resolve = done; }));
    const props = setup("Report");
    fireEvent.click(screen.getByRole("button", { name: "files.runSearch" }));
    const submit = screen.getByRole("button", { name: "files.searching" });
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(api.search).toHaveBeenCalledTimes(1);
    const signal = vi.mocked(api.search).mock.calls[0][3]!;
    props.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => resolve({ items: [file] }));
  });

  it("reports whether copying the full path succeeded", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const previous = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    try {
      const props = setup("Report");
      fireEvent.click(screen.getByRole("button", { name: "files.runSearch" }));
      const copy = await screen.findByRole("button", { name: "files.copyPath Report.TXT" });
      fireEvent.click(copy);
      await waitFor(() => expect(props.toast).toHaveBeenCalledWith("files.pathCopied"));
      expect(writeText).toHaveBeenCalledWith(file.path);
      writeText.mockRejectedValueOnce(new Error("Denied"));
      fireEvent.click(copy);
      await waitFor(() => expect(props.toast).toHaveBeenCalledWith("files.pathCopyFailed", "error"));
    } finally {
      if (previous) Object.defineProperty(navigator, "clipboard", previous);
      else Reflect.deleteProperty(navigator, "clipboard");
    }
  });
});
