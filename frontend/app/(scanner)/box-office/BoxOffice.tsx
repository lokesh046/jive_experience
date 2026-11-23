"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { inr } from "@/lib/format";
import { loadRazorpay, type RazorpayResponse } from "@/lib/razorpay";
import type { AssignedEvent, Booking, CheckoutResponse, EventDetail, Ticket } from "@/lib/types";

type Method = "CASH" | "ONLINE";
type Step = "sell" | "collect" | "paying" | "tickets";
interface SaleOut { booking: Booking; tickets: Ticket[] }
interface SellerRow { seller_id: string; seller_name: string | null; cash_tickets: number; cash_paise: number; online_tickets: number; online_paise: number }

function Qr({ value }: { value: string }) {
  const [svg, setSvg] = useState("");
  useEffect(() => {
    let live = true;
    import("qrcode").then((m) => m.toString(value, { type: "svg", margin: 0, errorCorrectionLevel: "M" })).then((s) => live && setSvg(s));
    return () => { live = false; };
  }, [value]);
  return <div className="bo-qr" role="img" aria-label="Ticket QR code" dangerouslySetInnerHTML={{ __html: svg }} />;
}

export function BoxOffice() {
  const [events, setEvents] = useState<AssignedEvent[] | null>(null);
  const [event, setEvent] = useState<AssignedEvent | null>(null);
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [cat, setCat] = useState<string | null>(null);
  const [qty, setQty] = useState(1);
  const [method, setMethod] = useState<Method>("CASH");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [step, setStep] = useState<Step>("sell");
  const [booking, setBooking] = useState<Booking | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sales, setSales] = useState<SellerRow[]>([]);
  const poll = useRef(0);

  useEffect(() => {
    api<AssignedEvent[]>("scanner/events")
      .then((l) => { setEvents(l); if (l.length === 1) setEvent(l[0]); })
      .catch((e) => { setEvents([]); setError(e instanceof ApiError ? e.message : "Could not load your events."); });
  }, []);

  const loadSales = useCallback((id: string) => {
    api<SellerRow[]>(`box-office/events/${id}/summary`).then(setSales).catch(() => {});
  }, []);

  useEffect(() => {
    if (!event) return;
    api<EventDetail>(`events/${event.slug}`).then((d) => {
      setDetail(d);
      const open = d.ticket_categories.find((c) => !c.is_sold_out);
      setCat(open?.id ?? null);
    }).catch(() => setError("Could not load this event's tickets."));
    loadSales(event.event_id);
  }, [event, loadSales]);

  const chosen = detail?.ticket_categories.find((c) => c.id === cat) ?? null;
  const total = chosen ? chosen.price_paise * qty : 0;

  // Wait for the worker to issue the tickets, then show them.
  const waitForTickets = useCallback(async (reference: string) => {
    const run = ++poll.current;
    for (let i = 0; i < 30 && run === poll.current; i++) {
      try {
        const r = await api<SaleOut>(`box-office/bookings/${reference}`);
        if (r.tickets.length > 0) { setBooking(r.booking); setTickets(r.tickets); setStep("tickets"); if (event) loadSales(event.event_id); return; }
      } catch {}
      await new Promise((res) => setTimeout(res, 1500));
    }
    setError("The tickets are taking longer than usual. Open this sale again in a moment.");
  }, [event, loadSales]);

  async function sell() {
    if (!event || !chosen) return;
    setBusy(true); setError(null);
    try {
      const b = await api<Booking>(`box-office/events/${event.event_id}/sales`, {
        method: "POST",
        json: { ticket_category_id: chosen.id, quantity: qty, method, buyer_name: name, buyer_phone: phone, buyer_email: email },
      });
      setBooking(b);
      if (b.status === "CONFIRMED") { setStep("paying"); void waitForTickets(b.reference); }
      else setStep("collect");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the sale. Please try again.");
    } finally { setBusy(false); }
  }

  async function verify(ref: string, r: RazorpayResponse) {
    setStep("paying");
    try {
      await api<Booking>(`box-office/bookings/${ref}/verify`, {
        method: "POST",
        json: { provider_payment_id: r.razorpay_payment_id, provider_order_id: r.razorpay_order_id, signature: r.razorpay_signature },
      });
    } catch { /* the webhook may still confirm it; keep checking */ }
    void waitForTickets(ref);
  }

  async function collect() {
    if (!booking) return;
    setBusy(true); setError(null);
    try {
      const co = await api<CheckoutResponse>(`box-office/bookings/${booking.reference}/checkout`, { method: "POST" });
      await loadRazorpay();
      const rzp = new window.Razorpay!({
        ...co.checkout_payload,
        prefill: { name: name || undefined, contact: phone || undefined, email: email || undefined },
        theme: { color: "#000000" },
        handler: (r: RazorpayResponse) => void verify(booking.reference, r),
        modal: { ondismiss: () => setBusy(false) },
      });
      rzp.on("payment.failed", () => { setBusy(false); setError("That payment did not go through. Try again, or take cash instead."); });
      rzp.open();
    } catch (e) {
      setBusy(false);
      setError(e instanceof ApiError ? e.message : "Could not open the payment window.");
    }
  }

  function again() {
    poll.current++;
    setStep("sell"); setBooking(null); setTickets([]); setQty(1); setName(""); setPhone(""); setEmail(""); setError(null); setBusy(false);
    if (event) { loadSales(event.event_id); api<EventDetail>(`events/${event.slug}`).then(setDetail).catch(() => {}); }
  }

  if (events === null) return <div className="sc-pad"><div className="skeleton" style={{ height: 40 }} /></div>;

  if (!event) {
    return (
      <div className="sc-pad">
        <h1 className="sc-h">Box office</h1>
        <p className="sc-who">Choose the event you are selling for.</p>
        {events.length === 0 && <p className="sc-empty">{error ?? "You are not assigned to any events yet."}</p>}
        {events.map((e) => (
          <button key={e.event_id} className="sc-event" onClick={() => setEvent(e)}><b>{e.title}</b><span>{e.venue_name}, {e.city}</span></button>
        ))}
        <p style={{ marginTop: 28 }}><Link className="link" href="/scan">Open the scanner</Link></p>
      </div>
    );
  }

  const mine = sales.reduce((a, r) => ({ cash: a.cash + r.cash_paise, online: a.online + r.online_paise, n: a.n + r.cash_tickets + r.online_tickets }), { cash: 0, online: 0, n: 0 });

  return (
    <div className="sc-pad bo">
      <header className="bo-head">
        <div><h1 className="sc-h">Box office</h1><p className="sc-who">{event.title}</p></div>
        {events.length > 1 && step === "sell" && <button className="link" onClick={() => { setEvent(null); setDetail(null); setCat(null); }}>Change</button>}
      </header>

      {step === "sell" && (
        <>
          {!detail && <div className="skeleton" style={{ height: 120 }} />}
          {detail && (
            <form onSubmit={(e) => { e.preventDefault(); void sell(); }}>
              <p className="sc-sub">Ticket</p>
              <div className="bo-cats" role="radiogroup" aria-label="Ticket type">
                {detail.ticket_categories.map((c) => (
                  <button type="button" key={c.id} role="radio" aria-checked={cat === c.id} className={`bo-cat${cat === c.id ? " on" : ""}`} disabled={c.is_sold_out} onClick={() => setCat(c.id)}>
                    <b>{c.name}</b><span>{c.is_sold_out ? "Sold out" : inr(c.price_paise)}</span>
                  </button>
                ))}
              </div>

              <p className="sc-sub">How many</p>
              <div className="bo-qty">
                <button type="button" aria-label="One fewer" onClick={() => setQty((q) => Math.max(1, q - 1))}>−</button>
                <output aria-live="polite">{qty}</output>
                <button type="button" aria-label="One more" onClick={() => setQty((q) => Math.min(chosen?.max_per_booking ?? 10, q + 1))}>+</button>
              </div>

              <p className="sc-sub">Paid by</p>
              <div className="bo-method" role="radiogroup" aria-label="Payment method">
                <button type="button" role="radio" aria-checked={method === "CASH"} className={method === "CASH" ? "on" : ""} onClick={() => setMethod("CASH")}>Cash</button>
                <button type="button" role="radio" aria-checked={method === "ONLINE"} className={method === "ONLINE" ? "on" : ""} onClick={() => setMethod("ONLINE")}>UPI / card</button>
              </div>

              <p className="sc-sub">Buyer (optional)</p>
              <div className="bo-fields">
                <input aria-label="Buyer name" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoComplete="off" />
                <input aria-label="Buyer phone" placeholder="Phone" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={20} autoComplete="off" />
                <input aria-label="Buyer email" placeholder="Email, to also send the tickets" inputMode="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
              </div>

              {error && <p className="err" role="alert">{error}</p>}
              <button className="pill full" type="submit" disabled={busy || !chosen}>{busy ? "One moment…" : method === "CASH" ? `Take ${inr(total)} cash and issue` : `Charge ${inr(total)}`}</button>
            </form>
          )}
          <details className="bo-sales" onToggle={(e) => (e.currentTarget as HTMLDetailsElement).open && loadSales(event.event_id)}>
            <summary>{mine.n} sold {sales.length > 0 && <>· cash to hand in {inr(mine.cash)}</>}</summary>
            {sales.length === 0 ? <p className="sc-empty">No sales yet.</p> : sales.map((r) => (
              <div key={r.seller_id} className="bo-row">
                <b>{r.seller_name ?? "Seller"}</b>
                <span>Cash {r.cash_tickets} · {inr(r.cash_paise)}</span>
                <span>Online {r.online_tickets} · {inr(r.online_paise)}</span>
              </div>
            ))}
          </details>
        </>
      )}

      {step === "collect" && booking && (
        <div className="bo-center">
          <p className="sc-sub">Collect</p>
          <p className="bo-amount">{inr(booking.total_paise)}</p>
          <p className="sc-who">{booking.quantity} × {booking.items[0]?.category_name}. Seats are held for a few minutes.</p>
          {error && <p className="err" role="alert">{error}</p>}
          <button className="pill full" onClick={collect} disabled={busy}>{busy ? "Opening payment…" : "Open payment"}</button>
          <p className="small">The payment window shows a UPI QR for the buyer to scan, or lets them pay by card.</p>
          <button className="link" onClick={again}>Cancel this sale</button>
        </div>
      )}

      {step === "paying" && <div className="bo-center"><p className="bo-amount">Issuing tickets…</p>{error && <p className="err" role="alert">{error}</p>}</div>}

      {step === "tickets" && booking && (
        <div>
          <p className="bo-done">Paid · {booking.source === "CASH" ? "cash" : "online"} · {inr(booking.total_paise)}</p>
          <p className="sc-who">Booking {booking.reference}. Show each code to the gate scanner.</p>
          {tickets.map((t) => (
            <div key={t.id} className="bo-ticket">
              {t.qr_token ? <Qr value={t.qr_token} /> : <p>No code</p>}
              <span>{t.serial}</span>
            </div>
          ))}
          <button className="pill full" onClick={again}>New sale</button>
        </div>
      )}
    </div>
  );
}
