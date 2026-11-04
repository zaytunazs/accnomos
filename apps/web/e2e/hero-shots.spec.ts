import { statSync } from "node:fs";
import path from "node:path";
import type { Locator, Page } from "@playwright/test";
import { expect, test, TODAY } from "./fixtures";

/**
 * The landing page's hero screenshots (public/shots/hero-review-*.webp and hero-phone*.webp, made from these by
 * scripts/marketing-images.py): Review in the demo sandbox, one of the sample books' own waiting documents, with the
 * original receipt, the supplier and amount, the proposed entry and Approve · Edit · Reject in one frame.
 *
 * Run: `HERO_SHOTS=1 pnpm exec playwright test e2e/hero-shots.spec.ts --project=desktop` after `pnpm run e2e:build`
 * (skipped otherwise, so `pnpm run e2e` never writes into docs/). Writes docs/submission/shots/hero-review.png
 * (1280 × 800) and hero-review-phone.png (430 × 932, an iPhone Pro Max's CSS size, same shape as 390 × 844).
 *
 * What is in the frame is the demo as every visitor gets it: the company demo's seeded books (its profile names
 * Bramblewood Joinery Ltd, fictional), a document the seed pre-read from the fields printed on it (the card says
 * "Pre-read sample document" and "seed:gold-reading"; no model and no test stub appear), the demo's own chrome.
 * Nothing in the page is changed before capture: the page is scrolled so the card sits under the sticky top bar,
 * and a frame that cannot hold the card from its title to its buttons fails rather than cropping them.
 */

test.skip(process.env.HERO_SHOTS !== "1", "hero shots run only with HERO_SHOTS=1");
test.describe.configure({ mode: "serial" });
test.use({ colorScheme: "light", launchOptions: { args: ["--lang=en-GB"] } });

const OUT = path.resolve(__dirname, "../../../docs/submission/shots");
const LIMIT = 450 * 1024;
const SEED_WAIT = 400_000;
/** The card: a joinery's timber and hardware invoice, VAT to reclaim, paid by bank transfer (tools/seed_demo.py). */
const SUPPLIER = process.env.HERO_SUPPLIER ?? "Northgate Timber & Hardware Supplies";

const bar = (page: Page) => page.getByRole("complementary", { name: "Demo sandbox" });

async function startDemo(page: Page): Promise<void> {
  await page.clock.install({ time: TODAY });
  await page.goto("/demo");
  await page.getByRole("button", { name: "Start the demo" }).click();
  await expect(page).toHaveURL(/\/review$/, { timeout: SEED_WAIT });
  await expect(bar(page)).toContainText("SAMPLE — FICTIONAL COMPANY");
  await expect(page.getByText("6 waiting for you")).toBeVisible({ timeout: 60_000 });
}

/** The chosen card, with its thumbnail loaded (it is lazy: scroll it into view first). */
async function card(page: Page): Promise<Locator> {
  const c = page.locator('section[aria-labelledby^="proposal-"]').filter({ hasText: SUPPLIER }).first();
  await expect(c).toBeVisible();
  await c.scrollIntoViewIfNeeded();
  const img = c.locator("img").first();
  await expect(img).toBeVisible({ timeout: 30_000 });
  await expect.poll(() => img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await expect(c).toContainText("Pre-read sample document");
  await expect(c).not.toContainText(/stub|test mode/i);
  return c;
}

/** Scroll so `top` sits `gap` px under the sticky top bar; the bar keeps the business name on screen. */
async function under(page: Page, top: Locator, gap: number): Promise<void> {
  const header = await page.locator("header").first().boundingBox();
  await top.evaluate((el, off) => {
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - off, behavior: "instant" });
  }, (header?.height ?? 64) + gap);
  await page.waitForTimeout(400);
}

async function shoot(page: Page, name: string, c: Locator): Promise<void> {
  // The whole card's decision row is in the frame, or the shot is wrong for the hero.
  const approve = c.getByRole("button", { name: /^Approve / }).first();
  const reject = c.getByRole("button", { name: "Reject" }).first();
  for (const b of [approve, c.getByRole("button", { name: "Edit" }).first(), reject]) await expect(b).toBeInViewport({ ratio: 1 });
  await expect(c.getByRole("heading", { level: 2 }).first()).toBeInViewport({ ratio: 1 });
  const file = path.join(OUT, name);
  await page.screenshot({ path: file, scale: "css", animations: "disabled", caret: "hide" });
  expect(statSync(file).size, `${name} is over ${LIMIT / 1024} kB`).toBeLessThan(LIMIT);
}

test.describe("desktop 1280 × 800", () => {
  test.use({ viewport: { width: 1280, height: Number(process.env.HERO_H ?? 800) } });

  test("hero-review.png: the card from its receipt to Approve · Edit · Reject", async ({ page }) => {
    test.setTimeout(SEED_WAIT + 120_000);
    await startDemo(page);
    await expect(page.getByRole("button", { name: /^Account: / })).toBeVisible();
    await expect(page.getByText("Profile not set up")).toHaveCount(0); // the demo's own profile (app/demo.py)
    await expect(page.getByText("Bramblewood Joinery Ltd").first()).toBeVisible();
    const c = await card(page);
    await under(page, c, 12);
    await expect(c.locator("img").first()).toBeInViewport({ ratio: 1 });
    await shoot(page, "hero-review.png", c);
  });
});

test.describe("phone 430 × 932", () => {
  test.use({ viewport: { width: 430, height: Number(process.env.HERO_PHONE_H ?? 932) }, isMobile: true, hasTouch: true });

  test("hero-review-phone.png: the same card, supplier and amount to the decision row", async ({ page }) => {
    test.setTimeout(SEED_WAIT + 120_000);
    await startDemo(page);
    const c = await card(page);
    // The phone stacks the receipt above the words; the frame starts at the supplier line so the decision fits.
    await under(page, c.getByRole("heading", { level: 2 }).first(), 12);
    await shoot(page, "hero-review-phone.png", c);
  });
});
