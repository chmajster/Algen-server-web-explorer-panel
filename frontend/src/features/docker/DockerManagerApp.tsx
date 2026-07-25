import {
  Archive,
  Boxes,
  Database,
  Gauge,
  HardDrive,
  History,
  Images,
  Network,
  RefreshCw,
  ScrollText,
  ServerCog,
  Settings,
  Stethoscope,
  Store,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  type DockerEngineAction,
  type DockerDashboard as Dashboard,
  type ModuleJob,
} from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { PackageJobDialog } from "../package-center/PackageJobDialog";
import { ComposeManager } from "./ComposeManager";
import { ContainerAppsCatalog } from "./ContainerAppsCatalog";
import { ContainersList } from "./ContainersList";
import { DockerBackups } from "./DockerBackups";
import { DockerDashboard } from "./DockerDashboard";
import { DockerDiagnostics } from "./DockerDiagnostics";
import { DockerEngineSettings } from "./DockerEngineSettings";
import { ImagesManager } from "./ImagesManager";
import { NetworksManager } from "./NetworksManager";
import { RegistryManager } from "./RegistryManager";
import { VolumesManager } from "./VolumesManager";
import { DockerTable, LoadState, errorMessage } from "./shared";
import "./docker-manager.css";

type Section =
  | "dashboard"
  | "containers"
  | "images"
  | "apps"
  | "compose"
  | "volumes"
  | "networks"
  | "registries"
  | "events"
  | "backups"
  | "engine"
  | "diagnostics";

export function DockerManagerApp({
  draftKey,
  permissions,
  t,
  toast,
  onDirtyChange,
}: {
  draftKey?: string;
  permissions: string[];
  t: Translate;
  toast: ToastFn;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [section, setSection] = useState<Section>(() => {
    const saved = draftKey ? sessionStorage.getItem(`${draftKey}:section`) : null;
    const valid: Section[] = ["dashboard", "containers", "images", "apps", "compose", "volumes", "networks", "registries", "events", "backups", "engine", "diagnostics"];
    return valid.includes(saved as Section) ? saved as Section : "dashboard";
  });
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [events, setEvents] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [job, setJob] = useState<ModuleJob | null>(null);
  const [resourceRefresh, setResourceRefresh] = useState(0);
  const [engineAction, setEngineAction] = useState<DockerEngineAction["action"] | null>(null);
  const [prune, setPrune] = useState(false);
  const can = useCallback(
    (permission: string) => permissions.includes(permission),
    [permissions],
  );
  useEffect(() => { if (draftKey) sessionStorage.setItem(`${draftKey}:section`, section); }, [draftKey, section]);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDashboard(await api.dockerDashboard());
      setError("");
      if (section === "events") setEvents((await api.dockerEvents()).items);
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setLoading(false);
    }
  }, [section, t]);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden && section === "dashboard") void load();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [load, section]);
  async function submitEngine(values: Record<string, string>) {
    if (!engineAction) return;
    try {
      const result = await api.dockerEngineAction({
        action: engineAction,
        confirmation: [
          "install",
          "reinstall",
          "update",
          "stop",
          "restart",
          "disable",
        ].includes(engineAction)
          ? `docker:${engineAction}`
          : "",
        pam_password: values.pam_password || null,
      });
      if (result.job) setJob(result.job);
      setEngineAction(null);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  async function submitPrune(values: Record<string, string>) {
    try {
      setJob(
        (
          await api.dockerPrune({
            resources: [
              "containers",
              "images",
              "networks",
              "volumes",
              "build_cache",
            ],
            confirmation: "PRUNE",
            pam_password: values.pam_password,
          })
        ).job,
      );
      setPrune(false);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  const allSections: Array<[Section, React.ReactNode, string]> = [
    ["dashboard", <Gauge />, "docker.view"],
    ["containers", <Boxes />, "docker.view_containers"],
    ["images", <Images />, "docker.view_images"],
    ["apps", <Store />, "docker.view_containers"],
    ["compose", <ScrollText />, "docker.manage_compose"],
    ["volumes", <Database />, "docker.manage_volumes"],
    ["networks", <Network />, "docker.manage_networks"],
    ["registries", <HardDrive />, "docker.manage_registries"],
    ["events", <History />, "docker.view"],
    ["backups", <Archive />, "docker.export_backup"],
    ["engine", <Settings />, "docker.view"],
    ["diagnostics", <Stethoscope />, "docker.diagnostics"],
  ];
  const sections = allSections.filter(([, , permission]) => can(permission));
  const started = (next: ModuleJob) => setJob(next);
  let content: React.ReactNode = null;
  if (section === "dashboard" && dashboard)
    content = (
      <DockerDashboard
        data={dashboard}
        canInstall={can("docker.install_engine")}
        canUpdate={can("docker.update_engine")}
        canStart={can("docker.start_service")}
        canStop={can("docker.stop_service")}
        busy={Boolean(job)}
        t={t}
        onRefresh={() => void load()}
        onEngineAction={setEngineAction}
        canPrune={can("docker.prune")}
        onPrune={() => setPrune(true)}
        onDiagnostics={() => setSection("diagnostics")}
      />
    );
  else if (section === "containers")
    content = (
      <ContainersList
        draftKey={draftKey ? `${draftKey}:create-container` : undefined}
        permissions={permissions}
        t={t}
        toast={toast}
        onJob={started}
      />
    );
  else if (section === "images")
    content = (
      <ImagesManager
        permissions={permissions}
        t={t}
        toast={toast}
        onJob={started}
      />
    );
  else if (section === "apps")
    content = (
      <ContainerAppsCatalog
        permissions={permissions}
        t={t}
        toast={toast}
        onJob={started}
      />
    );
  else if (section === "compose")
    content = (
      <ComposeManager
        permissions={permissions}
        t={t}
        toast={toast}
        onJob={started}
        onDirtyChange={onDirtyChange}
      />
    );
  else if (section === "volumes")
    content = <VolumesManager permissions={permissions} t={t} toast={toast} onJob={started} />;
  else if (section === "networks")
    content = <NetworksManager permissions={permissions} refreshToken={resourceRefresh} t={t} toast={toast} onJob={started} />;
  else if (section === "registries")
    content = <RegistryManager t={t} toast={toast} onJob={started} />;
  else if (section === "events")
    content = (
      <DockerTable
        items={events}
        empty={t("docker.noEvents")}
        columns={[
          { key: "time", label: t("docker.field.time") },
          { key: "Type", label: t("docker.field.type") },
          { key: "Action", label: t("docker.field.action") },
          { key: "Actor", label: t("docker.field.actor") },
        ]}
      />
    );
  else if (section === "backups")
    content = <DockerBackups permissions={permissions} t={t} toast={toast} onJob={started} />;
  else if (section === "engine")
    content = <DockerEngineSettings canEdit={can("docker.update_engine")} t={t} toast={toast} onJob={started} />;
  else if (section === "diagnostics") content = <DockerDiagnostics t={t} />;
  return (
    <>
      <section className="docker-manager">
        <header className="docker-manager-header">
          <div>
            <span className="docker-logo">
              <ServerCog />
            </span>
            <div>
              <h1>{t("docker.title")}</h1>
              <p>{t("docker.subtitle")}</p>
            </div>
          </div>
          <div>
            <button onClick={() => void load()}>
              <RefreshCw />
              {t("action.refresh")}
            </button>
            {can("docker.prune") && (
              <button className="button-danger" onClick={() => setPrune(true)}>
                {t("docker.prune")}
              </button>
            )}
          </div>
        </header>
        <div className="docker-manager-layout">
          <nav aria-label={t("docker.sections")}>
            {sections.map(([name, icon]) => (
              <button
                className={section === name ? "active" : ""}
                key={name}
                onClick={() => setSection(name)}
              >
                {icon}
                <span>{t(`docker.section.${name}`)}</span>
              </button>
            ))}
          </nav>
          <main>
            <LoadState
              loading={loading && section === "dashboard"}
              error={error}
              retry={() => void load()}
              t={t}
            >
              {content}
            </LoadState>
          </main>
        </div>
      </section>
      {job && (
        <PackageJobDialog
          initialJob={job}
          moduleName={t("docker.title")}
          t={t}
          onClose={() => {
            setJob(null);
            setResourceRefresh((current) => current + 1);
            void load();
          }}
        />
      )}
      {engineAction && (
        <AdminActionDialog
          title={t(`docker.engineAction.${engineAction}`)}
          danger={[
            "install",
            "reinstall",
            "update",
            "stop",
            "restart",
            "disable",
          ].includes(engineAction)}
          fields={
            [
              "install",
              "reinstall",
              "update",
              "stop",
              "restart",
              "disable",
            ].includes(engineAction)
              ? [
                  {
                    name: "pam_password",
                    label: t("docker.currentPassword"),
                    type: "password",
                    required: true,
                  },
                ]
              : []
          }
          t={t}
          onClose={() => setEngineAction(null)}
          onSubmit={submitEngine}
        />
      )}
      {prune && (
        <AdminActionDialog
          title={t("docker.prune")}
          danger
          fields={[
            {
              name: "pam_password",
              label: t("docker.currentPassword"),
              type: "password",
              required: true,
            },
          ]}
          t={t}
          onClose={() => setPrune(false)}
          onSubmit={submitPrune}
        />
      )}
    </>
  );
}
