"use client";
import { useEffect, useRef, type ReactNode } from "react";
import { RibbonArt, type RibbonItem } from "./ribbonArt";

/**
 * A musical staff drawn as a living ribbon that weaves around whatever it wraps (the event
 * ticker). Its five lines are one wave: they sway, twist and breathe, and the depth of each
 * point decides whether it is drawn behind the ticker or in front of it. Notes and instruments
 * ride the wave, closer and brighter in front, smaller and fainter behind.
 *
 * It runs only while on screen, and not at all under reduced motion (one still frame instead).
 */

const LINES = 5;
const LINE_GAP = 13;           // how far apart the five lines sit along the wave
const STEP = 10;               // px between sampled points
const FOCAL = 900;             // perspective: bigger is flatter

const ITEMS: Array<{ art: RibbonItem; size: number; lay?: number }> = [
  { art: "treble", size: 104 }, { art: "piano", size: 78 }, { art: "quarter", size: 62 }, { art: "trumpet", size: 84 },
  { art: "pair", size: 66 }, { art: "bass", size: 82 }, { art: "guitar", size: 92, lay: 68 }, { art: "eighth", size: 62 },
  { art: "saxophone", size: 86, lay: 24 }, { art: "half", size: 60 }, { art: "violin", size: 90, lay: 50 }, { art: "pair", size: 62 },
  { art: "flute", size: 82 }, { art: "drums", size: 78 }, { art: "quarter", size: 58 },
];

type Layer = "front" | "back";

export function RibbonStage({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  const backSvg = useRef<SVGSVGElement>(null);
  const frontSvg = useRef<SVGSVGElement>(null);
  const backPaths = useRef<Array<SVGPathElement | null>>([]);
  const frontPaths = useRef<Array<SVGPathElement | null>>([]);
  const backItems = useRef<Array<SVGGElement | null>>([]);
  const frontItems = useRef<Array<SVGGElement | null>>([]);

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let W = 0, H = 0, raf = 0, visible = true, last = 0, T = 0, clock = 0;

    const measure = () => {
      const r = el.getBoundingClientRect();
      W = Math.max(320, r.width); H = Math.max(160, r.height);
      for (const s of [backSvg.current, frontSvg.current]) s?.setAttribute("viewBox", `0 0 ${W} ${H}`);
    };

    const geometry = (x: number, time: number, j: number) => {
      const A = H * 0.27 * (1 + 0.28 * Math.sin(x / (0.2 * W) + 0.7 * time));           // loops swell and shrink
      const k = (2 * Math.PI) / Math.min(620, Math.max(300, W / 2.4));
      const theta = k * (x - (j - 2) * LINE_GAP) - time * 1.7
        + 0.9 * Math.sin(x / (0.27 * W) + 0.5 * time) + 0.5 * Math.sin(x / (0.11 * W) - 0.9 * time);
      const twist = 0.35 * Math.sin(0.5 * time + x / 300);                                 // the ribbon rolls
      const y = A * Math.sin(theta);
      const z = A * 1.15 * Math.cos(theta + twist);
      const s = FOCAL / (FOCAL - z);
      return { y: H / 2 + y * s, x: x + (x - W / 2) * (s - 1) * 0.35, z, s };
    };

    const draw = (time: number) => {
      // The five lines, split wherever the ribbon crosses the ticker's plane.
      for (let j = 0; j < LINES; j++) {
        const d: Record<Layer, string> = { front: "", back: "" };
        let cur: Layer | null = null;
        let prev: { x: number; y: number } | null = null;
        for (let x = -40; x <= W + 40; x += STEP) {
          const p = geometry(x, time, j);
          const layer: Layer = p.z >= 0 ? "front" : "back";
          const pt = `${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
          if (layer !== cur) {
            if (prev && cur) d[cur] += `L${pt}`;
            d[layer] += prev ? `M${prev.x.toFixed(1)} ${prev.y.toFixed(1)}L${pt}` : `M${pt}`;
            cur = layer;
          } else d[layer] += `L${pt}`;
          prev = p;
        }
        backPaths.current[j]?.setAttribute("d", d.back);
        frontPaths.current[j]?.setAttribute("d", d.front);
      }

      // The notes and instruments, each on its own beat.
      const span = W + 240;
      const u = Math.min(1, Math.max(0.6, W / 1100));              // smaller pieces on a small screen
      ITEMS.forEach((it, i) => {
        if (W < 640 && i % 2 === 1) {                               // and fewer of them
          backItems.current[i]?.setAttribute("display", "none");
          frontItems.current[i]?.setAttribute("display", "none");
          return;
        }
        const x = ((((i * span) / ITEMS.length + time * 74) % span) + span) % span - 120;
        const g = geometry(x, time, 2);
        const ahead = geometry(x + 6, time, 2);
        // Sit on the strings: centred on the middle line, turned to follow it, wobbling only a little.
        const follow = Math.atan2(ahead.y - g.y, ahead.x - g.x) * 57.3;
        const tilt = follow + (it.lay ?? 0) + 3 * Math.sin(time * 1.7 + i * 1.9);
        const bounce = 2.5 * Math.sin(time * 2.3 + i * 1.3);
        const pulse = 1 + 0.07 * Math.sin(time * 3.1 + i * 0.8);
        const depth = Math.pow(g.s, 2.6);
        const sc = (it.size / 100) * u * depth * pulse;
        const tf = `translate(${g.x.toFixed(1)} ${(g.y + bounce).toFixed(1)}) rotate(${tilt.toFixed(1)}) scale(${sc.toFixed(3)}) translate(-50 -50)`;
        const front = g.z >= 0;
        const fade = Math.min(1, Math.max(0, (g.z + 150) / 300));
        const on = front ? frontItems.current[i] : backItems.current[i];
        const off = front ? backItems.current[i] : frontItems.current[i];
        on?.setAttribute("transform", tf);
        on?.setAttribute("opacity", front ? "1" : (0.32 + 0.4 * fade).toFixed(2));
        on?.removeAttribute("display");
        off?.setAttribute("display", "none");
      });
    };

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (!visible) { last = 0; return; }
      const dt = last ? Math.min(0.05, (now - last) / 1000) : 0;
      last = now;
      clock += dt;
      T += dt * (1 + 0.35 * Math.sin(clock * 0.45) + 0.12 * Math.sin(clock * 1.3));      // speeds up and eases off
      draw(T);
    };

    measure();
    draw(T = 1.2);
    const ro = new ResizeObserver(() => { measure(); draw(T); });
    ro.observe(el);
    let io: IntersectionObserver | undefined;
    if (!still) {
      io = new IntersectionObserver(([e]) => { visible = !!e?.isIntersecting; }, { rootMargin: "80px" });
      io.observe(el);
      raf = requestAnimationFrame(frame);
    }
    return () => { cancelAnimationFrame(raf); ro.disconnect(); io?.disconnect(); };
  }, []);

  const items = (layer: Layer) =>
    ITEMS.map((it, i) => (
      <g key={i} ref={(n) => { (layer === "front" ? frontItems : backItems).current[i] = n; }} display="none">
        <RibbonArt item={it.art} />
      </g>
    ));
  const lines = (layer: Layer) =>
    Array.from({ length: LINES }, (_, j) => (
      <path key={j} ref={(n) => { (layer === "front" ? frontPaths : backPaths).current[j] = n; }} fill="none" stroke="currentColor"
        strokeWidth={layer === "front" ? 1.4 : 1} opacity={layer === "front" ? 0.95 : 0.4} strokeLinecap="round" strokeLinejoin="round" />
    ));

  return (
    <div className="rb" ref={root}>
      <svg className="rb-layer rb-back" ref={backSvg} aria-hidden="true" focusable="false">{lines("back")}{items("back")}</svg>
      <div className="rb-mid">{children}</div>
      <svg className="rb-layer rb-front" ref={frontSvg} aria-hidden="true" focusable="false">{lines("front")}{items("front")}</svg>
    </div>
  );
}
