import { site } from "@/lib/images";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Photo } from "@/components/Photo";
import { TicketPicker } from "@/components/TicketPicker";
import { getEvent, getEvents } from "@/lib/catalogue";
import { SITE_NAME, SITE_URL } from "@/lib/config";
import { inr, longDate, timeOf } from "@/lib/format";

export async function generateStaticParams() {
  const events = await getEvents();
  // Known nights are prerendered; a night published later renders on first visit.
  return events.length ? events.map((e) => ({ slug: e.slug })) : [{ slug: "-" }];
}

export async function generateMetadata({ params }: PageProps<"/events/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const e = await getEvent(slug);
  if (!e) return { title: "Event not found", robots: { index: false } };
  const when = longDate(e.starts_at, e.timezone);
  const description = `${e.title} at ${e.venue.name}, ${e.venue.city} — ${when}. ${e.subtitle ?? ""}`.trim();
  const image = e.banner_image_url ?? e.thumbnail_image_url;
  return {
    title: e.title,
    description,
    alternates: { canonical: `/events/${e.slug}` },
    openGraph: { title: e.title, description, type: "website", url: `/events/${e.slug}`, ...(image ? { images: [{ url: image }] } : {}) },
    twitter: { card: image ? "summary_large_image" : "summary", title: e.title, description },
  };
}

async function EventBody({ params }: Pick<PageProps<"/events/[slug]">, "params">) {
  const { slug } = await params;
  const e = await getEvent(slug);
  if (!e) notFound();

  const prices = e.ticket_categories.filter((c) => !c.is_sold_out).map((c) => c.price_paise);
  const cancelled = e.status === "CANCELLED";
  const saleMessage = cancelled
    ? "This event has been cancelled."
    : e.is_sold_out
      ? "This event is sold out."
      : e.sale_starts_at && new Date(e.sale_starts_at) > new Date()
        ? `Tickets go on sale ${longDate(e.sale_starts_at, e.timezone)}, ${timeOf(e.sale_starts_at, e.timezone)}.`
        : "Ticket sales have closed.";

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "MusicEvent",
    name: e.title,
    description: e.subtitle ?? e.description?.slice(0, 200),
    startDate: e.starts_at,
    ...(e.ends_at ? { endDate: e.ends_at } : {}),
    eventStatus: cancelled ? "https://schema.org/EventCancelled" : "https://schema.org/EventScheduled",
    eventAttendanceMode: "https://schema.org/OfflineEventAttendanceMode",
    location: {
      "@type": "Place",
      name: e.venue.name,
      address: { "@type": "PostalAddress", addressLocality: e.venue.city, addressRegion: e.venue.state ?? undefined, postalCode: e.venue.postal_code ?? undefined, addressCountry: "IN" },
    },
    image: [e.banner_image_url, e.thumbnail_image_url].filter(Boolean),
    organizer: { "@type": "Organization", name: SITE_NAME, url: SITE_URL },
    offers: e.ticket_categories.map((c) => ({
      "@type": "Offer",
      name: c.name,
      price: (c.price_paise / 100).toFixed(2),
      priceCurrency: c.currency,
      availability: c.is_sold_out ? "https://schema.org/SoldOut" : "https://schema.org/InStock",
      url: `${SITE_URL}/events/${e.slug}`,
    })),
  };

  const paragraphs = (e.description ?? "").split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);

  return (
    <main className="page">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }} />
      <div className="wrap">
        <header className="ev-head">
          <h1>{e.title}</h1>
          <p>
            <time dateTime={e.starts_at}>{longDate(e.starts_at, e.timezone)}, {timeOf(e.starts_at, e.timezone)}</time>
          </p>
          <p className="small">{e.venue.name}, {e.venue.city}</p>
          <p style={{ marginTop: 24 }}>
            <Link className="pill" href="#tickets">{e.on_sale ? "Get tickets" : "See details"}</Link>
          </p>
        </header>

        <div className="ev-photo">
          <Photo src={e.banner_image_url ?? site("hero")} alt={`${e.title} at ${e.venue.name}`} sizes="(max-width: 1000px) 100vw, 1000px" priority />
        </div>

        <div className="prose">
          {paragraphs.length > 0 && (
            <>
              <h2>The night</h2>
              {paragraphs.map((p, i) => <p key={i}>{p}</p>)}
            </>
          )}
          <h2>The venue</h2>
          <p>{e.venue.name}, {e.venue.city}{e.venue.state ? `, ${e.venue.state}` : ""}.</p>
          {e.venue.directions && <p>{e.venue.directions}</p>}
          {e.venue.map_url && <p><a className="link" href={e.venue.map_url} rel="noopener noreferrer" target="_blank">Open in maps</a></p>}
        </div>

        <section id="tickets" style={{ paddingTop: 96 }}>
          <h2>Tickets</h2>
          <p className="sub">
            {e.on_sale && prices.length > 0 ? `From ${inr(Math.min(...prices))}` : ""}
          </p>
          <TicketPicker slug={e.slug} categories={e.ticket_categories} maxPerCustomer={e.max_tickets_per_customer} onSale={e.on_sale} saleMessage={saleMessage} />
        </section>

        {e.terms_and_conditions && (
          <div className="prose">
            <h2>Good to know</h2>
            <p>{e.terms_and_conditions}</p>
          </div>
        )}
      </div>
    </main>
  );
}

export default function EventPage(props: PageProps<"/events/[slug]">) {
  return (
    <Suspense fallback={<main className="page"><div className="wrap"><div className="skeleton" style={{ height: 56, maxWidth: 480, margin: "0 auto" }} /><div className="skeleton" style={{ aspectRatio: "16/9", marginTop: 56, borderRadius: 24 }} /></div></main>}>
      <EventBody params={props.params} />
    </Suspense>
  );
}
