import { useCallback, useEffect, useState } from "react";
import { dcstClient } from "../api/client";
import type { DcstIPSet, DcstOverview, DcstPort, DcstService, DcstTag } from "../api/types";

export function useDcstOverview(onError: (error: unknown) => void) {
  const [overview, setOverview] = useState<DcstOverview | null>(null);
  const [services, setServices] = useState<DcstService[]>([]);
  const [tags, setTags] = useState<DcstTag[]>([]);
  const [ipsets, setIPSets] = useState<DcstIPSet[]>([]);
  const [ports, setPorts] = useState<DcstPort[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async (initial = false) => {
    if (initial) setLoading(true); else setRefreshing(true);
    try {
      const [nextOverview, nextServices, nextTags, nextIPSets, nextPorts] = await Promise.all([
        dcstClient.overview(), dcstClient.services(), dcstClient.tags(), dcstClient.ipsets(), dcstClient.ports(),
      ]);
      setOverview(nextOverview);
      setServices(nextServices);
      setTags(nextTags);
      setIPSets(nextIPSets);
      setPorts(nextPorts);
    } catch (error) {
      onError(error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [onError]);

  useEffect(() => { void refresh(true); }, [refresh]);

  return { overview, services, tags, ipsets, ports, loading, refreshing, refresh };
}
