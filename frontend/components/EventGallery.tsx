"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Photo } from "./Photo";

const EVERY_MS = 5000;

/**
 * The event photos as a slideshow: crossfades with a slow zoom, advances by itself,
 * and stops while the pointer or keyboard is on it, the tab is hidden, or the visitor
 * prefers reduced motion. One photo is shown plainly, without controls.
 */
export function EventGallery({ photos, title }: { photos: string[]; title: string }) {
  const [i, setI] = useState(0);
  const [held, setHeld] = useState(false);
  const [still, setStill] = useState(false);
  const touch = useRef<number | null>(null);
  const n = photos.length;

  useEffect(() => {
    const q = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setStill(q.matches);
    queueMicrotask(sync);
    q.addEventListener("change", sync);
    return () => q.removeEventListener("change", sync);
  }, []);

  const go = useCallback((to: number) => setI(((to % n) + n) % n), [n]);

  useEffect(() => {
    if (n < 2 || held || still) return;
    const id = setTimeout(() => {
      if (document.visibilityState === "visible") go(i + 1);
    }, EVERY_MS);
    return () => clearTimeout(id);
  }, [i, n, held, still, go]);

  if (n === 0) return null;
  if (n === 1) return <div className="ev-photo"><Photo src={photos[0]} alt={title} sizes="(max-width: 1000px) 100vw, 1000px" priority /></div>;

  return (
    <div
      className="ev-photo gal"
      role="group"
      aria-roledescription="carousel"
      aria-label={`${title} photos`}
      onMouseEnter={() => setHeld(true)}
      onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
      onKeyDown={(e) => { if (e.key === "ArrowRight") go(i + 1); if (e.key === "ArrowLeft") go(i - 1); }}
      onTouchStart={(e) => { touch.current = e.touches[0].clientX; }}
      onTouchEnd={(e) => {
        if (touch.current == null) return;
        const dx = e.changedTouches[0].clientX - touch.current;
        touch.current = null;
        if (Math.abs(dx) > 40) go(i + (dx < 0 ? 1 : -1));
      }}
    >
      {photos.map((src, k) => (
        <div
          key={src}
          className={`slide${k === i ? " on" : ""}`}
          role="group"
          aria-roledescription="slide"
          aria-label={`${k + 1} of ${n}`}
          aria-hidden={k === i ? undefined : true}
        >
          <Photo src={src} alt={k === i ? `${title}, photo ${k + 1} of ${n}` : ""} sizes="(max-width: 1000px) 100vw, 1000px" priority={k === 0} />
        </div>
      ))}
      <button type="button" className="gal-nav prev" aria-label="Previous photo" onClick={() => go(i - 1)}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M19 12H5M11 6l-6 6 6 6" /></svg>
      </button>
      <button type="button" className="gal-nav next" aria-label="Next photo" onClick={() => go(i + 1)}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
      </button>
      <div className="gal-dots">
        {photos.map((_, k) => (
          <button key={k} type="button" aria-label={`Show photo ${k + 1}`} aria-current={k === i ? "true" : undefined} onClick={() => go(k)}>
            <span className={k === i && !held && !still ? "run" : undefined} key={k === i ? `a${i}` : "b"} />
          </button>
        ))}
      </div>
      <p className="sr" aria-live={held ? "polite" : "off"}>Photo {i + 1} of {n}</p>
    </div>
  );
}
