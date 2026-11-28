import type { ReactNode } from "react";

export type InstrumentName = "piano" | "trumpet" | "saxophone" | "guitar" | "violin" | "drums" | "flute";

/** Thin line drawings in a 100 by 100 box. A tube is a thick line with a thinner one in the page colour on top. */
export const hollow = (d: string, w = 7, inner = 4.4) => (
  <>
    <path d={d} fill="none" stroke="currentColor" strokeWidth={w} strokeLinecap="round" strokeLinejoin="round" />
    <path d={d} fill="none" style={{ stroke: "var(--msa-bg)" }} strokeWidth={inner} strokeLinecap="round" strokeLinejoin="round" />
  </>
);

export const INSTRUMENTS: Record<InstrumentName, ReactNode> = {
  piano: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <rect x={8} y={30} width={84} height={16} rx={3} />
      <rect x={8} y={46} width={84} height={30} rx={3} />
      {[1, 2, 3, 4, 5, 6].map((i) => <line key={i} x1={8 + (84 / 7) * i} x2={8 + (84 / 7) * i} y1={46} y2={76} />)}
      {[1, 2, 4, 5, 6].map((i) => <rect key={i} x={8 + (84 / 7) * i - 3} y={46} width={6} height={18} fill="currentColor" />)}
      <path d="M26 30 V22 H74 V30" />
    </g>
  ),
  trumpet: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      {hollow("M8 52 H70", 6, 3.6)}
      <path d="M70 46 L94 30 M70 58 L94 74 M94 30 C 100 44, 100 60, 94 74" />
      <path d="M24 52 C 24 76, 62 76, 62 52" />
      <path d="M32 52 C 32 68, 54 68, 54 52" />
      {[38, 46, 54].map((x) => <g key={x}><line x1={x} y1={52} x2={x} y2={38} /><circle cx={x} cy={35} r={2.4} fill="currentColor" stroke="none" /></g>)}
    </g>
  ),
  saxophone: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      {hollow("M30 8 C 42 6, 48 12, 48 24 L48 66 C 48 84, 66 88, 74 74 C 80 64, 78 56, 76 50", 9, 5.8)}
      <path d="M69 48 H84" />
      <path d="M69 52 L66 46 M84 52 L87 46" />
      {[28, 38, 48, 58].map((y) => <circle key={y} cx={48} cy={y} r={2.2} fill="currentColor" stroke="none" />)}
    </g>
  ),
  guitar: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <path d="M36 52 C 31 40, 69 40, 64 52 C 62 58, 58 60, 62 66 C 76 72, 74 94, 50 95 C 26 94, 24 72, 38 66 C 42 60, 38 58, 36 52 Z" />
      <path d="M47 46 V12 M53 46 V12 M45 2 H55 V12 H45 Z" />
      <circle cx={50} cy={72} r={5.5} />
      <line x1={41} x2={59} y1={85} y2={85} />
      <line x1={50} y1={12} x2={50} y2={85} strokeWidth={0.8} />
    </g>
  ),
  violin: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <g transform="rotate(-18 50 50)">
        <path d="M38 48 C 33 40, 67 40, 62 48 C 60 54, 56 56, 62 62 C 72 68, 70 92, 50 93 C 30 92, 28 68, 38 62 C 44 56, 40 54, 38 48 Z" />
        <path d="M48 42 V14 M52 42 V14" />
        <circle cx={50} cy={10} r={4.5} />
        <path d="M43 66 C 41 72, 43 78, 45 80 M57 66 C 59 72, 57 78, 55 80" />
        <line x1={44} x2={56} y1={84} y2={84} />
      </g>
      <path d="M8 84 L92 30" />
      <path d="M8 84 L12 79" strokeWidth={3} />
    </g>
  ),
  drums: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx={50} cy={56} rx={32} ry={9} />
      <path d="M18 56 V82 C 18 92, 82 92, 82 82 V56" />
      <path d="M26 62 L34 88 M34 62 L42 90 M42 63 L50 91 M50 63 L58 91 M58 63 L66 90 M66 62 L74 88" strokeWidth={1} />
      <path d="M30 12 L54 50 M70 12 L46 50" strokeWidth={2.4} />
      <circle cx={30} cy={12} r={3} fill="currentColor" stroke="none" />
      <circle cx={70} cy={12} r={3} fill="currentColor" stroke="none" />
    </g>
  ),
  flute: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" transform="rotate(-22 50 50)">
      {hollow("M4 50 H96", 6.4, 3.8)}
      <ellipse cx={18} cy={50} rx={3.4} ry={2} />
      {[34, 46, 58, 70, 82].map((x) => <circle key={x} cx={x} cy={50} r={2} fill="currentColor" stroke="none" />)}
      <path d="M4 47 V53" />
    </g>
  ),
};

