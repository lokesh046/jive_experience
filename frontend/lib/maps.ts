import type { Venue } from "./types";

/** Coordinates inside a full Google Maps link (`@12.97,77.59` or `!3d12.97!4d77.59`), if there are any. */
export function coordsFromLink(link: string | null | undefined): string | null {
  if (!link) return null;
  const at = link.match(/@(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)/);
  if (at) return `${at[1]},${at[2]}`;
  const bang = link.match(/!3d(-?\d{1,3}\.\d+)!4d(-?\d{1,3}\.\d+)/);
  if (bang) return `${bang[1]},${bang[2]}`;
  const q = link.match(/[?&](?:q|query|ll)=(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)/);
  return q ? `${q[1]},${q[2]}` : null;
}

/** Only web links ever become an href. */
export const isWebLink = (u: string | null | undefined): u is string => !!u && /^https?:\/\//i.test(u);

export function addressOf(v: Venue): string {
  return [v.name, v.address_line1, v.address_line2, v.city, v.state, v.postal_code].filter(Boolean).join(", ");
}

/**
 * What the map shows. A pasted link with coordinates is the most exact; otherwise the venue's own
 * coordinates; otherwise a search for its address. (Short links such as maps.app.goo.gl hide the
 * place, so they open on click but cannot be drawn: the address is drawn instead.)
 */
export function mapQuery(v: Venue, link: string | null): string {
  return coordsFromLink(link) ?? (v.latitude != null && v.longitude != null ? `${v.latitude},${v.longitude}` : addressOf(v));
}

export const embedUrl = (query: string) => `https://www.google.com/maps?q=${encodeURIComponent(query)}&z=15&output=embed`;
export const searchUrl = (query: string) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
