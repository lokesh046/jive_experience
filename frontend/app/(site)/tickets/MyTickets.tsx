"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
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
        <div className="tabs" role="tablist" aria-label="Bookings">
          <button role="tab" type="button" aria-selected={tab === "up"} onClick={() => setTab("up")}>Upcoming</button>
          <button role="tab" type="button" aria-selected={tab === "past"} onClick={() => setTab("past")}>Past</button>
        </div>
        {error && <p className="err" role="alert">{error}</p>}
        {rows === null && !error && <div className="skeleton" style={{ height: 96, marginTop: 24 }} />}
        {rows && shown.length === 0 && (
          <p className="empty">{tab === "up" ? <>Nothing booked yet. <Link className="link" href="/#events">See what is on</Link>.</> : "No past bookings."}</p>
        )}
        {shown.map((b) => {
          const ev = events.get(b.event_id);
          const href = b.status === "PENDING" ? `/checkout/${b.reference}` : `/tickets/${b.reference}`;
          return (
            <Link className="bk" href={href} key={b.id}>
              <div className="d">{ev ? dayMonth(ev.starts_at, ev.timezone) : b.reference}</div>
              <div>
                <h3>{ev?.title ?? "Booking"}</h3>
                <p className="small" style={{ marginTop: 4 }}>
                  {ev ? `${ev.venue_name}, ${ev.city} · ` : ""}{b.items.map((i) => `${i.quantity} × ${i.category_name}`).join(", ")}
                </p>
              </div>
              <div className="r">{inr(b.total_paise)}<span>{LABEL[b.status] ?? b.status}</span></div>
            </Link>
          );
        })}
      </div>
    </main>
  );
}
