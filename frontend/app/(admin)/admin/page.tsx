"use client";
import Link from "next/link";
import { useState } from "react";
import { when, label } from "@/lib/admin";
import { useData } from "@/lib/use-data";
import type { EventAdmin, Page } from "@/lib/types";

const STATUSES = ["", "DRAFT", "PUBLISHED", "SOLD_OUT", "COMPLETED", "CANCELLED"];

export default function AdminEvents() {
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const q = `admin/events?size=100${status ? `&status=${status}` : ""}${search ? `&search=${encodeURIComponent(search)}` : ""}`;
  const { data, error, loading } = useData<Page<EventAdmin>>(q);

  return (
    <>
      <div className="ad-head">
        <h1>Events</h1>
        <Link className="pill" href="/admin/events/new">New event</Link>
      </div>
      <div className="ad-bar">
        <div className="f"><label htmlFor="s">Search</label><input id="s" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Title" /></div>
        <div className="f"><label htmlFor="st">Status</label>
          <select id="st" value={status} onChange={(e) => setStatus(e.target.value)}>{STATUSES.map((s) => <option key={s} value={s}>{s ? label(s) : "All"}</option>)}</select>
        </div>
      </div>
      {error && <p className="err" role="alert">{error}</p>}
      {loading && <div className="skeleton" style={{ height: 120, marginTop: 24 }} />}
      {data && (
        <div className="tbl" role="table" aria-label="Events">
          <div className="tr th" role="row" style={{ gridTemplateColumns: "2fr 1.4fr 1fr 1fr" }}><span>Event</span><span>Date</span><span>Status</span><span className="num">Sold</span></div>
          {data.items.length === 0 && <p className="empty">No events found.</p>}
          {data.items.map((e) => {
            const cap = e.ticket_categories.reduce((s, c) => s + c.capacity, 0);
            const sold = e.ticket_categories.reduce((s, c) => s + c.sold_count, 0);
            return (
              <Link key={e.id} href={`/admin/events/${e.id}`} className="tr" role="row" style={{ gridTemplateColumns: "2fr 1.4fr 1fr 1fr" }}>
                <span><span className="name">{e.title}</span><br /><span className="small">{e.venue.name}, {e.venue.city}</span></span>
                <span>{when(e.starts_at)}</span>
                <span className={`status${e.status === "PUBLISHED" ? " live" : ""}`}>{label(e.status)}</span>
                <span className="num">{sold} / {cap}</span>
              </Link>
            );
          })}
        </div>
      )}
    </>
  );
}
