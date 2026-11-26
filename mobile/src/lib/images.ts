import { CLOUDINARY_CLOUD } from "./config";

/** Site photos kept in Cloudinary under jive/site/. A replaced photo needs a new version here. */
const VERSION: Record<string, number> = { hero: 1795365071 };
export const site = (name: string) =>
  `https://res.cloudinary.com/${CLOUDINARY_CLOUD}/image/upload/${VERSION[name] ? `v${VERSION[name]}/` : ""}jive/site/${name}`;

/** Placeholder pool for events with no photo yet. Stable per slug, so a card never changes. */
const POOL = [site("hero"), site("archive-vinyl"), site("archive-vault"), site("archive-warehouse")];

export function eventImage(e: { slug: string; thumbnail_image_url: string | null; banner_image_url: string | null }, prefer: "thumb" | "banner" = "thumb"): string {
  const first = prefer === "banner" ? e.banner_image_url ?? e.thumbnail_image_url : e.thumbnail_image_url ?? e.banner_image_url;
  if (first) return first;
  let h = 0;
  for (const c of e.slug) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return POOL[h % POOL.length];
}
