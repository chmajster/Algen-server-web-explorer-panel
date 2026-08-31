import { Webhook } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const WebhookManagerApp = lazy(() => import("./WebhookManagerApp").then((loaded) => ({ default: loaded.WebhookManagerApp })));

const manifest: FrontendModuleManifest = {
  id: "webhook-manager",
  labelKey: "module.webhookManager",
  icon: <Webhook />,
  category: "automation",
  permission: "webhook-manager.view",
  minWidth: 1040,
  minHeight: 650,
  render: (context) => lazyView(
    <WebhookManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
