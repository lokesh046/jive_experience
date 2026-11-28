import type { CSSProperties } from "react";
import { INSTRUMENTS, type InstrumentName } from "./instruments";

/**
 * Between two events: a note or instrument that circles the staff in depth. It sweeps past in
 * front, big and bright, then slips behind the line, small and faint, and comes round again.
 * Each mark starts at a different point of the orbit so they never move in step.
 */
const SEQUENCE: Array<InstrumentName | "note" | "pair"> = ["piano", "note", "trumpet", "pair", "guitar", "note", "saxophone", "pair", "violin", "note", "flute", "drums"];

export function TickerMark({ n }: { n: number }) {
  const what = SEQUENCE[n % SEQUENCE.length]!;
  const timing: CSSProperties = { animationDelay: `${-((n * 2.3) % 9).toFixed(1)}s` };
  return (
    <svg className="mk" viewBox="0 0 160 80" aria-hidden="true" focusable="false">
      <path d="M0 58 C 26 50, 54 50, 80 58 S 134 66, 160 58" fill="none" stroke="currentColor" strokeWidth={1.1} opacity={0.55} />
      <g className="mk-i" style={timing}>
        {what === "note" && (
          <g transform="translate(80 54)" fill="currentColor" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round">
            <ellipse rx={5.2} ry={3.7} transform="rotate(-22)" />
            <line x1={4.4} y1={-1} x2={4.4} y2={-27} />
            <path d="M4.4 -27 C 4.4 -20, 13 -19, 14 -9" fill="none" />
          </g>
        )}
        {what === "pair" && (
          <g transform="translate(67 54)" fill="currentColor" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round">
            <ellipse rx={5} ry={3.5} transform="rotate(-22)" />
            <ellipse cx={25} cy={4} rx={5} ry={3.5} transform="rotate(-22 25 4)" />
            <line x1={4.2} y1={-1} x2={4.2} y2={-27} />
            <line x1={29.2} y1={3} x2={29.2} y2={-23} />
            <line x1={4.2} y1={-27} x2={29.2} y2={-23} strokeWidth={3.6} />
          </g>
        )}
        {what !== "note" && what !== "pair" && (
          <g className="mk-art" transform="translate(80 32) scale(0.4) translate(-50 -50)">{INSTRUMENTS[what]}</g>
        )}
      </g>
    </svg>
  );
}
