import { addressOf, embedUrl, isWebLink, mapQuery, searchUrl } from "@/lib/maps";
import type { Venue } from "@/lib/types";

/** Where the event is: a map you can see, the address, and a link that opens it in Maps. */
export function EventLocation({ venue, locationUrl }: { venue: Venue; locationUrl: string | null }) {
  const link = [locationUrl, venue.map_url].find(isWebLink) ?? null;
  const query = mapQuery(venue, link);
  const open = link ?? searchUrl(query);
  const lines = [venue.name, [venue.address_line1, venue.address_line2].filter(Boolean).join(", "), [venue.city, venue.state, venue.postal_code].filter(Boolean).join(", ")].filter(Boolean);
  return (
    <section className="loc" aria-labelledby="loc-title" style={{ paddingTop: 96 }}>
      <h2 id="loc-title">Location</h2>
      <div className="loc-map">
        <iframe
          title={`Map showing ${addressOf(venue)}`}
          src={embedUrl(query)}
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
          sandbox="allow-scripts allow-same-origin allow-popups"
        />
      </div>
      <div className="loc-info">
        <address>
          {lines.map((l, i) => (i === 0 ? <b key={i}>{l}</b> : <span key={i}>{l}</span>))}
        </address>
        <a className="pill" href={open} target="_blank" rel="noopener noreferrer">Open in Maps</a>
      </div>
      {venue.directions && <p className="loc-dir">{venue.directions}</p>}
    </section>
  );
}
