import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * Not-found, reader-down/offline and new-version strips. The reader-down test
 * blocks /health with page.route (the fixture's way of stopping the runtime);
 * the version test answers /version.json itself, so parallel workers sharing
 * out-e2e/ never see each other's versions.
 */

test("unknown paths show the not-found page, served as a 404", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const res = await page.goto("/no-such-page-xyz");
  expect(res?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  await page.getByRole("button", { name: "Copy details" }).click();
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  expect(clip).toContain("Page not found");
  expect(clip).toContain("Page: http://127.0.0.1:3100/no-such-page-xyz");
  await page.getByRole("link", { name: "Back to Home" }).click();
  await expect(page).toHaveURL("/");
});

test("a runtime 500 shows its correlation id, with copy", async ({ page, context, runtime }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await signIn(page);
  await createBooksFolder(page);
  await runtime.reset("bank");
  await page.route("**/books/bank/summary", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Ledger read failed", correlation_id: "corr-e2e-500" }),
    });
  });
  await page.goto("/bank");
  const note = page.getByRole("alert").filter({ hasText: /Something went wrong on our side/ });
  await expect(note).toBeVisible();
  await expect(note).toContainText("corr-e2e-500");
  await expect(note.getByRole("button", { name: "Try again" })).toBeVisible();
  await note.getByRole("button", { name: "Copy" }).click();
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  expect(clip).toBe("Accnomos error (status 500): Ledger read failed [ref corr-e2e-500]");
});

test("reader down: one shared strip with retry; the page keeps what it can", async ({ page }) => {
  await page.route("**/health", (route) => route.abort());
  await page.goto("/");

  // Live regions take no accessible name from their contents: match on text.
  const strip = page.getByRole("alert").filter({ hasText: /isn't answering/ });
  await expect(strip).toBeVisible();
  await expect(strip).toContainText("your files are safe in OneDrive");
  // Signed out, the page still renders the sample books underneath.
  await expect(page.getByRole("link", { name: "See the demo books" })).toBeVisible();

  await page.unroute("**/health");
  await strip.getByRole("button", { name: "Try again" }).click();
  await expect(strip).toHaveCount(0);
});

test("offline: the same strip says offline, then recovers", async ({ page }) => {
  await page.route("**/health", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByRole("alert").filter({ hasText: /isn't answering/ })).toBeVisible();

  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  const strip = page.getByRole("alert").filter({ hasText: /You're offline/i });
  await expect(strip).toBeVisible();
  await expect(strip).toContainText("Uploads will wait and resume");

  await page.unroute("**/health");
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect(strip).toHaveCount(0);
});

test("new version: the strip appears when version.json changes, and reload clears it", async ({ page }) => {
  let sha = "1111111";
  await page.route("**/version.json", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ sha, builtAt: "2026-10-27T00:00:00Z" }),
    });
  });
  await page.goto("/");
  await page.waitForTimeout(500); // let the first poll take sha as the baseline
  sha = "2222222";

  const strip = page.getByRole("status").filter({ hasText: /new version is available/i });
  await expect(strip).toBeVisible({ timeout: 15_000 });
  await strip.getByRole("button", { name: "Reload" }).click();
  await page.waitForLoadState("load");
  // After the reload the running sha is the baseline again: quiet for a full poll cycle.
  await page.waitForTimeout(4500);
  await expect(page.getByRole("status").filter({ hasText: /new version is available/i })).toHaveCount(0);
});
