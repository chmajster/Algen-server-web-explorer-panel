import { Webhook } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { WebhookManagerApp } from "./WebhookManagerApp";

const manifest: FrontendModuleManifest = {
  id: "webhook-manager",
  labelKey: "module.webhookManager",
  icon: <Webhook />,
  category: "automation",
  permission: "webhook-manager.view",
  minWidth: 1040,
  minHeight: 650,
  render: (context) => <WebhookManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
};

export default manifest;
