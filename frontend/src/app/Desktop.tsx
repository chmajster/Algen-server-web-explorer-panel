import { useEffect } from "react";
import { Desktop as DesktopController } from "./DesktopController";
import type { DesktopProps } from "./desktop/types";
import { ManagedShell } from "./shell/ManagedShell";
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
    <ManagedShell {...props} />
  </>;
}
