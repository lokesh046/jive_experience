"use client";
import { useState } from "react";
import { SalesChart } from "@/components/admin/SalesChart";
import { when } from "@/lib/admin";
import { inr } from "@/lib/format";
import { useData } from "@/lib/use-data";
import type { EventAdmin, Page, SalesEventRow, SalesReport } from "@/lib/types";

const RANGES = [7, 30, 90];
const pct = (a: number, b: number) => (b > 0 ? Math.round((a / b) * 100) : 0);

/** CSV cells that start with = + - @ are read as formulas by spreadsheets, so they are defused. */
const cell = (v: string | number) => {
  const t = String(v);
  const safe = /^[=+\-@\t\r]/.test(t) ? `'${t}` : t;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
};

function download(rows: SalesEventRow[], days: number) {
  const head = ["Event", "Starts", "Status", "Tickets sold", "Capacity", "Gross (INR)", "Refunded (INR)", "Net (INR)", "Bookings", "Cancelled bookings", "Checked in"];
  const lines = rows.map((r) => [r.title, r.starts_at, r.status, r.tickets_sold, r.capacity, r.gross_paise / 100, r.refunded_paise / 100, r.net_paise / 100, r.bookings, r.cancelled_bookings, r.checked_in].map(cell).join(","));
  const blob = new Blob([[head.map(cell).join(","), ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `jive-sales-${new Date().toISOString().slice(0, 10)}-${days}d.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export default function Sales() {
  const [days, setDays] = useState(30);
  const [eventId, setEventId] = useState("");
  const events = useData<Page<EventAdmin>>("admin/events?size=100");
  const report = useData<SalesReport>(`admin/reports/sales?days=${days}${eventId ? `&event_id=${eventId}` : ""}`);
  const r = report.data;
  const s = r?.summary;

  return (
    <>
      <div className="ad-head">
        <h1>Sales</h1>
        {r && r.events.length > 0 && <button className="pill sm ghost" type="button" onClick={() => download(r.events, days)}>Download CSV</button>}
      </div>
      <div className="ad-bar" style={{ flexDirection: "row" }}>
        <div className="f"><label htmlFor="se">Event</label>
          <select id="se" value={eventId} onChange={(e) => setEventId(e.target.value)}>
            <option value="">All events</option>
            {events.data?.items.map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}
          </select></div>
        <div className="f"><label htmlFor="sr">Chart range</label>
          <select id="sr" value={days} onChange={(e) => setDays(Number(e.target.value))}>{RANGES.map((d) => <option key={d} value={d}>Last {d} days</option>)}</select></div>
      </div>

      {report.error && <p className="err" role="alert">{report.error}</p>}
      {report.loading && <div className="skeleton" style={{ height: 160, marginTop: 24 }} />}

      {r && s && (
        <>
          <div className="tiles" aria-label="Totals">
            <div><span>Net revenue</span><strong>{inr(s.net_paise)}</strong><small>{inr(s.gross_paise)} sold, {inr(s.refunded_paise)} refunded</small></div>
            <div><span>Tickets sold</span><strong>{s.tickets_sold.toLocaleString("en-IN")}</strong><small>{s.capacity ? `${pct(s.tickets_sold, s.capacity)}% of ${s.capacity.toLocaleString("en-IN")} capacity` : "No capacity set"}</small></div>
            <div><span>Bookings</span><strong>{s.bookings.toLocaleString("en-IN")}</strong><small>{s.cancelled_bookings} cancelled or refunded</small></div>
            <div><span>Checked in</span><strong>{s.checked_in.toLocaleString("en-IN")}</strong><small>{s.tickets_sold ? `${pct(s.checked_in, s.tickets_sold)}% of tickets sold` : "—"}</small></div>
          </div>

          <section className="ad-sec" aria-labelledby="daily-h">
            <h2 id="daily-h">Sales by day</h2>
            <p className="hint" style={{ marginBottom: 16 }}>Money taken each day (before refunds), in India time. The last {r.days} days.</p>
            <SalesChart days={r.daily} />
          </section>

          {r.categories.length > 0 && (
            <section className="ad-sec" aria-labelledby="cat-h">
              <h2 id="cat-h">By ticket type</h2>
              <div className="tbl" role="table" aria-label="Sales by ticket type">
                <div className="tr th" style={{ gridTemplateColumns: "2fr 1fr 1.4fr 1fr" }}><span>Type</span><span className="num">Price</span><span className="num">Sold / capacity</span><span className="num">Sales</span></div>
                {r.categories.map((c) => (
                  <div className="tr" key={c.name} style={{ gridTemplateColumns: "2fr 1fr 1.4fr 1fr" }}>
                    <span><span className="name">{c.name}</span>{!c.is_active && <span className="small"> · hidden</span>}</span>
                    <span className="num">{inr(c.price_paise)}</span>
                    <span className="num">{c.tickets_sold} / {c.capacity} <span className="meter" aria-hidden="true"><i style={{ width: `${pct(c.tickets_sold, c.capacity)}%` }} /></span></span>
                    <span className="num">{inr(c.gross_paise)}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="ad-sec" aria-labelledby="ev-h">
            <h2 id="ev-h">{eventId ? "This event" : "By event"}</h2>
            {r.events.length === 0 && <p className="empty">No published events yet.</p>}
            {r.events.length > 0 && (
              <div className="tbl" role="table" aria-label="Sales by event">
                <div className="tr th sales-row"><span>Event</span><span className="num">Sold / capacity</span><span className="num">Net</span><span className="num">Refunded</span><span className="num">Checked in</span></div>
                {r.events.map((e) => (
                  <div className="tr sales-row" key={e.event_id}>
                    <span><button type="button" className="link name" onClick={() => setEventId(eventId ? "" : e.event_id)}>{e.title}</button><br /><span className="small">{when(e.starts_at)}{e.status === "CANCELLED" ? " · cancelled" : ""}</span></span>
                    <span className="num">{e.tickets_sold} / {e.capacity} <span className="meter" aria-hidden="true"><i style={{ width: `${pct(e.tickets_sold, e.capacity)}%` }} /></span></span>
                    <span className="num">{inr(e.net_paise)}</span>
                    <span className="num">{e.refunded_paise ? inr(e.refunded_paise) : "—"}</span>
                    <span className="num">{e.checked_in}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
