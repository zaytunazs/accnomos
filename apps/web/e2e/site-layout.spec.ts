import { createBooksFolder, expect, signIn, test } from "./fixtures";
import { PAGES } from "./pages";

/**
 * The site's two faces (docs/reviews/site-layout/REVIEW.md): signed out, `/` is the marketing home with its own top
 * bar and footer and nothing from the app; signed in, `/` is the dashboard. Every app URL keeps working either way.
 * The one-click demo from the landing page is driven end to end in sandbox.spec.ts (it waits for the seed).
 */

const PUBLIC = new Set(["/", "/how-it-works", "/meta-models", "/privacy", "/terms", "/judges", "/join"]); // lib/public-site.ts PUBLIC_PATHS

test.describe("signed out, / is the marketing home", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("every section, both calls to action, and no app chrome", async ({ page }) => {
    await page.goto("/");
    const main = page.getByRole("main");
    await expect(page.getByText(/Bookkeeping and Making Tax Digital for UK small businesses, sole traders, landlords and personal finances/)).toBeVisible();
    for (const name of [
      "One set of books, whoever you are",
      "How it works",
      "The rest of the books, in the same place",
      "Making Tax Digital, for VAT and Income Tax",
      "Voice and chat that wait",
      "Your books live in OneDrive",
      "Made for the phone in your pocket",
      "For accountants",
      "Pricing",
      "Questions",
    ]) {
      await expect(main.getByRole("heading", { level: 2, name, exact: true })).toBeAttached();
    }
    await expect(page.getByRole("list", { name: "The four steps" }).getByRole("listitem")).toHaveText([
      /Send it in/,
      /The AI proposes/,
      /You approve/,
      /VAT and records, ready/,
    ]);

    // The two calls to action, in the hero and again at the foot of the page.
    const hero = page.getByRole("region", { name: "Bookkeeping you only have to check" });
    // The headline is the largest text on the page (globals.css .hero-lines), not body size.
    const h1Size = await page.getByRole("heading", { level: 1 }).evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(h1Size).toBeGreaterThanOrEqual(38);
    await expect(hero.getByRole("link", { name: "Try the demo", exact: true })).toHaveAttribute("href", "/judges");
    await expect(hero.getByRole("link", { name: "Sign in with Microsoft" })).toHaveAttribute("href", "/connect?next=%2F");

    // The public top bar, with nothing from the app: no menu bar or sidebar, profile switcher, review count, to-dos,
    // greeting or sample banner.
    const bar = page.getByRole("navigation", { name: "Site" });
    for (const name of ["Features", "How it works", "Accountants", "Pricing & FAQ"]) await expect(bar.getByRole("link", { name })).toBeVisible();
    await expect(page.getByRole("banner").getByRole("link", { name: "Sign in", exact: true })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Sections" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /switch books|profile/i })).toHaveCount(0);
    await expect(page.getByText(/to review|To-dos|Good (morning|afternoon|evening)|SAMPLE — FICTIONAL COMPANY/)).toHaveCount(0);
    // The copy deck's text (docs/marketing/COPY.md), with its corrections: no pricing "shown in the app".
    await expect(page.getByRole("contentinfo")).toContainText("Accounting, intelligently done.");
    await expect(main).not.toContainText("Pricing is shown in the app");
    await expect(page.locator('meta[name="description"]')).toHaveAttribute("content", /^Bookkeeping for UK small firms: AI reads the paperwork/);

    // The footer: privacy, terms, contact and the honest list of what is untested.
    const footer = page.getByRole("contentinfo");
    await expect(footer.getByRole("link", { name: "Privacy policy" })).toHaveAttribute("href", "/privacy");
    await expect(footer.getByRole("link", { name: "Terms of use" })).toHaveAttribute("href", "/terms");
    await expect(footer.getByRole("link", { name: "Contact us" })).toHaveAttribute("href", /^mailto:.+@/);
    await expect(footer.getByRole("link", { name: /HONESTY\.md/ })).toHaveAttribute("href", /docs\/HONESTY\.md$/);
  });

  test("the hero screen is the LCP image: fetched first and never hidden by its entrance", async ({ page }) => {
    await page.goto("/");
    const lcp = page.locator('img[src="/shots/hero-review-1280.webp"]');
    await expect(lcp).toHaveAttribute("fetchpriority", "high");
    await expect(lcp).toHaveAttribute("loading", "eager");
    await expect(page.locator('img[fetchpriority="high"]')).toHaveCount(1);
    const opacity = await page.locator(".hero-laptop").evaluate((el) => getComputedStyle(el).opacity);
    expect(opacity).toBe("1");
  });

  test("terms and the judges' guide are public pages too", async ({ page }) => {
    for (const route of ["/terms", "/judges"]) {
      await page.goto(route);
      await expect(page.getByRole("navigation", { name: "Site" })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
    }
    await page.goto("/terms");
    await expect(page.getByRole("heading", { level: 1, name: "Terms of use" })).toBeVisible();
    await expect(page.getByRole("main")).toContainText("not tax, legal or accounting advice");
  });
});

test("signed in, / goes straight to the dashboard", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening), Sam$/ })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Site" })).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 2, name: "How it works", exact: true })).toHaveCount(0);
});

test.describe("every app URL still works", () => {
  test.describe.configure({ timeout: 120_000 });

  test("signed out: each page answers, the public ones in the public shell and the rest in the app", async ({ page }) => {
    for (const route of PAGES) {
      const res = await page.goto(route);
      expect(res?.status(), route).toBe(200);
      await expect(page.getByRole("heading", { name: "Page not found" }), route).toHaveCount(0);
      await expect(page.getByRole("navigation", { name: "Site" }), route).toHaveCount(PUBLIC.has(route) ? 1 : 0);
    }
  });

  test("signed in: each page answers in the app shell", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page);
    for (const route of PAGES) {
      const res = await page.goto(route);
      expect(res?.status(), route).toBe(200);
      await expect(page.getByRole("heading", { name: "Page not found" }), route).toHaveCount(0);
      await expect(page.getByRole("navigation", { name: "Site" }), route).toHaveCount(0);
      await expect(page.getByRole("navigation", { name: "Main" }), route).toBeVisible();
    }
  });
});
