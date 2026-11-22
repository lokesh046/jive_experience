"use client";
import { useEffect, useRef, useState } from "react";
import { PolicyEditor } from "@/components/admin/PolicyEditor";
import { ApiError, api } from "@/lib/api-client";
import { useData } from "@/lib/use-data";
import type { Policy, PolicyTier } from "@/lib/policy";

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
    </>
  );
}
