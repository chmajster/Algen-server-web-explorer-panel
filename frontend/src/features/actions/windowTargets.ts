import type { WindowDeepLink, WindowInstance } from "../../app/types";
import type { BackgroundAction } from "./types";

function matchingWindow(action: BackgroundAction, window: WindowInstance) {
  if (window.app !== action.target.app) return false;
  if (action.target.app === "module" && window.moduleId !== action.target.moduleId) return false;
  return true;
}

export function actionTargetIsVisible(action: BackgroundAction, windows: WindowInstance[]) {
  return windows.some(
    (window) =>
      matchingWindow(action, window) &&
      !window.minimized &&
      window.deepLink?.actionKey === action.key,
  );
}

export function backgroundOnly(actions: BackgroundAction[], windows: WindowInstance[]) {
  return actions.filter((action) => !actionTargetIsVisible(action, windows));
}

export function deepLinkForAction(action: BackgroundAction): WindowDeepLink {
  return {
    type: action.target.detailType,
    id: action.target.entityId || action.id,
    actionKey: action.key,
    section: action.target.section,
    jobId: action.target.jobId,
    issuedAt: Date.now(),
  };
}
