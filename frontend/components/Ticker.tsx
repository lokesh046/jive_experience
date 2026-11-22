import Link from "next/link";
import { dayMonth } from "@/lib/format";
import type { EventListItem } from "@/lib/types";

/** A scrolling strip of what is on. Each item links to its event; it pauses while hovered or focused. */
export function Ticker({ events }: { events: EventListItem[] }) {
  if (events.length === 0) return null;
  const shown = events.slice(0, 8);
  // Repeat short lists so one run is always wider than the screen and the loop has no gap.
  const run = Array.from({ length: Math.max(1, Math.ceil(6 / shown.length)) }, () => shown).flat();
  const strip = (hidden: boolean) => (
    <div aria-hidden={hidden || undefined}>
      {run.map((e, i) => (
        <span key={`${e.id}-${i}`}>
          <Link href={`/events/${e.slug}`} tabIndex={hidden ? -1 : undefined}>
            {e.title}
            <em>{dayMonth(e.starts_at, e.timezone)}</em>
            <em>{e.venue_name}</em>
          </Link>
          <i />
        </span>
      ))}
    </div>
  );
  return (
    <div className="ticker" role="region" aria-label="Events on now">
      <div className="view">
        <div className="track">
          {strip(false)}
          {strip(true)}
        </div>
      </div>
    </div>
  );
}
