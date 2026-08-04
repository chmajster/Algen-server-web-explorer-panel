import { SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { request } from "../../core/api/transport";
import type { ToastFn, Translate } from "../../app/types";


type UpdateDetailPolicy = {
  policy_id: string;
  detailed_steps: boolean;
  default_detailed_steps: boolean;
};

function languageText() {
  const language = (
    typeof document !== "undefined"
      ? document.documentElement.lang || navigator.language
      : "en"
  ).toLowerCase();
  const polish = language.startsWith("pl");
  return polish
    ? {
        title: "Szczegółowe kroki aktualizacji",
        description: "Pokazuj pełną listę etapów aktualizacji, daty rozpoczęcia, zakończenia i czas trwania.",
        open: "Ustaw widoczność kroków aktualizacji",
        loading: "Wczytywanie policy aktualizacji…",
        saveError: "Nie udało się zapisać policy aktualizacji.",
      }
    : {
        title: "Detailed update steps",
        description: "Show the full update-stage list, start and completion dates, and duration.",
        open: "Configure update-step visibility",
        loading: "Loading update policy…",
        saveError: "Could not save the update policy.",
      };
}

export function UpdateDetailsPolicyControl({
  active,
  t,
  toast,
}: {
  active: boolean;
  t: Translate;
  toast: ToastFn;
}) {
  const text = useMemo(languageText, []);
  const [target, setTarget] = useState<Element | null>(null);
  const [open, setOpen] = useState(false);
  const [policy, setPolicy] = useState<UpdateDetailPolicy | null>(null);
  const [draft, setDraft] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!active) {
      setTarget(null);
      setOpen(false);
      return;
    }

    let currentCount: HTMLElement | null = null;
    const restoreCount = () => {
      if (currentCount?.dataset.updateDetailsOriginalCount !== undefined) {
        currentCount.textContent = currentCount.dataset.updateDetailsOriginalCount;
        delete currentCount.dataset.updateDetailsOriginalCount;
      }
      currentCount = null;
    };

    const resolveTarget = () => {
      const browser = document.querySelector(".settings-content.policy-content .policy-browser");
      const updateGroup = browser?.querySelector(".policy-groups button:first-of-type");
      const list = browser?.querySelector(".policy-list");
      const updatesActive = Boolean(updateGroup?.classList.contains("active") && list);

      if (!updatesActive) {
        restoreCount();
        setTarget(null);
        return;
      }

      const count = list?.querySelector(":scope > header > b") as HTMLElement | null;
      if (count && count !== currentCount) {
        restoreCount();
        currentCount = count;
        currentCount.dataset.updateDetailsOriginalCount = currentCount.textContent || "4";
      }
      if (currentCount) {
        const original = Number(currentCount.dataset.updateDetailsOriginalCount || 4);
        currentCount.textContent = String(Math.max(5, original + 1));
      }

      let host = list?.querySelector("[data-update-details-policy-host]") as HTMLElement | null;
      if (!host && list) {
        host = document.createElement("span");
        host.dataset.updateDetailsPolicyHost = "true";
        host.style.display = "contents";
        list.appendChild(host);
      }
      setTarget(host);
    };

    resolveTarget();
    const observer = new MutationObserver(resolveTarget);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => {
      observer.disconnect();
      restoreCount();
      setTarget(null);
    };
  }, [active]);

  useEffect(() => {
    if (!active) return;
    let live = true;
    setLoading(true);
    request<UpdateDetailPolicy>("/api/admin/system/updates/detail-policy")
      .then((value) => {
        if (!live) return;
        setPolicy(value);
        setDraft(value.detailed_steps);
        setError("");
      })
      .catch((reason) => {
        if (!live) return;
        setError(reason instanceof Error ? reason.message : text.saveError);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [active, text.saveError]);

  async function save() {
    setSaving(true);
    setError("");
    try {
      const updated = await request<UpdateDetailPolicy>("/api/admin/system/updates/detail-policy", {
        method: "PATCH",
        body: JSON.stringify({ detailed_steps: draft }),
      });
      setPolicy(updated);
      setDraft(updated.detailed_steps);
      setOpen(false);
      toast(t("settings.saved"), "ok", "admin");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : text.saveError;
      setError(message);
      toast(message, "error", "admin");
    } finally {
      setSaving(false);
    }
  }

  return <>
    {target && createPortal(
      <button
        type="button"
        className={open ? "active" : ""}
        title={text.open}
        onClick={() => {
          setDraft(policy?.detailed_steps ?? false);
          setOpen(true);
        }}
      >
        <span>
          <strong>{text.title}</strong>
          <small>updates.detailed_steps</small>
        </span>
        <b>{t("settings.oneActiveRule")}</b>
      </button>,
      target,
    )}

    {open && createPortal(
      <div className="modal-backdrop">
        <section
          className="modal-panel"
          role="dialog"
          aria-modal="true"
          aria-labelledby="update-details-policy-title"
        >
          <header className="modal-header">
            <h2 id="update-details-policy-title"><SlidersHorizontal />{text.title}</h2>
            <button
              className="icon-button"
              type="button"
              aria-label={t("action.close")}
              onClick={() => {
                setDraft(policy?.detailed_steps ?? false);
                setOpen(false);
              }}
            >
              <X />
            </button>
          </header>
          <div className="modal-body">
            <p>{text.description}</p>
            <section className="policy-rule-card">
              <header>
                <span className={draft ? "enabled" : "disabled"}>
                  {t(draft ? "common.enabled" : "common.disabled")}
                </span>
                <b>{t("settings.priority")}: 100</b>
              </header>
              <dl>
                <div><dt>ID</dt><dd><code>updates.detailed_steps</code></dd></div>
                <div><dt>{t("settings.defaultValue")}</dt><dd><code>{t("common.disabled")}</code></dd></div>
                <div><dt>{t("settings.value")}</dt><dd><code>{t(draft ? "common.enabled" : "common.disabled")}</code></dd></div>
              </dl>
              <div className="setting-row">
                <span><strong>{text.title}</strong><small>{text.description}</small></span>
                <span className="setting-control">
                  <label className="settings-switch">
                    <input
                      type="checkbox"
                      aria-label={text.title}
                      checked={draft}
                      disabled={loading || saving}
                      onChange={(event) => setDraft(event.target.checked)}
                    />
                    <span aria-hidden="true" />
                  </label>
                </span>
              </div>
            </section>
            {loading && <p className="loading-state">{text.loading}</p>}
            {error && <p className="update-settings-error" role="alert">{error}</p>}
          </div>
          <footer className="modal-footer">
            <button
              type="button"
              disabled={saving}
              onClick={() => {
                setDraft(policy?.detailed_steps ?? false);
                setOpen(false);
              }}
            >
              {t("action.cancel")}
            </button>
            <button
              className="button-primary"
              type="button"
              disabled={loading || saving || !policy}
              onClick={() => void save()}
            >
              {saving ? t("settings.saving") : t("action.save")}
            </button>
          </footer>
        </section>
      </div>,
      document.body,
    )}
  </>;
}
