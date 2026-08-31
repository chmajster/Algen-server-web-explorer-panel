import { History } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const LoginHistoryApp = lazy(() => import("./LoginHistoryApp").then((loaded) => ({ default: loaded.LoginHistoryApp })));

const manifest: FrontendModuleManifest = {
  id: "login-history",
  labelKey: "Login History",
  icon: <History />,
  category: "security",
  permission: "login_history.view",
  minWidth: 960,
  minHeight: 620,
  render: (context) => lazyView(
    <LoginHistoryApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
