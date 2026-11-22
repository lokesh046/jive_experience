"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";
import type { AuthUser } from "@/lib/types";
import { Avatar } from "./Avatar";

/** Profile icon in the nav. Who is signed in is checked when the menu opens, so it costs nothing on page load. */
export function ProfileMenu() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<AuthUser | null | undefined>(undefined);
  const root = useRef<HTMLDivElement>(null);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next) api<AuthUser>("auth/me").then(setUser).catch(() => setUser(null));
  }

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);

  async function signOut() {
    setOpen(false);
    await api("auth/logout", { method: "POST", json: {} }).catch(() => {});
    setUser(null);
    router.push("/");
    router.refresh();
  }

  return (
    <div className="profile" ref={root}>
      <button type="button" className="avatar" aria-label="Account" aria-haspopup="menu" aria-expanded={open} onClick={toggle}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" />
        </svg>
      </button>
      {open && (
        <div className="menu" role="menu">
          {user && (
            <div className="head">
              <Avatar url={user.avatar_url} size={36} />
              <span title={user.email}>{user.full_name ?? user.email}</span>
            </div>
          )}
          {user && <Link role="menuitem" href="/profile" onClick={() => setOpen(false)}>Profile</Link>}
          {user?.role === "ADMIN" && <Link role="menuitem" href="/admin" onClick={() => setOpen(false)}>Admin</Link>}
          {(user?.role === "ADMIN" || user?.role === "EVENT_STAFF") && <Link role="menuitem" href="/scan" onClick={() => setOpen(false)}>Scan tickets</Link>}
          <Link role="menuitem" href="/tickets" onClick={() => setOpen(false)}>My tickets</Link>
          {user ? (
            <button role="menuitem" type="button" onClick={signOut}>Sign out</button>
          ) : user === null ? (
            <Link role="menuitem" href="/signin" onClick={() => setOpen(false)}>Sign in</Link>
          ) : null}
        </div>
      )}
    </div>
  );
}
