import { Power, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { Modal } from "../components/Modal";
import type { Translate } from "./types";

type ShutdownStatus = Awaited<ReturnType<typeof api.shutdownStatus>>;

export function ShutdownDialog({ t, onClose }: { t: Translate; onClose: () => void }) {
  const [status, setStatus] = useState<ShutdownStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [detailedInformation, setDetailedInformation] = useState(false);

  useEffect(() => {
    let active = true;
    void api.scheduleShutdown(10).then((value) => { if (active) setStatus(value as ShutdownStatus); }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : t("error.generic")); }).finally(() => { if (active) setBusy(false); });
    void api.shutdownPolicy().then((value) => { if (active) setDetailedInformation(value.detailed_information); }).catch(() => undefined);
    const timer = window.setInterval(() => void api.shutdownStatus().then((value) => { if (active) setStatus(value); }).catch(() => undefined), 500);
    return () => { active = false; window.clearInterval(timer); };
  }, [t]);

  async function cancel() {
    setBusy(true);
    try { await api.cancelShutdown(); onClose(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); setBusy(false); }
  }

  async function now() {
    setBusy(true); setError("");
    try { setStatus(await api.scheduleShutdown(0) as ShutdownStatus); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setBusy(false); }
  }

  const waiting = status?.state === "waiting_for_transfers" || Boolean(status?.blocker_count && status.remaining_seconds === 0);
  const message = waiting
    ? t("shutdown.waitingForTransfers").replace("{count}", String(status?.blocker_count || 0))
    : status?.state === "shutting_down" ? t("shutdown.inProgress")
    : t("shutdown.countdown").replace("{seconds}", String(status?.remaining_seconds ?? 10));

  return <Modal title={t("shutdown.title")} closeLabel={t("action.cancel")} onClose={() => void cancel()} footer={<><button type="button" disabled={busy || status?.state === "shutting_down"} onClick={() => void cancel()}>{t("action.cancel")}</button><button type="button" className="button-danger" disabled={busy || status?.state === "shutting_down"} onClick={() => void now()}><Power />{t("shutdown.now")}</button></>}>
    <div className="shutdown-dialog"><TriangleAlert /><div><p>{message}</p><small>{t("shutdown.transferSafety")}</small>{detailedInformation && <dl className="shutdown-details"><div><dt>{t("shutdown.detail.status")}</dt><dd>{t(`shutdown.state.${status?.state || "loading"}`)}</dd></div><div><dt>{t("shutdown.detail.deadline")}</dt><dd>{status?.deadline ? new Date(status.deadline * 1000).toLocaleTimeString() : "—"}</dd></div><div><dt>{t("shutdown.detail.blockers")}</dt><dd>{status?.blocker_count || 0}</dd></div><div><dt>{t("shutdown.detail.command")}</dt><dd><code>systemctl poweroff</code></dd></div><div><dt>{t("shutdown.detail.immediate")}</dt><dd>{t("shutdown.detail.immediateHint")}</dd></div></dl>}{error && <p className="error-state compact-error" role="alert">{error}</p>}</div></div>
  </Modal>;
}
