"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { MenuToggleIcon } from "./MenuToggleIcon";
import { RoleLinks } from "./RoleLinks";

/**
 * On a phone the header links do not fit, so they live behind this button. It opens a panel under
 * the header; a tap on a link, a tap outside, Escape, or a new page closes it.
 */
export function MobileMenu() {
  const [open, setOpen] = useState(false);
  const path = usePathname();
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  // A new page closes the menu.
  useEffect(() => { queueMicrotask(() => setOpen(false)); }, [path]);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [open]);

  return (
    <div className="mnav" ref={root}>
      <button
        ref={button}
        type="button"
        className="mnav-btn"
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
        aria-controls="mobile-menu"
        onClick={() => setOpen((o) => !o)}
      >
        <MenuToggleIcon open={open} width={26} height={26} />
      </button>
      <div id="mobile-menu" className={`mnav-panel${open ? " open" : ""}`} aria-hidden={!open}>
        <ul className="mnav-list" onClick={(e) => { if ((e.target as HTMLElement).closest("a")) setOpen(false); }}>
          <li><Link href="/events" tabIndex={open ? 0 : -1}>Events</Link></li>
          <li><Link href="/#artists" tabIndex={open ? 0 : -1}>Artists</Link></li>
          <li><Link href="/#private" tabIndex={open ? 0 : -1}>Private bookings</Link></li>
          <RoleLinks />
        </ul>
      </div>
    </div>
  );
}
