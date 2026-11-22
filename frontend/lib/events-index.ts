import { api } from "./api-client";
import type { EventListItem, Page } from "./types";

let cache: Promise<Map<string, EventListItem>> | null = null;

/**
 * Bookings carry only an event id, so pages that list them look the event up here.
 * One pair of requests per page load. (Cancelled events are not in the public list;
 * a backend `event` summary on bookings would remove this lookup.)
 */
export function eventsById(): Promise<Map<string, EventListItem>> {
  if (!cache) {
    cache = Promise.all([
      api<Page<EventListItem>>("events?size=100").catch(() => ({ items: [] as EventListItem[] })),
      api<Page<EventListItem>>("events?past=true&size=100").catch(() => ({ items: [] as EventListItem[] })),
    ]).then(([a, b]) => new Map([...a.items, ...b.items].map((e) => [e.id, e])));
    cache.catch(() => (cache = null));
  }
  return cache;
}
