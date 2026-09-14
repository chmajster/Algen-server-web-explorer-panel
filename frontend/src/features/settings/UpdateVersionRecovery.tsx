import { useEffect, useRef, useState } from "react";
import { HardDriveDownload, LoaderCircle } from "lucide-react";
import type { Translate } from "../../app/types";
import type { UpdateStart, UpdateVersion } from "../../core/api/contracts";
import { updatesClient } from "../../modules/updates/api/client";

export function UpdateVersionRecovery({ failedUpdateId, disconnected, t, onStarted }: {
  failedUpdateId: string | null;
  disconnected: boolean;
  t: Translate;
  onStarted?: (value: UpdateStart) => void;
}) {
  const [open, setOpen] = useState(false);
  const [versions, setVersions] = useState<UpdateVersion[]>([]);
  const [revision, setRevision] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const selectRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setLoading(true);
    setError("");
    setRevision("");
    setVersions([]);
    void updatesClient.updateVersions().then((items) => {
      if (live) setVersions(items);
    }).catch((reason: unknown) => {
      if (live) setError(reason instanceof Error ? reason.message : t("updateRecovery.loadError"));
    }).finally(() => {
      if (live) setLoading(false);
    });
    return () => { live = false; };
  }, [open, reload, t]);

  useEffect(() => {
    if (open && !loading && versions.length > 0) selectRef.current?.focus();
  }, [open, loading, versions]);

  async function install() {
    const selected = versions.find((item) => item.revision === revision);
    if (!selected || loading || submitting || disconnected || inFlight.current) return;
    const confirmation = t("updateRecovery.confirm").replace("{version}", `${selected.name} (${selected.revision.slice(0, 12)})`);
    if (!window.confirm(confirmation)) return;
    inFlight.current = true;
    setSubmitting(true);
    setError("");
    try {
      const result = await updatesClient.recoverUpdate(selected.revision, failedUpdateId);
      if (!mounted.current) return;
      onStarted?.(result);
      if (!result.ok || result.state === "failed") {
        setError(result.message || t("updateRecovery.installError"));
      } else {
        setOpen(false);
      }
    } catch (reason: unknown) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : t("updateRecovery.installError"));
    } finally {
      inFlight.current = false;
      if (mounted.current) setSubmitting(false);
    }
  }

  return <section className="update-version-recovery" aria-label={t("updateRecovery.title")}>
    <button type="button" disabled={disconnected || submitting} aria-expanded={open} aria-controls="update-version-options" onClick={() => setOpen(!open)}>
      <HardDriveDownload aria-hidden="true" />
      {t("updateRecovery.title")}
    </button>
    {open && <div id="update-version-options" aria-busy={loading || submitting}>
      <p>{t("updateRecovery.description")}</p>
      <p>{t("updateRecovery.warning")}</p>
      {error && <p role="alert">{error}</p>}
      {loading && <p role="status"><LoaderCircle className="spin" aria-hidden="true" />{t("updateRecovery.loading")}</p>}
      {!loading && versions.length === 0 && !error && <p role="status">{t("updateRecovery.empty")}</p>}
      <label htmlFor="update-recovery-version">{t("updateRecovery.version")}</label>
      <select id="update-recovery-version" ref={selectRef} value={revision} disabled={loading || submitting || disconnected || versions.length === 0} onChange={(event) => setRevision(event.target.value)}>
        <option value="">{t("updateRecovery.choose")}</option>
        {versions.map((item) => <option key={item.revision} value={item.revision}>
          {t(`updateRecovery.kind.${item.kind}`)}: {item.name} — {item.revision.slice(0, 12)}{item.published_at ? ` (${item.published_at.slice(0, 10)})` : ""}
        </option>)}
      </select>
      <div className="update-recovery-actions">
        <button type="button" disabled={loading || submitting || disconnected} onClick={() => setReload((value) => value + 1)}>{t("updateRecovery.refresh")}</button>
        <button className="button-primary" type="button" disabled={!revision || loading || submitting || disconnected} onClick={() => void install()}>
          {submitting && <LoaderCircle className="spin" aria-hidden="true" />}
          {t(submitting ? "updateRecovery.starting" : "updateRecovery.install")}
        </button>
      </div>
    </div>}
  </section>;
}
