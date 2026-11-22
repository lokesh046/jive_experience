"use client";
import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";

interface Type { id: string; name: string }

/** "Email me if tickets come back." Always answers the same way, so it reveals nothing about anyone else. */
export function WaitlistForm({ slug, soldOut, everythingGone }: { slug: string; soldOut: Type[]; everythingGone: boolean }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const type = String(f.get("type") ?? "");
    setBusy(true); setErr(null);
    try {
      await api(`events/${slug}/waitlist`, {
        method: "POST",
        json: { email: String(f.get("email") ?? "").trim(), quantity: Number(f.get("qty") ?? 1), ticket_category_id: type || null, website: String(f.get("website") ?? "") },
      });
      setDone(true);
    } catch (error) {
      if (error instanceof ApiError && error.code === "TICKETS_AVAILABLE") setErr("Tickets are available right now. Choose them above and book.");
      else if (error instanceof ApiError && error.status === 429) setErr("Too many requests. Please try again later.");
      else setErr(error instanceof ApiError ? error.message : "Something went wrong. Please try again.");
    } finally { setBusy(false); }
  }

  const form = done ? (
    <p className="notice" role="status"><span>You are on the list. We will email you if tickets come back. They are first come, first served.</span></p>
  ) : (
    <form onSubmit={submit} className="wait" aria-label="Join the waitlist">
      <div className="wait-grid">
        <div className="f"><label htmlFor="wl-e">Your email</label><input id="wl-e" name="email" type="email" required autoComplete="email" /></div>
        <div className="f"><label htmlFor="wl-t">Ticket type</label>
          <select id="wl-t" name="type" defaultValue="">
            <option value="">{everythingGone ? "Any type" : "Any type that comes back"}</option>
            {soldOut.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select></div>
        <div className="f"><label htmlFor="wl-q">Tickets</label>
          <select id="wl-q" name="qty" defaultValue="1">{[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}</select></div>
        <div className="hp" aria-hidden="true"><label>Website<input name="website" tabIndex={-1} autoComplete="off" /></label></div>
      </div>
      {err && <p className="err" role="alert">{err}</p>}
      <div><button className="pill" type="submit" disabled={busy}>{busy ? "Joining…" : "Join the waitlist"}</button></div>
    </form>
  );

  if (everythingGone) return <div className="wait-box"><h3>Sold out. Want a second chance?</h3><p className="small" style={{ margin: "8px 0 24px" }}>People sometimes cancel. Leave your email and we will tell you if tickets come back.</p>{form}</div>;
  return (
    <details className="wait-box">
      <summary>Not seeing the ticket you want? Join the waitlist</summary>
      <div style={{ marginTop: 20 }}>{form}</div>
    </details>
  );
}
