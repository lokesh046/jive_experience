"use client";
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

/**
 * A wave-shaped musical staff that slides across the page, carrying notes, clefs and line-drawn
 * instruments with it. It is decoration: hidden from assistive tech, still under reduced motion,
 * and paused whenever it is off screen.
 *
 * One tile is drawn once and repeated. Its wave has a whole number of periods and nothing
 * straddles its edges, so the loop has no jump and no gap.
 */

export interface MusicalStaffAnimationProps {
  /** Seconds for the staff to travel one tile. Higher is slower. */
  speed?: number;
  /** Which way the music travels. */
  direction?: "left" | "right";
  /** Line and note colour. Defaults to the page's text colour. */
  color?: string;
  /** Colour behind the instruments, used to hollow out their tubes. Defaults to the page background. */
  background?: string;
  /** Instrument size in tile units (the tile is 380 high), so it scales with `height`. */
  instrumentSize?: number;
  /** Strength of the staff lines, 0 to 1. Notes and instruments are drawn a little stronger. */
  opacity?: number;
  /** Height of the band in px. A single number, or one value per screen size. */
  height?: number | { base: number; tablet?: number; desktop?: number };
  /** Which instruments to show, in order. */
  instruments?: InstrumentName[];
  className?: string;
}

export type InstrumentName = "piano" | "trumpet" | "saxophone" | "guitar" | "violin" | "drums" | "flute";

const TILE_W = 2400;
const TILE_H = 380;
const CENTER = 190;            // the middle line of the staff
const GAP = 14;                // between staff lines
const WAVE = 20;               // how far the staff rises and falls
const PERIOD = TILE_W / 3;     // three whole waves per tile, so the tile repeats cleanly
const BOTTOM = CENTER + GAP * 2;
const TILES = 3;               // enough to cover a 2560px screen plus the tile that slides out

const wave = (x: number) => WAVE * Math.sin((2 * Math.PI * x) / PERIOD);
const slope = (x: number) => ((WAVE * 2 * Math.PI) / PERIOD) * Math.cos((2 * Math.PI * x) / PERIOD);
const tilt = (x: number) => (Math.atan(slope(x)) * 180) / Math.PI;
/** The y of a note on a given staff step (0 is the bottom line, each step is half a gap) at x. */
const noteY = (x: number, step: number) => BOTTOM - step * (GAP / 2) + wave(x);

const staffPath = (line: number) => {
  const pts: string[] = [];
  for (let x = -40; x <= TILE_W + 40; x += 20) pts.push(`${x === -40 ? "M" : "L"}${x} ${(CENTER + (line - 2) * GAP + wave(x)).toFixed(2)}`);
  return pts.join("");
};

/* ---------------------------------------------------------------- notes --- */

type NoteKind = "quarter" | "eighth" | "half" | "pair";
interface Note { x: number; step: number; kind: NoteKind; next?: number }

const MELODY: Array<[NoteKind, number, number?]> = [
  ["quarter", 4], ["pair", 6, 5], ["half", 3], ["eighth", 7], ["quarter", 2], ["pair", 4, 6], ["quarter", 8],
  ["half", 5], ["pair", 3, 2], ["quarter", 6], ["eighth", 9], ["quarter", 4], ["pair", 7, 5], ["half", 1],
  ["quarter", 5], ["pair", 8, 9], ["quarter", 3], ["half", 6], ["eighth", 4], ["quarter", 10], ["pair", 5, 3],
  ["quarter", 7], ["half", 2], ["pair", 4, 5], ["quarter", 0], ["eighth", 6], ["quarter", 8], ["pair", 3, 4],
];

const INSTRUMENT_ORDER: InstrumentName[] = ["piano", "trumpet", "saxophone", "guitar", "violin", "drums", "flute"];

interface Place { name: InstrumentName; x: number; above: boolean }

function layout(names: InstrumentName[]): { notes: Note[]; places: Place[] } {
  const list = names.length ? names : INSTRUMENT_ORDER;
  const span = (TILE_W - 560) / list.length;
  const places = list.map((name, i) => ({ name, x: 520 + i * span + span / 2 - 130, above: i % 2 === 0 }));
  const notes: Note[] = [];
  const step = (TILE_W - 560) / MELODY.length;
  MELODY.forEach(([kind, s, next], i) => {
    const x = 330 + i * step + step / 2;
    // Leave room for an instrument rather than drawing a note through it.
    if (places.some((p) => Math.abs(p.x - x) < 70)) return;
    notes.push({ x, step: s, kind, next });
  });
  return { notes, places };
}

function NoteGlyph({ note }: { note: Note }) {
  const { x, step, kind } = note;
  const y = noteY(x, step);
  const down = step >= 4;
  const stemX = down ? -4.6 : 4.6;
  const head = (hollow: boolean, dx = 0, dy = 0) => (
    <ellipse cx={dx} cy={dy} rx={5.6} ry={4} transform={`rotate(-22 ${dx} ${dy})`} fill={hollow ? "none" : "currentColor"} stroke="currentColor" strokeWidth={1.6} />
  );
  const ledger = (s: number, at: number) => {
    const out: ReactNode[] = [];
    if (s <= -2) for (let l = -2; l >= s; l -= 2) out.push(<line key={`b${l}`} x1={at - 10} x2={at + 10} y1={noteY(x + at, l) - y} y2={noteY(x + at, l) - y} />);
    if (s >= 10) for (let l = 10; l <= s; l += 2) out.push(<line key={`t${l}`} x1={at - 10} x2={at + 10} y1={noteY(x + at, l) - y} y2={noteY(x + at, l) - y} />);
    return out;
  };

  if (kind === "pair" && note.next !== undefined) {
    const dx = 24;
    const y2 = noteY(x + dx, note.next) - y;
    const sx2 = dx + stemX;
    const top1 = down ? 30 : -30;
    const top2 = y2 + (down ? 30 : -30);
    return (
      <g transform={`translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${tilt(x).toFixed(1)}) scale(1.25)`}>
        <g stroke="currentColor" strokeWidth={1.4}>{ledger(step, 0)}{ledger(note.next, dx)}</g>
        {head(false)}{head(false, dx, y2)}
        <g stroke="currentColor" strokeWidth={1.6} strokeLinecap="round">
          <line x1={stemX} y1={down ? 1 : -1} x2={stemX} y2={top1} />
          <line x1={sx2} y1={y2 + (down ? 1 : -1)} x2={sx2} y2={top2} />
          <line x1={stemX} y1={top1} x2={sx2} y2={top2} strokeWidth={4} />
        </g>
      </g>
    );
  }

  return (
    <g transform={`translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${tilt(x).toFixed(1)}) scale(1.25)`}>
      <g stroke="currentColor" strokeWidth={1.4}>{ledger(step, 0)}</g>
      {head(kind === "half")}
      <g stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" fill="none">
        <line x1={stemX} y1={down ? 1 : -1} x2={stemX} y2={down ? 30 : -30} />
        {kind === "eighth" && (down
          ? <path d="M-4.6 30 C -4.6 22, 4 20, 6 12" />
          : <path d="M4.6 -30 C 4.6 -22, 13 -20, 14 -10" />)}
      </g>
    </g>
  );
}

/* --------------------------------------------------------------- clefs --- */

function TrebleClef({ x }: { x: number }) {
  // Drawn in a 40 by 110 box; its spiral sits on the second line from the bottom.
  return (
    <g transform={`translate(${x} ${CENTER + wave(x) + GAP * 1.2}) rotate(${tilt(x).toFixed(1)}) scale(1.2) translate(-20 -62)`} fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 6 C 31 14, 32 30, 24 44 C 17 56, 12 62, 12 76 C 12 90, 30 94, 31 78 C 32 66, 20 62, 14 70 C 8 78, 13 90, 24 90" opacity={0} />
      <path d="M21 8 L21 96 C 21 104, 12 107, 10 100 C 9 96, 13 94, 15 97" />
      <path d="M21 78 C 5 76, 2 58, 14 50 C 24 43, 35 36, 29 21 C 26 13, 21 8, 21 8 C 17 16, 16 28, 22 40 C 28 52, 36 60, 36 72 C 36 84, 28 90, 21 88 C 14 86, 14 76, 21 74 C 26 72, 29 78, 24 81" />
    </g>
  );
}

function BassClef({ x }: { x: number }) {
  return (
    <g transform={`translate(${x} ${CENTER + wave(x) - GAP * 1.4}) rotate(${tilt(x).toFixed(1)}) scale(1.15) translate(-20 -6)`} fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round">
      <circle cx={9} cy={16} r={4.6} fill="currentColor" />
      <path d="M9 12 C 9 4, 30 4, 31 22 C 32 40, 18 54, 3 60" />
      <circle cx={38} cy={13} r={2.6} fill="currentColor" stroke="none" />
      <circle cx={38} cy={27} r={2.6} fill="currentColor" stroke="none" />
    </g>
  );
}

/* --------------------------------------------------------- instruments --- */

/** Thin line drawings in a 100 by 100 box. A tube is a thick line with a thinner one in the page colour on top. */
const hollow = (d: string, w = 7, inner = 4.4) => (
  <>
    <path d={d} fill="none" stroke="currentColor" strokeWidth={w} strokeLinecap="round" strokeLinejoin="round" />
    <path d={d} fill="none" style={{ stroke: "var(--msa-bg)" }} strokeWidth={inner} strokeLinecap="round" strokeLinejoin="round" />
  </>
);

const INSTRUMENTS: Record<InstrumentName, ReactNode> = {
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

function Instrument({ place, size, index }: { place: Place; size: number; index: number }) {
  const baseY = place.above ? CENTER - GAP * 2 - 22 - size / 2 : CENTER + GAP * 2 + 22 + size / 2;
  const y = baseY + wave(place.x);
  const scale = size / 100;
  const float: CSSProperties = { animationDelay: `${-(index * 1.3).toFixed(1)}s`, animationDuration: `${5 + (index % 3)}s` };
  return (
    <g transform={`translate(${place.x} ${y.toFixed(1)}) rotate(${(tilt(place.x) * 0.6).toFixed(1)}) scale(${scale}) translate(-50 -50)`}>
      <g className="msa-float" style={float}>{INSTRUMENTS[place.name]}</g>
    </g>
  );
}

/* ----------------------------------------------------------------- tile --- */

function Tile({ size, opacity, instruments }: { size: number; opacity: number; instruments: InstrumentName[] }) {
  const { notes, places } = layout(instruments);
  return (
    <svg className="msa-tile" viewBox={`0 0 ${TILE_W} ${TILE_H}`} preserveAspectRatio="xMinYMid meet" aria-hidden="true" focusable="false">
      <g fill="none" stroke="currentColor" strokeWidth={1.2} opacity={opacity}>
        {[0, 1, 2, 3, 4].map((l) => <path key={l} d={staffPath(l)} />)}
      </g>
      <g opacity={Math.min(1, opacity + 0.45)}>
        <TrebleClef x={90} />
        <BassClef x={TILE_W / 2 + 40} />
        {notes.map((n) => <NoteGlyph key={n.x} note={n} />)}
        {places.map((p, i) => <Instrument key={p.name} place={p} size={size} index={i} />)}
      </g>
    </svg>
  );
}

export function MusicalStaffAnimation({
  speed = 110,
  direction = "left",
  color,
  background,
  instrumentSize = 108,
  opacity = 0.32,
  height = { base: 220, tablet: 290, desktop: 360 },
  instruments = INSTRUMENT_ORDER,
  className = "",
}: MusicalStaffAnimationProps) {
  const root = useRef<HTMLDivElement>(null);

  // Stop moving whenever the band is off screen or the tab is hidden.
  useEffect(() => {
    const el = root.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => el.toggleAttribute("data-idle", !e?.isIntersecting), { rootMargin: "120px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const h = typeof height === "number" ? { base: height } : height;
  const style = {
    "--msa-speed": `${speed}s`,
    "--msa-h": `${h.base}px`,
    "--msa-h-tablet": `${h.tablet ?? h.base}px`,
    "--msa-h-desktop": `${h.desktop ?? h.tablet ?? h.base}px`,
    ...(color ? { color } : {}),
    ...(background ? { "--msa-bg": background } : {}),
  } as CSSProperties;

  return (
    <div ref={root} className={`msa ${className}`.trim()} data-direction={direction} style={style} aria-hidden="true">
      <div className="msa-track">
        {Array.from({ length: TILES }, (_, i) => <Tile key={i} size={instrumentSize} opacity={opacity} instruments={instruments} />)}
      </div>
    </div>
  );
}
