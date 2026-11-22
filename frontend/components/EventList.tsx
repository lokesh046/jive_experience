"use client";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { dayMonth, inr } from "@/lib/format";
import type { EventListItem } from "@/lib/types";

const fold = (t: string) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

/** What a search can match: the words people would use to look for a night. */
function haystack(e: EventListItem): string {
  const month = new Intl.DateTimeFormat("en-IN", { month: "long", timeZone: e.timezone }).format(new Date(e.starts_at));
  return fold([e.title, e.subtitle, e.venue_name, e.city, e.category.replace(/_/g, " "), month].filter(Boolean).join(" "));
}

/** Search and the city filter run in the browser over the already-loaded list: instant, no request. */
export function EventList({ events }: { events: EventListItem[] }) {
  const [city, setCity] = useState("all");
  const [query, setQuery] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const cities = useMemo(() => [...new Set(events.map((e) => e.city))].sort(), [events]);
  const index = useMemo(() => new Map(events.map((e) => [e.id, haystack(e)])), [events]);

  // A link such as /events?q=jazz starts with that search; /events#search puts the cursor in the box.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    queueMicrotask(() => {
      if (q) setQuery(q.slice(0, 80));
      if (window.location.hash === "#search") input.current?.focus();
    });
  }, []);

  function type(value: string) {
    setQuery(value);
    const url = new URL(window.location.href);
    if (value.trim()) url.searchParams.set("q", value.trim()); else url.searchParams.delete("q");
    window.history.replaceState(null, "", url);
  }

  const words = fold(query).split(/\s+/).filter(Boolean);
  const shown = events
    .filter((e) => city === "all" || e.city === city)
    .filter((e) => words.every((w) => index.get(e.id)?.includes(w)));
  const searching = words.length > 0;

  return (
    <>
      <div className="find" role="search">
        <label htmlFor="event-search" className="sr">Search events</label>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        <input
          id="event-search"
          ref={input}
          type="search"
          value={query}
          onChange={(e) => type(e.target.value)}
          placeholder="Search by event, venue, city or month"
          autoComplete="off"
          maxLength={80}
          enterKeyHint="search"
        />
        {query && <button type="button" className="clear" aria-label="Clear search" onClick={() => { type(""); input.current?.focus(); }}>×</button>}
      </div>
      <p className="sr" role="status" aria-live="polite">{searching ? `${shown.length} ${shown.length === 1 ? "event" : "events"} found` : ""}</p>
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
          searching || city !== "all"
            ? <p className="empty">Nothing matches{searching ? ` “${query.trim()}”` : ""}. <button type="button" className="link" onClick={() => { type(""); setCity("all"); }}>Show all events</button></p>
            : <p className="empty">No upcoming nights yet. New dates are announced here first.</p>
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
