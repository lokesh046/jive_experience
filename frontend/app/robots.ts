import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/config";

export default function robots(): MetadataRoute.Robots {
  return {
    // Private, per-person pages and the proxy are never useful in search results.
    rules: [{ userAgent: "*", allow: "/", disallow: ["/api/", "/checkout/", "/tickets", "/signin", "/phone", "/profile", "/auth/", "/admin", "/scan"] }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
