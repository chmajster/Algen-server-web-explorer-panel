/** Typed API facade composed from independently owned module clients. */
import { platformClient } from "./core/api/platformClient";
import { apmidClient } from "./modules/apmid/api/client";
import { filesClient } from "./modules/files/api/client";
import { transfersClient } from "./modules/transfers/api/client";
import { activityClient } from "./modules/activity/api/client";
import { settingsClient } from "./modules/settings/api/client";
import { identityClient } from "./modules/identity/api/client";
import { systemClient } from "./modules/system/api/client";
import { logsClient } from "./modules/logs/api/client";
import { networkClient } from "./modules/network/api/client";
import { powerClient } from "./modules/power/api/client";
import { updatesClient } from "./modules/updates/api/client";
import { servicesClient } from "./modules/services/api/client";
import { packageCenterClient } from "./modules/package-center/api/client";
import { moduleCenterClient } from "./modules/module-center/api/client";
import { osRepositoriesClient } from "./modules/os-repositories/api/client";
import { ansibleControllerClient } from "./modules/ansible-controller/api/client";
import { hostsManagerClient } from "./modules/hosts-manager/api/client";
import { proxmoxManagerClient } from "./modules/proxmox-manager/api/client";
import { containersClient } from "./modules/containers/api/client";
import { sambaClient } from "./modules/samba/api/client";
import { mountsClient } from "./modules/mounts/api/client";
import { cronClient } from "./modules/cron/api/client";
import { dhcpClient } from "./modules/dhcp/api/client";

export * from "./core/api/contracts";
export { ApiError, login, logout, me, onAuthenticationInvalidated, resetAuthenticationState, setApiBaseUrl } from "./core/api/transport";
export { downloadUrl } from "./modules/files/api/client";
export { apmidClient } from "./modules/apmid/api/client";
export { filesClient } from "./modules/files/api/client";
export { transfersClient } from "./modules/transfers/api/client";
export { activityClient } from "./modules/activity/api/client";
export { settingsClient } from "./modules/settings/api/client";
export { identityClient } from "./modules/identity/api/client";
export { systemClient } from "./modules/system/api/client";
export { logsClient } from "./modules/logs/api/client";
export { networkClient } from "./modules/network/api/client";
export { powerClient } from "./modules/power/api/client";
export { updatesClient } from "./modules/updates/api/client";
export { servicesClient } from "./modules/services/api/client";
export { packageCenterClient } from "./modules/package-center/api/client";
export { moduleCenterClient } from "./modules/module-center/api/client";
export { osRepositoriesClient } from "./modules/os-repositories/api/client";
export { ansibleControllerClient } from "./modules/ansible-controller/api/client";
export { hostsManagerClient } from "./modules/hosts-manager/api/client";
export { proxmoxManagerClient } from "./modules/proxmox-manager/api/client";
export type { ProxmoxConnection, ProxmoxConnectionInput, ProxmoxVm, ProxmoxVmList } from "./modules/proxmox-manager/api/client";
export { containersClient } from "./modules/containers/api/client";
export { sambaClient } from "./modules/samba/api/client";
export { mountsClient } from "./modules/mounts/api/client";
export { cronClient } from "./modules/cron/api/client";
export { dhcpClient } from "./modules/dhcp/api/client";
export type { DhcpBackup, DhcpConfiguration, DhcpDiagnostic, DhcpInterface, DhcpLease, DhcpPlan, DhcpReservation, DhcpStatus, DhcpSubnet, DhcpValidation } from "./modules/dhcp/api/client";

export const api = {
  ...platformClient,
  ...apmidClient,
  ...filesClient,
  ...transfersClient,
  ...activityClient,
  ...settingsClient,
  ...identityClient,
  ...systemClient,
  ...logsClient,
  ...networkClient,
  ...powerClient,
  ...updatesClient,
  ...servicesClient,
  ...packageCenterClient,
  ...moduleCenterClient,
  ...osRepositoriesClient,
  ...ansibleControllerClient,
  ...hostsManagerClient,
  ...proxmoxManagerClient,
  ...containersClient,
  ...sambaClient,
  ...mountsClient,
  ...cronClient,
  ...dhcpClient,
} as const;