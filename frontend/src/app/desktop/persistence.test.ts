import { clearWindowDrafts, desktopStorageKeys, pushRecentApp, readRecentApps } from "./persistence";

describe("desktop persistence", () => {
  it("keeps per-user storage namespaces explicit", () => {
    expect(desktopStorageKeys("alice").sessionWindows).toBe("webnas_windows_alice_session");
    expect(desktopStorageKeys("alice").draftPrefix).toBe("webnas_window_draft_alice_");
  });

  it("sanitizes recent app storage", () => {
    const result = readRecentApps(JSON.stringify([{ id: "files", usedAt: 10 }, { id: "unknown", usedAt: 20 }, { nope: true }]), (id) => id === "files");
    expect(result).toEqual([{ id: "files", usedAt: 10 }]);
  });

  it("moves a recently used app to the front without duplicates", () => {
    expect(pushRecentApp([{ id: "files", usedAt: 1 }, { id: "settings", usedAt: 2 }], "files", 3)).toEqual([{ id: "files", usedAt: 3 }, { id: "settings", usedAt: 2 }]);
  });

  it("clears only window drafts in the requested namespace", () => {
    sessionStorage.setItem("webnas_window_draft_alice_1", "x");
    sessionStorage.setItem("keep", "y");
    clearWindowDrafts(sessionStorage, "webnas_window_draft_alice_");
    expect(sessionStorage.getItem("webnas_window_draft_alice_1")).toBeNull();
    expect(sessionStorage.getItem("keep")).toBe("y");
  });
});
