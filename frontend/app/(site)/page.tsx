import { site } from "@/lib/images";
import Link from "next/link";
import type { Metadata } from "next";
import { Suspense } from "react";
import { ArchiveMorph } from "@/components/ArchiveMorph";
import { EventCard } from "@/components/EventCard";
import { Photo } from "@/components/Photo";
import { Ticker } from "@/components/Ticker";
import { ARCHIVE, ARTISTS, PRIVATE_SERVICES } from "@/lib/content";
import { getArtists, getEvents } from "@/lib/catalogue";
import { CONTACT_EMAIL, SITE_NAME, SITE_URL } from "@/lib/config";
import { longDate } from "@/lib/format";

export const metadata: Metadata = {
  title: { absolute: "JIVE — Live music evenings in Mumbai, Bengaluru, Delhi and Goa" },
  description: "Intimate live music evenings in converted mills, vaults and warehouses. See what is on and book tickets.",
  alternates: { canonical: "/" },
};

async function HomeContent() {
  const events = await getEvents();
  // Real performers once admins add lineups; until then the placeholder artists keep the section filled.
  const real = await getArtists(events);
  const artists = real.length ? real : ARTISTS.map((a) => ({ name: a.name, note: a.note, img: a.img, slug: "" }));
  // The banner shows the soonest event an admin marked "Show in the homepage banner", or simply the soonest.
  const next = events.find((e) => e.is_featured) ?? events[0];

  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      { "@type": "Organization", name: SITE_NAME, url: SITE_URL },
      { "@type": "WebSite", name: SITE_NAME, url: SITE_URL },
    ],
  };

  return (
    <main>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }} />

      <section className="hero" aria-label="Featured event">
        <Photo src={next?.banner_image_url ?? next?.thumbnail_image_url ?? site("hero")} alt="" sizes="100vw" priority />
        <div className="wrap">
          <h1>{next ? next.title : "Live music evenings"}</h1>
          <p>
            {next
              ? `${longDate(next.starts_at, next.timezone)} · ${next.venue_name}, ${next.city}`
              : "Intimate nights in converted mills, vaults and warehouses."}
          </p>
          <Link className="pill" href={next ? `/events/${next.slug}` : "#events"}>
            {next ? "Get tickets" : "See what is on"}
          </Link>
        </div>
      </section>

      <Ticker events={events} />

      <section className="block" id="events">
        <div className="wrap">
          <h2>Upcoming nights</h2>
          {events.length === 0 ? (
            <p className="empty" style={{ marginTop: 32 }}>No upcoming nights yet. New dates are announced here first.</p>
          ) : (
            <div className="cards">
              {events.slice(0, 6).map((e, i) => <EventCard key={e.id} event={e} priority={i < 3} />)}
            </div>
          )}
          {events.length > 0 && <p className="more"><Link className="pill ghost" href="/events">See all events</Link></p>}
        </div>
      </section>

      <section className="block" id="artists">
        <div className="wrap">
          <h2>Artists</h2>
          <div className="artists">
            {artists.map((a) => (
              <div key={a.name}>
                <div className="ph"><Photo src={a.img} alt="" sizes="(max-width: 820px) 50vw, 240px" priority={false} /></div>
                <h3>{a.slug ? <Link href={`/events/${a.slug}`}>{a.name}</Link> : a.name}</h3>
                <p>{a.note}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="block" id="private">
        <div className="wrap narrow">
          <h2>Private bookings</h2>
          <p style={{ marginTop: 24 }}>
            Our rooms are available for private listening sessions, brand showcases and table reservations.
          </p>
          <div className="svc" style={{ marginTop: 40 }}>
            {PRIVATE_SERVICES.map((s) => (
              <div key={s.name}><b>{s.name}</b><span>{s.note}</span></div>
            ))}
          </div>
          {CONTACT_EMAIL && (
            <p style={{ marginTop: 32 }}>
              <a className="link" href={`mailto:${CONTACT_EMAIL}?subject=Private%20booking%20enquiry`}>Make an enquiry</a>
            </p>
          )}
        </div>
      </section>

      <section className="block">
        <div className="wrap">
          <h2>From the archive</h2>
          <ArchiveMorph photos={ARCHIVE} />
        </div>
      </section>
    </main>
  );
}

export default function Home() {
  return (
    <Suspense
      fallback={
        <main>
          <section className="hero" aria-label="JIVE">
            <Photo src={site("hero")} alt="" sizes="100vw" priority />
            <div className="wrap"><h1>Live music evenings</h1></div>
          </section>
        </main>
      }
    >
      <HomeContent />
    </Suspense>
  );
}
