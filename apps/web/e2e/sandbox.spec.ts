import type { Page } from "@playwright/test";
import { WEB_URL } from "./env.mjs";
import { expect, pickVatPeriod, test, TODAY } from "./fixtures";
import { routeSandboxRelay, SANDBOX_RECEIPT, SANDBOX_USER } from "./sandbox-relay";

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
  // One click on the landing page's "Try the demo" (DemoLink.tsx): a sandbox, opened on the demo guide.
  await page.getByRole("main").getByRole("link", { name: "Try the demo", exact: true }).first().click();
  await expect(bar(page)).toContainText("Demo sandbox with sample data — changes reset after 2 hours.", { timeout: SEED_WAIT });
  await expect(page).toHaveURL(/\/demo$/);
  await expect(page.getByRole("heading", { name: "Your demo of Accnomos" })).toBeVisible();
  await expect(page.getByText("SAMPLE — FICTIONAL COMPANY · demo data only")).toHaveCount(0); // live books, not the static sample

  // Review: six documents waiting (two need a look); approve one.
  await page.goto("/review");
  await expect(page.getByText("6 waiting for you")).toBeVisible();
  const approve = page.getByRole("button", { name: /^Approve / }).first();
  await approve.click();
  await expect(status(page)).toHaveText("Approved · posted to your books · U to undo");
  await expect(page.getByText("5 waiting for you")).toBeVisible();

  // The VAT return, filed to HMRC's sandbox (a routed relay standing in for it): a test user made for this demo, the
  // sign-in round trip, HMRC's periods for the test VRN, the declaration, and HMRC's receipt. Never "simulated".
  const calls = await routeSandboxRelay(page);
  await page.goto("/vat");
  await pickVatPeriod(page, "Jul–Sep 2026");
  const ret = page.getByRole("region", { name: /Your return/ });
  await expect(ret).toContainText("Your return · Jul–Sep 2026");
  await expect(ret).not.toContainText("0 approved entries");
  const hmrc = page.getByRole("region", { name: "Connect to HMRC" });
  await expect(hmrc).toContainText("HMRC sandbox — real test service, no real tax filed");
  await expect(hmrc).toContainText("Filing for real needs HMRC's approval");
  await expect(hmrc).not.toContainText(/simulated/i);
  await hmrc.getByRole("button", { name: "Make an HMRC sandbox test user" }).click();
  const user = hmrc.getByRole("group", { name: "HMRC sandbox test user" });
  await expect(user).toContainText("HMRC sandbox test user — made just now for this demo");
  await expect(user.getByTestId("sandbox-user-id")).toHaveText(SANDBOX_USER.userId);
  await expect(user.getByTestId("sandbox-password")).toHaveText(SANDBOX_USER.password);
  await expect(user.getByTestId("sandbox-vat-number")).toHaveText(SANDBOX_USER.vrn);
  await expect(user.getByRole("button", { name: "Copy Password" })).toBeVisible();
  await hmrc.getByRole("button", { name: "Connect to HMRC sandbox" }).click();
  // Back from HMRC's page: the code is out of the address bar, the tab is connected as the test user.
  await expect(hmrc.getByText(`Connected to HMRC's sandbox as test user ${SANDBOX_USER.userId}`)).toBeVisible();
  expect(page.url()).toBe(`${WEB_URL}/vat`);
  await expect(hmrc.getByLabel("VAT registration number")).toHaveValue(SANDBOX_USER.vrn);
  await expect(ret).toContainText("Your return · Jul–Sep 2026"); // the picked period survived the round trip
  await hmrc.getByRole("button", { name: "Show obligations" }).click();
  await expect(hmrc.getByRole("radio", { name: "Choose period 18A2" })).toBeChecked();
  await hmrc.getByRole("button", { name: "Prepare submission" }).click();
  await expect(hmrc).toContainText("That's expected with sandbox test data");
  const send = hmrc.getByRole("button", { name: "Submit to HMRC sandbox" });
  await expect(send).toBeDisabled(); // the declaration first, by a tap
  await hmrc.getByLabel("I confirm the information is true and complete").check();
  await send.click();
  await expect(hmrc.getByRole("heading", { name: "Submitted to HMRC sandbox · key 18A2" })).toBeVisible();
  await expect(hmrc).toContainText(SANDBOX_RECEIPT.formBundleNumber);
  await expect(hmrc).toContainText(SANDBOX_RECEIPT.chargeRefNumber);
  await expect(hmrc).toContainText(`HMRC's own sandbox receipt for test user ${SANDBOX_USER.userId}`);
  await expect(hmrc).toContainText("Saved to the demo's books: 06 VAT returns/18A2/receipt.json");
  await expect(hmrc).not.toContainText(/simulated|not contacted/i);
  expect(calls.map((c) => c.path)).toEqual([
    "/hmrc/test-user",
    "/hmrc/authorize",
    "/hmrc/exchange",
    `/vat/${SANDBOX_USER.vrn}/obligations`,
    `/vat/${SANDBOX_USER.vrn}/returns`,
  ]);
  const sent = calls[4].body as { method: string; return: { periodKey: string; finalised: boolean; netVatDue: number } };
  expect(sent.method).toBe("WEB_APP_VIA_SERVER");
  expect(sent.return.periodKey).toBe("18A2");
  expect(sent.return.finalised).toBe(true);
  expect(sent.return.netVatDue).toBeGreaterThan(0); // the demo books' own box 5 for Jul–Sep 2026

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

test("/demo: a short guide that starts a demo in one click; /judges keeps the judges' notes", async ({ page }) => {
  test.setTimeout(SEED_WAIT + 60_000);
  await page.clock.install({ time: TODAY });
  await page.goto("/demo");
  await expect(page.getByRole("heading", { name: "Your demo of Accnomos" })).toBeVisible();
  const steps = page.getByRole("region", { name: "What to try" }).getByRole("listitem");
  await expect(steps).toHaveText([/receipt/, /Approve/, /Ask/, /invoice/, /bank/, /VAT return/, /goal/, /Reports and contacts/]);
  await expect(page.getByRole("main")).toContainText("reset after 2 hours");
  await expect(page.getByRole("main")).toContainText("No real tax is filed");
  await expect(page.getByRole("main")).toContainText("Sign in with Microsoft and Accnomos sets up real books in a folder in your own OneDrive");
  await expect(page.getByRole("main")).not.toContainText(/judg/i); // written for the owner, not the hackathon

  // The judges' notes: a footer link, the same Start buttons, the tour one link away.
  await page.goto("/judges");
  await expect(page.getByRole("heading", { name: "Try Accnomos in one click" })).toBeVisible();
  await expect(page.getByRole("main")).toContainText("This sandbox is specially for testing");
  await expect(page.getByRole("main").getByRole("link", { name: "the demo guide" })).toHaveAttribute("href", "/demo");
  await expect(page.getByRole("main").getByRole("link", { name: "docs/submission/JUDGING.md" })).toHaveAttribute("href", /JUDGING\.md$/);

  await page.goto("/demo");
  await page.getByRole("button", { name: "Start the demo" }).click();
  await expect(page).toHaveURL(/\/review$/, { timeout: SEED_WAIT });
  await expect(bar(page)).toBeVisible();
  await expect(page.getByText("6 waiting for you")).toBeVisible();
});

test("demo sandbox: Add a receipt reads only the upload, with progress, a type to confirm and the card in Review", async ({ page, runtime }) => {
  test.setTimeout(SEED_WAIT + 90_000);
  await page.clock.install({ time: TODAY });
  await page.goto("/demo");
  await page.getByRole("button", { name: "Start the demo" }).click();
  await expect(page).toHaveURL(/\/review$/, { timeout: SEED_WAIT });
  await expect(page.getByText("6 waiting for you")).toBeVisible();

  // The demo's 00 Inbox already holds 19 unread sample documents: the upload's job must read only the upload
  // (the owner's report: one blocking request read up to 10 Inbox files before answering).
  const started: string[] = [];
  page.on("request", (r) => new URL(r.url()).pathname === "/books/scan/jobs" && r.method() === "POST" && started.push(r.postData() ?? ""));
  await page.locator('input[type="file"]').first().setInputFiles({ name: "currys-receipt.png", mimeType: "image/png", buffer: await runtime.goldPng() });
  await expect(page.getByText("1 file added to 00 Inbox. Reading now")).toBeVisible();
  expect(started).toHaveLength(1);
  expect(JSON.parse(started[0])).toEqual({ names: ["currys-receipt.png"], source: "upload" });

  const row = page.locator('[data-scan-file="currys-receipt.png"]');
  await expect(row).toHaveAttribute("data-stage", "confirm", { timeout: 30_000 });
  await expect(row.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  await expect(row).toContainText("Looks like a receipt (90% sure)");
  await expect(page.locator("[data-scan-badge]")).toHaveText("1 to confirm"); // the top bar's count
  await expect(page.getByText("6 waiting for you")).toBeVisible(); // nothing read in full before the type is confirmed

  await row.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(row).toHaveAttribute("data-stage", /^(ready|needs_a_look)$/, { timeout: 30_000 });
  await expect(row.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  await expect(status(page)).toHaveText("1 new proposal");
  await expect(page.getByText("7 waiting for you")).toBeVisible();
  await expect(page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" })).toBeVisible();
  await expect(page.locator("[data-scan-badge]")).toHaveCount(0);
});

test("no HMRC sandbox for the relay: the demo falls back to simulated, says why, and never claims the sandbox", async ({ page }) => {
  test.setTimeout(SEED_WAIT + 60_000);
  await page.clock.install({ time: TODAY });
  await page.goto("/demo");
  await page.getByRole("button", { name: "Start the demo" }).click();
  await expect(bar(page)).toContainText("Demo sandbox with sample data", { timeout: SEED_WAIT });
  const calls = await routeSandboxRelay(page, { testUser: "unconfigured" });
  await page.goto("/vat");
  await pickVatPeriod(page, "Jul–Sep 2026");
  const hmrc = page.getByRole("region", { name: "Connect to HMRC" });
  await hmrc.getByRole("button", { name: "Make an HMRC sandbox test user" }).click();
  await expect(hmrc).toContainText("Demo · HMRC simulated");
  await expect(hmrc).toContainText("the HMRC relay has no sandbox credentials set up");
  await expect(hmrc).not.toContainText("HMRC sandbox — real test service");
  await hmrc.getByRole("button", { name: "Connect to HMRC (simulated)" }).click();
  await hmrc.getByRole("button", { name: "Show obligations" }).click();
  await expect(hmrc.getByRole("radio", { name: "Choose period 26A3" })).toBeChecked();
  await hmrc.getByRole("button", { name: "Prepare submission" }).click();
  await hmrc.getByLabel("I confirm the information is true and complete").check();
  await hmrc.getByRole("button", { name: "Submit (demo — simulated)" }).click();
  await expect(hmrc.getByRole("heading", { name: "Demo — submission simulated · key 26A3" })).toBeVisible();
  await expect(hmrc).toContainText("HMRC was not contacted");
  expect(calls.map((c) => c.path)).toEqual(["/hmrc/test-user"]); // the one ask; nothing else reaches the relay
});
