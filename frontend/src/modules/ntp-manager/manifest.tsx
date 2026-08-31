import { Clock } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const NtpManagerApp = lazy(() => import("./NtpManagerApp").then((loaded) => ({ default: loaded.NtpManagerApp })));

const manifest: FrontendModuleManifest = {
  id: "ntp-manager",
  labelKey: "NTP Manager",
  icon: <Clock />,
  category: "network",
  permission: "ntp.view",
  minWidth: 900,
  minHeight: 600,
  render: (context) => lazyView(
    <NtpManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
