import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
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
  retry.textContent = "Retry";
  retry.addEventListener("click", () => window.location.reload());

  container.append(message, retry);
  root.replaceChildren(container);
}

export async function bootstrap() {
  const preferredLanguage = detectLanguage(localStorage.getItem("webnas_language"));
  try {
    await loadLanguageWithFallback(preferredLanguage);
  } catch (error) {
    renderBootstrapError(error);
    return;
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void bootstrap();
