"use client";
import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";

/** Footer signup. It always answers the same way, so it never reveals who is already on the list. */
export function NewsletterSignup() {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true); setErr(null);
    try {
      await api("newsletter/subscribe", { method: "POST", json: { email: String(f.get("email") ?? "").trim(), website: String(f.get("website") ?? "") } });
      setDone(true);
    } catch (error) {
      setErr(error instanceof ApiError && error.status === 429 ? "Too many requests. Please try again later." : "Please check the email address and try again.");
    } finally { setBusy(false); }
  }

  return (
    <div className="news">
      <b>New nights, first</b>
      {done ? <p role="status">Thank you. Check your inbox: we sent a short confirmation.</p> : (
        <form onSubmit={submit} aria-label="Newsletter signup">
          <label htmlFor="nl-e" className="sr">Email address</label>
          <input id="nl-e" name="email" type="email" required placeholder="Your email" autoComplete="email" />
          <div className="hp" aria-hidden="true"><label>Website<input name="website" tabIndex={-1} autoComplete="off" /></label></div>
          <button className="pill sm" type="submit" disabled={busy}>{busy ? "Joining…" : "Join"}</button>
        </form>
      )}
      {err && <p className="err" role="alert">{err}</p>}
    </div>
  );
}
