import type { Metadata } from "next";
import { EventList } from "@/components/EventList";
import { getEvents, getPastEvents } from "@/lib/catalogue";
import { SITE_URL } from "@/lib/config";

export const metadata: Metadata = {
  title: "Events",
  description: "Every upcoming JIVE night, by city. Pick a night to see the details and book tickets.",
  alternates: { canonical: "/events" },
};

export default async function EventsPage() {
  const [events, past] = await Promise.all([getEvents(), getPastEvents()]);
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    itemListElement: events.map((e, i) => ({ "@type": "ListItem", position: i + 1, url: `${SITE_URL}/events/${e.slug}`, name: e.title })),
  };
  return (
    <main className="page">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }} />
      <div className="wrap">
        <h1>Events</h1>
        <EventList events={events} past={past} />
      </div>
    </main>
  );
}
