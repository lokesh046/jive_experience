"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, api, rememberNext, takeNext } from "@/lib/api-client";

const MESSAGES: Record<string, string> = {
  PHONE_TAKEN: "That number is already used by another account.",
  PHONE_COUNTRY_NOT_ALLOWED: "We can only accept numbers from supported countries.",
};

export default function Phone() {
  const router = useRouter();
  const [value, setValue] = useState("+91");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("auth/phone", { method: "PUT", json: { phone_e164: value.replace(/[\s-]/g, "") } });
      router.replace(takeNext());
    } catch (err) {
      setBusy(false);
      if (err instanceof ApiError && err.status === 401) { rememberNext("/phone"); router.replace("/signin"); return; }
      setError(err instanceof ApiError ? (MESSAGES[err.code] ?? err.message) : "Could not save your number. Please try again.");
    }
  }

  return (
    <main className="page">
      <div className="wrap narrow">
        <h1>Add your phone number</h1>
        <p style={{ margin: "16px 0 36px" }}>We need it to reach you about your bookings. It is not shown to anyone else.</p>
        <form onSubmit={save}>
          <div className="f">
            <label htmlFor="p">Mobile number</label>
            <input id="p" type="tel" inputMode="tel" autoComplete="tel" value={value} onChange={(e) => setValue(e.target.value)} placeholder="+91 98765 43210" required />
          </div>
          {error && <p className="err" role="alert">{error}</p>}
          <div><button className="pill" type="submit" disabled={busy}>{busy ? "Saving…" : "Save and continue"}</button></div>
        </form>
      </div>
    </main>
  );
}
