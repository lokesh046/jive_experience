"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { RequireRole } from "@/components/RequireRole";

const NAV = [
  { href: "/admin", label: "Events", match: (p: string) => p === "/admin" || p.startsWith("/admin/events") },
  { href: "/admin/bookings", label: "Bookings", match: (p: string) => p.startsWith("/admin/bookings") },
  { href: "/admin/venues", label: "Venues", match: (p: string) => p.startsWith("/admin/venues") },
  { href: "/admin/team", label: "Team", match: (p: string) => p.startsWith("/admin/team") },
];

export function AdminShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <RequireRole roles={["ADMIN"]} next={path}>
      {(user) => (
        <div className="ad">
          <aside className="ad-side">
            <Link className="logo" href="/admin">JIVE <span>admin</span></Link>
            <nav aria-label="Admin">
              {NAV.map((n) => <Link key={n.href} href={n.href} aria-current={n.match(path) ? "page" : undefined}>{n.label}</Link>)}
            </nav>
            <div className="ad-side-foot">
              <Link href="/scan">Scanner</Link>
              <Link href="/">View site</Link>
              <span className="small" title={user.email}>{user.full_name ?? user.email}</span>
            </div>
          </aside>
          <main className="ad-main">{children}</main>
        </div>
      )}
    </RequireRole>
  );
}
