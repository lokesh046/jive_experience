"use client";
import { useState } from "react";

const PHRASES = ["Pure black sessions", "Curated nightlife", "Architectural acoustics", "Heritage venues", "Resonance in ruin"];

export function Ticker() {
  const [paused, setPaused] = useState(false);
  const run = (hidden: boolean) => (
    <div aria-hidden={hidden || undefined}>
      {PHRASES.map((p) => (
        <span key={p}>
          {p}
          <i />
        </span>
      ))}
    </div>
  );
  return (
    <div className="ticker" role="region" aria-label="Highlights">
      <button type="button" onClick={() => setPaused((v) => !v)} aria-label={paused ? "Resume scrolling text" : "Pause scrolling text"}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          {paused ? <path d="M7 4.5v15l12-7.5z" /> : <><rect x="5" y="4" width="4.5" height="16" rx="1" /><rect x="14.5" y="4" width="4.5" height="16" rx="1" /></>}
        </svg>
      </button>
      <div className="view">
        <div className={`track${paused ? " paused" : ""}`}>
          {run(false)}
          {run(true)}
        </div>
      </div>
    </div>
  );
}
