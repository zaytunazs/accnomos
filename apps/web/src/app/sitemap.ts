import type { MetadataRoute } from "next";
import { HELP_ARTICLES } from "@/lib/help";

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
  "/meta-models",
];

export default function sitemap(): MetadataRoute.Sitemap {
  return [...PUBLIC_PAGES, ...HELP_ARTICLES.map((a) => `/help/${a.id}`)].map((path) => ({ url: `${SITE}${path}` }));
}
