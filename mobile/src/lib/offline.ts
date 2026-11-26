import AsyncStorage from "@react-native-async-storage/async-storage";
import { ApiError, api } from "./api";
import { eventsById } from "./eventsIndex";
import type { AuthUser, Booking, EventDetail, EventListItem, Page, Ticket, Venue } from "./types";

/**
 * Booked tickets kept on the phone, so a QR opens with no signal. Venues in old mills and vaults
 * often have none. Only bookings that are still worth showing are kept, and everything is wiped
 * when the person signs out.
 */
const BUNDLES = "jive_offline_bundles_v1";
const LIST = "jive_offline_list_v1";
const USER = "jive_offline_user_v1";
const MAX_BUNDLES = 30;
const FRESH_MS = 5 * 60_000;

export interface Bundle {
  reference: string;
  booking: Booking;
  tickets: Ticket[];
  event: EventListItem | null;
  venue: Venue | null;
  prices: number[];
  savedAt: number;
}

/** True when the request failed because there is no connection, not because the server said no. */
export const isOffline = (e: unknown) => e instanceof ApiError && e.status === 0;

async function readBundles(): Promise<Record<string, Bundle>> {
  try {
    const raw = await AsyncStorage.getItem(BUNDLES);
    return raw ? (JSON.parse(raw) as Record<string, Bundle>) : {};
  } catch { return {}; }
}

export async function saveBundle(b: Omit<Bundle, "savedAt">) {
  try {
    const all = await readBundles();
    all[b.reference] = { ...b, savedAt: Date.now() };
    const keys = Object.keys(all);
    if (keys.length > MAX_BUNDLES) {
      keys.sort((x, y) => all[x].savedAt - all[y].savedAt).slice(0, keys.length - MAX_BUNDLES).forEach((k) => delete all[k]);
    }
    await AsyncStorage.setItem(BUNDLES, JSON.stringify(all));
  } catch { /* the cache is a convenience; never break the screen over it */ }
}

export async function loadBundle(reference: string): Promise<Bundle | null> {
  return (await readBundles())[reference] ?? null;
}

interface SavedList { bookings: Booking[]; events: EventListItem[]; savedAt: number }

async function saveList(bookings: Booking[], events: EventListItem[]) {
  try { await AsyncStorage.setItem(LIST, JSON.stringify({ bookings, events, savedAt: Date.now() } satisfies SavedList)); } catch {}
}
async function loadList(): Promise<SavedList | null> {
  try { const raw = await AsyncStorage.getItem(LIST); return raw ? (JSON.parse(raw) as SavedList) : null; } catch { return null; }
}

export async function clearOffline() {
  try { await AsyncStorage.multiRemove([BUNDLES, LIST, USER]); } catch {}
}

/** Who was signed in, so the app can open with no signal instead of asking to sign in again. */
export async function saveUser(u: AuthUser) { try { await AsyncStorage.setItem(USER, JSON.stringify(u)); } catch {} }
export async function loadUser(): Promise<AuthUser | null> {
  try { const raw = await AsyncStorage.getItem(USER); return raw ? (JSON.parse(raw) as AuthUser) : null; } catch { return null; }
}

export interface MyBookings { bookings: Booking[]; events: Map<string, EventListItem>; offline: boolean; savedAt?: number }

/** The person's bookings: from the server when there is a connection, else what was saved last time. */
export async function loadMyBookings(force = false): Promise<MyBookings> {
  try {
    const [b, ev] = await Promise.all([api<Page<Booking>>("bookings?size=50"), eventsById(force)]);
    void saveList(b.items, [...ev.values()]);
    return { bookings: b.items, events: ev, offline: false };
  } catch (e) {
    if (isOffline(e)) {
      const c = await loadList();
      if (c) return { bookings: c.bookings, events: new Map(c.events.map((x) => [x.id, x])), offline: true, savedAt: c.savedAt };
    }
    throw e;
  }
}

const DEFAULT_LENGTH_MS = 5 * 60 * 60 * 1000;
export const endsAt = (e: EventListItem & { ends_at?: string | null }) =>
  e.ends_at ? new Date(e.ends_at).getTime() : new Date(e.starts_at).getTime() + DEFAULT_LENGTH_MS;
export const isLive = (b: Booking) => b.status === "CONFIRMED" || b.status === "PARTIALLY_REFUNDED";

/** Save the tickets of every booking still to come, so they open without a signal. */
export async function prefetchTickets(bookings: Booking[], events: Map<string, EventListItem>) {
  const all = await readBundles();
  const now = Date.now();
  const want = bookings.filter((b) => isLive(b) && (events.get(b.event_id) ? endsAt(events.get(b.event_id)!) > now : true)).slice(0, 8);
  for (const b of want) {
    const have = all[b.reference];
    if (have && have.tickets.length && now - have.savedAt < FRESH_MS) continue;
    try {
      const t = await api<Ticket[] | { items: Ticket[] }>(`bookings/${b.reference}/tickets`);
      const tickets = Array.isArray(t) ? t : t.items;
      const ev = events.get(b.event_id) ?? null;
      let venue = have?.venue ?? null;
      let prices = have?.prices ?? [];
      if (ev) {
        try {
          const d = await api<EventDetail>(`events/${ev.slug}`);
          venue = d.venue;
          prices = d.ticket_categories.map((c) => c.price_paise);
        } catch {}
      }
      await saveBundle({ reference: b.reference, booking: b, tickets, event: ev, venue, prices });
    } catch (e) { if (isOffline(e)) return; }
  }
}
