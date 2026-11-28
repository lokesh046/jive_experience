"use client";
import { useEffect, useRef } from "react";

/**
 * A drum kit drawn in white line art that plays itself: two sticks strike the pieces in a
 * one-bar groove, each piece answers its hits, and a ring spreads from every strike. The motion
 * is all CSS keyframes tied to the same four-second bar, so the loop never drifts or jumps.
 * It is decoration: hidden from assistive tech, paused off screen, still under reduced motion.
 */

const HEAD = "var(--bg)";
const rim = { stroke: "currentColor", strokeWidth: 2.2, strokeLinecap: "round", strokeLinejoin: "round" } as const;

function Tom({ cx, cy, rx, ry, h, cls }: { cx: number; cy: number; rx: number; ry: number; h: number; cls: string }) {
  return (
    <g className={cls}>
      <path d={`M${cx - rx} ${cy} V${cy + h} C ${cx - rx} ${cy + h + ry * 1.7}, ${cx + rx} ${cy + h + ry * 1.7}, ${cx + rx} ${cy + h} V${cy}`} fill={HEAD} {...rim} />
      {[-0.62, -0.2, 0.2, 0.62].map((k) => <line key={k} x1={cx + rx * k} y1={cy + ry * 0.9} x2={cx + rx * k} y2={cy + h * 0.78} strokeWidth={1.4} stroke="currentColor" opacity={0.55} />)}
      <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill="currentColor" fillOpacity={0.9} {...rim} />
      <ellipse cx={cx} cy={cy} rx={rx * 0.82} ry={ry * 0.74} fill="none" stroke={HEAD} strokeWidth={1.4} />
    </g>
  );
}

function Cymbal({ cx, cy, rx, cls }: { cx: number; cy: number; rx: number; cls: string }) {
  return (
    <g className={cls}>
      <ellipse cx={cx} cy={cy} rx={rx} ry={rx * 0.2} fill={HEAD} {...rim} />
      <ellipse cx={cx} cy={cy - 1} rx={rx * 0.62} ry={rx * 0.11} fill="none" stroke="currentColor" strokeWidth={1.3} opacity={0.7} />
      <ellipse cx={cx} cy={cy - 2} rx={rx * 0.16} ry={rx * 0.05} fill="currentColor" stroke="none" />
    </g>
  );
}

const Ring = ({ cx, cy, rx, ry, cls }: { cx: number; cy: number; rx: number; ry: number; cls: string }) => (
  <ellipse className={cls} cx={cx} cy={cy} rx={rx} ry={ry} fill="none" stroke="currentColor" strokeWidth={1.6} opacity={0} />
);

const Stick = ({ cls }: { cls: string }) => (
  <g className={`dk-st ${cls}`}>
    <line x1={0} y1={-3} x2={0} y2={-230} stroke="currentColor" strokeWidth={5} strokeLinecap="round" />
    <line x1={0} y1={-3} x2={0} y2={-12} stroke={HEAD} strokeWidth={2} strokeLinecap="round" />
    <circle cx={0} cy={0} r={4.6} fill="currentColor" />
  </g>
);

export function DrumKit({ className = "" }: { className?: string }) {
  const root = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const el = root.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => el.classList.toggle("dk-idle", !e?.isIntersecting), { rootMargin: "80px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <svg ref={root} className={`dk dk-loop ${className}`.trim()} viewBox="0 0 480 360" aria-hidden="true" focusable="false">
      {/* the floor */}
      <g fill="none" {...rim} strokeWidth={1.4} opacity={0.5}><path d="M10 342 H470 M40 352 H440" /></g>

      {/* stands */}
      <g fill="none" {...rim} strokeWidth={2}>
        <path d="M56 168 V318 M56 318 L22 344 M56 318 L90 344 M56 318 V346" />
        <path d="M140 92 V318 M140 318 L106 344 M140 318 L174 344" />
        <path d="M420 100 V318 M420 318 L386 344 M420 318 L454 344" />
        <path d="M150 262 V318 M150 288 L118 340 M150 288 L182 340" />
      </g>

      {/* hi-hat, crash and ride */}
      <Cymbal cx={56} cy={158} rx={38} cls="dk-hihat" />
      <Cymbal cx={56} cy={166} rx={36} cls="dk-hihat" />
      <Cymbal cx={140} cy={80} rx={58} cls="dk-crash" />
      <Cymbal cx={420} cy={90} rx={55} cls="dk-ride" />

      {/* bass drum */}
      <g className="dk-kick">
        <circle cx={262} cy={262} r={88} fill={HEAD} {...rim} />
        {Array.from({ length: 10 }, (_, i) => {
          const a = (i / 10) * Math.PI * 2;
          return <line key={i} x1={262 + Math.cos(a) * 82} y1={262 + Math.sin(a) * 82} x2={262 + Math.cos(a) * 92} y2={262 + Math.sin(a) * 92} stroke="currentColor" strokeWidth={3.2} strokeLinecap="round" />;
        })}
        <circle cx={262} cy={262} r={74} fill="currentColor" fillOpacity={0.92} {...rim} />
        <circle cx={262} cy={262} r={30} fill="none" stroke={HEAD} strokeWidth={1.6} />
      </g>

      {/* floor tom, rack toms, snare */}
      <Tom cx={392} cy={212} rx={48} ry={14} h={56} cls="dk-floor" />
      <Tom cx={195} cy={152} rx={40} ry={12} h={36} cls="dk-tom1" />
      <Tom cx={283} cy={152} rx={40} ry={12} h={36} cls="dk-tom2" />
      <Tom cx={150} cy={234} rx={56} ry={15} h={30} cls="dk-snare" />

      {/* what each strike sends out */}
      <Ring cx={140} cy={80} rx={60} ry={14} cls="dk-r-crash" />
      <Ring cx={56} cy={160} rx={42} ry={10} cls="dk-r-hihat" />
      <Ring cx={150} cy={234} rx={58} ry={17} cls="dk-r-snare" />
      <Ring cx={195} cy={152} rx={42} ry={14} cls="dk-r-tom1" />
      <Ring cx={283} cy={152} rx={42} ry={14} cls="dk-r-tom2" />
      <Ring cx={392} cy={212} rx={50} ry={16} cls="dk-r-floor" />
      <Ring cx={420} cy={92} rx={57} ry={14} cls="dk-r-ride" />
      <circle className="dk-r-kick" cx={262} cy={262} r={96} fill="none" stroke="currentColor" strokeWidth={1.6} opacity={0} />

      {/* the sticks, struck in time */}
      <Stick cls="dk-stl" />
      <Stick cls="dk-str" />
    </svg>
  );
}
