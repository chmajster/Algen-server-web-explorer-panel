import { RefreshCw, ServerCog } from "lucide-react";
import type { Translate } from "./types";
import "./application-restart-screen.css";

export function ApplicationRestartScreen({ elapsedSeconds, t }: { elapsedSeconds: number; t: Translate }) {
  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = String(elapsedSeconds % 60).padStart(2, "0");
  return <div className="application-restart-screen" role="status" aria-live="polite" aria-label={t("updateStatus.phase.restarting")}>
    <section>
      <div className="application-restart-mark"><ServerCog /><span><RefreshCw /></span></div>
      <small>WebNAS</small>
      <h1>{t("updateStatus.phase.restarting")}</h1>
      <p>{t("connection.reconnecting")}</p>
      <div className="application-restart-progress"><span /></div>
      <dl><dt>{t("updateStatus.duration")}</dt><dd>{minutes} min {seconds} s</dd></dl>
      <footer>{t("updateStatus.doNotInterrupt")}</footer>
    </section>
  </div>;
}
