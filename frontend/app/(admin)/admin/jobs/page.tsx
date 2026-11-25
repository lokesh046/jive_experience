"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { ago } from "@/lib/format";
import type { JobRow, JobsOverview, Page } from "@/lib/types";

type Tab = "FAILED" | "PENDING" | "PROCESSING" | "DONE";
const TABS: { key: Tab; label: string }[] = [
  { key: "FAILED", label: "Failed" }, { key: "PENDING", label: "Waiting" }, { key: "PROCESSING", label: "Running" }, { key: "DONE", label: "Done" },
];
const LANE = ["Urgent", "Normal", "Reminder", "Bulk"];
const every = (s: number) => (s < 90 ? `${s} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`);

export default function Jobs() {
  const [o, setO] = useState<JobsOverview | null>(null);
  const [tab, setTab] = useState<Tab | null>(null);
  const [rows, setRows] = useState<Page<JobRow> | null>(null);
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; ok?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const picked = useRef(false);

  const loadOverview = useCallback(() => api<JobsOverview>("admin/jobs/overview").then((d) => {
    setO(d);
    if (!picked.current) { picked.current = true; setTab(d.queue.failed > 0 ? "FAILED" : "PENDING"); }
  }).catch((e) => setMsg({ text: e instanceof ApiError ? e.message : "Could not load the worker status." })), []);

  const loadRows = useCallback(() => {
    if (!tab) return;
    api<Page<JobRow>>(`admin/jobs?status=${tab}&page=${page}&size=25`).then(setRows).catch(() => {});
  }, [tab, page]);

  useEffect(() => { void loadOverview(); }, [loadOverview]);
  useEffect(() => { loadRows(); }, [loadRows]);
  useEffect(() => {
    const id = setInterval(() => { void loadOverview(); loadRows(); }, 10000);
    return () => clearInterval(id);
  }, [loadOverview, loadRows]);

  async function act(run: () => Promise<unknown>, done: string) {
    setBusy(true); setMsg(null);
    try { await run(); setMsg({ text: done, ok: true }); await loadOverview(); loadRows(); }
    catch (e) { setMsg({ text: e instanceof ApiError ? e.message : "That did not work. Please try again." }); }
    finally { setBusy(false); }
  }
  const retry = (j: JobRow) => act(() => api(`admin/jobs/${j.id}/retry`, { method: "POST" }), "Back in the queue. The worker will pick it up in a few seconds.");
  const retryAll = () => act(async () => { const r = await api<{ retried: number }>("admin/jobs/retry-failed", { method: "POST" }); setMsg({ text: `${r.retried} job${r.retried === 1 ? "" : "s"} back in the queue.`, ok: true }); }, "");
  const discard = (j: JobRow) => { if (window.confirm(`Discard "${j.label}"? It will not be tried again.`)) void act(() => api(`admin/jobs/${j.id}`, { method: "DELETE" }), "Discarded."); };

  const q = o?.queue;
  const state = !o ? "…" : !o.worker_ever_seen ? "Never started" : o.worker_alive ? "Running" : "Stopped";
  const w = o?.workers[0];

  return (
    <>
      <div className="ad-head"><h1>Background jobs</h1></div>
      <p className="hint">Everything the site does behind the scenes: issuing and emailing tickets, sending refunds, reminders and notifications. This page refreshes itself.</p>
      {msg && <p className={msg.ok ? "ok" : "err"} role={msg.ok ? "status" : "alert"} style={msg.ok ? { marginLeft: 0 } : undefined}>{msg.text}</p>}

      <div className="jb-cards five">
        <div className={`jb-card ${o && o.worker_ever_seen && !o.worker_alive ? "bad" : ""}`}>
          <span className="small">Worker</span>
          <strong className={o?.worker_alive ? "good" : ""}>{state}</strong>
          <span className="small">{w ? `Seen ${ago(w.last_seen_at)}${w.host ? ` · ${w.host}` : ""}` : o ? "No worker has reported in yet." : ""}</span>
        </div>
        <div className="jb-card"><span className="small">Waiting</span><strong>{q?.waiting ?? "…"}</strong><span className="small">{q ? (q.ready === 0 ? "Nothing ready to run" : `${q.ready} ready now${q.oldest_ready_seconds > 60 ? `, oldest ${Math.round(q.oldest_ready_seconds / 60)} min` : ""}`) : ""}</span></div>
        <div className="jb-card"><span className="small">Running now</span><strong>{q?.running ?? "…"}</strong><span className="small">{q ? `${q.done_24h} done in 24 h` : ""}</span></div>
        <div className={`jb-card ${o?.email.enforced && o.email.used_24h >= o.email.limit * 0.9 ? "warn" : ""}`}>
          <span className="small">Email, last 24 hours</span>
          <strong>{o ? (o.email.enforced ? `${o.email.used_24h} / ${o.email.limit}` : "No limit") : "…"}</strong>
          <span className="small">{o ? (o.email.enforced ? `Newsletters and reminders may use ${o.email.bulk_cap}; the rest is kept for tickets and refunds.` : "Set EMAIL_DAILY_LIMIT to stay inside your mail account's allowance.") : ""}</span>
        </div>
        <div className={`jb-card ${q && q.failed > 0 ? "warn" : ""}`}><span className="small">Failed</span><strong>{q?.failed ?? "…"}</strong><span className="small">{q ? (q.failed ? "Gave up after several tries" : "Nothing is stuck") : ""}</span></div>
      </div>

      <div className="tabs" role="tablist" aria-label="Jobs">
        {TABS.map((t) => (
          <button key={t.key} role="tab" type="button" aria-selected={tab === t.key} onClick={() => { setTab(t.key); setPage(1); setOpen(null); }}>
            {t.label}{t.key === "FAILED" && q && q.failed > 0 ? ` (${q.failed})` : ""}
          </button>
        ))}
      </div>
      {tab === "FAILED" && q && q.failed > 0 && <p style={{ margin: "0 0 12px" }}><button className="pill sm" type="button" onClick={() => void retryAll()} disabled={busy}>Retry all {q.failed} failed</button></p>}

      {!rows && <div className="skeleton" style={{ height: 96 }} />}
      {rows && rows.items.length === 0 && <p className="empty">{tab === "FAILED" ? "Nothing has failed." : tab === "PENDING" ? "Nothing is waiting." : tab === "PROCESSING" ? "Nothing is running right now." : "Nothing finished recently."}</p>}
      {rows && rows.items.length > 0 && (
        <div className="tbl" role="table" aria-label="Jobs">
          <div className="tr th" style={{ gridTemplateColumns: "2fr 0.8fr 1fr auto" }}><span>Job</span><span>Tries</span><span>When</span><span /></div>
          {rows.items.map((j) => (
            <div key={j.id}>
              <div className="tr" style={{ gridTemplateColumns: "2fr 0.8fr 1fr auto" }}>
                <span><span className="name">{j.label}</span>{j.priority !== 1 && <span className="tag">{LANE[j.priority] ?? "Normal"}</span>}{j.label !== j.topic && <><br /><span className="small">{j.topic}</span></>}{j.last_error && <><br /><span className="small jb-err">{j.last_error.slice(0, 110)}{j.last_error.length > 110 ? "…" : ""}</span></>}</span>
                <span>{j.attempts} of {j.max_attempts}</span>
                <span className="small">{j.status === "DONE" && j.completed_at ? `Done ${ago(j.completed_at)}` : j.status === "PENDING" && new Date(j.available_at) > new Date() ? `Runs ${new Date(j.available_at).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}` : `Queued ${ago(j.created_at)}`}</span>
                <span style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                  {j.status === "FAILED" && <><button className="link" type="button" onClick={() => void retry(j)} disabled={busy}>Retry</button><button className="link" type="button" onClick={() => discard(j)} disabled={busy}>Discard</button></>}
                  <button className="link" type="button" onClick={() => setOpen(open === j.id ? null : j.id)} aria-expanded={open === j.id}>Details</button>
                </span>
              </div>
              {open === j.id && <pre className="jb-detail">{JSON.stringify({ id: j.id, payload: j.payload, error: j.last_error, created: j.created_at, next_attempt: j.available_at }, null, 2)}</pre>}
            </div>
          ))}
          {rows.total > rows.size && <p className="pager"><button type="button" className="link" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button> Page {page} of {Math.ceil(rows.total / rows.size)} <button type="button" className="link" disabled={page >= Math.ceil(rows.total / rows.size)} onClick={() => setPage(page + 1)}>Next</button></p>}
        </div>
      )}

      <section className="ad-sec" aria-labelledby="sch-h">
        <h2 id="sch-h">Scheduled jobs</h2>
        <p className="hint" style={{ marginBottom: 16 }}>Work the worker does on a timer. A job shows as late if it has missed several runs in a row.</p>
        {o && o.schedules.length === 0 && <p className="empty">None have run yet. They appear once the worker has started.</p>}
        {o && o.schedules.length > 0 && (
          <div className="tbl" role="table" aria-label="Scheduled jobs">
            <div className="tr th" style={{ gridTemplateColumns: "2fr 0.8fr 1fr 1fr" }}><span>Job</span><span>Every</span><span>Last run</span><span>Result</span></div>
            {o.schedules.map((s) => (
              <div className="tr" key={s.name} style={{ gridTemplateColumns: "2fr 0.8fr 1fr 1fr" }}>
                <span className="name">{s.label}</span>
                <span>{every(s.interval_seconds)}</span>
                <span className="small">{s.last_finished_at ? ago(s.last_finished_at) : "Not yet"}</span>
                <span><span className={`stchip ${s.last_status === "ERROR" || s.overdue ? "off" : "good"}`} title={s.last_error ?? undefined}>{s.last_status === "ERROR" ? "Failed" : s.overdue ? "Late" : "On time"}</span></span>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
