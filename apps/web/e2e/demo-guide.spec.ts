import type { Page } from "@playwright/test";
import { expect, test, TODAY } from "./fixtures";

/**
 * The demo guide (src/app/demo): where "Try the demo" lands, written for the person who will keep their own books
 * here. The hackathon's notes stay on /judges, reached from the footers only. The full sandbox flow (approve, the VAT
 * return, reset, leave) is sandbox.spec.ts.
 */

const SEED_WAIT = 300_000; // the first demo of a runtime waits while the sample books are seeded (sandbox.spec.ts)

const bar = (page: Page) => page.getByRole("complementary", { name: "Demo sandbox" });

test("Try the demo lands on /demo, in the sandbox, with the demo bar and nothing about judges", async ({ page }) => {
  test.setTimeout(SEED_WAIT + 60_000);
  await page.clock.install({ time: TODAY });
  await page.goto("/");
  await page.getByRole("main").getByRole("link", { name: "Try the demo", exact: true }).first().click();
  await expect(page).toHaveURL(/\/demo$/, { timeout: SEED_WAIT });
  await expect(bar(page)).toContainText("Demo sandbox with sample data — changes reset after 2 hours.");
  await expect(bar(page)).toContainText("SAMPLE — FICTIONAL COMPANY");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { level: 1 })).toHaveText("Your demo of Accnomos");
  await expect(main.getByRole("heading", { name: "What to try" })).toBeVisible();
  await expect(main).not.toContainText(/judg/i);
  await expect(page).toHaveTitle("Your demo · Accnomos");
  // Inside the demo it keeps the app shell: the tour's links open the sample books.
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(main.getByRole("link", { name: "Open a receipt that is waiting for you" })).toHaveAttribute("href", "/review");
  await expect(main.getByRole("link", { name: "File a VAT return to HMRC’s test service" })).toHaveAttribute("href", "/vat");

  // Help lists the guide for users; the judges' notes are a footer link only.
  await page.goto("/help");
  const guides = page.getByRole("list", { name: "Guides" });
  await expect(guides.getByRole("link", { name: /^Demo guide/ })).toHaveAttribute("href", "/demo");
  await expect(guides.getByRole("link", { name: /judges/i })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Main" })).not.toContainText(/judges/i);
  const about = page.getByRole("navigation", { name: "About" });
  await expect(about.getByRole("link", { name: "Demo guide" })).toHaveAttribute("href", "/demo");
  await expect(about.getByRole("link", { name: "For judges" })).toHaveAttribute("href", "/judges");
});

test("signed out, /demo is a public page with no judges wording; /judges is the footer's", async ({ page }) => {
  await page.goto("/demo");
  await expect(page.getByRole("navigation", { name: "Site" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { level: 1 })).toHaveText("Your demo of Accnomos");
  await expect(main).not.toContainText(/judg/i);
  await expect(main.getByRole("button", { name: "Start the demo" })).toBeVisible();
  await expect(main.getByRole("button", { name: "Start the personal demo" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Site" })).not.toContainText(/judges/i);
  await expect(page.getByRole("contentinfo").getByRole("link", { name: "For judges" })).toHaveAttribute("href", "/judges");
  await expect(page.getByRole("contentinfo").getByRole("link", { name: "Try the demo" })).toHaveAttribute("href", "/demo");
});
