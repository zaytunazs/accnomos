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
