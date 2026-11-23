"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Photo } from "@/components/Photo";
import { ApiError, api, rememberNext } from "@/lib/api-client";
import { eventsById } from "@/lib/events-index";
import { dayMonth, inr } from "@/lib/format";
import type { Booking, EventListItem, Page } from "@/lib/types";

const LABEL: Record<string, string> = {
  PENDING: "Waiting for payment",
  CONFIRMED: "Confirmed",
  EXPIRED: "Not completed",
  CANCELLED: "Cancelled",
  REFUNDED: "Cancelled, refunded",
  PARTIALLY_REFUNDED: "Partly refunded",
};

export function MyTickets() {
  const router = useRouter();
  const [rows, setRows] = useState<Booking[] | null>(null);
  const [events, setEvents] = useState<Map<string, EventListItem>>(new Map());
  const [now, setNow] = useState(0);
  const [tab, setTab] = useState<"up" | "past">("up");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([api<Page<Booking>>("bookings?size=50"), eventsById()])
      .then(([b, ev]) => { if (live) { setNow(Date.now()); setRows(b.items); setEvents(ev); } })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) { rememberNext("/tickets"); router.replace("/signin"); return; }
        if (live) setError(e instanceof ApiError ? e.message : "We could not load your bookings.");
      });
    return () => { live = false; };
  }, [router]);

  const isUpcoming = (b: Booking) => {
    if (b.status === "CANCELLED" || b.status === "REFUNDED" || b.status === "EXPIRED") return false;
    const ev = events.get(b.event_id);
    return ev ? new Date(ev.starts_at).getTime() >= now : b.status === "CONFIRMED" || b.status === "PENDING";
  };
  const shown = (rows ?? []).filter((b) => (tab === "up" ? isUpcoming(b) : !isUpcoming(b)));

  return (
    <main className="page">
      <div className="wrap">
        <h1>My tickets</h1>
        <p className="sub" style={{ margin: "12px 0 0" }}>{rows === null ? " " : rows.length === 0 ? "Your bookings will appear here." : `${rows.length} booking${rows.length === 1 ? "" : "s"}`}</p>
        <div className="tabs" role="tablist" aria-label="Bookings">
          <button role="tab" type="button" aria-selected={tab === "up"} onClick={() => setTab("up")}>Upcoming</button>
          <button role="tab" type="button" aria-selected={tab === "past"} onClick={() => setTab("past")}>Past</button>
        </div>
        {error && <p className="err" role="alert">{error}</p>}
        {rows === null && !error && <div className="skeleton" style={{ height: 96, marginTop: 24 }} />}
        {rows && shown.length === 0 && (
          <p className="empty">{tab === "up" ? <>Nothing booked yet. <Link className="link" href="/#events">See what is on</Link>.</> : "No past bookings."}</p>
        )}
        <div className="mt-list">
          {shown.map((b) => {
            const ev = events.get(b.event_id);
            const pending = b.status === "PENDING";
            const href = pending ? `/checkout/${b.reference}` : `/tickets/${b.reference}`;
            const tone = b.status === "CONFIRMED" || b.status === "PARTIALLY_REFUNDED" ? "good" : pending ? "wait" : "off";
            return (
              <Link className="mt-card" href={href} key={b.id}>
                <div className="mt-img">
                  {ev?.thumbnail_image_url && <Photo src={ev.thumbnail_image_url} alt="" sizes="(max-width: 700px) 100vw, 220px" />}
                  <span className="mt-date">{ev ? dayMonth(ev.starts_at, ev.timezone) : b.reference}</span>
                </div>
                <div className="mt-body">
                  <span className={`stchip ${tone}`}>{LABEL[b.status] ?? b.status}</span>
                  <h3>{ev?.title ?? "Booking"}</h3>
                  {ev && <p className="small">{ev.venue_name}, {ev.city}</p>}
                  <ul className="cats" aria-label="Ticket types">
                    {b.items.map((i) => <li key={i.ticket_category_id}><b>{i.category_name}</b> × {i.quantity}</li>)}
                  </ul>
                </div>
                <div className="mt-side">
                  <strong>{inr(b.total_paise)}</strong>
                  <span className="mt-go">{pending ? "Complete payment" : "View tickets"} <i aria-hidden="true">→</i></span>
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </main>
  );
}
