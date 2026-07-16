import type { SettingsMe } from "../api";
import { defaultUserPreferences } from "../app/defaultSettings";

export function settingsFixture(overrides: Partial<SettingsMe> = {}): SettingsMe {
  return {
    ...defaultUserPreferences,
    username: "test",
    uid: 1000,
    gid: 1000,
    groups: ["users"],
    home: "/home/test",
    shell: "/bin/bash",
    gecos: "Test User",
    is_admin: false,
    role: "user",
    role_source: "default",
    permissions: ["files.view", "files.read", "files.download", "files.upload", "files.create", "files.edit", "files.rename", "files.copy", "files.move", "files.delete", "files.chmod", "transfers.view_own", "transfers.create", "transfers.pause", "transfers.resume", "transfers.cancel", "transfers.retry", "transfers.change_priority", "settings.view_own", "settings.edit_own", "settings.change_own_password", "audit.view_own", "system.status"],
    ...overrides,
  };
}
