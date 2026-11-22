import Link from "next/link";
import { ProfileMenu } from "@/components/ProfileMenu";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
        <a className="skip" href="#main">Skip to content</a>
      <header className="top">
        <nav className="nav" aria-label="Main">
          <Link className="logo" href="/">JIVE</Link>
          <ul>
            <li><Link href="/events">Events</Link></li>
            <li><Link href="/#artists">Artists</Link></li>
            <li><Link href="/#private">Venue</Link></li>
          </ul>
          <ProfileMenu />
        </nav>
      </header>
      <div id="main" style={{ flex: 1, display: "flex", flexDirection: "column" }}>{children}</div>
      <footer className="site">
        <div className="wrap">
          <span>© JIVE</span>
          <nav aria-label="Footer">
            <Link href="/events">Events</Link>
            <Link href="/terms">Terms</Link>
            <Link href="/cancellation-policy">Cancellation and refund policy</Link>
            <Link href="/privacy">Privacy</Link>
          </nav>
        </div>
      </footer>
    </>
  );
}
