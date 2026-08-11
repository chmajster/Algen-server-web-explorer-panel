import type { AppJob } from "../../api";

export const OPEN_OPERATION_WINDOW_EVENT = "webnas:open-operation-window";

export type OpenOperationWindowDetail = {
  jobId: string;
  moduleId: string;
  moduleName: string;
};

export function requestOperationWindow(job: Pick<AppJob, "id" | "module_id">, moduleName?: string) {
  const event = new CustomEvent<OpenOperationWindowDetail>(OPEN_OPERATION_WINDOW_EVENT, {
    cancelable: true,
    detail: {
      jobId: job.id,
      moduleId: job.module_id,
      moduleName: moduleName || job.module_id,
    },
  });
  return !window.dispatchEvent(event);
}
