import { Desktop as DesktopController } from "./DesktopController";
import { DesktopEnhancements } from "./DesktopEnhancements";
import type { DesktopProps } from "./desktop/types";

/**
 * Desktop composition root.
 *
 * Window state/reducer, registry-backed module rendering, launcher, taskbar,
 * dialogs and widgets remain independent subsystems. The controller owns only
 * the orchestration contract between those existing pieces while this file is
 * the stable application boundary imported by App.
 */
export function Desktop(props: DesktopProps) {
  return <>
    <DesktopController {...props} />
    <DesktopEnhancements profile={props.profile} t={props.t} toast={props.toast} onSettingsChange={props.onSettingsChange} />
  </>;
}
