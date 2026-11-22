"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, api, rememberNext } from "@/lib/api-client";
import type { AuthUser } from "@/lib/types";

/** Gate for staff and admin screens. The backend enforces roles on every call; this only decides what to show. */
export function RequireRole({
  roles, next, children,
}: { roles: string[]; next: string; children: React.ReactNode | ((user: AuthUser) => React.ReactNode) }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    let live = true;
    api<AuthUser>("auth/me")
      .then((u) => { if (!live) return; if (roles.includes(u.role)) setUser(u); else setDenied(true); })
      .catch((e) => { if (e instanceof ApiError && e.status === 401) { rememberNext(next); router.replace("/signin"); } else if (live) setDenied(true); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (denied) {
    return (
      <div className="wrap narrow" style={{ padding: "96px 24px" }}>
        <h1>You do not have access</h1>
        <p style={{ margin: "16px 0 32px" }}>This area is for JIVE staff. If you should have access, ask an administrator to add your Google account.</p>
        <Link className="pill" href="/">Back to JIVE</Link>
      </div>
    );
  }
  if (!user) return <div className="wrap" style={{ padding: "96px 24px" }}><div className="skeleton" style={{ height: 48, maxWidth: 360 }} /></div>;
  return <>{typeof children === "function" ? children(user) : children}</>;
}
