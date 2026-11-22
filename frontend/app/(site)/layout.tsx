import Link from "next/link";
import { SiteHeader } from "@/components/SiteHeader";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
        <a className="skip" href="#main">Skip to content</a>
      <SiteHeader />
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
