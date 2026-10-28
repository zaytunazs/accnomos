import path from "node:path";
import type { Page } from "@playwright/test";
import { createBooksFolder, DEMO_DAY, expect, signIn, test } from "./fixtures";

/**
 * Design-review screenshots for docs/research/DESIGN.md: the first screen of each key page at 1280 × 800 and
 * 390 × 844, signed out (the labelled fictional sample) plus Home signed in with the demo books.
 * Run: `DESIGN_SHOTS=1 DESIGN_SHOTS_TAG=before pnpm exec playwright test e2e/design-shots.spec.ts --project=desktop`
 * (tag `after` once a change lands). Skipped from the normal e2e run, so `pnpm run e2e` never writes into docs/.
 */

test.skip(process.env.DESIGN_SHOTS !== "1", "design shots run only with DESIGN_SHOTS=1");

const OUT = path.resolve(__dirname, "../../../docs/research/design-shots");
const TAG = process.env.DESIGN_SHOTS_TAG ?? "before";

const VIEWPORTS = [
  { name: "1280", use: { viewport: { width: 1280, height: 800 } } },
  { name: "390", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
] as const;

const PAGES: { slug: string; path: string; ready: (page: Page) => Promise<void> }[] = [
  { slug: "home", path: "/", ready: (p) => expect(p.getByRole("link", { name: "See the demo books" })).toBeVisible() },
  { slug: "review", path: "/review", ready: (p) => expect(p.getByRole("heading", { level: 1 })).toBeVisible() },
  { slug: "vat", path: "/vat", ready: (p) => expect(p.getByRole("heading", { level: 1, name: "VAT return" })).toBeVisible() },
  { slug: "invoices", path: "/invoices", ready: (p) => expect(p.getByText("INV-0006 · Acme Kitchens Ltd")).toBeVisible() },
  { slug: "reports", path: "/reports", ready: (p) => expect(p.getByRole("heading", { name: /Profit and loss/ })).toBeVisible() },
  { slug: "ask", path: "/ask", ready: (p) => expect(p.getByRole("heading", { level: 1 })).toBeVisible() },
  { slug: "connect", path: "/connect", ready: (p) => expect(p.getByRole("heading", { level: 1 })).toBeVisible() },
];

async function shoot(page: Page, slug: string, vp: string): Promise<void> {
  await page.screenshot({ path: path.join(OUT, `${slug}-${vp}-${TAG}.png`), scale: "css", animations: "disabled", caret: "hide" });
}

for (const vp of VIEWPORTS) {
  test.describe(`design shots · ${vp.name}`, () => {
    test.use({ ...vp.use, colorScheme: "light" });
    test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "viewports are set per test"));

    for (const p of PAGES) {
      test(p.slug, async ({ page }) => {
        await page.goto(p.path);
        await p.ready(page);
        await shoot(page, p.slug, vp.name);
      });
    }

    test("home, today figures", async ({ page }) => {
      await page.goto("/");
      const today = page.getByRole("region", { name: "Today", exact: true });
      await expect(today.getByRole("group", { name: "Cash in bank" })).toContainText("£");
      await today.scrollIntoViewIfNeeded();
      await shoot(page, "home-figures", vp.name);
    });

    test("home signed in, demo books", async ({ page, runtime }) => {
      await runtime.reset("demo");
      await signIn(page, DEMO_DAY);
      await createBooksFolder(page);
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1, name: "Good morning, Sam" })).toBeVisible();
      await page.waitForLoadState("networkidle");
      await shoot(page, "home-signed-in", vp.name);
    });
  });
}
