"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { dayMonth, inr } from "@/lib/format";
import type { EventListItem } from "@/lib/types";

/** City filter runs in the browser over the already-loaded list: instant, no request. */
export function EventList({ events }: { events: EventListItem[] }) {
  const [city, setCity] = useState("all");
  const cities = useMemo(() => [...new Set(events.map((e) => e.city))].sort(), [events]);
  const shown = city === "all" ? events : events.filter((e) => e.city === city);

  return (
    <>
      {cities.length > 1 && (
        <div className="filters" role="group" aria-label="Filter by city">
          {["all", ...cities].map((c) => (
            <button key={c} type="button" aria-pressed={city === c} onClick={() => setCity(c)}>
              {c === "all" ? "All cities" : c}
            </button>
          ))}
        </div>
      )}
      <div>
        {shown.length === 0 && (
          <p className="empty">No upcoming nights yet. New dates are announced here first.</p>
        )}
        {shown.map((e) => (
          <article className="row" key={e.id}>
            <div className="d">{dayMonth(e.starts_at, e.timezone)}</div>
            <div>
              <h3><Link href={`/events/${e.slug}`}>{e.title}</Link></h3>
              {e.subtitle && <p>{e.subtitle}</p>}
              <small>{e.venue_name}, {e.city}</small>
            </div>
            <div className="r">
              {e.is_sold_out ? <span className="muted">Sold out</span> : e.starting_price_paise != null && <span>From {inr(e.starting_price_paise)}</span>}
              <Link className="pill sm" href={`/events/${e.slug}`}>{e.is_sold_out ? "Details" : "Book"}</Link>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
