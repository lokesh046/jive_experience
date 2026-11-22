import type { MetadataRoute } from "next";
import { connection } from "next/server";
import { getEvents } from "@/lib/catalogue";
import { SITE_URL } from "@/lib/config";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // Built per request so a newly published night appears without a redeploy.
  await connection();
  const events = await getEvents();
  return [
    { url: SITE_URL, changeFrequency: "daily", priority: 1 },
    { url: `${SITE_URL}/events`, changeFrequency: "daily", priority: 0.9 },
    ...events.map((e) => ({ url: `${SITE_URL}/events/${e.slug}`, lastModified: new Date(e.starts_at), changeFrequency: "daily" as const, priority: 0.8 })),
  ];
}
