"use client";
import { useEffect, useRef, useState } from "react";
import { PolicyEditor } from "@/components/admin/PolicyEditor";
import { ApiError, api } from "@/lib/api-client";
import { useData } from "@/lib/use-data";
import type { Policy, PolicyTier } from "@/lib/policy";

function AutomaticEmails() {
  const { data, error, reload } = useData<{ abandoned_emails: boolean }>("admin/settings/emails");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  async function flip(next: boolean) {
    setBusy(true); setNote(null);
    try { await api("admin/settings/emails", { method: "PUT", json: { abandoned_emails: next } }); reload(); }
    catch (e) { setNote(e instanceof ApiError ? e.message : "Could not save."); }
    finally { setBusy(false); }
  }
  return (
    <section className="ad-sec" aria-labelledby="auto-h">
      <h2 id="auto-h">Automatic emails</h2>
      <p className="hint" style={{ marginBottom: 20 }}>Ticket, reminder, cancellation and refund emails always go out. This one is optional.</p>
      {error && <p className="err" role="alert">{error}</p>}
      {data && (
        <div className="chk">
          <label><input type="checkbox" checked={data.abandoned_emails} disabled={busy} onChange={(e) => void flip(e.target.checked)} /> Remind people who started a booking but did not pay</label>
          <p className="hint" style={{ marginTop: 8 }}>One email, about half an hour later, with a link back to the event. Only if the night is still on sale and the tickets they wanted are still available. Never more than once a day per night, and never to counter sales.</p>
        </div>
      )}
      {note && <p className="err" role="alert">{note}</p>}
    </section>
  );
}

export default function Settings() {
  const { data, error } = useData<{ policy: Policy | null }>("admin/settings/cancellation-policy");
  const [tiers, setTiers] = useState<PolicyTier[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ text: string; ok?: boolean } | null>(null);
  const loaded = useRef(false);
  useEffect(() => {
    if (data && !loaded.current) { loaded.current = true; queueMicrotask(() => setTiers(data.policy?.tiers ?? [])); }
  }, [data]);

  async function save() {
    setBusy(true); setNote(null);
    try {
      await api("admin/settings/cancellation-policy", { method: "PUT", json: { policy: tiers && tiers.length ? { tiers } : null } });
      setNote({ text: "Saved. Event pages now show this policy.", ok: true });
    } catch (e) { setNote({ text: e instanceof ApiError ? e.message : "Could not save." }); }
    finally { setBusy(false); }
  }

  return (
    <>
      <div className="ad-head"><h1>Settings</h1></div>
      <section className="ad-sec" style={{ borderTop: 0, marginTop: 0, paddingTop: 0 }} aria-labelledby="pol-h">
        <h2 id="pol-h">Default refund policy</h2>
        <p className="hint" style={{ marginBottom: 20 }}>Used by every event that doesn&apos;t set its own. Customers see it on the event page and on the Cancellation policy page, and it decides what a customer gets back when they cancel a booking. If the company cancels an event, every booking is refunded in full whatever this says.</p>
        {error && <p className="err" role="alert">{error}</p>}
        {tiers && <PolicyEditor tiers={tiers} onChange={(t) => { setTiers(t); setNote(null); }} />}
        {note && <p className={note.ok ? "ok" : "err"} role={note.ok ? "status" : "alert"} style={note.ok ? { marginLeft: 0 } : undefined}>{note.text}</p>}
        <div className="ad-actions"><button className="pill" type="button" onClick={save} disabled={busy || tiers === null}>{busy ? "Saving…" : "Save policy"}</button></div>
      </section>
      <AutomaticEmails />
    </>
  );
}
