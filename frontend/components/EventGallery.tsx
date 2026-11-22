"use client";

import { useEffect, useRef, useState } from "react";
import { Photo } from "./Photo";

const SLICES = 16;
const CAMERA = 1.6;
const BEND = 78 * Math.PI / 180;
const ASPECT = 16 / 9;
const PHOTO_DURATION = 5200;

function measure(width: number, height: number, count: number) {
  const radius = width * (CAMERA - 1 + Math.cos(BEND)) / (2 * CAMERA * Math.sin(BEND));
  const tileHeight = Math.min(height * 0.43, width * 0.55 / ASPECT);
  const tileWidth = tileHeight * ASPECT;
  const pitch = (tileWidth + tileHeight * 0.06) / radius;
  const limit = BEND + tileWidth / (2 * radius);
  // Use whole repetitions of the photo list. Every panel keeps the same image
  // for the entire loop and wraps only once its last facet has passed the edge.
  const columns = count * Math.ceil((2 * limit / pitch + 0.1) / count);
  return { radius, tileHeight, tileWidth, pitch, limit, columns };
}

function turn(angle: number, radius: number) {
  return `translateZ(${radius}px) rotateY(${angle}rad) translateZ(${-radius}px)`;
}

export function EventGallery({ photos, title }: { photos: string[]; title: string }) {
  const viewport = useRef<HTMLDivElement>(null);
  const scene = useRef<HTMLDivElement>(null);
  const position = useRef(0);
  const destination = useRef<number | null>(null);
  const touch = useRef<{ x: number; y: number } | null>(null);
  const [layout, setLayout] = useState<ReturnType<typeof measure> | null>(null);
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const count = photos.length;

  useEffect(() => {
    const rail = viewport.current;
    if (!rail || count < 2) return;

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setLayout(measure(width, height, count));
    });
    observer.observe(rail);
    return () => observer.disconnect();
  }, [count]);

  useEffect(() => {
    const rail = viewport.current;
    const band = scene.current;
    if (!rail || !band || !layout) return;

    const cards = Array.from(band.children) as HTMLElement[];
    const { columns, pitch, radius, limit } = layout;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let previous = 0;

    function animate(now: number) {
      const elapsed = previous ? Math.min(now - previous, 32) : 0;
      previous = now;

      if (destination.current !== null) {
        const remaining = destination.current - position.current;
        if (Math.abs(remaining) < 0.002) {
          position.current = destination.current;
          destination.current = null;
        } else {
          position.current += remaining * (1 - Math.exp(-elapsed / 140));
        }
      } else if (!paused && !hovered && !focused) {
        position.current += elapsed / PHOTO_DURATION;
      }

      cards.forEach((card, index) => {
        const offset = position.current - index;
        const angle = (offset - columns * Math.floor(offset / columns + 0.5)) * pitch;
        const visible = Math.abs(angle) < limit;
        card.style.visibility = visible ? "visible" : "hidden";
        if (visible) card.style.transform = turn(angle, radius);
      });
      rail!.dataset.animated = "true";
      frame = requestAnimationFrame(animate);
    }

    function sync() {
      cancelAnimationFrame(frame);
      previous = 0;
      if (motion.matches) {
        delete rail!.dataset.animated;
      } else if (!document.hidden) {
        frame = requestAnimationFrame(animate);
      }
    }

    sync();
    motion.addEventListener("change", sync);
    document.addEventListener("visibilitychange", sync);
    return () => {
      cancelAnimationFrame(frame);
      motion.removeEventListener("change", sync);
      document.removeEventListener("visibilitychange", sync);
    };
  }, [layout, paused, hovered, focused]);

  function step(direction: number) {
    destination.current = Math.round(destination.current ?? position.current) + direction;
  }

  if (count === 0) return null;
  if (count === 1) {
    return <div className="ev-photo"><Photo src={photos[0]} alt={title} sizes="(max-width: 1000px) 100vw, 1000px" priority /></div>;
  }

  return (
    <div
      className="event-gallery"
      role="group"
      aria-roledescription="carousel"
      aria-label={`${title} photos`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
      }}
      onKeyDown={(event) => {
        if (!viewport.current?.dataset.animated) return;
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
          event.preventDefault();
          step(event.key === "ArrowRight" ? 1 : -1);
        }
      }}
    >
      <div
        className="event-gallery__viewport"
        ref={viewport}
        tabIndex={0}
        onTouchStart={(event) => {
          const { clientX: x, clientY: y } = event.touches[0];
          touch.current = { x, y };
        }}
        onTouchCancel={() => { touch.current = null; }}
        onTouchEnd={(event) => {
          const start = touch.current;
          touch.current = null;
          if (!start || !viewport.current?.dataset.animated) return;
          const dx = event.changedTouches[0].clientX - start.x;
          const dy = event.changedTouches[0].clientY - start.y;
          if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) step(dx < 0 ? 1 : -1);
        }}
      >
        <ul className="event-gallery__still">
          {photos.map((src, index) => (
            <li key={index} className="event-gallery__photo">
              <Photo src={src} alt={`${title}, photo ${index + 1} of ${count}`} sizes="(max-width: 640px) 55vw, 32vw" priority={index === 0} />
            </li>
          ))}
        </ul>
        <div className="event-gallery__scene" ref={scene} aria-hidden style={{ perspective: layout ? layout.radius * CAMERA : undefined }}>
          {layout && Array.from({ length: layout.columns }, (_, index) => {
            const { tileWidth, tileHeight, radius } = layout;
            const strip = tileWidth / SLICES;
            return (
              <div key={index} className="event-gallery__tile" style={{ width: tileWidth, height: tileHeight, marginLeft: -tileWidth / 2, marginTop: -tileHeight / 2 }}>
                {Array.from({ length: SLICES }, (_, slice) => (
                  <div key={slice} className="event-gallery__slice" style={{
                    left: (tileWidth - strip) / 2,
                    width: strip + (slice === SLICES - 1 ? 0 : 1),
                    transform: turn((tileWidth / 2 - (slice + 0.5) * strip) / radius, radius),
                  }}>
                    <div className="event-gallery__slice-image" style={{ width: tileWidth, left: -slice * strip }}>
                      <Photo src={photos[index % count]} alt="" sizes={`${Math.ceil(tileWidth * 1.5)}px`} />
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>
      <div className="event-gallery__controls">
        <button type="button" aria-label="Previous photo" onClick={() => step(-1)}>←</button>
        <button type="button" onClick={() => setPaused(!paused)}>{paused ? "Play" : "Pause"}</button>
        <button type="button" aria-label="Next photo" onClick={() => step(1)}>→</button>
      </div>
    </div>
  );
}
