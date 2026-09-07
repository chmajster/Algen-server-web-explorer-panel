import { DesktopEnhancements } from "../DesktopEnhancements";
import { DesktopWorkspacePortal } from "../DesktopWorkspacePortal";
import type { DesktopProps } from "../desktop/types";
import { DesktopContextBridge } from "./DesktopContextBridge";
import { ShellStateController } from "./ShellStateController";
import { StartGlobalSearchBridge } from "./StartGlobalSearchBridge";
import { SystemSearchProviders } from "./SystemSearchProviders";

export function ManagedShell(props: DesktopProps) {
  return <>
    <DesktopEnhancements profile={props.profile} t={props.t} toast={props.toast} onSettingsChange={props.onSettingsChange} />
    <DesktopWorkspacePortal {...props} />
    <DesktopContextBridge />
    <SystemSearchProviders profile={props.profile} />
    <StartGlobalSearchBridge />
    <ShellStateController />
  </>;
}
