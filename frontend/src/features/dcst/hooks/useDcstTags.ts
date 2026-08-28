import { useState } from "react";
import { dcstClient } from "../api/client";
import type { DcstTag } from "../api/types";

export function useDcstTags({ refresh, onError, onSuccess }: {
  refresh: () => Promise<void>;
  onError: (error: unknown) => void;
  onSuccess: (message: string) => void;
}) {
  const [details, setDetails] = useState<DcstTag | null>(null);
  async function synchronize() {
    try { await dcstClient.syncTags(false); await refresh(); onSuccess("DCST inventory synchronized"); }
    catch (error) { onError(error); }
  }
  return { details, setDetails, synchronize };
}
