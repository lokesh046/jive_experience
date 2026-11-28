import { INSTRUMENTS, type InstrumentName } from "./instruments";

/** Between two events: a short stretch of staff with a note or a small instrument on it. */
const SEQUENCE: Array<InstrumentName | "note" | "pair"> = ["note", "piano", "pair", "trumpet", "note", "guitar", "saxophone", "pair", "violin", "note", "flute", "drums"];

export function TickerMark({ n }: { n: number }) {
  const what = SEQUENCE[n % SEQUENCE.length]!;
  return (
    <svg className="mk" viewBox="0 0 120 44" aria-hidden="true" focusable="false">
      <path d="M0 33 C 20 25, 40 25, 60 33 S 100 41, 120 33" fill="none" stroke="currentColor" strokeWidth={1} opacity={0.45} />
      {what === "note" && (
        <g transform="translate(60 33)" fill="currentColor" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round">
          <ellipse rx={4.6} ry={3.2} transform="rotate(-22)" />
          <line x1={3.8} y1={-1} x2={3.8} y2={-22} />
          <path d="M3.8 -22 C 3.8 -16, 11 -15, 12 -8" fill="none" />
        </g>
      )}
      {what === "pair" && (
        <g transform="translate(48 33)" fill="currentColor" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round">
          <ellipse rx={4.4} ry={3.1} transform="rotate(-22)" />
          <ellipse cx={22} cy={4} rx={4.4} ry={3.1} transform="rotate(-22 22 4)" />
          <line x1={3.6} y1={-1} x2={3.6} y2={-22} />
          <line x1={25.6} y1={3} x2={25.6} y2={-18} />
          <line x1={3.6} y1={-22} x2={25.6} y2={-18} strokeWidth={3} />
        </g>
      )}
      {what !== "note" && what !== "pair" && (
        <g transform="translate(60 16) scale(0.33) translate(-50 -50)">{INSTRUMENTS[what]}</g>
      )}
    </svg>
  );
}
