"use client";

import { useEffect, useRef } from "react";
import { Photo } from "@/components/Photo";

export function ArchiveMorph({ photos }: { photos: ReadonlyArray<{ img: string; caption: string }> }) {
  const archive = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stage = archive.current;
    if (!stage) return;

    const cards = Array.from(stage.querySelectorAll("figure"));
    const motion = window.matchMedia("(min-width: 821px) and (prefers-reduced-motion: no-preference)");
    let frame = 0;

    function update() {
      frame = 0;
      if (!stage || !motion.matches) return;

      const height = window.innerHeight;
      const top = stage.getBoundingClientRect().top;
      const remaining = document.documentElement.scrollHeight - height - window.scrollY;
      const start = height * 0.94;
      const end = Math.max(height * 0.45, top - Math.max(0, remaining));
      const progress = remaining <= 1 ? 1 : Math.max(0, Math.min(1, (start - top) / Math.max(1, start - end)));
      stage.style.setProperty("--orbit-morph", String(progress * progress * (3 - 2 * progress)));
    }

    function schedule() {
      if (!frame) frame = requestAnimationFrame(update);
    }

    function measure() {
      if (!stage) return;
      if (!motion.matches) {
        stage.removeAttribute("data-morph");
        return;
      }

      cards.forEach((card, index) => {
        // The initial card centers sit on the ellipse and keep their left-to-right order.
        const fraction = cards.length > 1 ? index / (cards.length - 1) : 0.5;
        const angle = Math.PI * (1.12 + fraction * 0.76);
        const x = stage.clientWidth * (0.5 + 0.32 * Math.cos(angle));
        const y = stage.clientHeight / 2 + 74 * Math.sin(angle);
        card.style.setProperty("--orbit-x", `${x - card.offsetLeft - card.offsetWidth / 2}px`);
        card.style.setProperty("--orbit-y", `${y - card.offsetTop - card.offsetHeight / 2}px`);
      });
      update();
      stage.dataset.morph = "";
    }

    const observer = new ResizeObserver(measure);
    observer.observe(stage);
    motion.addEventListener("change", measure);
    window.addEventListener("scroll", schedule, { passive: true });
    measure();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      motion.removeEventListener("change", measure);
      window.removeEventListener("scroll", schedule);
    };
  }, [photos.length]);

  return (
    <div className="arch archive-morph" ref={archive}>
      <div className="archive-morph__ring" aria-hidden="true" />
      {photos.map((photo) => (
        <figure key={photo.caption}>
          <div className="ph"><Photo src={photo.img} alt="" sizes="(max-width: 820px) 66vw, 304px" /></div>
          <figcaption><p>{photo.caption}</p></figcaption>
        </figure>
      ))}
    </div>
  );
}
