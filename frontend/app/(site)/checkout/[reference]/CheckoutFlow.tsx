"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, rememberNext } from "@/lib/api-client";
import { eventsById } from "@/lib/events-index";
import { inr, longDate, timeOf } from "@/lib/format";
import type { AuthUser, Booking, CheckoutResponse, EventListItem, Ticket } from "@/lib/types";

type View = "loading" | "review" | "processing" | "failed" | "confirmed" | "expired" | "closed" | "unreachable";

interface RazorpayResponse { razorpay_payment_id: string; razorpay_order_id: string; razorpay_signature: string }
interface RazorpayInstance { open(): void; on(ev: string, cb: (r: unknown) => void): void }
declare global { interface Window { Razorpay?: new (o: Record<string, unknown>) => RazorpayInstance } }

function loadRazorpay(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.Razorpay) return resolve();
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Could not load the payment window."));
    document.head.appendChild(s);
  });
}

const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

function Shell({ embedded, children }: { embedded: boolean; children: React.ReactNode }) {
  return embedded
    ? <div className="co-embedded" id="checkout-panel" tabIndex={-1}>{children}</div>
    : <main className="page"><div className="wrap">{children}</div></main>;
}

export type EventSummary = Pick<EventListItem, "slug" | "title" | "starts_at" | "timezone" | "venue_name" | "city">;

/**
 * Review and pay. It runs as its own page (/checkout/REF, used to come back to an unpaid booking) and,
 * `embedded`, inside the event page's ticket section so buying never leaves the event.
 */
export function CheckoutFlow({
  reference, embedded = false, event: eventProp, onRestart,
}: { reference: string; embedded?: boolean; event?: EventSummary; onRestart?: () => void }) {
  const router = useRouter();
  const [view, setView] = useState<View>("loading");
  const [booking, setBooking] = useState<Booking | null>(null);
  const [event, setEvent] = useState<EventSummary | null>(eventProp ?? null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [left, setLeft] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ticketsReady, setTicketsReady] = useState(false);
  const polling = useRef(false);

  const toSignIn = useCallback(() => { rememberNext(embedded && eventProp ? `/events/${eventProp.slug}#tickets` : `/checkout/${reference}`); router.replace("/signin"); }, [reference, router, embedded, eventProp]);

  const apply = useCallback((b: Booking) => {
    setBooking(b);
    if (b.status === "CONFIRMED") setView("confirmed");
    else if (b.status === "PENDING") setView((v) => (v === "processing" || v === "failed" ? v : b.expires_at && new Date(b.expires_at) <= new Date() ? "expired" : "review"));
    else if (b.status === "EXPIRED") setView("expired");
    else setView("closed");
  }, []);

  // Load the booking, who is paying, and which event it is for.
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const [b, u] = await Promise.all([api<Booking>(`bookings/${reference}`), api<AuthUser>("auth/me")]);
        if (!live) return;
        setUser(u);
        apply(b);
        if (!eventProp) {
          const ev = (await eventsById()).get(b.event_id) ?? null;
          if (live) setEvent(ev);
        }
      } catch (e) {
        if (!live) return;
        if (e instanceof ApiError && e.status === 401) return toSignIn();
        if (e instanceof ApiError && e.status === 404) { setError("We could not find that booking."); setView("closed"); return; }
        setError(e instanceof ApiError ? e.message : "We could not load your booking.");
        setView("unreachable");
      }
    })();
    return () => { live = false; };
  }, [reference, apply, toSignIn, eventProp]);

  // Countdown to the hold's expiry, taken from the booking, never a fixed duration.
  useEffect(() => {
    if (!booking?.expires_at || (view !== "review" && view !== "failed")) return;
    const end = new Date(booking.expires_at).getTime();
    const tick = () => {
      const s = Math.max(0, Math.round((end - Date.now()) / 1000));
      setLeft(s);
      if (s === 0) setView("expired");
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [booking?.expires_at, view]);

  // After paying, the server confirms asynchronously: poll until it does.
  const pollBooking = useCallback(async () => {
    if (polling.current) return;
    polling.current = true;
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const b = await api<Booking>(`bookings/${reference}`);
        if (b.status !== "PENDING") { apply(b); polling.current = false; return; }
      } catch {}
    }
    polling.current = false;
    setError("This is taking longer than usual. Your payment is safe: check My tickets in a few minutes.");
  }, [reference, apply]);

  // Confirmed: wait for the tickets to be issued.
  useEffect(() => {
    if (view !== "confirmed") return;
    let live = true;
    (async () => {
      for (let i = 0; i < 20 && live; i++) {
        try {
          const t = await api<Ticket[] | { items: Ticket[] }>(`bookings/${reference}/tickets`);
          const list = Array.isArray(t) ? t : t.items;
          if (list.length > 0) { if (live) setTicketsReady(true); return; }
        } catch {}
        await new Promise((r) => setTimeout(r, 2500));
      }
    })();
    return () => { live = false; };
  }, [view, reference]);

  async function verify(r: RazorpayResponse) {
    setView("processing");
    try {
      const b = await api<Booking>(`bookings/${reference}/verify`, {
        method: "POST",
        json: { provider_payment_id: r.razorpay_payment_id, provider_order_id: r.razorpay_order_id, signature: r.razorpay_signature },
      });
      apply(b);
      if (b.status === "PENDING") void pollBooking();
    } catch {
      // The webhook may still confirm it; keep checking rather than telling them it failed.
      void pollBooking();
    }
  }

  async function pay() {
    setBusy(true);
    setError(null);
    try {
      const co = await api<CheckoutResponse>(`bookings/${reference}/checkout`, { method: "POST" });
      await loadRazorpay();
      const rzp = new window.Razorpay!({
        ...co.checkout_payload,
        prefill: { email: user?.email, contact: user?.phone_e164 ?? undefined, name: user?.full_name ?? undefined },
        theme: { color: "#000000" },
        handler: (r: RazorpayResponse) => void verify(r),
        modal: { ondismiss: () => setBusy(false) },
      });
      rzp.on("payment.failed", () => { setBusy(false); setView("failed"); });
      rzp.open();
    } catch (e) {
      setBusy(false);
      if (e instanceof ApiError && e.status === 401) return toSignIn();
      if (e instanceof ApiError && (e.code === "BOOKING_EXPIRED")) return setView("expired");
      setError(e instanceof ApiError ? e.message : "We could not open the payment window. Please try again.");
    }
  }

  const holdable = view === "review" || view === "failed";
  const H = embedded ? "h3" : "h1";

  return (
    <Shell embedded={embedded}>
        <div className="cols">
          <section aria-live="polite">
            {view === "loading" && <div className="skeleton" style={{ height: 56, maxWidth: 420 }} />}

            {view === "review" && booking && (
              <>
                <H>Review and pay</H>
                <p style={{ margin: "16px 0 36px" }}>Check your order, then pay securely with Razorpay. Your tickets appear in your account as soon as the payment is confirmed.</p>
                {user && (
                  <div className="rows" style={{ marginBottom: 36 }}>
                    <div><span className="name">Booked by</span><span>{user.email}</span></div>
                    {user.phone_e164 && <div><span className="name">Mobile</span><span>{user.phone_e164}</span></div>}
                  </div>
                )}
                <button className="pill full" type="button" onClick={pay} disabled={busy}>{busy ? "Opening payment…" : `Pay ${inr(booking.total_paise)}`}</button>
                {error && <p className="err" role="alert">{error}</p>}
                <p className="small" style={{ marginTop: 18 }}>By paying you accept the <Link className="link" href="/cancellation-policy">cancellation and refund policy</Link>.</p>
              </>
            )}

            {view === "processing" && (
              <>
                <H>Confirming your payment</H>
                <p style={{ margin: "16px 0 28px" }}>This usually takes a few seconds. Please keep this page open and do not pay again.</p>
                <div className="notice"><span>Waiting for the bank to confirm.</span></div>
                {error && <p className="err" role="alert">{error}</p>}
              </>
            )}

            {view === "failed" && (
              <>
                <H>The payment did not go through</H>
                <p style={{ margin: "16px 0 36px" }}>You have not been charged for this attempt. Your tickets are still held, so you can try again with the same method or another one.</p>
                <button className="pill" type="button" onClick={pay} disabled={busy}>Try again</button>
              </>
            )}

            {view === "confirmed" && booking && (
              <>
                <H>You are going</H>
                <p style={{ margin: "16px 0 28px" }}>Your payment is confirmed. Booking reference <span style={{ color: "#fff" }}>{booking.reference}</span>.</p>
                {!ticketsReady && <div className="notice"><span>Preparing your tickets…</span></div>}
                <div style={{ marginTop: 36 }}>
                  <Link className="pill" href={`/tickets/${booking.reference}`}>{ticketsReady ? "View my tickets" : "Go to my booking"}</Link>
                </div>
              </>
            )}

            {view === "expired" && (
              <>
                <H>Your hold has ended</H>
                <p style={{ margin: "16px 0 36px" }}>The time to pay ran out and these tickets went back on sale. If you were charged, the payment will be returned to you.</p>
                {embedded && onRestart
                  ? <button className="pill" type="button" onClick={onRestart}>Choose tickets again</button>
                  : <Link className="pill" href={event ? `/events/${event.slug}#tickets` : "/#events"}>Choose tickets again</Link>}
              </>
            )}

            {view === "closed" && (
              <>
                <H>This booking can no longer be paid</H>
                <p style={{ margin: "16px 0 36px" }}>{error ?? "It has been cancelled or already handled."}</p>
                <Link className="pill" href="/tickets">My tickets</Link>
              </>
            )}

            {view === "unreachable" && (
              <>
                <H>We could not load your booking</H>
                <p style={{ margin: "16px 0 36px" }}>{error}</p>
                <button className="pill" type="button" onClick={() => location.reload()}>Try again</button>
              </>
            )}
          </section>

          {booking && (
            <aside aria-label="Your order" style={{ opacity: view === "expired" || view === "closed" ? 0.5 : 1 }}>
              <h2 style={{ fontSize: 24 }}>Your order</h2>
              {event && (
                <p className="small" style={{ margin: "6px 0 20px" }}>
                  {event.title} · {longDate(event.starts_at, event.timezone)}, {timeOf(event.starts_at, event.timezone)}<br />
                  {event.venue_name}, {event.city}
                </p>
              )}
              <div className="rows">
                {booking.items.map((i) => (
                  <div key={i.ticket_category_id}><span className="name">{i.category_name} × {i.quantity}</span><span>{inr(i.line_total_paise)}</span></div>
                ))}
                {(booking.discount_paise ?? 0) > 0 && <div><span>Promo discount</span><span>−{inr(booking.discount_paise ?? 0)}</span></div>}
                {booking.fees_paise > 0 && <div><span>Fees</span><span>{inr(booking.fees_paise)}</span></div>}
              </div>
              <div className="total"><span className="small">Total</span><strong>{inr(booking.total_paise)}</strong></div>
              {holdable && left !== null && (
                <div>
                  <p className="small">Your tickets are held for</p>
                  <div className="timer" role="timer" aria-label="Time left to pay">{mmss(left)}</div>
                </div>
              )}
            </aside>
          )}
        </div>
    </Shell>
  );
}
