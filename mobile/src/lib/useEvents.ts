import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { EventListItem, Page } from "./types";

export function useEvents(past = false) {
  const [events, setEvents] = useState<EventListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const page = await api<Page<EventListItem>>(`events?size=50${past ? "&past=true" : ""}`);
      setEvents(page.items); setError(null);
    } catch (e: any) {
      setError(e?.message ?? "Could not load events.");
    }
  }, [past]);

  useEffect(() => { load(); }, [load]);
  const refresh = useCallback(async () => { setRefreshing(true); await load(); setRefreshing(false); }, [load]);
  return { events, error, refreshing, refresh };
}
