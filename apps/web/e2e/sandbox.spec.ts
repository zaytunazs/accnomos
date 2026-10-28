import type { Page } from "@playwright/test";
import { RELAY_URL } from "./env.mjs";
import { expect, pickVatPeriod, test, TODAY } from "./fixtures";

// The demo sandbox (services/runtime/app/demo.py, src/lib/demo.ts): the whole app on the sample books with no
// sign-in. The e2e runtime runs with DEMO_MODE=1; its first session waits while today's sample books are seeded
// (the full tools/seed_demo.py plan, in a background thread the runtime starts on its first /health).

const SEED_WAIT = 300_000; // seeding took ~2 minutes on a heavily loaded 2-core box; seconds on an idle one

const bar = (page: Page) => page.getByRole("complementary", { name: "Demo sandbox" });
const status = (page: Page) => page.locator('p[role="status"][aria-live="polite"]');

test.describe.configure({ mode: "serial" }); // one seed for both tests

test("Try the demo from the landing: review and approve a receipt, the VAT return, reset, leave", async ({ page }) => {
  test.setTimeout(SEED_WAIT + 120_000);
  await page.clock.install({ time: TODAY });
  await page.goto("/");
  // One click on the landing page's "Try the demo" (DemoLink.tsx): a sandbox, opened on the judges' guide.
  await page.getByRole("main").getByRole("link", { name: "Try the demo", exact: true }).first().click();
  await expect(bar(page)).toContainText("Demo sandbox with sample data — changes reset after 2 hours.", { timeout: SEED_WAIT });
  await expect(page).toHaveURL(/\/judges$/);
  await expect(page.getByRole("heading", { name: "Try Accnomos in one click" })).toBeVisible();
  await expect(page.getByText("SAMPLE — FICTIONAL COMPANY · demo data only")).toHaveCount(0); // live books, not the static sample

  // Review: six documents waiting (two need a look); approve one.
  await page.goto("/review");
  await expect(page.getByText("6 waiting for you")).toBeVisible();
  const approve = page.getByRole("button", { name: /^Approve / }).first();
  await approve.click();
  await expect(status(page)).toHaveText("Approved · posted to your books · U to undo");
  await expect(page.getByText("5 waiting for you")).toBeVisible();

  // The VAT return, then a submission that is simulated and says so: the relay is never called.
  let relayCalls = 0;
  await page.route(`${RELAY_URL}/**`, (route) => {
    relayCalls++;
    return route.abort();
  });
  await page.goto("/vat");
  await pickVatPeriod(page, "Jul–Sep 2026");
  const ret = page.getByRole("region", { name: /Your return/ });
  await expect(ret).toContainText("Your return · Jul–Sep 2026");
  await expect(ret).not.toContainText("0 approved entries");
  const hmrc = page.getByRole("region", { name: "Connect to HMRC" });
  await expect(hmrc).toContainText("Demo · HMRC simulated");
  await hmrc.getByRole("button", { name: "Connect to HMRC (simulated)" }).click();
  await hmrc.getByRole("button", { name: "Show obligations" }).click();
  await expect(hmrc.getByRole("radio", { name: "Choose period 26A3" })).toBeChecked();
  await hmrc.getByRole("button", { name: "Prepare submission" }).click();
  await hmrc.getByLabel("I confirm the information is true and complete").check();
  await hmrc.getByRole("button", { name: "Submit (demo — simulated)" }).click();
  await expect(hmrc.getByRole("heading", { name: "Demo — submission simulated · key 26A3" })).toBeVisible();
  await expect(hmrc).toContainText("HMRC was not contacted");
  expect(relayCalls).toBe(0);

  // Reset demo: a fresh copy, the approval gone.
  await bar(page).getByRole("button", { name: "Reset demo" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/review");
  await expect(page.getByText("6 waiting for you")).toBeVisible();

  // Set up your own books: out of the demo, to the real sign-in.
  await bar(page).getByRole("button", { name: "Set up your own books →" }).click();
  await expect(page).toHaveURL(/\/connect$/);
  await expect(page.getByRole("button", { name: "Sign in with Microsoft" })).toBeVisible();
  await expect(bar(page)).toHaveCount(0);
});

test("/judges: a short guide that starts a demo in one click", async ({ page }) => {
  test.setTimeout(SEED_WAIT + 60_000);
  await page.clock.install({ time: TODAY });
  await page.goto("/judges");
  await expect(page.getByRole("heading", { name: "Try Accnomos in one click" })).toBeVisible();
  const steps = page.getByRole("region", { name: "What to try, in this order" }).getByRole("listitem");
  await expect(steps).toHaveText([/Review a receipt/, /Approve/, /VAT return/, /Ask/, /Reports/, /Contacts/, /Bank/]);
  await expect(page.getByRole("main")).toContainText("This sandbox is specially for testing");
  await expect(page.getByRole("main")).toContainText("Signing in with Microsoft sets up real books in a folder in your own OneDrive");
  await page.getByRole("button", { name: "Start the demo" }).click();
  await expect(page).toHaveURL(/\/review$/, { timeout: SEED_WAIT });
  await expect(bar(page)).toBeVisible();
  await expect(page.getByText("6 waiting for you")).toBeVisible();
});
