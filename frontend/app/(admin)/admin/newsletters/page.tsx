"use client";
import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { when } from "@/lib/admin";
import { useData } from "@/lib/use-data";
import type { Campaign, EventAdmin, Page, SubscriberPage } from "@/lib/types";

interface Form { id: string | null; subject: string; body: string; event: string; label: string; url: string }
const BLANK: Form = { id: null, subject: "", body: "", event: "", label: "", url: "" };

export default function Newsletters() {
  const list = useData<Campaign[]>("admin/newsletters");
  const events = useData<Page<EventAdmin>>("admin/events?size=100");
  const subs = useData<SubscriberPage>("admin/subscribers?size=1");
  const [form, setForm] = useState<Form | null>(null);
  const [view, setView] = useState<Campaign | null>(null);
  const [busy, setBusy] = useState<"save" | "test" | "send" | null>(null);
  const [msg, setMsg] = useState<{ text: string; ok?: boolean } | null>(null);
  const reload = list.reload;
  const active = subs.data?.active ?? 0;
  const sending = list.data?.some((c) => c.status === "SENT" && c.pending > 0);

  // While an issue is going out, keep its counts fresh.
  useEffect(() => {
    if (!sending) return;
    const id = setInterval(reload, 4000);
    return () => clearInterval(id);
  }, [sending, reload]);

  const event = events.data?.items.find((e) => e.id === form?.event);
  const fail = (e: unknown, fallback: string) => setMsg({ text: e instanceof ApiError ? e.message : fallback });
  const body = (f: Form) => ({ subject: f.subject.trim(), body: f.body.trim(), event_id: f.event || null, button_label: f.label.trim() || null, button_url: f.url.trim() || null });

  async function save(): Promise<string | null> {
    if (!form) return null;
    if (!form.subject.trim() || !form.body.trim()) { setMsg({ text: "Add a subject and a message." }); return null; }
    if (!!form.label.trim() !== !!form.url.trim()) { setMsg({ text: "A button needs both a label and a link." }); return null; }
    const saved = form.id
      ? await api<Campaign>(`admin/newsletters/${form.id}`, { method: "PUT", json: body(form) })
      : await api<Campaign>("admin/newsletters", { method: "POST", json: body(form) });
    setForm({ ...form, id: saved.id });
    reload();
    return saved.id;
  }
  async function run(kind: "save" | "test" | "send") {
    setBusy(kind); setMsg(null);
    try {
      const id = await save();
      if (!id) return;
      if (kind === "save") setMsg({ text: "Draft saved.", ok: true });
      if (kind === "test") {
        const r = await api<{ sent_to: string }>(`admin/newsletters/${id}/test`, { method: "POST" });
        setMsg({ text: `A test copy is on its way to ${r.sent_to}.`, ok: true });
      }
      if (kind === "send") {
        if (!window.confirm(`Send this to ${active} ${active === 1 ? "person" : "people"}? It cannot be recalled.`)) return;
        const r = await api<{ queued: number }>(`admin/newsletters/${id}/send`, { method: "POST" });
        setForm(null); reload();
        setMsg({ text: `Sending to ${r.queued} ${r.queued === 1 ? "person" : "people"}. Progress shows below.`, ok: true });
      }
    } catch (e) { fail(e, "Something went wrong. Please try again."); }
    finally { setBusy(null); }
  }
  async function remove(c: Campaign) {
    if (!window.confirm(`Delete the draft "${c.subject}"?`)) return;
    try { await api(`admin/newsletters/${c.id}`, { method: "DELETE" }); reload(); }
    catch (e) { fail(e, "Could not delete the draft."); }
  }
  function edit(c: Campaign) {
    setView(null); setMsg(null);
    setForm({ id: c.id, subject: c.subject, body: c.body, event: c.event_id ?? "", label: c.button_label ?? "", url: c.button_url ?? "" });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const status = (c: Campaign) =>
    c.status === "DRAFT" ? "Draft"
      : c.pending > 0 ? `Sending: ${c.delivered} of ${c.recipients}`
      : c.failed > 0 ? `Sent to ${c.delivered} of ${c.recipients}, ${c.failed} failed`
      : `Sent to ${c.delivered}`;

  const preview = (f: { subject: string; body: string; label: string; url: string; eventTitle?: string | null; eventWhen?: string | null }) => {
    const paras = f.body.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
    const label = f.label || (f.eventTitle ? "Get tickets" : "");
    return (
      <div className="nl-prev" aria-label="Preview">
        <p className="nl-logo">JIVE</p>
        {paras.length === 0 && <p className="hint">Your message appears here.</p>}
        {paras.map((p, i) => <p key={i} style={{ whiteSpace: "pre-line" }}>{p}</p>)}
        {f.eventTitle && <div className="nl-card"><b>{f.eventTitle}</b><span>{f.eventWhen}</span></div>}
        {label && (f.url || f.eventTitle) && <span className="nl-btn">{label}</span>}
        <p className="nl-foot">You get this because you joined the JIVE list. Unsubscribe.</p>
      </div>
    );
  };

  return (
    <>
      <div className="ad-head"><h1>Newsletters</h1>{!form && <button className="pill" type="button" onClick={() => { setForm(BLANK); setView(null); setMsg(null); }}>New newsletter</button>}</div>
      <p className="hint">Write to everyone who joined the list. {subs.data ? <><strong style={{ color: "var(--fg)" }}>{active}</strong> {active === 1 ? "person is" : "people are"} subscribed.</> : null} Every email has its own unsubscribe link. Gmail sends about 500 emails a day, so a longer list needs a mail service.</p>
      {msg && <p className={msg.ok ? "ok" : "err"} role={msg.ok ? "status" : "alert"} style={msg.ok ? { marginLeft: 0 } : undefined}>{msg.text}</p>}

      {form && (
        <section className="ad-sec nl-compose" style={{ borderTop: 0, marginTop: 20, paddingTop: 0 }}>
          <h2>{form.id ? "Edit newsletter" : "New newsletter"}</h2>
          <div className="nl-cols">
            <div className="nl-fields">
              <div className="f"><label htmlFor="ns">Subject</label><input id="ns" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} maxLength={200} placeholder="A new night at the vault" /></div>
              <div className="f"><label htmlFor="nb">Message</label><textarea id="nb" rows={10} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} maxLength={10000} placeholder={"Hello,\n\nWrite as you would to a friend. A blank line starts a new paragraph."} /></div>
              <div className="f"><label htmlFor="ne">Feature a night (optional)</label>
                <select id="ne" value={form.event} onChange={(e) => setForm({ ...form, event: e.target.value })}><option value="">None</option>{events.data?.items.filter((e) => e.status !== "CANCELLED").map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}</select>
                <span className="hint">Adds its photo, date and a Get tickets button.</span></div>
              <div className="ad-grid">
                <div className="f"><label htmlFor="nl">Button label (optional)</label><input id="nl" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} maxLength={60} placeholder="Get tickets" /></div>
                <div className="f"><label htmlFor="nu">Button link</label><input id="nu" type="url" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} maxLength={500} placeholder="https://" /></div>
              </div>
              <div className="ad-actions">
                <button className="pill" type="button" onClick={() => void run("send")} disabled={busy !== null || active === 0}>{busy === "send" ? "Sending…" : `Send to ${active}`}</button>
                <button className="pill ghost" type="button" onClick={() => void run("test")} disabled={busy !== null}>{busy === "test" ? "Sending test…" : "Send a test to me"}</button>
                <button className="link" type="button" onClick={() => void run("save")} disabled={busy !== null}>{busy === "save" ? "Saving…" : "Save draft"}</button>
                <button className="link" type="button" onClick={() => { setForm(null); setMsg(null); }}>Close</button>
              </div>
              {active === 0 && <p className="hint">Nobody is subscribed yet, so there is nobody to send to.</p>}
            </div>
            {preview({ ...form, eventTitle: event?.title, eventWhen: event ? when(event.starts_at) : null })}
          </div>
        </section>
      )}

      {view && (
        <section className="ad-sec" style={{ marginTop: 20 }}>
          <div className="ad-head"><h2 style={{ margin: 0 }}>{view.subject}</h2><button className="link" type="button" onClick={() => setView(null)}>Close</button></div>
          <p className="hint" style={{ marginBottom: 16 }}>{status(view)}{view.sent_at ? ` · ${when(view.sent_at)}` : ""}</p>
          {preview({ subject: view.subject, body: view.body, label: view.button_label ?? "", url: view.button_url ?? "", eventTitle: events.data?.items.find((e) => e.id === view.event_id)?.title, eventWhen: null })}
        </section>
      )}

      {list.error && <p className="err" role="alert">{list.error}</p>}
      {list.loading && <div className="skeleton" style={{ height: 120, marginTop: 24 }} />}
      {list.data && list.data.length === 0 && !form && <p className="empty">No newsletters yet. Write one to announce a new night.</p>}
      {list.data && list.data.length > 0 && (
        <div className="tbl" role="table" aria-label="Newsletters">
          <div className="tr th" style={{ gridTemplateColumns: "2fr 1.6fr 1fr auto" }}><span>Subject</span><span>Status</span><span>Date</span><span /></div>
          {list.data.map((c) => (
            <div className="tr" key={c.id} style={{ gridTemplateColumns: "2fr 1.6fr 1fr auto" }}>
              <span className="name">{c.subject}</span>
              <span><span className={`stchip ${c.status === "SENT" ? (c.pending > 0 ? "wait" : c.failed > 0 ? "off" : "good") : "off"}`}>{status(c)}</span></span>
              <span className="small">{when(c.sent_at ?? c.created_at)}</span>
              <span style={{ display: "flex", gap: 16 }}>
                {c.status === "DRAFT"
                  ? <><button className="link" type="button" onClick={() => edit(c)}>Edit</button><button className="link" type="button" onClick={() => void remove(c)}>Delete</button></>
                  : <button className="link" type="button" onClick={() => { setView(c); setForm(null); }}>View</button>}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
