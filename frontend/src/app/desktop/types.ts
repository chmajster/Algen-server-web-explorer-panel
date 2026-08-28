import type { SettingsMe, SettingsPatch, Task } from "../../api";
import type { UploadControls } from "../../features/transfers/useUploadManager";
import type { Language } from "../../i18n";
import type { Theme, Toast, ToastFn, Translate, User } from "../types";

export interface DesktopProps {
  user: User;
  profile: SettingsMe;
  language: Language;
  theme: Theme;
  tasks: Task[];
  uploadControls: UploadControls;
  toasts: Toast[];
  t: Translate;
  toast: ToastFn;
  onSettingsChange: (patch: SettingsPatch) => Promise<void>;
  onTheme: (theme: Theme) => void;
  onLoggedOut: () => void;
}
