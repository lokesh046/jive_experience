"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

export function Unsubscribe() {
  const [token, setToken] = useState<string | undefined>(undefined);
  const [state, setState] = useState<"ask" | "busy" | "done" | "fail">("ask");
  useEffect(() => { queueMicrotask(() => setToken(new URLSearchParams(window.location.search).get("token") ?? "")); }, []);

  async function go() {
    if (!token) return;
    setState("busy");
    try { await api("newsletter/unsubscribe", { method: "POST", json: { token } }); setState("done"); }
    catch { setState("fail"); }
  }

  if (state === "done") return <><p style={{ margin: "24px 0 32px" }}>You are unsubscribed. We will not email you announcements any more.</p><Link className="pill" href="/">Back to the site</Link></>;
  if (token === undefined) return null;
  if (!token) return <p style={{ marginTop: 24 }}>This link is missing its code. Use the unsubscribe link in the email we sent you.</p>;
  return (
    <>
      <p style={{ margin: "24px 0 32px" }}>Stop receiving announcements about new nights?</p>
      <button className="pill" type="button" onClick={go} disabled={state === "busy"}>{state === "busy" ? "Working…" : "Unsubscribe"}</button>
      {state === "fail" && <p className="err" role="alert">That did not work. Please try again.</p>}
    </>
  );
}
