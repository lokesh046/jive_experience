"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, rememberNext } from "@/lib/api-client";
import { inr } from "@/lib/format";
import { isPremiumType } from "@/lib/premium";
import { TicketPreview } from "@/components/TicketPreview";
import type { Availability, Booking, TicketCategoryPublic } from "@/lib/types";

interface Props {
  slug: string;
  categories: TicketCategoryPublic[];
  maxPerCustomer: number;
  onSale: boolean;
  saleMessage?: string;
  preview: { when: string; title: string; venue: string; year: string };
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

/** What a ticket type includes: one benefit per line in the admin's description. */
function Includes({ text }: { text: string | null }) {
  const lines = (text ?? "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines.length === 0) return null;
  if (lines.length === 1) return <p className="inc-one">{lines[0]}</p>;
  return <ul className="inc">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>;
}

const isPremium = (c: TicketCategoryPublic, all: TicketCategoryPublic[]) =>
  isPremiumType(c.name, c.price_paise, all.map((x) => x.price_paise));

const isOut = (c: TicketCategoryPublic) => c.is_sold_out || c.available <= 0;
const capFor = (c: TicketCategoryPublic, maxPerCustomer: number) => Math.max(0, Math.min(c.max_per_booking, c.available, maxPerCustomer));

export function TicketPicker({ slug, categories, maxPerCustomer, onSale, saleMessage, preview }: Props) {
  const router = useRouter();
  const [cats, setCats] = useState(categories);
  const [picked, setPicked] = useState<string | null>(null);
  const [wanted, setWanted] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keyRef = useRef<{ sig: string; key: string } | null>(null);
  const storeKey = `jive_sel_${slug}`;

  // General is chosen to begin with; otherwise the first type that still has tickets.
  const open = cats.filter((c) => !isOut(c));
  const fallback = open.find((c) => /^general/i.test(c.name)) ?? open[0] ?? null;
  const current = cats.find((c) => c.id === picked && !isOut(c)) ?? fallback;
  const cap = current ? capFor(current, maxPerCustomer) : 0;
  const floor = current ? Math.max(1, Math.min(current.min_per_booking, cap)) : 1;
  const count = current ? Math.min(Math.max(wanted, floor), cap) : 0;

  // Restore a selection made before signing in.
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(storeKey);
      if (saved) {
        const r = JSON.parse(saved) as { cat?: string; count?: number };
        sessionStorage.removeItem(storeKey);
        queueMicrotask(() => { if (r.cat) setPicked(r.cat); if (r.count) setWanted(r.count); });
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

  const total = current ? current.price_paise * count : 0;

  function choose(c: TicketCategoryPublic) {
    setError(null);
    setPicked(c.id);
    setWanted(1);
  }

  async function checkout() {
    if (!current || count < 1) return;
    const items = [{ ticket_category_id: current.id, quantity: count }];
    setBusy(true);
    setError(null);
    // Same selection → same key, so a double-click or retry cannot create two bookings.
    const sig = JSON.stringify(items);
    if (keyRef.current?.sig !== sig) keyRef.current = { sig, key: crypto.randomUUID() };
    const remember = () => { try { sessionStorage.setItem(storeKey, JSON.stringify({ cat: current.id, count })); } catch {} };
    try {
      const b = await api<Booking>("bookings", { method: "POST", json: { event_slug: slug, items, idempotency_key: keyRef.current.key } });
      router.push(`/checkout/${b.reference}`);
    } catch (e) {
      setBusy(false);
      if (e instanceof ApiError) {
        if (e.status === 401) { remember(); rememberNext(`/events/${slug}#tickets`); router.push("/signin"); return; }
        if (e.code === "PHONE_NUMBER_REQUIRED") { remember(); rememberNext(`/events/${slug}#tickets`); router.push("/phone"); return; }
        if (e.code === "INSUFFICIENT_INVENTORY") void refresh();
        setError(MESSAGES[e.code] ?? e.message);
      } else setError("Something went wrong. Please try again.");
    }
  }

  if (!onSale) {
    return <p className="notice"><span>{saleMessage ?? "Tickets are not on sale right now."}</span></p>;
  }

  return (
    <>
      <TicketPreview when={preview.when} title={preview.title} venue={preview.venue} ticket={current?.name ?? null} premium={!!current && isPremium(current, cats)} year={preview.year} admit={count} total={count ? inr(total) : null} />

      <h3 className="step">1. Choose a ticket type</h3>
      <div className="types" role="radiogroup" aria-label="Ticket type">
        {cats.map((c) => {
          const out = isOut(c);
          const on = current?.id === c.id;
          return (
            <button
              key={c.id}
              type="button"
              role="radio"
              aria-checked={on}
              disabled={out}
              className={`type${on ? " on" : ""}${out ? " out" : ""}`}
              onClick={() => choose(c)}
            >
              <span className="type-top">
                <b>{c.name}</b>
                <span className="mark" aria-hidden="true" />
              </span>
              <span className="type-price">{inr(c.price_paise)}<small> per ticket</small></span>
              <Includes text={c.description} />
              <span className="type-note">{out ? "Sold out" : c.available <= 10 ? `Only ${c.available} left` : ""}</span>
            </button>
          );
        })}
      </div>

      <div className="cols">
        <div>
          <h3 className="step">2. How many?</h3>
          {current ? (
            <div className="how">
              <div className="qty" role="group" aria-label={`${current.name} quantity`}>
                <button type="button" aria-label="Fewer tickets" disabled={count <= floor} onClick={() => setWanted(count - 1)}>−</button>
                <output aria-live="polite">{count}</output>
                <button type="button" aria-label="More tickets" disabled={count >= cap} onClick={() => setWanted(count + 1)}>+</button>
              </div>
              <p className="small">{current.name} · {inr(current.price_paise)} each. Maximum {Math.min(cap, maxPerCustomer)} per booking.</p>
            </div>
          ) : (
            <p className="small">Every ticket type is sold out.</p>
          )}
        </div>
        <div className="sum">
          <div className="rows">
            {current && count > 0
              ? <div><span className="name">{current.name} × {count}</span><span>{inr(total)}</span></div>
              : <div><span>No tickets selected</span><span /></div>}
          </div>
          <div className="total"><span className="small">Total</span><strong>{inr(total)}</strong></div>
          <button className="pill full" type="button" disabled={!current || count < 1 || busy} onClick={checkout}>
            {busy ? "Reserving…" : "Continue to checkout"}
          </button>
          {error && <p className="err" role="alert">{error}</p>}
        </div>
      </div>
    </>
  );
}
