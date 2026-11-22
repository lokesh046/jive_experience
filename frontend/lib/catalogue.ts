import { cacheLife } from "next/cache";
import { API_V1 } from "./config";
import type { EventDetail, EventListItem, Page } from "./types";

/**
 * Public catalogue reads. Cached on the server, so a spike of visitors costs the
 * backend one request per cache lifetime instead of one per visitor.
 *
 * A failed fetch is cached only briefly, so a backend blip never pins an empty page.
 */
export async function getEvents(): Promise<EventListItem[]> {
  "use cache";
  try {
    const res = await fetch(`${API_V1}/events?size=50`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) throw new Error(String(res.status));
    const page = (await res.json()) as Page<EventListItem>;
    cacheLife("minutes");
    return page.items;
  } catch {
    cacheLife("seconds");
    return [];
  }
}

export async function getEvent(slug: string): Promise<EventDetail | null> {
  "use cache";
  try {
    const res = await fetch(`${API_V1}/events/${encodeURIComponent(slug)}`, { signal: AbortSignal.timeout(5000) });
    if (res.status === 404) {
      cacheLife("minutes");
      return null;
    }
    if (!res.ok) throw new Error(String(res.status));
    cacheLife("minutes");
    return (await res.json()) as EventDetail;
  } catch {
    cacheLife("seconds");
    return null;
  }
}
