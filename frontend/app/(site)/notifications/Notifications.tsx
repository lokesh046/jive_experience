"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api, rememberNext } from "@/lib/api-client";
import { ago } from "@/lib/format";
import { disablePush, enablePush, pushState, sendTestPush, type PushState } from "@/lib/push";
import type { AppNotification, NotificationFeed, NotificationPreference } from "@/lib/types";

export function Notifications() {
  const router = useRouter();
  const [tab, setTab] = useState<"all" | "unread">("all");
  const [items, setItems] = useState<AppNotification[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [unread, setUnread] = useState(0);
  const [prefs, setPrefs] = useState<NotificationPreference[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [push, setPush] = useState<PushState | null>(null);
  const [pushNote, setPushNote] = useState<string | null>(null);

  const guard = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) { rememberNext("/notifications"); router.replace("/signin"); return; }
    setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
  }, [router]);

  const load = useCallback(async (which: "all" | "unread") => {
    try {
      const f = await api<NotificationFeed>(`notifications?limit=20${which === "unread" ? "&unread_only=true" : ""}`);
      setItems(f.items); setCursor(f.next_before); setUnread(f.unread);
    } catch (e) { guard(e); }
  }, [guard]);

  useEffect(() => {
    queueMicrotask(() => void load(tab));
  }, [tab, load]);
  useEffect(() => {
    api<NotificationPreference[]>("notifications/preferences").then(setPrefs).catch(() => {});
    void pushState().then(setPush).catch(() => setPush("unsupported"));
  }, []);

  async function togglePush() {
    setPushNote(null); setBusy(true);
    try {
      const next = push === "on" ? await disablePush() : await enablePush();
      setPush(next);
      if (next === "denied") setPushNote("Notifications are blocked for this site in your browser. Allow them in the site settings, then try again.");
    } catch (e) { guard(e); } finally { setBusy(false); }
  }
  async function testPush() {
    setPushNote(null); setBusy(true);
    try {
      const r = await sendTestPush();
      setPushNote(r.sent > 0 ? "A test notification is on its way." : "Nothing was delivered. Try turning it off and on again.");
    } catch (e) { guard(e); } finally { setBusy(false); }
  }

  async function more() {
    if (!cursor) return;
    setBusy(true);
    try {
      const f = await api<NotificationFeed>(`notifications?limit=20&before=${encodeURIComponent(cursor)}${tab === "unread" ? "&unread_only=true" : ""}`);
      setItems((cur) => [...(cur ?? []), ...f.items]); setCursor(f.next_before);
    } catch (e) { guard(e); } finally { setBusy(false); }
  }
  async function readAll() {
    try { await api("notifications/read-all", { method: "POST", json: {} }); setUnread(0); setItems((cur) => cur && (tab === "unread" ? [] : cur.map((n) => ({ ...n, read: true })))); window.dispatchEvent(new Event("jive-auth")); } catch (e) { guard(e); }
  }
  async function opened(n: AppNotification) {
    if (n.read) return;
    setItems((cur) => cur && cur.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
    try { const r = await api<{ unread: number }>("notifications/read", { method: "POST", json: { ids: [n.id] } }); setUnread(r.unread); } catch {}
  }
  async function change(category: string, field: "in_app" | "email" | "push", value: boolean) {
    setPrefs((cur) => cur && cur.map((p) => (p.category === category ? { ...p, [field]: value } : p)));
    try { setPrefs(await api<NotificationPreference[]>("notifications/preferences", { method: "PUT", json: { changes: [{ category, [field]: value }] } })); }
    catch (e) { guard(e); void api<NotificationPreference[]>("notifications/preferences").then(setPrefs).catch(() => {}); }
  }

  return (
    <main className="page">
      <div className="wrap">
        <div className="ad-head"><h1>Notifications</h1>{unread > 0 && <button className="pill sm ghost" type="button" onClick={() => void readAll()}>Mark all read</button>}</div>
        <p className="sub" style={{ margin: "12px 0 0" }}>{items === null ? " " : unread > 0 ? `${unread} unread` : "You are all caught up."}</p>
        <div className="tabs" role="tablist" aria-label="Show">
          <button role="tab" type="button" aria-selected={tab === "all"} onClick={() => setTab("all")}>All</button>
          <button role="tab" type="button" aria-selected={tab === "unread"} onClick={() => setTab("unread")}>Unread</button>
        </div>
        {error && <p className="err" role="alert">{error}</p>}
        {items === null && !error && <div className="skeleton" style={{ height: 96 }} />}
        {items && items.length === 0 && <p className="empty">{tab === "unread" ? "Nothing unread." : "Nothing yet. We will tell you here when something happens."}</p>}
        <ul className="nt-list">
          {items?.map((n) => {
            const inner = (<><i className={`dot ${n.severity}${n.read ? " read" : ""}`} aria-hidden="true" /><span><b>{n.title}</b>{n.body && <small>{n.body}</small>}<em>{ago(n.created_at)}</em></span></>);
            return <li key={n.id} className={n.read ? "" : "new"}>{n.link ? <Link href={n.link} onClick={() => void opened(n)}>{inner}</Link> : <div onClick={() => void opened(n)}>{inner}</div>}</li>;
          })}
        </ul>
        {cursor && <p style={{ marginTop: 24 }}><button className="pill ghost" type="button" onClick={() => void more()} disabled={busy}>{busy ? "Loading…" : "Show older"}</button></p>}

        <section className="nt-prefs" id="settings" aria-labelledby="np-h">
          <h2 id="np-h">What we tell you</h2>
          <p className="hint">Choose where each kind of message reaches you. The bell is the notification list above.</p>
          <div className="nt-push" id="browser">
            <div>
              <b>Browser notifications</b>
              <p>{push === "unsupported" ? "This browser cannot show them. On an iPhone, add JIVE to your Home Screen first."
                : push === "unconfigured" ? "They are not switched on for this site yet."
                : push === "denied" ? "Blocked in your browser's settings for this site."
                : push === "on" ? "On for this browser. You will get them even when the site is closed."
                : "Get a pop-up on this device, even when the site is closed."}</p>
              {pushNote && <p className="hint" role="status">{pushNote}</p>}
            </div>
            {push && push !== "unsupported" && push !== "unconfigured" && (
              <div className="nt-push-act">
                <button className={`pill sm${push === "on" ? " ghost" : ""}`} type="button" onClick={() => void togglePush()} disabled={busy || push === "denied"}>{push === "on" ? "Turn off here" : "Turn on here"}</button>
                {push === "on" && <button className="link" type="button" onClick={() => void testPush()} disabled={busy}>Send a test</button>}
              </div>
            )}
          </div>
          {prefs === null && <div className="skeleton" style={{ height: 80, marginTop: 20 }} />}
          {prefs?.map((p) => (
            <div className="nt-row" key={p.category}>
              <div><b>{p.label}</b><p>{p.description}</p></div>
              <label><input type="checkbox" checked={p.in_app} onChange={(e) => void change(p.category, "in_app", e.target.checked)} aria-label={`${p.label}: show in the bell`} />Bell</label>
              {p.email_choice
                ? <label><input type="checkbox" checked={p.email} onChange={(e) => void change(p.category, "email", e.target.checked)} aria-label={`${p.label}: send by email`} />Email</label>
                : <span className="fixed">Email<br />always on</span>}
              <label><input type="checkbox" checked={p.push} onChange={(e) => void change(p.category, "push", e.target.checked)} aria-label={`${p.label}: browser notification`} />Browser</label>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
