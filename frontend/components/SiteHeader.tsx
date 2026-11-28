import Link from "next/link";
import { MobileMenu } from "@/components/MobileMenu";
import { NotificationBell } from "@/components/NotificationBell";
import { ProfileMenu } from "@/components/ProfileMenu";
import { RoleLinks } from "@/components/RoleLinks";

/** The floating header shared by the public site and the admin area. */
export function SiteHeader() {
  return (
    <header className="top">
      <nav className="nav" aria-label="Main">
        <Link className="logo" href="/">JIVE</Link>
        <ul>
          <li><Link href="/events">Events</Link></li>
          <li><Link href="/#artists">Artists</Link></li>
          <li><Link href="/#private">Private bookings</Link></li>
          <RoleLinks />
        </ul>
        <div className="nav-end">
          <Link className="search" href="/events#search" aria-label="Search events">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
          </Link>
          <NotificationBell />
          <ProfileMenu />
          <MobileMenu />
        </div>
      </nav>
    </header>
  );
}
