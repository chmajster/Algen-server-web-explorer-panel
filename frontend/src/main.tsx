import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { SystemContextMenuHost } from "./components/SystemContextMenuHost";
import { detectLanguage, loadLanguageWithFallback } from "./i18n";
import "./styles/app.css";
import "./styles/design-system.css";
import "./styles/update-transition-fix.css";
import "./styles/dsm.css";
import "./styles/dialog-compat.css";
import "./styles/ui-consistency.css";
import "./styles/ui-feature-consistency.css";
import "./styles/ui-specialized-consistency.css";
import "./styles/ui-review-fixes.css";
import "./styles/mobile-shell.css";
import "./styles/shell-taskbar.css";
import "./styles/visual-regressions.css";

function renderBootstrapError(error: unknown) {
  console.error("WebNAS bootstrap failed", error);
  const root = document.getElementById("root");
  if (!root) return;
  const container = document.createElement("div");
  container.className = "boot-screen";
  container.setAttribute("role", "alert");

  const message = document.createElement("span");
  message.textContent = "WebNAS could not load language resources.";
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "button button-primary boot-retry";
  retry.textContent = "Retry";
  retry.addEventListener("click", () => window.location.reload());

  container.append(message, retry);
  root.replaceChildren(container);
}

function installThemeColorSync() {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  const root = document.getElementById("root");
  if (!meta || !root) return;

  const update = () => {
    const desktop = root.querySelector<HTMLElement>(".desktop");
    meta.content = desktop?.classList.contains("dark") ? "#20252a" : "#f4f5f6";
  };

  update();
  const observer = new MutationObserver(update);
  observer.observe(root, { attributes: true, attributeFilter: ["class"], childList: true, subtree: true });
}

export async function bootstrap() {
  const preferredLanguage = detectLanguage(localStorage.getItem("webnas_language"));
  try {
    await loadLanguageWithFallback(preferredLanguage);
  } catch (error) {
    renderBootstrapError(error);
    return;
  }
  installThemeColorSync();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
      <SystemContextMenuHost />
    </StrictMode>,
  );
}

void bootstrap();
