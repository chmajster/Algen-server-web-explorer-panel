import { Images } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const ImageConverterApp = lazy(() => import("./ImageConverterApp").then((loaded) => ({ default: loaded.ImageConverterApp })));

const manifest: FrontendModuleManifest = {
  id: "image-converter",
  moduleId: "image-converter",
  labelKey: "module.imageConverter",
  icon: <Images />,
  category: "tools",
  permission: "image_converter.view",
  dependencies: [],
  minWidth: 860,
  minHeight: 600,
  render: (context) => lazyView(
    <ImageConverterApp homePath={context.user.home} permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
