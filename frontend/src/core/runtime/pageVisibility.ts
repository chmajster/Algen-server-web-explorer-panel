type VisibilityListener = (visible: boolean) => void;

const listeners = new Set<VisibilityListener>();
let attached = false;

export function pageIsVisible() {
  return typeof document === "undefined" || document.visibilityState === "visible";
}

function notify() {
  const visible = pageIsVisible();
  listeners.forEach((listener) => listener(visible));
}

function attach() {
  if (attached || typeof document === "undefined") return;
  document.addEventListener("visibilitychange", notify);
  attached = true;
}

function detachIfIdle() {
  if (!attached || listeners.size || typeof document === "undefined") return;
  document.removeEventListener("visibilitychange", notify);
  attached = false;
}

export function subscribePageVisibility(listener: VisibilityListener) {
  listeners.add(listener);
  attach();
  return () => {
    listeners.delete(listener);
    detachIfIdle();
  };
}
