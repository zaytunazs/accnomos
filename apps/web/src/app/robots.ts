import type { MetadataRoute } from "next";

export const dynamic = "force-static";

/** App shells: signed-out they show sample pages, so crawlers stay out. */
const DISALLOWED = [
  "/review",
  "/bank",
  "/settings",
  "/files",
  "/ask",
  "/invoices",
  "/sales",
  "/purchases",
  "/contacts",
  "/reports",
  "/vat",
  "/month-end",
  "/payroll",
  "/accounting",
  "/audit",
  "/jobs",
  "/vehicles",
  "/cis",
  "/self-employment",
  "/property",
  "/personal",
  "/spending",
  "/prices",
  "/shopping",
  "/import",
  "/setup",
  "/accountant",
  "/connect",
  "/judges",
  "/auth",
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: DISALLOWED }],
    sitemap: "https://accnomos.com/sitemap.xml",
  };
}
