"use client";
import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { label, rupees, toPaise, when } from "@/lib/admin";
import { inr } from "@/lib/format";
import { useData } from "@/lib/use-data";
import type { BookingAdmin, EventAdmin, Page, RefundRow } from "@/lib/types";

const STATUSES = ["", "PENDING", "CONFIRMED", "EXPIRED", "CANCELLED", "REFUNDED", "PARTIALLY_REFUNDED"];

export default function Bookings() {
  const [ref, setRef] = useState("");
  const [typed, setTyped] = useState("");
  const [status, setStatus] = useState("");
  const [eventId, setEventId] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const events = useData<Page<EventAdmin>>("admin/events?size=100");
  const q = `admin/bookings?size=20&page=${page}${ref ? `&reference=${encodeURIComponent(ref)}` : ""}${status ? `&status=${status}` : ""}${eventId ? `&event_id=${eventId}` : ""}`;
  const list = useData<Page<BookingAdmin>>(q);
  const titleOf = (id: string) => events.data?.items.find((e) => e.id === id)?.title ?? "Event";
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.size)) : 1;
  const cols = "1.3fr 1.6fr 1fr 0.8fr 1fr";

  return (
    <>
      <div className="ad-head"><h1>Bookings</h1></div>
      <form className="ad-bar" style={{ flexDirection: "row" }} onSubmit={(e) => { e.preventDefault(); setRef(typed.trim()); setPage(1); }}>
        <div className="f"><label htmlFor="r">Reference</label><input id="r" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="JIVE-…" /></div>
        <div className="f"><label htmlFor="ev">Event</label>
          <select id="ev" value={eventId} onChange={(e) => { setEventId(e.target.value); setPage(1); }}><option value="">All events</option>{events.data?.items.map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}</select></div>
        <div className="f"><label htmlFor="bs">Status</label>
          <select id="bs" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>{STATUSES.map((s) => <option key={s} value={s}>{s ? label(s) : "All"}</option>)}</select></div>
        <button className="pill sm" type="submit">Search</button>
      </form>
      {list.error && <p className="err" role="alert">{list.error}</p>}
      {list.loading && <div className="skeleton" style={{ height: 120, marginTop: 24 }} />}
      {list.data && (
        <div className="tbl" role="table" aria-label="Bookings">
          <div className="tr th" style={{ gridTemplateColumns: cols }}><span>Reference</span><span>Event</span><span>Status</span><span className="num">Tickets</span><span className="num">Total</span></div>
          {list.data.items.length === 0 && <p className="empty">No bookings match.</p>}
          {list.data.items.map((b) => (
            <div key={b.id}>
              <button type="button" className="tr" style={{ gridTemplateColumns: cols }} aria-expanded={open === b.id} onClick={() => setOpen(open === b.id ? null : b.id)}>
                <span className="name">{b.reference}</span><span>{titleOf(b.event_id)}</span><span className="status">{label(b.status)}</span><span className="num">{b.quantity}</span><span className="num">{inr(b.total_paise)}</span>
              </button>
              {open === b.id && <Detail booking={b} onChange={list.reload} />}
            </div>
          ))}
        </div>
      )}
      {list.data && pages > 1 && (
        <div className="ad-actions">
          <button className="pill sm ghost" type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="small">Page {page} of {pages} · {list.data.total} bookings</span>
          <button className="pill sm ghost" type="button" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </>
  );
}

function Detail({ booking: b, onChange }: { booking: BookingAdmin; onChange: () => void }) {
  const refunds = useData<RefundRow[]>(`admin/bookings/${b.id}/refunds`);
  const [mode, setMode] = useState<"" | "cancel" | "refund">("");
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canAct = b.status === "CONFIRMED" || b.status === "PARTIALLY_REFUNDED";
  const left = b.total_paise - b.refunded_paise;

  async function run(path: string, json: unknown) {
    setBusy(true); setErr(null);
    try { await api(`admin/bookings/${b.id}/${path}`, { method: "POST", json }); setMode(""); onChange(); refunds.reload(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "That did not work."); }
    finally { setBusy(false); }
  }

  return (
    <div className="drawer">
      <div className="rows" style={{ maxWidth: 560 }}>
        {b.items.map((i) => <div key={i.ticket_category_id}><span className="name">{i.category_name} × {i.quantity}</span><span>{inr(i.line_total_paise)}</span></div>)}
        <div><span>Booked</span><span>{when(b.created_at)}</span></div>
        <div><span>Paid</span><span>{inr(b.total_paise)}</span></div>
        <div><span>Refunded so far</span><span>{inr(b.refunded_paise)}</span></div>
        {b.cancellation_reason && <div><span>Cancelled because</span><span>{b.cancellation_reason}</span></div>}
        {b.customer_note && <div><span>Customer note</span><span>{b.customer_note}</span></div>}
      </div>
      {refunds.data && refunds.data.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <p className="small" style={{ marginBottom: 6 }}>Refunds</p>
          {refunds.data.map((r) => <p key={r.id} className="small">{inr(r.amount_paise)} · {label(r.status)} · {when(r.created_at)}{r.failure_reason ? ` · ${r.failure_reason}` : ""}</p>)}
        </div>
      )}
      {canAct && !mode && (
        <div className="ad-actions">
          <button className="pill sm danger" type="button" onClick={() => setMode("cancel")}>Cancel and refund in full</button>
          {left > 0 && <button className="pill sm ghost" type="button" onClick={() => setMode("refund")}>Partial refund</button>}
        </div>
      )}
      {mode === "cancel" && (
        <div style={{ marginTop: 20, maxWidth: 560 }}>
          <p className="small" style={{ marginBottom: 12 }}>This cancels every ticket in the booking and refunds the full amount paid. The customer&apos;s own cancellation tiers do not apply.</p>
          <div className="f"><label htmlFor={`cr-${b.id}`}>Reason</label><input id={`cr-${b.id}`} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></div>
          <div className="ad-actions"><button className="pill sm danger" type="button" disabled={busy || !reason.trim()} onClick={() => run("cancel", { reason: reason.trim() })}>Cancel booking</button><button className="link" type="button" onClick={() => setMode("")}>Back</button></div>
        </div>
      )}
      {mode === "refund" && (
        <div style={{ marginTop: 20, maxWidth: 560 }}>
          <div className="f"><label htmlFor={`ra-${b.id}`}>Amount (₹), up to {rupees(left)}</label><input id={`ra-${b.id}`} type="number" min="1" step="0.01" max={left / 100} value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
          <div className="f" style={{ marginTop: 20 }}><label htmlFor={`rn-${b.id}`}>Note</label><input id={`rn-${b.id}`} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></div>
          <div className="ad-actions"><button className="pill sm" type="button" disabled={busy || !amount || toPaise(amount) < 100 || toPaise(amount) > left} onClick={() => run("refunds", { amount_paise: toPaise(amount), reason: "ADMIN_CANCELLED", note: reason.trim() || null })}>Refund {amount ? `₹${amount}` : ""}</button><button className="link" type="button" onClick={() => setMode("")}>Back</button></div>
        </div>
      )}
      {err && <p className="err" role="alert">{err}</p>}
    </div>
  );
}
