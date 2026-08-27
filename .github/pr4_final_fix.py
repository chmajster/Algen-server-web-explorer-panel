from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if old not in text:
        raise SystemExit(f"Expected source fragment not found in {path}: {old[:100]!r}")
    file.write_text(text.replace(old, new, 1))


modal = "frontend/src/components/Modal.tsx"
replace_once(
    modal,
    "export function Modal(",
    '''const visibleDialogOrder: symbol[] = [];

function activateDialog(token: symbol) {
  const index = visibleDialogOrder.indexOf(token);
  if (index >= 0) visibleDialogOrder.splice(index, 1);
  visibleDialogOrder.push(token);
}

function deactivateDialog(token: symbol) {
  const index = visibleDialogOrder.indexOf(token);
  if (index >= 0) visibleDialogOrder.splice(index, 1);
}

function isActiveDialog(token: symbol) {
  return visibleDialogOrder[visibleDialogOrder.length - 1] === token;
}

export function Modal('''
)
replace_once(
    modal,
    '  const titleId = useId();\n',
    '  const titleId = useId();\n  const [dialogToken] = useState(() => Symbol("dialog"));\n'
)
replace_once(
    modal,
    '''  useEffect(() => {
    if (minimized) return;
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
      }
    }
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [minimized]);''',
    '''  useEffect(() => {
    if (minimized) {
      deactivateDialog(dialogToken);
      return;
    }
    activateDialog(dialogToken);
    return () => deactivateDialog(dialogToken);
  }, [dialogToken, minimized]);

  useEffect(() => {
    if (minimized) return;
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape" && isActiveDialog(dialogToken)) {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
      }
    }
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [dialogToken, minimized]);'''
)
replace_once(
    modal,
    '        onPointerDown={(event) => event.stopPropagation()}\n',
    '        onPointerDown={(event) => { activateDialog(dialogToken); event.stopPropagation(); }}\n        onFocusCapture={() => activateDialog(dialogToken)}\n'
)

modal_test = "frontend/src/components/Modal.test.tsx"
replace_once(
    modal_test,
    '  it("ignores Escape while minimized", () => {',
    '''  it("closes only the active visible dialog with Escape", () => {
    const firstClose = vi.fn();
    const secondClose = vi.fn();
    render(<><Modal title="First active" onClose={firstClose}><p>First</p></Modal><Modal title="Second active" onClose={secondClose}><p>Second</p></Modal></>);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(firstClose).not.toHaveBeenCalled();
    expect(secondClose).toHaveBeenCalledOnce();

    fireEvent.pointerDown(screen.getByRole("dialog", { name: "First active" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(firstClose).toHaveBeenCalledOnce();
    expect(secondClose).toHaveBeenCalledOnce();
  });

  it("ignores Escape while minimized", () => {'''
)

dialog_service = "frontend/src/components/DialogService.tsx"
replace_once(
    dialog_service,
    '''function isUpdateDialog(dialog: HTMLElement): boolean {
  const labelledBy = dialog.getAttribute("aria-labelledby") || "";
  const classes = [
    dialog.className,
    dialog.closest<HTMLElement>(".modal-backdrop")?.className || "",
  ].join(" ");
  return labelledBy.startsWith("update-") || /(^|\\s)update-(progress|completion|details|status)/.test(classes);
}''',
    '''function isUpdateDialog(dialog: HTMLElement): boolean {
  const labelledBy = dialog.getAttribute("aria-labelledby") || "";
  const classes = [
    dialog.className,
    dialog.closest<HTMLElement>(".modal-backdrop")?.className || "",
  ].join(" ").split(/\\s+/);
  return labelledBy === "update-progress-title" || classes.includes("update-progress-backdrop") || classes.includes("update-progress-dialog");
}'''
)

apmid = "frontend/src/features/modules/apmid/ApmidApp.tsx"
replace_once(
    apmid,
    'import { useCallback, useEffect, useState } from "react";',
    'import { useCallback, useEffect, useRef, useState } from "react";'
)
replace_once(
    apmid,
    '''function Backups({ values, canCreate, canRestore, t, toast, onRefresh }: { values: ApmidBackup[]; canCreate: boolean; canRestore: boolean; t: Translate; toast: ToastFn; onRefresh: () => Promise<void> }) {
  async function create() {''',
    '''function Backups({ values, canCreate, canRestore, t, toast, onRefresh }: { values: ApmidBackup[]; canCreate: boolean; canRestore: boolean; t: Translate; toast: ToastFn; onRefresh: () => Promise<void> }) {
  const pendingRestores = useRef(new Set<ApmidBackup["id"]>());
  async function create() {'''
)
replace_once(
    apmid,
    '''  async function restore(backup: ApmidBackup) {
    const confirmation = (await promptDialog(t, t("apmid.backup.restoreConfirm"), "")) ?? "";
    if (!confirmation) return;
    try { await api.restoreApmidBackup(backup.id, confirmation); await onRefresh(); toast(t("apmid.backup.restored"), "ok"); } catch (error) { toast(message(error, t), "error"); }
  }''',
    '''  async function restore(backup: ApmidBackup) {
    if (pendingRestores.current.has(backup.id)) return;
    pendingRestores.current.add(backup.id);
    try {
      const confirmation = (await promptDialog(t, t("apmid.backup.restoreConfirm"), "")) ?? "";
      if (!confirmation) return;
      await api.restoreApmidBackup(backup.id, confirmation);
      await onRefresh();
      toast(t("apmid.backup.restored"), "ok");
    } catch (error) {
      toast(message(error, t), "error");
    } finally {
      pendingRestores.current.delete(backup.id);
    }
  }'''
)

apmid_test = Path("frontend/src/features/modules/apmid/ApmidApp.test.tsx")
test_text = apmid_test.read_text()
marker = "\n});\n"
if not test_text.endswith(marker):
    raise SystemExit("Unexpected ApmidApp.test.tsx ending")
addition = '''

  it("coalesces duplicate backup restores while one request is pending", async () => {
    vi.mocked(api.apmidBackups).mockResolvedValue([{
      id: "backup-1", schema_version: 1, created_at: 1, created_by: "admin",
      description: "test", sha256: "abc", database: "/tmp/apmid.db",
    }]);
    vi.mocked(api.restoreApmidBackup).mockImplementation(() => new Promise(() => {}));
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("RESTORE");

    render(<ApmidApp permissions={["apmid.restore"]} t={t} toast={vi.fn()} />);
    await screen.findByText("apmid.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: "module.section.backups" }));
    const restore = await screen.findByRole("button", { name: "apmid.backup.restore" });
    fireEvent.click(restore);
    fireEvent.click(restore);

    await waitFor(() => expect(api.restoreApmidBackup).toHaveBeenCalledTimes(1));
    expect(prompt).toHaveBeenCalledTimes(1);
    prompt.mockRestore();
  });'''
apmid_test.write_text(test_text[:-len(marker)] + addition + marker)
