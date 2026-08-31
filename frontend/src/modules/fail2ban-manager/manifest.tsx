import { ShieldBan } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const Fail2BanManagerApp = lazy(() => import("./Fail2BanManagerApp").then((loaded) => ({ default: loaded.Fail2BanManagerApp })));

const manifest: FrontendModuleManifest = {
  id: "fail2ban-manager",
  labelKey: "module.fail2banManager",
  icon: <ShieldBan />,
  category: "security",
  permission: "fail2ban-manager.view",
  minWidth: 980,
  minHeight: 620,
  render: (context) => lazyView(
    <Fail2BanManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
