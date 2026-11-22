"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

function readRole(): string | null {
  const m = document.cookie.match(/(?:^|; )jive_role=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** Header links for staff and admins. The cookie only picks which links to show; the API still checks every request. */
export function RoleLinks() {
  const [role, setRole] = useState<string | null>(null);
  useEffect(() => {
    const sync = () => setRole(readRole());
    queueMicrotask(sync);
    window.addEventListener("jive-auth", sync);
    window.addEventListener("focus", sync);
    return () => { window.removeEventListener("jive-auth", sync); window.removeEventListener("focus", sync); };
  }, []);
  if (role === "ADMIN") return (<><li><Link href="/admin">Admin</Link></li><li><Link href="/scan">Scanner</Link></li></>);
  if (role === "EVENT_STAFF") return <li><Link href="/scan">Scanner</Link></li>;
  return null;
}
