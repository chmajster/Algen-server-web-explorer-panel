import {
  Activity,
  Box,
  CircleAlert,
  Clock3,
  Container,
  Download,
  HardDrive,
  Network,
  Package,
  RefreshCw,
  Server,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useRef, type RefObject } from "react";
import type { Translate } from "../../app/types";
import { isActiveAction, type BackgroundAction } from "./types";

function SourceIcon({ source }: { source: BackgroundAction["source"] }) {
  if (source === "upload") return <Upload aria-hidden="true" />;
  if (source === "transfer") return <Download aria-hidden="true" />;
  if (source === "package") return <Package aria-hidden="true" />;
  if (source === "docker") return <Container aria-hidden="true" />;
  if (source === "mount") return <HardDrive aria-hidden="true" />;
  if (source === "ansible") return <Activity aria-hidden="true" />;
  if (source === "hosts") return <Server aria-hidden="true" />;
  if (source === "network") return <Network aria-hidden="true" />;
  if (source === "system") return <RefreshCw aria-hidden="true" />;
  return <Box aria-hidden="true" />;
}

export function ActionsCenter({
  actions,
  locale,
  t,
  triggerRef,
  onOpen,
  onDismiss,
  onClose,
}: {
  actions: BackgroundAction[];
  locale: string;
  t: Translate;
  triggerRef: RefObject<HTMLButtonElement>;
  onOpen: (action: BackgroundAction) => void;
  onDismiss: (key: string) => void;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const timeFormatter = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" });

  useEffect(() => {
    function outside(event: MouseEvent) {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      onClose();
    }
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", keyboard);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", keyboard);
    };
  }, [onClose, triggerRef]);

  useEffect(
    () => () => {
      triggerRef.current?.focus({ preventScroll: true });
    },
    [triggerRef],
  );

  return (
    <aside
      ref={panelRef}
      id="actions-center"
      className="actions-center"
      aria-label={t("actions.backgroundTitle")}
    >
      <header>
        <div>
          <Activity aria-hidden="true" />
          <span>
            <strong>{t("actions.title")}</strong>
            <small>{t("actions.backgroundTitle")}</small>
          </span>
        </div>
        <button type="button" aria-label={t("action.close")} onClick={onClose}>
          <X aria-hidden="true" />
        </button>
      </header>
      <div className="actions-center-list">
        {actions.length === 0 ? (
          <div className="actions-center-empty">
            <Clock3 aria-hidden="true" />
            <strong>{t("actions.empty")}</strong>
            <span>{t("actions.emptyHint")}</span>
          </div>
        ) : (
          actions.map((action) => {
            const progress = action.progress === undefined ? undefined : Math.round(action.progress);
            return (
              <article className={`background-action ${action.status}`} key={action.key}>
                <button
                  type="button"
                  className="background-action-open"
                  aria-label={`${t("actions.openDetails")}: ${action.title}`}
                  onClick={() => onOpen(action)}
                >
                  <span className="background-action-icon">
                    <SourceIcon source={action.source} />
                  </span>
                  <span className="background-action-copy">
                    <span>
                      <strong>{action.title}</strong>
                      <small className={`status-badge ${action.status}`}>{t(`actions.status.${action.status}`)}</small>
                    </span>
                    {action.subtitle && <span>{action.subtitle}</span>}
                    {action.currentStep && <small>{action.currentStep}</small>}
                    <span className={`background-action-progress ${progress === undefined && isActiveAction(action) ? "indeterminate" : ""}`}>
                      <i style={progress === undefined ? undefined : { width: `${progress}%` }} />
                    </span>
                    <span className="background-action-meta">
                      {progress !== undefined && <b>{progress}%</b>}
                      <time dateTime={new Date(action.createdAt).toISOString()}>
                        {t("actions.started")} {timeFormatter.format(action.createdAt)}
                      </time>
                    </span>
                    {action.error && <span className="background-action-error"><CircleAlert aria-hidden="true" />{action.error}</span>}
                  </span>
                </button>
                {!isActiveAction(action) && (
                  <button
                    type="button"
                    className="background-action-dismiss"
                    aria-label={`${t("actions.dismiss")}: ${action.title}`}
                    onClick={() => onDismiss(action.key)}
                  >
                    <X aria-hidden="true" />
                  </button>
                )}
              </article>
            );
          })
        )}
      </div>
    </aside>
  );
}
