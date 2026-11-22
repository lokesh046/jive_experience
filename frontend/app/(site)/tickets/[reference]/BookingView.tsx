"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, api, rememberNext } from "@/lib/api-client";
import { eventsById } from "@/lib/events-index";
import { inr, longDate, timeOf } from "@/lib/format";
import type { Booking, EventListItem, RefundQuote, Ticket } from "@/lib/types";

function QrCode({ value }: { value: string }) {
  const [svg, setSvg] = useState("");
  useEffect(() => {
    let live = true;
    // Loaded on demand so the QR library stays out of every other page's bundle.
    import("qrcode").then((m) => m.toString(value, { type: "svg", margin: 0, errorCorrectionLevel: "M" })).then((s) => live && setSvg(s));
    return () => { live = false; };
  }, [value]);
  return <div className="qr" role="img" aria-label="Entry code" dangerouslySetInnerHTML={{ __html: svg }} />;
}

const STATUS: Record<string, string> = { PENDING: "Waiting for payment", CONFIRMED: "Confirmed", EXPIRED: "Not completed", CANCELLED: "Cancelled", REFUNDED: "Cancelled, refunded", PARTIALLY_REFUNDED: "Partly refunded" };

export function BookingView({ reference }: { reference: string }) {
  const router = useRouter();
  const [b, setB] = useState<Booking | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [event, setEvent] = useState<EventListItem | null>(null);
  const [quote, setQuote] = useState<RefundQuote | null>(null);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const booking = await api<Booking>(`bookings/${reference}`);
        if (!live) return;
        setB(booking);
        if (booking.status === "PENDING") { router.replace(`/checkout/${reference}`); return; }
        const [t, ev] = await Promise.all([
          api<Ticket[] | { items: Ticket[] }>(`bookings/${reference}/tickets`).catch(() => []),
          eventsById(),
        ]);
        if (!live) return;
        setTickets(Array.isArray(t) ? t : t.items);
        setEvent(ev.get(booking.event_id) ?? null);
      } catch (e) {
        if (!live) return;
        if (e instanceof ApiError && e.status === 401) { rememberNext(`/tickets/${reference}`); router.replace("/signin"); return; }
        setError(e instanceof ApiError ? e.message : "We could not load this booking.");
      }
    })();
    return () => { live = false; };
  }, [reference, router]);

  // Tickets are issued a moment after payment by a background worker: keep checking until they appear.
  const waiting = !!b && (b.status === "CONFIRMED" || b.status === "PARTIALLY_REFUNDED") && tickets.length === 0;
  const [tries, setTries] = useState(0);
  useEffect(() => {
    if (!waiting || tries >= 40) return;
    const id = setTimeout(async () => {
      try {
        const t = await api<Ticket[] | { items: Ticket[] }>(`bookings/${reference}/tickets`);
        const list = Array.isArray(t) ? t : t.items;
        if (list.length) setTickets(list);
      } catch {}
      setTries((n) => n + 1);
    }, 3000);
    return () => clearTimeout(id);
  }, [waiting, tries, reference]);

  async function ask() {
    setError(null);
    try { setQuote(await api<RefundQuote>(`bookings/${reference}/refund-quote`)); setAsking(true); }
    catch (e) { setError(e instanceof ApiError ? e.message : "We could not work out the refund."); }
  }
  async function cancel() {
    setBusy(true);
    try { setB(await api<Booking>(`bookings/${reference}/cancel`, { method: "POST", json: {} })); setAsking(false); setTickets((t) => t.map((x) => ({ ...x, qr_token: null, status: "CANCELLED" }))); }
    catch (e) { setError(e instanceof ApiError ? e.message : "We could not cancel this booking."); }
    finally { setBusy(false); }
  }

  if (error && !b) return <main className="page"><div className="wrap narrow"><h1>Booking not available</h1><p style={{ margin: "16px 0 36px" }}>{error}</p><Link className="pill" href="/tickets">My tickets</Link></div></main>;
  if (!b) return <main className="page"><div className="wrap"><div className="skeleton" style={{ height: 56, maxWidth: 420 }} /></div></main>;

  const live = b.status === "CONFIRMED" || b.status === "PARTIALLY_REFUNDED";

  return (
    <main className="page">
      <div className="wrap">
        <Link className="link" href="/tickets" style={{ display: "inline-block", marginBottom: 28 }}>← All tickets</Link>
        <h1>{event?.title ?? "Your booking"}</h1>
        {event && (
          <>
            <p style={{ margin: "12px 0 4px" }}>{longDate(event.starts_at, event.timezone)}, {timeOf(event.starts_at, event.timezone)}</p>
            <p className="small">{event.venue_name}, {event.city}</p>
          </>
        )}
        <p className="small" style={{ marginTop: 20 }}>Booking <span style={{ color: "#fff" }}>{b.reference}</span> · {STATUS[b.status] ?? b.status} · {inr(b.total_paise)}</p>

        {tickets.length > 0 ? (
          <div style={{ marginTop: 36 }}>
            {tickets.map((t, n) => {
              const used = t.status === "CHECKED_IN";
              return (
                <div className="tk" key={t.id}>
                  {t.qr_token ? <QrCode value={t.qr_token} /> : <div className="void">{used ? "This ticket has been scanned. The code is no longer shown." : "This ticket is no longer valid."}</div>}
                  <div>
                    <span className="cat">{b.items.find((i) => i.ticket_category_id === t.ticket_category_id)?.category_name ?? "Ticket"}</span>
                    <h3>Ticket {n + 1} of {tickets.length}</h3>
                    <p className="serial" style={{ marginTop: 6 }}>{t.serial}</p>
                    <p className="small" style={{ marginTop: 6 }}>{t.qr_token ? "Valid until the end of the event" : used ? "Used" : "Not valid"}</p>
                  </div>
                </div>
              );
            })}
            {live && <p className="small" style={{ marginTop: 20 }}>Show the code at the gate. Each ticket works once, and a ticket that has been scanned cannot be shown again.</p>}
          </div>
        ) : live ? (
          <div className="notice" style={{ marginTop: 36 }} role="status">
            {tries < 40
              ? <span>Your payment went through. We are preparing your tickets: they will appear here in a few seconds.</span>
              : <span>Your payment went through, but the tickets are taking longer than usual. <button type="button" className="link" onClick={() => setTries(0)}>Check again</button>. If they still do not appear, contact us with booking {b.reference}.</span>}
          </div>
        ) : null}

        {error && <p className="err" role="alert">{error}</p>}

        {live && (
          <div className="dialog">
            {!asking ? (
              <button className="link" type="button" onClick={ask}>Cancel this booking</button>
            ) : quote && (
              <>
                <h3>Cancel this booking?</h3>
                <div className="rows" style={{ margin: "16px 0 24px" }}>
                  {quote.eligible
                    ? <><div><span className="name">Refund</span><span>{inr(quote.amount_paise)}</span></div><div><span>Share of the amount you paid</span><span>{quote.percent}%</span></div></>
                    : <div><span className="name">Refund</span><span>Not available</span></div>}
                </div>
                {!quote.eligible && <p className="small" style={{ marginBottom: 16 }}>{quote.reason}</p>}
                <p className="small" style={{ marginBottom: 24 }}>Cancelling cancels every ticket in this booking. This cannot be undone.</p>
                <button className="pill" type="button" onClick={cancel} disabled={busy}>{busy ? "Cancelling…" : "Cancel booking"}</button>
                <button className="link" type="button" style={{ marginLeft: 20 }} onClick={() => setAsking(false)}>Keep my tickets</button>
              </>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
