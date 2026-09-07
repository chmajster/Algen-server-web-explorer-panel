import { useEffect } from "react";
import { Desktop as DesktopController } from "./DesktopController";
import { DesktopEnhancements } from "./DesktopEnhancements";
import type { DesktopProps } from "./desktop/types";
import { WebNAS } from "./shell/WebNASShell";

/**
 * Desktop composition root.
 *
 * Window state/reducer, registry-backed module rendering, launcher, taskbar,
 * dialogs and widgets remain independent subsystems. The controller owns only
 * the orchestration contract between those existing pieces while this file is
 * the stable application boundary imported by App.
 *
 * The WebNAS runtime is installed here so system-wide layers and public shell
 * services have one lifecycle boundary instead of being owned by individual
 * applications.
 */
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
  </>;
}
