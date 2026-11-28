"use client";
import { useEffect, useRef } from "react";

/**
 * The drum kit drawing, cut into pieces so it can play itself: two sticks strike the cymbals
 * and toms in a one-bar groove, each piece answers its hits, and ticks fly off every strike.
 * It is decoration: hidden from assistive tech, paused off screen, still under reduced motion.
 */

const PIECES = ["kick", "tom1", "tom2", "tom3", "cymL", "crash", "ride", "cymR"] as const;
const SPARKS = ["crash", "cymL", "ride", "cymR", "tom1", "tom2", "tom3", "snare"] as const;

export function DrumKit({ className = "" }: { className?: string }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = root.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => el.classList.toggle("dk-idle", !e?.isIntersecting), { rootMargin: "80px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div ref={root} className={`dk dk-loop ${className}`.trim()} aria-hidden="true">
      <img className="dk-base" src="/art/drum/base.png" alt="" width={956} height={716} loading="lazy" decoding="async" draggable={false} />
      {PIECES.map((n) => <img key={n} className={`dk-p dk-${n}`} src={`/art/drum/${n}.png`} alt="" loading="lazy" decoding="async" draggable={false} />)}
      <svg className="dk-fx" viewBox="0 0 478 358" focusable="false">
        {SPARKS.map((n) => (
          <g key={n} className={`dk-sp dk-sp-${n}`} stroke="currentColor" strokeWidth={1.8} strokeLinecap="round">
            <line x1={0} y1={-9} x2={0} y2={-17} /><line x1={-7} y1={-6} x2={-12} y2={-12} /><line x1={7} y1={-6} x2={12} y2={-12} />
          </g>
        ))}
        {(["dk-stl", "dk-str"] as const).map((c) => (
          <g key={c} className={`dk-st ${c}`}>
            <path d="M-1.1 0 L1.1 0 L2.8 -170 L-2.8 -170 Z" fill="currentColor" stroke="#000" strokeWidth={0.9} strokeLinejoin="round" />
            <circle cx={0} cy={0} r={2.9} fill="currentColor" stroke="#000" strokeWidth={0.9} />
          </g>
        ))}
      </svg>
    </div>
  );
}
