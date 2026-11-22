import { dayMonth, timeOf } from "@/lib/format";
import type { Performer } from "@/lib/types";
import { Photo } from "./Photo";

/** Who is playing, in running order. Times are shown in the event's own time zone (India time). */
export function Lineup({ performers, zone, eventStart }: { performers: Performer[]; zone: string; eventStart: string }) {
  if (performers.length === 0) return null;
  const sameDay = (iso: string) => dayMonth(iso, zone) === dayMonth(eventStart, zone);
  return (
    <section className="lineup" aria-labelledby="lineup-title" style={{ paddingTop: 96 }}>
      <h2 id="lineup-title">Lineup</h2>
      <ol className="artists" style={{ listStyle: "none" }}>
        {performers.map((p, i) => (
          <li key={`${p.name}-${i}`}>
            <div className={`ph${p.photo_url ? "" : " none"}`}>
              {p.photo_url
                ? <Photo src={p.photo_url} alt={`${p.name}`} sizes="(max-width: 820px) 50vw, 240px" />
                : <span aria-hidden="true">{p.name.charAt(0).toUpperCase()}</span>}
            </div>
            {p.performs_at ? (
              <time className="at" dateTime={p.performs_at}>
                {sameDay(p.performs_at) ? timeOf(p.performs_at, zone) : `${dayMonth(p.performs_at, zone)} · ${timeOf(p.performs_at, zone)}`}
              </time>
            ) : <span className="at" aria-hidden="true">&nbsp;</span>}
            <h3>{p.name}</h3>
            {p.role && <p>{p.role}</p>}
          </li>
        ))}
      </ol>
    </section>
  );
}
