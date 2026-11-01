import { expect, test } from "./fixtures";

/** Public-site SEO: robots, sitemap, canonical, structured data and shell noindex. */

test("robots.txt allows the site and disallows the app shells", async ({ request }) => {
  const res = await request.get("/robots.txt");
  expect(res.status()).toBe(200);
  const body = await res.text();
  expect(body).toContain("Sitemap: https://accnomos.com/sitemap.xml");
  expect(body).toMatch(/^User-Agent: \*/m);
  for (const shell of ["/review", "/bank", "/settings", "/auth"]) {
    expect(body).toMatch(new RegExp(`^Disallow: ${shell}$`, "m"));
  }
});

test("sitemap.xml lists the public pages, never the app shells", async ({ request }) => {
  const res = await request.get("/sitemap.xml");
  expect(res.status()).toBe(200);
  const body = await res.text();
  for (const page of ["/how-it-works", "/help", "/try", "/join", "/privacy", "/terms", "/models", "/meta-models"]) {
    expect(body).toContain(`https://accnomos.com${page}`);
  }
  expect(body).not.toContain("/review");
  expect(body).not.toContain("/bank");
});

test("the landing page has a canonical link and valid JSON-LD", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", "https://accnomos.com");
  const raw = await page.locator('script[type="application/ld+json"]').first().textContent();
  expect(raw).toBeTruthy();
  const data = JSON.parse(raw as string);
  const graph = Array.isArray(data) ? data : (data["@graph"] ?? [data]);
  const org = graph.find((node: { "@type"?: string }) => node["@type"] === "Organization");
  expect(org?.name).toBe("Accnomos");
  expect(org?.url).toBe("https://accnomos.com");
  const app = graph.find((node: { "@type"?: string }) => node["@type"] === "SoftwareApplication");
  expect(app?.name).toBe("Accnomos");
  expect(app?.applicationCategory).toBe("BusinessApplication");
});

test("an app shell carries noindex, not a canonical public listing", async ({ page }) => {
  await page.goto("/review");
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", "noindex, nofollow");
});
