"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";
import { ago } from "@/lib/format";
import type { NotificationFeed } from "@/lib/types";

const hasSession = () => /(?:^|; )jive_role=/.test(document.cookie);

/** The bell in the header. It only appears for signed-in people, and asks for a count, nothing more, until opened. */
export function NotificationBell() {
  const [signedIn, setSignedIn] = useState(false);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [feed, setFeed] = useState<NotificationFeed | null>(null);
  const root = useRef<HTMLDivElement>(null);

  const count = useCallback(async () => {
    if (!hasSession() || document.hidden) return;
    try { setUnread((await api<{ unread: number }>("notifications/unread")).unread); } catch {}
  }, []);

  useEffect(() => {
    const sync = () => { const on = hasSession(); setSignedIn(on); if (on) void count(); else { setUnread(0); setOpen(false); } };
    queueMicrotask(sync);
    const id = setInterval(count, 60000);
    window.addEventListener("jive-auth", sync);
    window.addEventListener("focus", sync);
    document.addEventListener("visibilitychange", count);
    return () => { clearInterval(id); window.removeEventListener("jive-auth", sync); window.removeEventListener("focus", sync); document.removeEventListener("visibilitychange", count); };
  }, [count]);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next) {
      try { const f = await api<NotificationFeed>("notifications?limit=8"); setFeed(f); setUnread(f.unread); } catch {}
    }
  }
  async function readOne(id: string) {
    setFeed((f) => f && { ...f, items: f.items.map((n) => (n.id === id ? { ...n, read: true } : n)) });
    setOpen(false);
    try { setUnread((await api<{ unread: number }>("notifications/read", { method: "POST", json: { ids: [id] } })).unread); } catch {}
  }
  async function readAll() {
    setFeed((f) => f && { ...f, unread: 0, items: f.items.map((n) => ({ ...n, read: true })) });
    setUnread(0);
    try { await api("notifications/read-all", { method: "POST", json: {} }); } catch {}
  }

  if (!signedIn) return null;
  return (
    <div className="bell" ref={root}>
      <button type="button" className="bell-btn" aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"} aria-haspopup="dialog" aria-expanded={open} onClick={() => void toggle()}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 9a6 6 0 1 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9" /><path d="M10 20a2 2 0 0 0 4 0" /></svg>
        {unread > 0 && <span className="bell-badge" aria-hidden="true">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="bell-panel" role="dialog" aria-label="Notifications">
          <div className="bell-head"><b>Notifications</b>{(feed?.unread ?? unread) > 0 && <button type="button" className="link" onClick={() => void readAll()}>Mark all read</button>}</div>
          {!feed && <div className="skeleton" style={{ height: 80, margin: 12 }} />}
          {feed && feed.items.length === 0 && <p className="bell-empty">Nothing yet. We will tell you here when something happens.</p>}
          <ul>
            {feed?.items.map((n) => {
              const body = (
                <>
                  <i className={`dot ${n.severity}${n.read ? " read" : ""}`} aria-hidden="true" />
                  <span><b>{n.title}</b>{n.body && <small>{n.body}</small>}<em>{ago(n.created_at)}</em></span>
                </>
              );
              return (
                <li key={n.id} className={n.read ? "" : "new"}>
                  {n.link ? <Link href={n.link} onClick={() => void readOne(n.id)}>{body}</Link> : <button type="button" onClick={() => void readOne(n.id)}>{body}</button>}
                </li>
              );
            })}
          </ul>
          <div className="bell-foot"><Link href="/notifications" onClick={() => setOpen(false)}>See all</Link><Link href="/notifications#settings" onClick={() => setOpen(false)}>Settings</Link></div>
        </div>
      )}
    </div>
  );
}
