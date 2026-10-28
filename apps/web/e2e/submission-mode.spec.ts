import type { Page } from "@playwright/test";
import { prelaunchHits } from "../scripts/prelaunch-words.mjs";
import { expect, signIn, test } from "./fixtures";
import { PAGES } from "./pages";

/**
 * The submission build (NEXT_PUBLIC_SUBMISSION_MODE unset or "1", the e2e default) shows nothing pre-launch on any
 * page: no "Early access / testers", "coming soon", "beta", "launching", launch date or early-adopter list. Each page
 * is read whole (title, meta description, all text in the DOM including closed menus, and accessible names held in
 * attributes); scripts are left out because test builds carry the pre-launch branch for specs that flip the mode.
 * The production export is checked file by file in CI (scripts/prelaunch-words.mjs).
 */

async function pageWords(page: Page): Promise<string> {
  return page.evaluate(() => {
    const body = document.body.cloneNode(true) as HTMLElement;
    body.querySelectorAll("script, style, template, noscript").forEach((n) => n.remove());
    const attrs = [...body.querySelectorAll("*")].flatMap((el) =>
      ["aria-label", "title", "alt", "placeholder", "aria-description"].map((a) => el.getAttribute(a) ?? ""),
    );
    const meta = document.querySelector('meta[name="description"]')?.getAttribute("content") ?? "";
    return [document.title, meta, body.textContent ?? "", ...attrs].join("\n");
  });
}

async function sweep(page: Page, route: string) {
  await page.goto(route);
  await expect(page.locator("main").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(prelaunchHits(await pageWords(page)), `${route}: pre-launch wording`).toEqual([]);
}

test.describe("submission mode: no pre-launch wording", () => {
  test.skip(process.env.NEXT_PUBLIC_SUBMISSION_MODE === "0", "pre-launch build");
  // One test reads every page in turn (about 1.5 s each, waiting for the network to settle): the budget grows with the list.
  test.describe.configure({ timeout: Math.max(90_000, PAGES.length * 4_000) });

  test("every page, signed out", async ({ page }) => {
    for (const route of PAGES) await sweep(page, route);
  });

  test("the public menu at phone width, opened", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto("/");
    await page.getByRole("button", { name: "Menu" }).click();
    await expect(page.getByRole("navigation", { name: "Site menu" })).toBeVisible();
    expect(prelaunchHits(await pageWords(page))).toEqual([]);
  });

  test("every page, signed in", async ({ page }) => {
    await signIn(page);
    for (const route of PAGES) await sweep(page, route);
  });
});
