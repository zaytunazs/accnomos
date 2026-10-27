import { writeFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { createBooksFolder, expect, signIn, test } from "./fixtures";
import { PAGES } from "./pages";

/**
 * axe-core on every page of the phone smoke list (project "phone"), signed out (the sample books) and signed in
 * (test mode, one posted receipt). Fails on any serious or critical violation; moderate and minor are printed.
 * No rule is disabled.
 */
const BLOCKING = new Set(["serious", "critical"]);

async function audit(page: Page, path: string) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const res = await page.goto(path);
  expect(res?.status()).toBe(200);
  await page.waitForLoadState("networkidle");
  await expect(page.locator("main").first()).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: /^Loading/ })).toHaveCount(0); // skeletons gone: audit the real page

  const { violations } = await new AxeBuilder({ page }).analyze();
  // The full report, for the trace viewer and test-results/<test>/axe.json.
  const report = test.info().outputPath("axe.json");
  writeFileSync(report, JSON.stringify({ path, violations }, null, 2));
  await test.info().attach("axe.json", { path: report, contentType: "application/json" });
  const lines = violations.map(
    (v) => `[${v.impact}] ${v.id}: ${v.help} (${v.nodes.length}×) ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`,
  );
  for (const l of lines.filter((l) => !/^\[(serious|critical)\]/.test(l))) console.log(`${path}: ${l}`);
  expect(lines.filter((_, i) => BLOCKING.has(violations[i].impact ?? "")), `${path}: serious or critical axe violations`).toEqual([]);
  expect(errors).toEqual([]);
}

test.describe("axe, signed out", () => {
  for (const path of PAGES) test(`${path}`, ({ page }) => audit(page, path));
});

test.describe("axe, signed in", () => {
  test.beforeEach(async ({ page, runtime }) => {
    await signIn(page);
    await createBooksFolder(page);
    await runtime.postGold();
  });

  for (const path of PAGES) test(`${path}`, ({ page }) => audit(page, path));
});
