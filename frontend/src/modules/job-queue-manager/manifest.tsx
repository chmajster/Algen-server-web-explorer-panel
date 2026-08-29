import { ListChecks } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { JobQueueManagerApp } from "./JobQueueManagerApp";
const manifest:FrontendModuleManifest={id:"job-queue-manager",labelKey:"Job Queue Manager",icon:<ListChecks/>,category:"system",permission:"jobs.view",minWidth:980,minHeight:620,render:(context)=><JobQueueManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast}/>};
export default manifest;
