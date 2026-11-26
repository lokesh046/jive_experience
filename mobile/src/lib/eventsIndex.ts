import { api } from "./api";
import type { EventListItem, Page } from "./types";

let cache: { at: number; map: Map<string, EventListItem> } | null = null;

/** Every event we can show, upcoming and past, by id. Bookings only carry the event's id. */
export async function eventsById(force = false): Promise<Map<string, EventListItem>> {
  if (!force && cache && Date.now() - cache.at < 60_000) return cache.map;
  const [up, past] = await Promise.all([
    api<Page<EventListItem>>("events?size=50"),
    api<Page<EventListItem>>("events?past=true&size=50").catch(() => ({ items: [] as EventListItem[] })),
  ]);
  const map = new Map<string, EventListItem>();
  for (const e of [...past.items, ...up.items]) map.set(e.id, e);
  cache = { at: Date.now(), map };
  return map;
}
