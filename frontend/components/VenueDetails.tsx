import type { Venue } from "@/lib/types";
import { Photo } from "./Photo";

/** About the place: what it is like, how it looks, and what it offers. */
export function VenueDetails({ venue }: { venue: Venue }) {
  const paragraphs = (venue.description ?? "").split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  const photos = venue.image_urls ?? [];
  const benefits = venue.benefits ?? [];
  return (
    <section className="venue" aria-labelledby="venue-title" style={{ paddingTop: 96 }}>
      <div className="prose" style={{ margin: 0 }}>
        <h2 id="venue-title" style={{ marginTop: 0 }}>The venue</h2>
        <p><b style={{ color: "var(--fg)", fontWeight: 500 }}>{venue.name}</b>, {venue.city}{venue.state ? `, ${venue.state}` : ""}.</p>
        {paragraphs.map((p, i) => <p key={i}>{p}</p>)}
        {venue.directions && <p>{venue.directions}</p>}
      </div>
      {photos.length > 0 && (
        <ul className={`vphotos n${Math.min(photos.length, 3)}`} aria-label={`Photos of ${venue.name}`}>
          {photos.map((src, i) => (
            <li key={src}>
              <Photo src={src} alt={`${venue.name}, photo ${i + 1} of ${photos.length}`} sizes="(max-width: 820px) 100vw, 480px" />
            </li>
          ))}
        </ul>
      )}
      {benefits.length > 0 && (
        <div className="vbenefits">
          <h3 className="step">What the venue offers</h3>
          <ul className="inc">{benefits.map((b, i) => <li key={i}>{b}</li>)}</ul>
        </div>
      )}
    </section>
  );
}
