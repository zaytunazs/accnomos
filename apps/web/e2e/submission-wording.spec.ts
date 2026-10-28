import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * The submission build (NEXT_PUBLIC_SUBMISSION_MODE unset = 1, as this e2e build is) says nothing about a future
 * launch on the pages the tax batch added (claude/batch-tax): no "coming soon", "beta", "early access" or
 * "launching", signed out or signed in with books.
 */
const NEW_PAGES = ["/self-employment", "/cis", "/property", "/payroll", "/vat", "/settings", "/contacts", "/bank"];
const LAUNCH_WORDS = /coming soon|\bbeta\b|early access|launching/i;

async function pageText(page: import("@playwright/test").Page, path: string): Promise<string> {
  await page.goto(path);
  await expect(page.locator("main")).toBeVisible();
  await page.waitForLoadState("networkidle");
  return page.locator("body").innerText();
}

test("signed out: the batch's pages say nothing about a launch", async ({ page }) => {
  for (const path of NEW_PAGES) expect(await pageText(page, path), path).not.toMatch(LAUNCH_WORDS);
});

test("signed in with books: the batch's pages say nothing about a launch", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.evaluate(() => {
    window.localStorage.setItem("accnomos.landlord.show", "1");
    window.localStorage.setItem("accnomos.personal.show", "1");
  });
  for (const path of NEW_PAGES) expect(await pageText(page, path), path).not.toMatch(LAUNCH_WORDS);
});
