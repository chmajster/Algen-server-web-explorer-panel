import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import "./styles/app.css";
import "./styles/update-transition-fix.css";
import "./styles/dsm.css";
import "./styles/ui-consistency.css";
import "./styles/ui-feature-consistency.css";
import "./styles/ui-specialized-consistency.css";
import "./styles/ui-review-fixes.css";

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
