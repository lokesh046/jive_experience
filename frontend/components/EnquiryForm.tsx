"use client";
import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";

/** Private-booking enquiry. The hidden "website" box is for bots: people never see or fill it. */
export function EnquiryForm() {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const text = (k: string) => String(f.get(k) ?? "").trim();
    setBusy(true); setErr(null);
    try {
      await api("enquiries", {
        method: "POST",
        json: {
          name: text("name"), email: text("email"), phone: text("phone") || null,
          event_date: text("event_date") || null, guests: text("guests") ? Number(text("guests")) : null,
          message: text("message"), website: text("website"),
        },
      });
      setDone(true);
    } catch (error) {
      setErr(error instanceof ApiError && error.status === 429 ? "Too many requests from this connection. Please try again later." : error instanceof ApiError ? error.message : "Something went wrong. Please try again.");
    } finally { setBusy(false); }
  }

  if (done) return <div className="notice" role="status" style={{ marginTop: 48 }}><span>Thank you. We have your enquiry and will reply by email soon.</span></div>;

  return (
    <form onSubmit={submit} className="enq" aria-label="Private booking enquiry">
      <div className="enq-intro">
        <h3>Tell us about your evening</h3>
        <p>Share the date, the number of guests and what you have in mind. We reply by email.</p>
      </div>
      <div className="enq-body">
        <div className="enq-grid">
          <div className="f s3"><label htmlFor="en-n">Your name</label><input id="en-n" name="name" required maxLength={120} autoComplete="name" placeholder="Priya Nair" /></div>
          <div className="f s3"><label htmlFor="en-e">Email</label><input id="en-e" name="email" type="email" required autoComplete="email" placeholder="you@example.com" /></div>
          <div className="f s2"><label htmlFor="en-p">Phone <i>optional</i></label><input id="en-p" name="phone" type="tel" maxLength={30} autoComplete="tel" placeholder="+91" /></div>
          <div className="f s2"><label htmlFor="en-d">Date <i>optional</i></label><input id="en-d" name="event_date" type="date" min={new Date().toISOString().slice(0, 10)} /></div>
          <div className="f s2"><label htmlFor="en-g">Guests <i>optional</i></label><input id="en-g" name="guests" type="number" min={1} max={5000} placeholder="40" /></div>
          <div className="f s6"><label htmlFor="en-m">What are you planning?</label><textarea id="en-m" name="message" required minLength={10} maxLength={2000} rows={5} placeholder="A private listening evening for 40 guests…" /></div>
          <div className="hp" aria-hidden="true"><label>Website<input name="website" tabIndex={-1} autoComplete="off" /></label></div>
        </div>
        {err && <p className="err" role="alert">{err}</p>}
        <button className="pill" type="submit" disabled={busy}>{busy ? "Sending…" : "Send enquiry"}</button>
      </div>
    </form>
  );
}
