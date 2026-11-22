"use client";
import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { fromIst, rupees, toPaise, when } from "@/lib/admin";
import { useData } from "@/lib/use-data";
import type { EventAdmin, Page, Promo } from "@/lib/types";

const EMPTY = { code: "", description: "", type: "PERCENT", value: "10", event: "", max: "", per: "1", from: "", until: "" };

export default function Promos() {
  const [page, setPage] = useState(1);
  const list = useData<Page<Promo>>(`admin/promos?size=20&page=${page}`);
  const events = useData<Page<EventAdmin>>("admin/events?size=100");
  const [form, setForm] = useState<typeof EMPTY | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.size)) : 1;
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((f) => (f ? { ...f, [k]: e.target.value } : f));
  const titleOf = (id: string | null) => (id ? events.data?.items.find((e) => e.id === id)?.title ?? "One event" : "All events");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy(true); setMsg(null);
    try {
      await api("admin/promos", {
        method: "POST",
        json: {
          code: form.code.trim(), description: form.description.trim() || null,
          discount_type: form.type,
          percent_off: form.type === "PERCENT" ? Number(form.value) : null,
          amount_off_paise: form.type === "FIXED" ? toPaise(form.value) : null,
          event_id: form.event || null,
          max_uses: form.max ? Number(form.max) : null,
          max_uses_per_customer: form.per ? Number(form.per) : null,
          valid_from: fromIst(form.from), valid_until: fromIst(form.until),
        },
      });
      setForm(null); list.reload();
    } catch (err) { setMsg(err instanceof ApiError ? err.message : "Could not save the code."); }
    finally { setBusy(false); }
  }
  async function toggle(p: Promo) {
    try { await api(`admin/promos/${p.id}`, { method: "PATCH", json: { is_active: !p.is_active } }); list.reload(); }
    catch (err) { setMsg(err instanceof ApiError ? err.message : "Could not change the code."); }
  }
  async function remove(p: Promo) {
    if (!window.confirm(`Delete ${p.code}? This cannot be undone.`)) return;
    try { await api(`admin/promos/${p.id}`, { method: "DELETE" }); list.reload(); }
    catch (err) { setMsg(err instanceof ApiError ? err.message : "Could not delete the code."); }
  }
  const cols = "1.2fr 1.1fr 1.2fr 0.9fr 1.2fr auto";

  return (
    <>
      <div className="ad-head"><h1>Promo codes</h1>{!form && <button className="pill" type="button" onClick={() => setForm(EMPTY)}>New code</button>}</div>
      {msg && !form && <p className="err" role="alert">{msg}</p>}

      {form && (
        <form onSubmit={save} className="ad-sec" style={{ borderTop: 0, marginTop: 0, paddingTop: 0 }}>
          <h2>New promo code</h2>
          <div className="ad-grid">
            <div className="f"><label htmlFor="pc">Code</label><input id="pc" value={form.code} onChange={set("code")} required minLength={3} maxLength={32} placeholder="SPRING2027" style={{ textTransform: "uppercase" }} /></div>
            <div className="f"><label htmlFor="pd">Note (only you see this)</label><input id="pd" value={form.description} onChange={set("description")} maxLength={200} placeholder="Newsletter subscribers" /></div>
            <div className="f"><label htmlFor="pt">Type</label>
              <select id="pt" value={form.type} onChange={set("type")}><option value="PERCENT">Percentage off</option><option value="FIXED">Fixed amount off the whole booking</option></select></div>
            <div className="f"><label htmlFor="pv">{form.type === "PERCENT" ? "Percent off (1 to 100)" : "Rupees off"}</label><input id="pv" type="number" min={form.type === "PERCENT" ? 1 : 1} max={form.type === "PERCENT" ? 100 : undefined} step={form.type === "PERCENT" ? 1 : 0.01} value={form.value} onChange={set("value")} required /></div>
            <div className="f"><label htmlFor="pe">Works for</label>
              <select id="pe" value={form.event} onChange={set("event")}><option value="">All events</option>{events.data?.items.map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}</select></div>
            <div className="f"><label htmlFor="pm">Total uses (blank = unlimited)</label><input id="pm" type="number" min={1} value={form.max} onChange={set("max")} /></div>
            <div className="f"><label htmlFor="pp">Uses per customer (blank = unlimited)</label><input id="pp" type="number" min={1} value={form.per} onChange={set("per")} /></div>
            <div className="f" />
            <div className="f"><label htmlFor="pf">Starts (India time, optional)</label><input id="pf" type="datetime-local" value={form.from} onChange={set("from")} /></div>
            <div className="f"><label htmlFor="pu">Ends (India time, optional)</label><input id="pu" type="datetime-local" value={form.until} onChange={set("until")} /></div>
          </div>
          <p className="hint" style={{ marginTop: 16 }}>The discount, the code and which events it works for cannot be changed after you save: make a new code instead. A discount can never take more than the ticket price, and a code worth the full price confirms the booking without payment.</p>
          {msg && <p className="err" role="alert">{msg}</p>}
          <div className="ad-actions"><button className="pill" type="submit" disabled={busy}>{busy ? "Saving…" : "Save code"}</button><button className="link" type="button" onClick={() => { setForm(null); setMsg(null); }}>Cancel</button></div>
        </form>
      )}

      {list.error && <p className="err" role="alert">{list.error}</p>}
      {list.loading && <div className="skeleton" style={{ height: 120, marginTop: 24 }} />}
      {list.data && (
        <div className="tbl" role="table" aria-label="Promo codes">
          <div className="tr th" style={{ gridTemplateColumns: cols }}><span>Code</span><span>Discount</span><span>Works for</span><span className="num">Used</span><span>When</span><span /></div>
          {list.data.items.length === 0 && <p className="empty">No promo codes yet. Create one to offer a discount.</p>}
          {list.data.items.map((p) => (
            <div className="tr" key={p.id} style={{ gridTemplateColumns: cols }}>
              <span><span className="name">{p.code}</span>{!p.is_active && <span className="tag">Off</span>}{p.description && <><br /><span className="small">{p.description}</span></>}</span>
              <span>{p.discount_type === "PERCENT" ? `${p.percent_off}% off` : `₹${rupees(p.amount_off_paise ?? 0)} off`}</span>
              <span>{titleOf(p.event_id)}</span>
              <span className="num">{p.used_count}{p.max_uses ? ` / ${p.max_uses}` : ""}</span>
              <span className="small">{p.valid_from ? when(p.valid_from) : "Now"} to {p.valid_until ? when(p.valid_until) : "no end"}</span>
              <span style={{ display: "flex", gap: 16 }}>
                <button className="link" type="button" onClick={() => void toggle(p)}>{p.is_active ? "Switch off" : "Switch on"}</button>
                {p.used_count === 0 && <button className="link" type="button" onClick={() => void remove(p)}>Delete</button>}
              </span>
            </div>
          ))}
          {pages > 1 && <p className="pager"><button type="button" className="link" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button> Page {page} of {pages} <button type="button" className="link" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button></p>}
        </div>
      )}
      {list.data && <p className="hint" style={{ marginTop: 24 }}>Customers enter a code on the event page. The discount is worked out on the server when they book, so it cannot be changed in the browser.</p>}
    </>
  );
}
