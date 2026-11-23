"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { NewsletterSignup } from "@/components/NewsletterSignup";

const COLUMNS = [
  { title: "Explore", links: [{ label: "Events", href: "/events" }, { label: "Artists", href: "/#artists" }, { label: "Private bookings", href: "/#private" }] },
  { title: "Account", links: [{ label: "Sign in", href: "/signin" }, { label: "My tickets", href: "/tickets" }, { label: "Profile", href: "/profile" }] },
  { title: "Legal", links: [{ label: "Terms", href: "/terms" }, { label: "Privacy", href: "/privacy" }, { label: "Cancellation and refund policy", href: "/cancellation-policy" }] },
];
const WORD = "JIVE";

/**
 * The site footer: links and the newsletter on top, then a large wordmark whose letters rise through a
 * floor line the first time it scrolls into view, with a faint reflection below. Hover lifts a letter.
 */
export function SiteFooter() {
  const root = useRef<HTMLElement>(null);
  const [seen, setSeen] = useState(false);
  const [hover, setHover] = useState(-1);
  const [year, setYear] = useState<number | null>(null);

  useEffect(() => { queueMicrotask(() => setYear(new Date().getFullYear())); }, []);

  useEffect(() => {
    const el = root.current;
    if (!el || typeof IntersectionObserver === "undefined") { queueMicrotask(() => setSeen(true)); return; }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setSeen(true); io.disconnect(); } }, { threshold: 0.25 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const letters = [...WORD];

  return (
    <footer className="ft" ref={root} data-in={seen ? "true" : "false"}>
      <div className="wrap">
        <div className="ft-top">
          <div className="ft-brand">
            <Link className="ft-mark" href="/" aria-label="JIVE home">JIVE</Link>
            <p>Intimate live music evenings in converted mills, vaults and warehouses.</p>
            <NewsletterSignup />
          </div>
          <div className="ft-cols">
            {COLUMNS.map((c) => (
              <nav key={c.title} aria-label={c.title}>
                <p className="ft-h">{c.title}</p>
                <ul>{c.links.map((l) => <li key={l.label}><Link href={l.href}>{l.label}</Link></li>)}</ul>
              </nav>
            ))}
          </div>
        </div>

        <div className="ft-word" role="img" aria-label={WORD} onPointerLeave={() => setHover(-1)}>
          <div className="ft-row" aria-hidden="true">
            {letters.map((l, i) => (
              <span key={i} className="ft-l" style={{ "--i": i } as React.CSSProperties} onPointerEnter={() => setHover(i)}>
                <span className="ft-g" style={{ transform: hover === i ? "translateY(-8px)" : undefined }}>{l}</span>
              </span>
            ))}
          </div>
          <div className="ft-floor" aria-hidden="true" />
          <div className="ft-refl" aria-hidden="true">
            <div className="ft-row mirror">
              {letters.map((l, i) => <span key={i} className="ft-g" style={{ transform: hover === i ? "translateY(-8px)" : undefined }}>{l}</span>)}
            </div>
          </div>
        </div>

        <div className="ft-legal">
          <span>©{year ? ` ${year}` : ""} JIVE</span>
          <nav aria-label="Legal">
            <Link href="/terms">Terms</Link>
            <Link href="/privacy">Privacy</Link>
            <Link href="/cancellation-policy">Cancellation and refund policy</Link>
          </nav>
        </div>
      </div>
    </footer>
  );
}
