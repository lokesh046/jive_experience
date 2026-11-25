"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { RequireRole } from "@/components/RequireRole";
import { JobsBanner } from "@/components/admin/JobsBanner";
import { TableLabels } from "@/components/admin/TableLabels";

const NAV = [
  { href: "/admin", label: "Events", match: (p: string) => p === "/admin" || p.startsWith("/admin/events") },
  { href: "/admin/sales", label: "Sales", match: (p: string) => p.startsWith("/admin/sales") },
  { href: "/admin/bookings", label: "Bookings", match: (p: string) => p.startsWith("/admin/bookings") },
  { href: "/admin/newsletters", label: "Newsletters", match: (p: string) => p.startsWith("/admin/newsletters") },
  { href: "/admin/jobs", label: "Jobs", match: (p: string) => p.startsWith("/admin/jobs") },
  { href: "/admin/inbox", label: "Inbox", match: (p: string) => p.startsWith("/admin/inbox") },
  { href: "/admin/artists", label: "Artists", match: (p: string) => p.startsWith("/admin/artists") },
  { href: "/admin/archive", label: "Archive", match: (p: string) => p.startsWith("/admin/archive") },
  { href: "/admin/promos", label: "Promo codes", match: (p: string) => p.startsWith("/admin/promos") },
  { href: "/admin/venues", label: "Venues", match: (p: string) => p.startsWith("/admin/venues") },
  { href: "/admin/settings", label: "Settings", match: (p: string) => p.startsWith("/admin/settings") },
  { href: "/admin/team", label: "Team", match: (p: string) => p.startsWith("/admin/team") },
];

export function AdminShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <RequireRole roles={["ADMIN"]} next={path}>
      {(user) => (
        <div className="ad">
          <aside className="ad-side">
            <nav aria-label="Admin">
              {NAV.map((n) => <Link key={n.href} href={n.href} aria-current={n.match(path) ? "page" : undefined}>{n.label}</Link>)}
            </nav>
            <div className="ad-side-foot">
              <Link href="/scan">Scanner</Link>
              <Link href="/">View site</Link>
              <span className="small" title={user.email}>{user.full_name ?? user.email}</span>
            </div>
          </aside>
          <main className="ad-main"><TableLabels /><JobsBanner />{children}</main>
        </div>
      )}
    </RequireRole>
  );
}
