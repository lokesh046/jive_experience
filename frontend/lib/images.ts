import { CLOUDINARY_CLOUD } from "./config";

/**
 * Site photos kept in Cloudinary under jive/site/. Browsers keep Cloudinary images for 30 days, so
 * a replaced photo needs a new version number here, or visitors keep seeing the old one.
 */
const VERSION: Record<string, number> = { hero: 1795365071 };
export const site = (name: string) =>
  `https://res.cloudinary.com/${CLOUDINARY_CLOUD}/image/upload/${VERSION[name] ? `v${VERSION[name]}/` : ""}jive/site/${name}`;

/** Placeholder pool for events that have no image yet. Stable per slug, so a card never changes between renders. */
const POOL = [site("hero"), site("archive-vinyl"), site("archive-vault"), site("archive-warehouse")];

export function eventImage(e: { slug: string; thumbnail_image_url: string | null; banner_image_url: string | null }): string {
  if (e.thumbnail_image_url) return e.thumbnail_image_url;
  if (e.banner_image_url) return e.banner_image_url;
  let h = 0;
  for (const c of e.slug) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return POOL[h % POOL.length];
}
