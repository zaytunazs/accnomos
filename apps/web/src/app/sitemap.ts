import type { MetadataRoute } from "next";

export const dynamic = "force-static";

const SITE = "https://accnomos.com";

/** Public pages only: the app shells are disallowed in robots.ts and noindexed. */
const PUBLIC_PAGES = [
  "/",
  "/how-it-works",
  "/help",
  "/try",
  "/join",
  "/pricing",
  "/privacy",
  "/terms",
  "/models",
  "/ai-models",
];

export default function sitemap(): MetadataRoute.Sitemap {
  return PUBLIC_PAGES.map((path) => ({ url: `${SITE}${path}` }));
}
