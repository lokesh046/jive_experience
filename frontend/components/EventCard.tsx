import Link from "next/link";
import { eventImage } from "@/lib/images";
import { dayMonth, inr } from "@/lib/format";
import type { EventListItem } from "@/lib/types";
import { Photo } from "./Photo";

/** The whole card is one link: clicking the image (or anything on it) opens the event, where tickets are booked. */
export function EventCard({ event: e, priority = false }: { event: EventListItem; priority?: boolean }) {
  return (
    <Link className="card" href={`/events/${e.slug}`}>
      <div className="ph">
        <Photo src={eventImage(e)} alt="" sizes="(max-width: 820px) 100vw, (max-width: 1100px) 50vw, 320px" priority={priority} />
      </div>
      <p className="when small">
        <time dateTime={e.starts_at}>{dayMonth(e.starts_at, e.timezone)}</time> · {e.city}
      </p>
      <h3>{e.title}</h3>
      <p className="small">{e.venue_name}</p>
      <p className="small price">
        {e.is_sold_out ? "Sold out" : e.starting_price_paise != null ? `From ${inr(e.starting_price_paise)}` : " "}
      </p>
    </Link>
  );
}
