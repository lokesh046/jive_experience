"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { OtpInput } from "@/components/OtpInput";
import { Photo } from "@/components/Photo";
import { ApiError, api, takeNext } from "@/lib/api-client";
import { site } from "@/lib/images";

const GOOGLE = (
  <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M23 12.3c0-.8-.1-1.5-.2-2.2H12v4.3h6.2a5.3 5.3 0 0 1-2.3 3.5v2.9h3.7c2.2-2 3.4-5 3.4-8.5z"/><path fill="#34A853" d="M12 24c3.1 0 5.7-1 7.6-2.8l-3.7-2.9c-1 .7-2.3 1.1-3.9 1.1-3 0-5.5-2-6.4-4.7H1.8v3A12 12 0 0 0 12 24z"/><path fill="#FBBC05" d="M5.6 14.7a7.2 7.2 0 0 1 0-4.6v-3H1.8a12 12 0 0 0 0 10.6l3.8-3z"/><path fill="#EA4335" d="M12 4.8c1.7 0 3.2.6 4.4 1.7l3.3-3.3A11.6 11.6 0 0 0 12 0 12 12 0 0 0 1.8 6.9l3.8 3c.9-2.7 3.4-5.1 6.4-5.1z"/></svg>
);

export default function SignIn() {
  const router = useRouter();
  const [googleBusy, setGoogleBusy] = useState(false);
  const [googleError, setGoogleError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [wait, setWait] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wrong, setWrong] = useState(false);
  const submitting = useRef(false);

  // A new code can be asked for once a minute, matching the server.
  useEffect(() => {
    if (wait <= 0) return;
    const id = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(id);
  }, [wait]);

  async function google() {
    setGoogleBusy(true); setGoogleError(null);
    try {
      const r = await api<{ authorization_url: string }>("auth/google/authorize");
      window.location.assign(r.authorization_url);
    } catch (e) {
      setGoogleBusy(false);
      setGoogleError(e instanceof ApiError ? e.message : "We could not start sign-in. Please try again.");
    }
  }

  async function sendCode(e?: React.FormEvent) {
    e?.preventDefault();
    setBusy(true); setError(null); setWrong(false);
    try {
      await api("auth/email/request", { method: "POST", json: { email: email.trim() } });
      setSent(true); setWait(60); setCode("");
    } catch (err) {
      setError(err instanceof ApiError ? (err.status === 429 ? "Too many attempts. Please wait a few minutes." : err.message) : "We could not send the code. Please try again.");
    } finally { setBusy(false); }
  }

  async function verify(value: string) {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true); setError(null); setWrong(false);
    try {
      await api("auth/email/verify", { method: "POST", json: { email: email.trim(), code: value } });
      router.replace(takeNext());
    } catch (err) {
      setBusy(false); setWrong(true); setCode("");
      setError(err instanceof ApiError ? err.message : "Sign-in did not complete. Please try again.");
    } finally { submitting.current = false; }
  }

  function changeEmail() {
    setSent(false); setCode(""); setError(null); setWrong(false); setWait(0);
  }

  return (
    <main className="page auth-page">
      <div className="wrap">
        <section className="auth">
          <div className="auth-card">
            <Link className="auth-logo" href="/" aria-label="JIVE home">JIVE</Link>

            {!sent ? (
              <>
                <div className="auth-head">
                  <h1>Sign in</h1>
                  <p>One account for your tickets, bookings and entry codes. Staff sign in the same way.</p>
                </div>
                <button className="pill ghost full auth-google" type="button" onClick={google} disabled={googleBusy}>
                  {GOOGLE}{googleBusy ? "Opening Google…" : "Continue with Google"}
                </button>
                {googleError && <p className="err" role="alert">{googleError}</p>}
                <div className="or" role="separator"><span>or with email</span></div>
                <form className="otp" onSubmit={sendCode}>
                  <div className="f">
                    <label htmlFor="otp-e">Email address</label>
                    <input id="otp-e" type="email" required autoComplete="email" inputMode="email" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
                  </div>
                  <button className="pill full" type="submit" disabled={busy || !email.trim()}>{busy ? "Sending…" : "Email me a code"}</button>
                  {error && <p className="err" role="alert">{error}</p>}
                </form>
                <p className="small auth-note">We never see your Google password. Email sign-in uses a one-time code, so there is no password to remember.</p>
              </>
            ) : (
              <>
                <button type="button" className="auth-back" onClick={changeEmail}><span aria-hidden="true">←</span> Change email</button>
                <div className="auth-head">
                  <h1>Check your email</h1>
                  <p>We sent a 6-digit code to <b>{email.trim()}</b>. It works for 10 minutes.</p>
                </div>
                <form className="otp" onSubmit={(e) => { e.preventDefault(); if (code.length === 6) void verify(code); }}>
                  <div className="f otp-field">
                    <label id="otp-l">Verification code</label>
                    <OtpInput value={code} onChange={(v) => { setCode(v); if (wrong) setWrong(false); }} onComplete={(v) => void verify(v)} invalid={wrong} disabled={busy} />
                  </div>
                  <button className="pill full" type="submit" disabled={busy || code.length !== 6}>{busy ? "Checking…" : "Sign in"}</button>
                  {error && <p className="err" role="alert">{error}</p>}
                  <p className="small auth-links">
                    Did not get it? <button type="button" className="link" onClick={() => void sendCode()} disabled={wait > 0 || busy}>{wait > 0 ? `Send a new code in ${wait}s` : "Send a new code"}</button>
                  </p>
                </form>
              </>
            )}
          </div>

          <div className="auth-side" aria-hidden="true">
            <Photo src={site("hero")} alt="" sizes="440px" />
            <div className="auth-side-text">
              <p>Intimate live music evenings in converted mills, vaults and warehouses.</p>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
