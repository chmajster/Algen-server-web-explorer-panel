import { HardDrive } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const FileManager = lazy(() => import("../../features/files/FileManager").then((loaded) => ({ default: loaded.FileManager })));

export default {
  id: "files", labelKey: "app.fileManager", icon: <HardDrive />, category: "storage",
  permission: "files.view", minWidth: 680, minHeight: 440,
  render: (context) => lazyView(<FileManager homePath={context.user.home} initialPath={context.item.initialPath} settings={context.profile} tasks={context.tasks} isAdmin={context.profile.is_admin} t={context.t} toast={context.toast} onUpload={context.uploadControls.add} onUploadCancel={context.uploadControls.cancel} onUploadRetry={context.uploadControls.retry} onSettingsChange={context.onSettingsChange} onOpenFolderWindow={(path) => context.openApp("files", path)} onShareSamba={(path) => context.openApp("module", path, "samba")} />, context.t("status.loading")),
} satisfies FrontendModuleManifest;
