"use client";
import { useEffect, useRef } from "react";

const FAST = 3.2; // hovering speeds the strip up, like the example, instead of stopping it

/** Wraps the strip and eases its speed up while the pointer is over it, and back down on leaving. */
export function TickerShell({ children }: { children: React.ReactNode }) {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = root.current;
    const track = el?.querySelector<HTMLElement>(".track");
    if (!el || !track || typeof track.getAnimations !== "function") return;
    let rate = 1, target = 1, raf = 0;
    const step = () => {
      const anim = track.getAnimations()[0];
      rate += (target - rate) * 0.08;
      if (Math.abs(target - rate) < 0.01) rate = target;
      anim?.updatePlaybackRate(rate);
      if (rate !== target) raf = requestAnimationFrame(step);
    };
    const go = (t: number) => () => { target = t; cancelAnimationFrame(raf); raf = requestAnimationFrame(step); };
    const fast = go(FAST), slow = go(1);
    el.addEventListener("pointerenter", fast);
    el.addEventListener("pointerleave", slow);
    return () => { el.removeEventListener("pointerenter", fast); el.removeEventListener("pointerleave", slow); cancelAnimationFrame(raf); };
  }, []);

  return <div className="ticker" role="region" aria-label="Events on now" ref={root}>{children}</div>;
}
