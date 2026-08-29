import { ShieldBan } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { Fail2BanManagerApp } from "./Fail2BanManagerApp";

const manifest: FrontendModuleManifest = {
  id: "fail2ban-manager",
  labelKey: "Fail2Ban Manager",
  icon: <ShieldBan />,
  category: "security",
  permission: "fail2ban-manager.view",
  minWidth: 980,
  minHeight: 620,
  render: (context) => <Fail2BanManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
};

export default manifest;
