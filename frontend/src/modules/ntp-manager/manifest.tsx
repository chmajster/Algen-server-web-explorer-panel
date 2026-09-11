import { Clock } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const NtpManagerApp = lazy(() => import("./NtpManagerApp").then((loaded) => ({ default: loaded.NtpManagerApp })));

const manifest: FrontendModuleManifest = {
  id: "ntp-manager",
  labelKey: "NTP Manager",
  icon: <Clock />,
  category: "system",
  permission: "ntp.view",
  minWidth: 980,
  minHeight: 650,
  render: (context) => lazyView(
    <NtpManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
