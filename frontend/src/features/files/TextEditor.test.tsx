import { EditorView } from "codemirror";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type FileItem } from "../../api";
import { TextEditor } from "./TextEditor";

vi.mock("../../api", () => ({
  ApiError: class ApiError extends Error { constructor(message: string, public status: number, public code?: string) { super(message); } },
  api: { readText: vi.fn(), writeText: vi.fn() },
}));

const t = (key: string) => key;
const item: FileItem = {
  name: "notes.txt", path: "/home/alice/notes.txt", type: "txt", is_dir: false, size: 5,
  owner: "alice", group: "alice", mode: "-rw-r--r--", permissions: "0644", modified: 1,
  mtime: 1, mime: "text/plain", can_read: true, can_write: true, can_delete: true,
  can_rename: true, is_symlink: false,
};

function replaceDocument(editor: HTMLElement, content: string) {
  const view = EditorView.findFromDOM(editor);
  expect(view).not.toBeNull();
  act(() => {
    view?.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: content } });
  });
}

describe("text editor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.readText).mockResolvedValue({ path: item.path, content: "hello", encoding: "utf-8", size: 5, mtime_ns: "100" });
    vi.mocked(api.writeText).mockResolvedValue({ path: item.path, encoding: "utf-8", size: 11, mtime_ns: "200", ok: true });
  });

  it("loads CodeMirror, edits and saves with Ctrl+S", async () => {
    const onSaved = vi.fn();
    render(<TextEditor item={item} t={t} onClose={vi.fn()} onSaved={onSaved} />);
    const editor = await screen.findByRole("textbox", { name: "editor.content" });

    expect(editor.closest(".cm-editor")).not.toBeNull();
    replaceDocument(editor, "hello world");
    fireEvent.keyDown(editor, { key: "s", ctrlKey: true });

    await waitFor(() => expect(api.writeText).toHaveBeenCalledWith(item.path, "hello world", "100"));
    expect(onSaved).toHaveBeenCalled();
    expect(await screen.findByText("editor.saved")).toBeInTheDocument();
  });

  it("opens a non-writable file in read-only mode", async () => {
    render(<TextEditor item={{ ...item, can_write: false }} t={t} onClose={vi.fn()} onSaved={vi.fn()} />);

    const editor = await screen.findByRole("textbox", { name: "editor.content" });
    expect(editor).toHaveAttribute("contenteditable", "false");
    expect(screen.getByText("editor.readOnly")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /action.save/ })).toBeDisabled();
  });

  it("asks before closing with unsaved CodeMirror changes", async () => {
    const onClose = vi.fn();
    render(<TextEditor item={item} t={t} onClose={onClose} onSaved={vi.fn()} />);
    const editor = await screen.findByRole("textbox", { name: "editor.content" });
    replaceDocument(editor, "changed");

    const closeButtons = screen.getAllByRole("button", { name: "action.close" });
    fireEvent.click(closeButtons[closeButtons.length - 1]);
    expect(screen.getByText("editor.closeMessage")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "editor.discard" }));
    expect(onClose).toHaveBeenCalled();
  });
});
