"use client";
import { useEffect, useState } from "react";

/** A slim bar on phones that keeps "Get tickets" within reach until the ticket section is on screen. */
export function StickyBuy({ price, label }: { price: string | null; label: string }) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const tickets = document.getElementById("tickets");
    const head = document.querySelector(".ev-actions");
    if (!tickets) return;
    // Show once the header's own button has scrolled away, hide again while the tickets are on screen.
    let headGone = !head;
    let ticketsBelow = true;
    const update = () => setShow(headGone && ticketsBelow);
    const ioHead = new IntersectionObserver(([e]) => { headGone = !e.isIntersecting; update(); });
    const ioTickets = new IntersectionObserver(
      ([e]) => { ticketsBelow = !e.isIntersecting && e.boundingClientRect.top > 0; update(); },
      { rootMargin: "0px 0px -20% 0px" },
    );
    if (head) ioHead.observe(head);
    ioTickets.observe(tickets);
    return () => { ioHead.disconnect(); ioTickets.disconnect(); };
  }, []);
  return (
    <div className={`sticky-buy${show ? " on" : ""}`} aria-hidden={!show}>
      <span>{price ? <>From <b>{price}</b></> : "Tickets"}</span>
      <a className="pill" href="#tickets" tabIndex={show ? 0 : -1}>{label}</a>
    </div>
  );
}
