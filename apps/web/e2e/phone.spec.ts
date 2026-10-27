import { createBooksFolder, expect, signIn, test } from "./fixtures";

/** Every page of the static export, at phone width (project "phone"), signed in with a posted receipt. */
const PAGES = [
  "/", "/ask", "/bank", "/contacts", "/files", "/invoices", "/invoices/new", "/jobs", "/jobs/job", "/payroll", "/review", "/settings",
  "/vat", "/vehicles", "/privacy", "/connect", "/connect/ai", "/connect/business", "/connect/ready",
];

/** The pages used most on a phone, with the control each must show without scrolling sideways. */
const NARROW: [string, string][] = [
  ["/", "Ask"], ["/review", "Scan 00 Inbox now"], ["/ask", "Ask"], ["/vat", "Ask about Oct–Dec 2026"], ["/settings", "Business"],
];

test.describe("390 px wide (iPhone 12–15)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test.beforeEach(async ({ page, runtime }) => {
    await signIn(page);
    await createBooksFolder(page);
    await runtime.postGold();
  });

  for (const [path, control] of NARROW) {
    test(`${path}: no horizontal scroll, every button on screen`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.getByRole("main").getByRole(path === "/settings" ? "tab" : path === "/vat" ? "link" : "button", { name: control, exact: true }).first()).toBeInViewport();
      const { scroll, width, offscreen } = await page.evaluate(() => {
        // Buttons inside a sideways-scrolling table are reachable by scrolling it; everything else must fit.
        const inScroller = (el: Element) => {
          for (let p = el.parentElement; p; p = p.parentElement) {
            if (["auto", "scroll"].includes(getComputedStyle(p).overflowX)) return true;
          }
          return false;
        };
        const offscreen = [...document.querySelectorAll("button, [role=tab], a[class*='rounded-xl']")]
          .filter((el) => el.checkVisibility() && !inScroller(el))
          .filter((el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && (r.left < -1 || r.right > window.innerWidth + 1);
          })
          .map((el) => (el.textContent ?? "").trim().slice(0, 40));
        return { scroll: document.documentElement.scrollWidth, width: window.innerWidth, offscreen };
      });
      expect(width).toBe(390);
      expect(scroll, `${path}: page is ${scroll}px wide`).toBeLessThanOrEqual(width);
      expect(offscreen, `${path}: buttons cut off at the edge`).toEqual([]);
    });
  }
});

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
