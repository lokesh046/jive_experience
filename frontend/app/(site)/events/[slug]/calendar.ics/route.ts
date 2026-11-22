import { getEvent } from "@/lib/catalogue";
import { SITE_URL } from "@/lib/config";
import { icsFor } from "@/lib/calendar";

/** The event as a calendar file. Same cached data as the event page, so it costs the backend nothing extra. */
export async function GET(_req: Request, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const e = await getEvent(slug);
  if (!e) return new Response("Not found", { status: 404 });
  const where = [e.venue.name, e.venue.address_line1, e.venue.city, e.venue.state, e.venue.postal_code].filter(Boolean).join(", ");
  const body = icsFor({ id: e.id, slug: e.slug, title: e.title, subtitle: e.subtitle, starts_at: e.starts_at, ends_at: e.ends_at, where, url: `${SITE_URL}/events/${e.slug}` });
  return new Response(body, {
    headers: {
      "content-type": "text/calendar; charset=utf-8",
      "content-disposition": `attachment; filename="${e.slug}.ics"`,
      "cache-control": "public, max-age=300",
    },
  });
}
