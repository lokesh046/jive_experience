import Link from "next/link";
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
          <li><Link href="/#private">Venue</Link></li>
          <RoleLinks />
        </ul>
        <ProfileMenu />
      </nav>
    </header>
  );
}
