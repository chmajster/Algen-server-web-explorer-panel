import { undo } from "@codemirror/commands";
import { Text } from "@codemirror/state";
import { EditorView } from "codemirror";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type FileItem } from "../../api";
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
    view?.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: Text.of(content.split(/\r\n|\r|\n/)) } });
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("text editor", () => {
  beforeEach(() => {
    vi.resetAllMocks();
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

  it("keeps typing during a save dirty and uses the new version for the next save", async () => {
    const pending = deferred<Awaited<ReturnType<typeof api.writeText>>>();
    vi.mocked(api.writeText).mockReturnValueOnce(pending.promise);
    const onClose = vi.fn();
    render(<TextEditor item={item} t={t} onClose={onClose} onSaved={vi.fn()} />);
    const editor = await screen.findByRole("textbox", { name: "editor.content" });
    replaceDocument(editor, "first draft");
    act(() => {
      fireEvent.keyDown(editor, { key: "s", ctrlKey: true });
      fireEvent.keyDown(editor, { key: "s", ctrlKey: true });
    });
    expect(api.writeText).toHaveBeenCalledTimes(1);
    replaceDocument(editor, "newer draft");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByText("editor.closeMessage")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "editor.reload" })).toBeDisabled();
    await act(async () => pending.resolve({ path: item.path, encoding: "utf-8", size: 11, mtime_ns: "201", ok: true }));

    expect(editor).toHaveTextContent("newer draft");
    expect(screen.getByRole("status")).toHaveTextContent("editor.unsaved");
    expect(screen.getByRole("button", { name: "action.save" })).toBeEnabled();
    fireEvent.keyDown(editor, { key: "s", ctrlKey: true });
    await waitFor(() => expect(api.writeText).toHaveBeenLastCalledWith(item.path, "newer draft", "201"));
    expect(await screen.findByText("editor.saved")).toBeInTheDocument();
  });

  it("preserves the document, selection and undo history when language or permissions change", async () => {
    const props = { item, t, onClose: vi.fn(), onSaved: vi.fn() };
    const { rerender } = render(<TextEditor {...props} />);
    const editor = await screen.findByRole("textbox", { name: "editor.content" });
    const view = EditorView.findFromDOM(editor)!;
    replaceDocument(editor, "draft in progress");
    act(() => view.dispatch({ selection: { anchor: 5 } }));
    rerender(<TextEditor {...props} t={(key) => `pl:${key}`} item={{ ...item, can_write: false }} />);

    expect(api.readText).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("textbox", { name: "pl:editor.content" })).toBe(editor);
    expect(editor).toHaveTextContent("draft in progress");
    expect(view.state.selection.main.head).toBe(5);
    expect(editor).toHaveAttribute("contenteditable", "false");
    rerender(<TextEditor {...props} />);
    act(() => { undo(view); });
    expect(editor).toHaveTextContent("hello");
    expect(screen.getByRole("button", { name: "action.save" })).toBeDisabled();
  });

  it("aborts reads for a previous file and ignores a late response", async () => {
    const first = deferred<Awaited<ReturnType<typeof api.readText>>>();
    vi.mocked(api.readText).mockReturnValueOnce(first.promise);
    const props = { item, t, onClose: vi.fn(), onSaved: vi.fn() };
    const { rerender, unmount } = render(<TextEditor {...props} />);
    const signal = vi.mocked(api.readText).mock.calls[0][1]!;
    rerender(<TextEditor {...props} item={{ ...item, path: "/home/alice/second.txt", name: "second.txt" }} />);
    const editor = await screen.findByRole("textbox", { name: "editor.content" });
    expect(signal.aborted).toBe(true);
    replaceDocument(editor, "keep second draft");
    await act(async () => first.resolve({ path: item.path, content: "late first file", encoding: "utf-8", size: 15, mtime_ns: "99" }));
    expect(editor).toHaveTextContent("keep second draft");
    unmount();
    expect(vi.mocked(api.readText).mock.calls[1][1]!.aborted).toBe(true);
  });

  it.each(["\r\n", "\r", "\n"])("preserves UTF-8 BOM and %j line endings when saving edits", async (separator) => {
    const content = `\uFEFFhello${separator}world${separator}`;
    vi.mocked(api.readText).mockResolvedValueOnce({ path: item.path, content, encoding: "utf-8", size: 18, mtime_ns: "100" });
    render(<TextEditor item={item} t={t} onClose={vi.fn()} onSaved={vi.fn()} />);
    const editor = await screen.findByRole("textbox", { name: "editor.content" });
    const view = EditorView.findFromDOM(editor)!;
    expect(view.state.doc.lines).toBe(3);
    act(() => view.dispatch({ changes: { from: 1, to: 6, insert: "Hi" } }));
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));
    await waitFor(() => expect(api.writeText).toHaveBeenCalledWith(item.path, `\uFEFFHi${separator}world${separator}`, "100"));
  });

  it("requires an explicit ending choice before editing mixed endings", async () => {
    vi.mocked(api.readText).mockResolvedValueOnce({ path: item.path, content: "one\r\ntwo\nthree\r", encoding: "utf-8", size: 15, mtime_ns: "100" });
    render(<TextEditor item={item} t={t} onClose={vi.fn()} onSaved={vi.fn()} />);
    const editor = await screen.findByRole("textbox", { name: "editor.content" });
    expect(editor).toHaveAttribute("contenteditable", "false");
    expect(screen.getByText("editor.mixedNotice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "action.save" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "editor.lineEndings" }), { target: { value: "CRLF" } });
    expect(editor).toHaveAttribute("contenteditable", "true");
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));
    await waitFor(() => expect(api.writeText).toHaveBeenCalledWith(item.path, "one\r\ntwo\r\nthree\r\n", "100"));
  });

  it("accepts multiline inserted text while preserving the file's CRLF format", async () => {
    vi.mocked(api.readText).mockResolvedValueOnce({ path: item.path, content: "one\r\ntwo", encoding: "utf-8", size: 8, mtime_ns: "100" });
    render(<TextEditor item={item} t={t} onClose={vi.fn()} onSaved={vi.fn()} />);
    const editor = await screen.findByRole("textbox", { name: "editor.content" });
    const view = EditorView.findFromDOM(editor)!;
    act(() => view.dispatch({ changes: { from: view.state.doc.length, insert: "\nthree\rfour\r\nfive" } }));
    expect(view.state.doc.lines).toBe(5);
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));
    await waitFor(() => expect(api.writeText).toHaveBeenCalledWith(item.path, "one\r\ntwo\r\nthree\r\nfour\r\nfive", "100"));
  });

  it("counts serialized UTF-8 bytes, including CRLF, against the size limit", async () => {
    const content = `${"a".repeat(1024 * 1024 - 5)}\r\n`;
    vi.mocked(api.readText).mockResolvedValueOnce({ path: item.path, content, encoding: "utf-8", size: content.length, mtime_ns: "100" });
    render(<TextEditor item={item} t={t} onClose={vi.fn()} onSaved={vi.fn()} />);
    const editor = await screen.findByRole("textbox", { name: "editor.content" });
    const view = EditorView.findFromDOM(editor)!;
    act(() => view.dispatch({ changes: { from: view.state.doc.length, insert: "😀" } }));
    expect(await screen.findByText("editor.tooLarge")).toBeInTheDocument();
    expect(view.state.doc.toString()).toBe(content.replace(/\r\n/g, "\n"));
    act(() => view.dispatch({ changes: { from: view.state.doc.length, insert: "€" } }));
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));
    await waitFor(() => expect(api.writeText).toHaveBeenCalledWith(item.path, `${content}€`, "100"));
  });

  it("indents and unindents a multiline selection without deleting it", async () => {
    render(<TextEditor item={item} t={t} onClose={vi.fn()} onSaved={vi.fn()} />);
    const editor = await screen.findByRole("textbox", { name: "editor.content" });
    replaceDocument(editor, "one\ntwo");
    const view = EditorView.findFromDOM(editor)!;
    act(() => view.dispatch({ selection: { anchor: 0, head: view.state.doc.length } }));
    fireEvent.keyDown(editor, { key: "Tab", keyCode: 9 });
    expect(view.state.sliceDoc()).toBe("  one\n  two");
    fireEvent.keyDown(editor, { key: "Tab", keyCode: 9, shiftKey: true });
    expect(view.state.sliceDoc()).toBe("one\ntwo");
  });

  it("closes the search panel with Escape without closing the editor", async () => {
    const onClose = vi.fn();
    render(<TextEditor item={item} t={t} onClose={onClose} onSaved={vi.fn()} />);
    await screen.findByRole("textbox", { name: "editor.content" });
    fireEvent.click(screen.getByRole("button", { name: "editor.findReplace" }));
    const search = screen.getByRole("textbox", { name: "editor.search.find" });
    fireEvent.keyDown(search, { key: "Escape", keyCode: 27 });
    expect(screen.queryByRole("textbox", { name: "editor.search.find" })).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps a conflicting draft until reload is explicitly confirmed, then saves against the refreshed version", async () => {
    vi.mocked(api.writeText).mockRejectedValueOnce(new ApiError("conflict", 409, "changed_on_disk"));
    render(<TextEditor item={item} t={t} onClose={vi.fn()} onSaved={vi.fn()} />);
    const editor = await screen.findByRole("textbox", { name: "editor.content" });
    replaceDocument(editor, "my draft");
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));
    expect(await screen.findByText("editor.changedOnDisk")).toBeInTheDocument();
    expect(editor).toHaveTextContent("my draft");
    fireEvent.click(screen.getByRole("button", { name: "editor.reload" }));
    fireEvent.click(screen.getAllByRole("button", { name: "action.cancel" }).pop()!);
    expect(api.readText).toHaveBeenCalledTimes(1);
    expect(editor).toHaveTextContent("my draft");
    vi.mocked(api.readText).mockResolvedValueOnce({ path: item.path, content: "new on disk", encoding: "utf-8", size: 11, mtime_ns: "500" });
    fireEvent.click(screen.getByRole("button", { name: "editor.reload" }));
    fireEvent.click(screen.getAllByRole("button", { name: "editor.reload" }).pop()!);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "editor.content" })).toHaveTextContent("new on disk"));
    replaceDocument(screen.getByRole("textbox", { name: "editor.content" }), "based on new disk version");
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));
    await waitFor(() => expect(api.writeText).toHaveBeenLastCalledWith(item.path, "based on new disk version", "500"));
  });
});
