"use client";
import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { when } from "@/lib/admin";
import { useData } from "@/lib/use-data";
import type { Enquiry, EnquiryPage, SubscriberPage } from "@/lib/types";

const STATUS: Record<string, string> = { NEW: "New", CONTACTED: "Contacted", CLOSED: "Closed" };

export default function Inbox() {
  const [tab, setTab] = useState<"enquiries" | "news">("enquiries");
  return (
    <>
      <div className="ad-head"><h1>Inbox</h1></div>
      <div className="tabs" role="tablist" aria-label="Inbox" style={{ marginTop: 0 }}>
        <button role="tab" type="button" aria-selected={tab === "enquiries"} onClick={() => setTab("enquiries")}>Enquiries</button>
        <button role="tab" type="button" aria-selected={tab === "news"} onClick={() => setTab("news")}>Newsletter</button>
      </div>
      {tab === "enquiries" ? <Enquiries /> : <Newsletter />}
    </>
  );
}

function Enquiries() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const list = useData<EnquiryPage>(`admin/enquiries?size=20&page=${page}${status ? `&status=${status}` : ""}`);
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.size)) : 1;
  const counts = list.data?.counts ?? {};
  return (
    <>
      <div className="filters" role="group" aria-label="Filter by status" style={{ marginTop: 20 }}>
        {["", "NEW", "CONTACTED", "CLOSED"].map((s) => (
          <button key={s} type="button" aria-pressed={status === s} onClick={() => { setStatus(s); setPage(1); }}>
            {s ? STATUS[s] : "All"}{s && counts[s] ? ` (${counts[s]})` : ""}
          </button>
        ))}
      </div>
      {list.error && <p className="err" role="alert">{list.error}</p>}
      {list.loading && <div className="skeleton" style={{ height: 120, marginTop: 24 }} />}
      {list.data && list.data.items.length === 0 && <p className="empty">Nothing here yet. Enquiries from the homepage form appear in this list.</p>}
      {list.data?.items.map((e) => <EnquiryCard key={e.id} enquiry={e} onSaved={list.reload} />)}
      {pages > 1 && <p className="pager"><button type="button" className="link" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button> Page {page} of {pages} <button type="button" className="link" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button></p>}
    </>
  );
}

function EnquiryCard({ enquiry: e, onSaved }: { enquiry: Enquiry; onSaved: () => void }) {
  const [note, setNote] = useState(e.admin_note ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function save(next: Partial<{ status: string; admin_note: string }>) {
    setBusy(true); setErr(null);
    try { await api(`admin/enquiries/${e.id}`, { method: "PATCH", json: next }); onSaved(); }
    catch (x) { setErr(x instanceof ApiError ? x.message : "Could not save."); }
    finally { setBusy(false); }
  }
  return (
    <article className="enq-card">
      <header>
        <div><b>{e.name}</b><span className={`tag st-${e.status.toLowerCase()}`}>{STATUS[e.status]}</span><br /><span className="small">{when(e.created_at)}</span></div>
        <div className="enq-act">
          <a className="link" href={`mailto:${e.email}`}>Reply by email</a>
          <select aria-label={`Status of the enquiry from ${e.name}`} value={e.status} disabled={busy} onChange={(ev) => void save({ status: ev.target.value })}>
            {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
      </header>
      <p className="small">{e.email}{e.phone ? ` · ${e.phone}` : ""}{e.event_date ? ` · wants ${e.event_date}` : ""}{e.guests ? ` · ${e.guests} guests` : ""}</p>
      <p className="enq-msg">{e.message}</p>
      <div className="f"><label htmlFor={`note-${e.id}`}>Your note (only admins see it)</label>
        <textarea id={`note-${e.id}`} value={note} onChange={(ev) => setNote(ev.target.value)} onBlur={() => note !== (e.admin_note ?? "") && void save({ admin_note: note })} rows={2} maxLength={2000} /></div>
      {err && <p className="err" role="alert">{err}</p>}
    </article>
  );
}

function Newsletter() {
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const list = useData<SubscriberPage>(`admin/subscribers?size=20&page=${page}${q ? `&search=${encodeURIComponent(q)}` : ""}`);
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.size)) : 1;

  async function download() {
    setBusy(true); setErr(null);
    try {
      const res = await fetch("/api/admin/subscribers.csv", { cache: "no-store" });
      if (!res.ok) throw new Error();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await res.blob());
      a.download = `newsletter-subscribers-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch { setErr("The list could not be downloaded. Please try again."); }
    finally { setBusy(false); }
  }

  return (
    <>
      <div className="ad-head" style={{ marginTop: 24 }}>
        <p><strong style={{ font: "400 32px var(--font-serif), serif", color: "var(--fg)" }}>{list.data?.active ?? "—"}</strong> <span className="small">people are subscribed</span></p>
        {list.data && list.data.active > 0 && <button className="pill sm ghost" type="button" onClick={download} disabled={busy}>{busy ? "Preparing…" : "Download addresses (CSV)"}</button>}
      </div>
      {err && <p className="err" role="alert">{err}</p>}
      <form className="ad-bar" style={{ flexDirection: "row" }} onSubmit={(e) => { e.preventDefault(); setQ(typed.trim()); setPage(1); }}>
        <div className="f"><label htmlFor="ns">Search</label><input id="ns" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Email" maxLength={80} /></div>
        <button className="pill sm" type="submit">Search</button>
      </form>
      {list.error && <p className="err" role="alert">{list.error}</p>}
      {list.data && (
        <div className="tbl" role="table" aria-label="Subscribers">
          <div className="tr th" style={{ gridTemplateColumns: "2fr 1fr 1fr" }}><span>Email</span><span>Joined</span><span>Status</span></div>
          {list.data.items.length === 0 && <p className="empty">No one yet. The signup box is in the footer of every page.</p>}
          {list.data.items.map((s) => (
            <div className="tr" key={s.email} style={{ gridTemplateColumns: "2fr 1fr 1fr" }}>
              <span style={{ overflowWrap: "anywhere" }}>{s.email}</span><span>{when(s.created_at)}</span><span>{s.subscribed ? "Subscribed" : "Unsubscribed"}</span>
            </div>
          ))}
          {pages > 1 && <p className="pager"><button type="button" className="link" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button> Page {page} of {pages} <button type="button" className="link" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button></p>}
        </div>
      )}
    </>
  );
}
