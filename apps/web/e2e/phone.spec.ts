import { createBooksFolder, expect, signIn, test } from "./fixtures";

/** Every page of the static export, at phone width (project "phone"), signed in with a posted receipt. */
const PAGES = [
  "/", "/ask", "/bank", "/contacts", "/files", "/jobs", "/jobs/job", "/review", "/settings", "/vat", "/vehicles", "/privacy",
  "/connect", "/connect/ai", "/connect/business", "/connect/ready",
];

test.describe("phone viewport smoke", () => {
  test.beforeEach(async ({ page, runtime }) => {
    await signIn(page);
    await createBooksFolder(page);
    await runtime.postGold();
  });

  for (const path of PAGES) {
    test(`${path} has no horizontal scroll`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      const res = await page.goto(path);
      expect(res?.status()).toBe(200);
      await page.waitForLoadState("networkidle");
      await expect(page.locator("main").first()).toBeVisible();
      const { scroll, width } = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        width: window.innerWidth,
      }));
      expect(scroll, `${path}: page is ${scroll}px wide in a ${width}px viewport`).toBeLessThanOrEqual(width);
      expect(errors).toEqual([]);
    });
  }
});

test.describe("Review at 390 px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("signed-out sample: no horizontal scroll, action rows never wrap, approve and undo work", async ({ page }) => {
    await page.goto("/review");
    await expect(page.getByText("SAMPLE — FICTIONAL COMPANY · Bramblewood Joinery Ltd.")).toBeVisible();
    await page.waitForLoadState("networkidle");
    const { scroll, width } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: window.innerWidth }));
    expect(scroll, `review is ${scroll}px wide in a ${width}px viewport`).toBeLessThanOrEqual(width);

    // Approve, Edit and Reject sit on one line on every card.
    const rows = await page.getByRole("button", { name: /^Approve .* and post to books$/ }).evaluateAll((buttons) =>
      buttons.map((b) => {
        const row = [...b.parentElement!.children].map((c) => c.getBoundingClientRect());
        return { tops: new Set(row.map((r) => Math.round(r.top))).size, right: Math.max(...row.map((r) => r.right)) };
      }),
    );
    expect(rows.length).toBe(4);
    for (const r of rows) {
      expect(r.tops).toBe(1);
      expect(r.right).toBeLessThanOrEqual(390);
    }

    const screwfix = page.getByRole("region", { name: "Screwfix · £38.47" });
    await screwfix.getByRole("button", { name: /^Approve Screwfix/ }).click();
    await expect(screwfix).toHaveCount(0);
    await page.keyboard.press("u");
    await expect(screwfix).toBeVisible();
  });
});
