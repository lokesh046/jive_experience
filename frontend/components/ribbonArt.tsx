import type { ReactNode } from "react";
import { INSTRUMENTS, type InstrumentName } from "./instruments";

/** What rides on the ribbon. Every drawing is centred in a 100 by 100 box so it can be placed by its middle. */
export type RibbonItem = InstrumentName | "treble" | "bass" | "quarter" | "half" | "eighth" | "pair";

const line = { fill: "none", stroke: "currentColor", strokeLinecap: "round", strokeLinejoin: "round" } as const;

const ART: Record<Exclude<RibbonItem, InstrumentName>, ReactNode> = {
  treble: (
    <g transform="translate(50 52) scale(0.92) translate(-21 -57)" {...line} strokeWidth={3.4}>
      <path d="M21 8 L21 96 C 21 104, 12 107, 10 100 C 9 96, 13 94, 15 97" />
      <path d="M21 78 C 5 76, 2 58, 14 50 C 24 43, 35 36, 29 21 C 26 13, 21 8, 21 8 C 17 16, 16 28, 22 40 C 28 52, 36 60, 36 72 C 36 84, 28 90, 21 88 C 14 86, 14 76, 21 74 C 26 72, 29 78, 24 81" />
    </g>
  ),
  bass: (
    <g transform="translate(50 50) scale(1.5) translate(-20 -33)" {...line} strokeWidth={3}>
      <circle cx={9} cy={16} r={4.6} fill="currentColor" />
      <path d="M9 12 C 9 4, 30 4, 31 22 C 32 40, 18 54, 3 60" />
      <circle cx={38} cy={13} r={2.6} fill="currentColor" stroke="none" />
      <circle cx={38} cy={27} r={2.6} fill="currentColor" stroke="none" />
    </g>
  ),
  quarter: (
    <g stroke="currentColor" strokeWidth={4.5} strokeLinecap="round" fill="currentColor">
      <ellipse cx={40} cy={74} rx={14} ry={10} transform="rotate(-22 40 74)" />
      <line x1={52.5} y1={70} x2={52.5} y2={14} fill="none" />
    </g>
  ),
  half: (
    <g stroke="currentColor" strokeWidth={4.5} strokeLinecap="round" fill="none">
      <ellipse cx={40} cy={74} rx={14} ry={10} transform="rotate(-22 40 74)" />
      <line x1={52.5} y1={70} x2={52.5} y2={14} />
    </g>
  ),
  eighth: (
    <g stroke="currentColor" strokeWidth={4.5} strokeLinecap="round" fill="currentColor">
      <ellipse cx={38} cy={76} rx={14} ry={10} transform="rotate(-22 38 76)" />
      <path d="M50.5 72 L50.5 14 C 50.5 34, 76 36, 72 62" fill="none" />
    </g>
  ),
  pair: (
    <g stroke="currentColor" strokeWidth={4.5} strokeLinecap="round" fill="currentColor">
      <ellipse cx={26} cy={78} rx={13} ry={9} transform="rotate(-22 26 78)" />
      <ellipse cx={70} cy={66} rx={13} ry={9} transform="rotate(-22 70 66)" />
      <line x1={38} y1={74} x2={38} y2={22} fill="none" />
      <line x1={82} y1={62} x2={82} y2={10} fill="none" />
      <line x1={38} y1={22} x2={82} y2={10} strokeWidth={10} fill="none" />
    </g>
  ),
};

export function RibbonArt({ item }: { item: RibbonItem }) {
  if (item in INSTRUMENTS) return <g className="rb-art">{INSTRUMENTS[item as InstrumentName]}</g>;
  return <g>{ART[item as Exclude<RibbonItem, InstrumentName>]}</g>;
}
