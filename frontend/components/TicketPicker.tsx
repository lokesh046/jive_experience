"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, rememberNext } from "@/lib/api-client";
import { inr } from "@/lib/format";
import type { Availability, Booking, TicketCategoryPublic } from "@/lib/types";

interface Props {
  slug: string;
  categories: TicketCategoryPublic[];
  maxPerCustomer: number;
  onSale: boolean;
  saleMessage?: string;
}

const MESSAGES: Record<string, string> = {
  PURCHASE_LIMIT_EXCEEDED: "That is over the limit for this event. Reduce the number of tickets and try again.",
  INSUFFICIENT_INVENTORY: "Those tickets have just sold out. Pick a different category or fewer tickets.",
  SALE_NOT_OPEN: "Sales for this event have not opened yet.",
  SALE_CLOSED: "Sales for this event have closed.",
  EVENT_STARTED: "This event has already started.",
  EVENT_NOT_SELLABLE: "Tickets for this event are not on sale.",
  CATEGORY_INACTIVE: "That ticket type is no longer available.",
  BELOW_MINIMUM: "That ticket type has a minimum number of tickets per booking.",
  ABOVE_MAXIMUM: "That is more than the maximum for this ticket type.",
};

export function TicketPicker({ slug, categories, maxPerCustomer, onSale, saleMessage }: Props) {
  const router = useRouter();
  const [cats, setCats] = useState(categories);
  const [qty, setQty] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keyRef = useRef<{ sig: string; key: string } | null>(null);
  const storeKey = `jive_sel_${slug}`;

  // Restore a selection made before signing in.
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(storeKey);
      if (saved) {
        const restored = JSON.parse(saved);
        sessionStorage.removeItem(storeKey);
        queueMicrotask(() => setQty(restored));
      }
    } catch {}
  }, [storeKey]);

  // Live availability while the tab is visible. The backend caches this for a couple of
  // seconds, so polling is cheap; the authoritative check is at booking time.
  const refresh = useCallback(async () => {
    try {
      const a = await api<Availability>(`events/${slug}/availability`);
      const by = new Map(a.categories.map((c) => [c.ticket_category_id, c]));
      setCats((prev) => prev.map((c) => { const n = by.get(c.id); return n ? { ...c, available: n.available, is_sold_out: n.is_sold_out } : c; }));
    } catch {}
  }, [slug]);
  useEffect(() => {
    if (!onSale) return;
    const tick = () => { if (document.visibilityState === "visible") void refresh(); };
    const id = setInterval(tick, 15_000);
    document.addEventListener("visibilitychange", tick);
    return () => { clearInterval(id); document.removeEventListener("visibilitychange", tick); };
  }, [onSale, refresh]);

  const total = cats.reduce((s, c) => s + (qty[c.id] ?? 0) * c.price_paise, 0);
  const count = cats.reduce((s, c) => s + (qty[c.id] ?? 0), 0);

  function change(c: TicketCategoryPublic, d: number) {
    setError(null);
    setQty((q) => {
      const cur = q[c.id] ?? 0;
      const others = count - cur;
      const cap = Math.max(0, Math.min(c.max_per_booking, c.available, maxPerCustomer - others));
      const next = Math.max(0, Math.min(cap, cur + d));
      return { ...q, [c.id]: next };
    });
  }

  async function checkout() {
    const items = cats.filter((c) => (qty[c.id] ?? 0) > 0).map((c) => ({ ticket_category_id: c.id, quantity: qty[c.id] }));
    if (!items.length) return;
    setBusy(true);
    setError(null);
    // Same selection → same key, so a double-click or retry cannot create two bookings.
    const sig = JSON.stringify(items);
    if (keyRef.current?.sig !== sig) keyRef.current = { sig, key: crypto.randomUUID() };
    try {
      const b = await api<Booking>("bookings", { method: "POST", json: { event_slug: slug, items, idempotency_key: keyRef.current.key } });
      router.push(`/checkout/${b.reference}`);
    } catch (e) {
      setBusy(false);
      if (e instanceof ApiError) {
        if (e.status === 401) {
          try { sessionStorage.setItem(storeKey, JSON.stringify(qty)); } catch {}
          rememberNext(`/events/${slug}#tickets`);
          router.push("/signin");
          return;
        }
        if (e.code === "PHONE_NUMBER_REQUIRED") {
          try { sessionStorage.setItem(storeKey, JSON.stringify(qty)); } catch {}
          rememberNext(`/events/${slug}#tickets`);
          router.push("/phone");
          return;
        }
        if (e.code === "INSUFFICIENT_INVENTORY") void refresh();
        setError(MESSAGES[e.code] ?? e.message);
      } else setError("Something went wrong. Please try again.");
    }
  }

  if (!onSale) {
    return <p className="notice"><span>{saleMessage ?? "Tickets are not on sale right now."}</span></p>;
  }

  return (
    <div className="cols">
      <div>
        {cats.map((c) => {
          const q = qty[c.id] ?? 0;
          const out = c.is_sold_out || c.available <= 0;
          const others = count - q;
          const cap = Math.max(0, Math.min(c.max_per_booking, c.available, maxPerCustomer - others));
          return (
            <div className={`tier${out ? " out" : ""}`} key={c.id}>
              <div>
                <b>{c.name}</b>
                {c.description && <small>{c.description}{!out && c.available <= 10 ? ` · ${c.available} left` : ""}</small>}
                {!c.description && !out && c.available <= 10 && <small>{c.available} left</small>}
                <span className="pr">{inr(c.price_paise)}</span>
              </div>
              {out ? (
                <small>Sold out</small>
              ) : (
                <div className="qty" role="group" aria-label={`${c.name} quantity`}>
                  <button type="button" aria-label={`Fewer ${c.name}`} disabled={q === 0} onClick={() => change(c, -1)}>−</button>
                  <output aria-live="polite">{q}</output>
                  <button type="button" aria-label={`More ${c.name}`} disabled={q >= cap} onClick={() => change(c, 1)}>+</button>
                </div>
              )}
            </div>
          );
        })}
        <p className="small" style={{ marginTop: 16 }}>Maximum {maxPerCustomer} tickets per person.</p>
      </div>
      <div className="sum">
        <div className="rows">
          {cats.filter((c) => (qty[c.id] ?? 0) > 0).map((c) => (
            <div key={c.id}><span className="name">{c.name} × {qty[c.id]}</span><span>{inr(c.price_paise * (qty[c.id] ?? 0))}</span></div>
          ))}
          {count === 0 && <div><span>No tickets selected</span><span /></div>}
        </div>
        <div className="total"><span className="small">Total</span><strong>{inr(total)}</strong></div>
        <button className="pill full" type="button" disabled={count === 0 || busy} onClick={checkout}>
          {busy ? "Reserving…" : "Continue to checkout"}
        </button>
        {error && <p className="err" role="alert">{error}</p>}
      </div>
    </div>
  );
}
