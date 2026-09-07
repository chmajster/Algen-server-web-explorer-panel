import { useEffect } from "react";
import { SystemContextMenuHost } from "../components/SystemContextMenuHost";
import { Desktop as DesktopController } from "./DesktopController";
import { DesktopEnhancements } from "./DesktopEnhancements";
import { DesktopWorkspacePortal } from "./DesktopWorkspacePortal";
import type { DesktopProps } from "./desktop/types";
import { DesktopContextBridge } from "./shell/DesktopContextBridge";
import { ShellStateController } from "./shell/ShellStateController";
import { StartGlobalSearchBridge } from "./shell/StartGlobalSearchBridge";
import { SystemSearchProviders } from "./shell/SystemSearchProviders";
import { WebNAS } from "./shell/WebNASShell";

/** Desktop composition root and lifecycle boundary for the managed WebNAS Shell. */
export function Desktop(props: DesktopProps) {
  useEffect(() => {
    WebNAS.install();
    window.WebNAS = WebNAS;
    return () => {
      if (window.WebNAS === WebNAS) delete window.WebNAS;
      WebNAS.uninstall();
    };
  }, []);

  return <>
    <DesktopController {...props} />
    <DesktopEnhancements profile={props.profile} t={props.t} toast={props.toast} onSettingsChange={props.onSettingsChange} />
    <DesktopWorkspacePortal {...props} />
    <DesktopContextBridge />
    <SystemSearchProviders profile={props.profile} />
    <StartGlobalSearchBridge />
    <ShellStateController />
    <SystemContextMenuHost />
  </>;
}
