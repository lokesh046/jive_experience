import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { api } from "./api";
import { endsAt, isLive, loadBundle, loadMyBookings, prefetchTickets } from "./offline";
import type { Booking, EventDetail, EventListItem, Venue } from "./types";

export interface EventDay { booking: Booking; event: EventListItem; venue: Venue | null; offline: boolean }

const sameDay = (a: number, b: number, zone: string) => {
  const f = (ms: number) => new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(ms));
  return f(a) === f(b);
};

/** The night the person has a ticket for today, or is at right now. The soonest one wins. */
export function pickEventDay(bookings: Booking[], events: Map<string, EventListItem>, now: number) {
  let best: { booking: Booking; event: EventListItem; start: number } | null = null;
  for (const booking of bookings) {
    if (!isLive(booking)) continue;
    const event = events.get(booking.event_id);
    if (!event) continue;
    const start = new Date(event.starts_at).getTime();
    if (now > endsAt(event)) continue;                              // it is over
    if (!(now >= start || sameDay(start, now, event.timezone))) continue; // not today
    if (!best || start < best.start) best = { booking, event, start };
  }
  return best;
}

/** Works with no signal too: the bookings and the venue come from what the phone saved. */
export function useEventDay() {
  const [day, setDay] = useState<EventDay | null>(null);

  useFocusEffect(useCallback(() => {
    let live = true;
    (async () => {
      try {
        const r = await loadMyBookings();
        const pick = pickEventDay(r.bookings, r.events, Date.now());
        if (!pick) { if (live) setDay(null); return; }
        let venue = (await loadBundle(pick.booking.reference))?.venue ?? null;
        if (!venue && !r.offline) {
          try { venue = (await api<EventDetail>(`events/${pick.event.slug}`)).venue; } catch {}
        }
        if (live) setDay({ booking: pick.booking, event: pick.event, venue, offline: r.offline });
        if (!r.offline) void prefetchTickets(r.bookings, r.events);
      } catch { if (live) setDay(null); }
    })();
    return () => { live = false; };
  }, []));

  return day;
}
