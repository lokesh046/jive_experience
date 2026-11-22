import { cacheLife, cacheTag } from "next/cache";
import { API_V1 } from "./config";
import type { Policy } from "./policy";
import type { EventDetail, EventListItem, Page } from "./types";

/**
 * Public catalogue reads. Cached on the server, so a spike of visitors costs the
 * backend one request per cache lifetime instead of one per visitor.
 *
 * A failed fetch is cached only briefly, so a backend blip never pins an empty page.
 */
export async function getEvents(): Promise<EventListItem[]> {
  "use cache";
  cacheTag("events");
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

/** Events that have already started, most recent first. */
export async function getPastEvents(): Promise<EventListItem[]> {
  "use cache";
  cacheTag("events");
  try {
    const res = await fetch(`${API_V1}/events?past=true&size=50`, { signal: AbortSignal.timeout(5000) });
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
  cacheTag("events");
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

export interface Artist { name: string; note: string; img: string; slug: string }

/** Performers with a photo across the upcoming events, for the homepage: one card per person, soonest event first. */
export async function getArtists(events: EventListItem[]): Promise<Artist[]> {
  const details = await Promise.all(events.slice(0, 8).map((e) => getEvent(e.slug)));
  const seen = new Set<string>();
  const out: Artist[] = [];
  for (const d of details) {
    for (const p of d?.lineup ?? []) {
      if (!p.photo_url) continue; // the homepage cards are photo-led
      const key = p.name.trim().toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ name: p.name, note: p.role ?? "", img: p.photo_url, slug: d!.slug });
    }
  }
  return out.slice(0, 8);
}

/** The default cancellation and refund policy, or null when the company has not set one. */
export async function getDefaultPolicy(): Promise<Policy | null> {
  "use cache";
  cacheTag("events");
  try {
    const res = await fetch(`${API_V1}/system/policy/cancellation`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) throw new Error(String(res.status));
    const body = (await res.json()) as { policy: Policy | null };
    cacheLife("minutes");
    return body.policy;
  } catch {
    cacheLife("seconds");
    return null;
  }
}
