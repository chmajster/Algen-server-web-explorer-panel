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
    permissions: ["apps.files", "apps.settings", "apps.monitor", "apps.transfers", "widgets.manage"],
    ...overrides,
  };
}
