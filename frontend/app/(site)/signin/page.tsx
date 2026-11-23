"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, api, takeNext } from "@/lib/api-client";

export default function SignIn() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [wait, setWait] = useState(0);
  const [mailBusy, setMailBusy] = useState(false);
  const [mailError, setMailError] = useState<string | null>(null);

  // Resend is allowed once a minute, matching the server.
  useEffect(() => {
    if (wait <= 0) return;
    const id = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(id);
  }, [wait]);

  async function sendCode(e?: React.FormEvent) {
    e?.preventDefault();
    setMailBusy(true); setMailError(null);
    try {
      await api("auth/email/request", { method: "POST", json: { email: email.trim() } });
      setSent(true); setWait(60); setCode("");
    } catch (err) {
      setMailError(err instanceof ApiError ? (err.status === 429 ? "Too many attempts. Please wait a few minutes." : err.message) : "We could not send the code. Please try again.");
    } finally { setMailBusy(false); }
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setMailBusy(true); setMailError(null);
    try {
      await api("auth/email/verify", { method: "POST", json: { email: email.trim(), code: code.trim() } });
      router.replace(takeNext());
    } catch (err) {
      setMailBusy(false);
      setMailError(err instanceof ApiError ? err.message : "Sign-in did not complete. Please try again.");
    }
  }

  async function go() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ authorization_url: string }>("auth/google/authorize");
      window.location.assign(r.authorization_url);
    } catch (e) {
      setBusy(false);
      setError(e instanceof ApiError ? e.message : "We could not start sign-in. Please try again.");
    }
  }

  return (
    <main className="page">
      <div className="wrap narrow">
        <h1>Sign in</h1>
        <p style={{ margin: "16px 0 40px" }}>One account for your tickets, bookings and entry codes. Staff sign in the same way.</p>
        <button className="pill full" type="button" onClick={go} disabled={busy}>
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M23 12.3c0-.8-.1-1.5-.2-2.2H12v4.3h6.2a5.3 5.3 0 0 1-2.3 3.5v2.9h3.7c2.2-2 3.4-5 3.4-8.5z"/><path fill="#34A853" d="M12 24c3.1 0 5.7-1 7.6-2.8l-3.7-2.9c-1 .7-2.3 1.1-3.9 1.1-3 0-5.5-2-6.4-4.7H1.8v3A12 12 0 0 0 12 24z"/><path fill="#FBBC05" d="M5.6 14.7a7.2 7.2 0 0 1 0-4.6v-3H1.8a12 12 0 0 0 0 10.6l3.8-3z"/><path fill="#EA4335" d="M12 4.8c1.7 0 3.2.6 4.4 1.7l3.3-3.3A11.6 11.6 0 0 0 12 0 12 12 0 0 0 1.8 6.9l3.8 3c.9-2.7 3.4-5.1 6.4-5.1z"/></svg>
          {busy ? "Opening Google…" : "Continue with Google"}
        </button>
        {error && <p className="err" role="alert">{error}</p>}
        <p className="small" style={{ marginTop: 24 }}>We never see your Google password.</p>

        <div className="or" role="separator"><span>or</span></div>

        {!sent ? (
          <form className="otp" onSubmit={sendCode}>
            <div className="f">
              <label htmlFor="otp-e">Email address</label>
              <input id="otp-e" type="email" required autoComplete="email" inputMode="email" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <button className="pill ghost full" type="submit" disabled={mailBusy || !email.trim()}>{mailBusy ? "Sending…" : "Email me a code"}</button>
            {mailError && <p className="err" role="alert">{mailError}</p>}
          </form>
        ) : (
          <form className="otp" onSubmit={verify}>
            <p aria-live="polite">We sent a 6-digit code to <b style={{ color: "var(--fg)" }}>{email.trim()}</b>. It works for 10 minutes.</p>
            <div className="f">
              <label htmlFor="otp-c">Code</label>
              <input id="otp-c" className="otp-code" inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required placeholder="123456" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} autoFocus />
            </div>
            <button className="pill full" type="submit" disabled={mailBusy || code.length !== 6}>{mailBusy ? "Checking…" : "Sign in"}</button>
            {mailError && <p className="err" role="alert">{mailError}</p>}
            <p className="small">
              <button type="button" className="link" onClick={() => void sendCode()} disabled={wait > 0 || mailBusy}>{wait > 0 ? `Send a new code in ${wait}s` : "Send a new code"}</button>
              {" · "}
              <button type="button" className="link" onClick={() => { setSent(false); setCode(""); setMailError(null); }}>Use a different email</button>
            </p>
          </form>
        )}
      </div>
    </main>
  );
}
