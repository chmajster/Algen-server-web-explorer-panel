import { describe, expect, it, vi } from "vitest";
import { ApplicationManager, ClipboardManager, NotificationManager, SearchManager, WindowManager } from "./managers";

const viewport = { width: 1280, height: 720, bottom: 58 };

describe("WebNAS shell managers", () => {
  it("routes window commands through the managed dispatcher contract", () => {
    const manager = new WindowManager();
    manager.bind({ windows: [], activeId: "", counter: 0, topZ: 10 }, viewport);
    const listener = vi.fn();
    manager.subscribe(listener);
    manager.open("files", { initialPath: "/tmp" });
    expect(listener).toHaveBeenCalledWith(expect.objectContaining({
      type: "dispatch",
      detail: expect.objectContaining({ type: "open", app: "files", initialPath: "/tmp", viewport }),
    }));
  });

  it("keeps notification history and unread state centrally", () => {
    const manager = new NotificationManager();
    const item = manager.send({ type: "service", title: "nginx", body: "Stopped", source: "systemd", level: "warning" });
    expect(manager.unread()).toBe(1);
    manager.markRead(item.id);
    expect(manager.unread()).toBe(0);
    manager.remove(item.id);
    expect(manager.list()).toEqual([]);
  });

  it("filters global search providers and respects runtime permission predicates", async () => {
    const manager = new SearchManager();
    manager.register("apps", () => [
      { id: "files", title: "Files", category: "application", run: vi.fn() },
      { id: "admin", title: "Restart nginx", category: "action", permitted: () => false, run: vi.fn() },
    ]);
    await expect(manager.search("files")).resolves.toEqual([expect.objectContaining({ id: "files" })]);
    await expect(manager.search("nginx")).resolves.toEqual([]);
  });

  it("validates application manifests and blocks traversal/invalid permissions", () => {
    const manager = new ApplicationManager();
    manager.register({ id: "docker", name: "Docker", version: "1.0.0", entry: "/apps/docker", permissions: ["docker.read"], multiWindow: true, category: "system" });
    expect(manager.get("docker")?.name).toBe("Docker");
    expect(() => manager.register({ id: "evil", name: "Evil", version: "1.0.0", entry: "/apps/../etc", permissions: [], multiWindow: false, category: "system" })).toThrow("Invalid application entry");
    expect(() => manager.register({ id: "bad", name: "Bad", version: "1.0.0", entry: "/apps/bad", permissions: ["x<script>"], multiWindow: false, category: "system" })).toThrow("Invalid application permissions");
  });

  it("owns clipboard cut/copy state instead of using application globals", () => {
    const manager = new ClipboardManager();
    manager.copy(["/a", "/b"]);
    expect(manager.get()).toEqual({ mode: "copy", items: ["/a", "/b"] });
    manager.cut(["/c"]);
    expect(manager.get()).toEqual({ mode: "cut", items: ["/c"] });
    manager.clear();
    expect(manager.get()).toBeNull();
  });
});
