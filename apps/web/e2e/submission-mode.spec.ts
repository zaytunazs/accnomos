import type { Page } from "@playwright/test";
import { NOT_YET_WORDS, THIRD_PARTY_NAMES, prelaunchHits } from "../scripts/prelaunch-words.mjs";
import { expect, signIn, test } from "./fixtures";
import { PAGES } from "./pages";

/**
 * The submission build (NEXT_PUBLIC_SUBMISSION_MODE unset or "1", the e2e default) shows nothing pre-launch on any
 * page: no "Early access / testers", "coming soon", "beta", "launching", launch date or early-adopter list. Each page
 * is read whole (title, meta description, all text in the DOM including closed menus, and accessible names held in
 * attributes); scripts are left out because test builds carry the pre-launch branch for specs that flip the mode.
 * The production export is checked file by file in CI (scripts/prelaunch-words.mjs).
 * The same read also finds no non-Meta tool, engine or hardware name (Whisper, Kokoro, Ollama, vLLM, Qwen, ComfyUI,
 * DGX, Baseten): a non-Meta fallback is "a local fallback model" on every public or judge-facing page.
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
  const words = await pageWords(page);
  expect(prelaunchHits(words, NOT_YET_WORDS), `${route}: pre-launch wording`).toEqual([]);
  expect(prelaunchHits(words, THIRD_PARTY_NAMES), `${route}: non-Meta tool names`).toEqual([]);
}

/** Every page of the app, plus what only shows after a click: each Settings tab and the account menu. */
const APP_PAGES = PAGES; // includes /help and /meta-models

async function sweepSettingsTabs(page: Page) {
  await page.goto("/settings");
  const tabs = page.getByRole("tablist", { name: "Settings groups" }).getByRole("tab");
  for (const name of await tabs.allTextContents()) {
    await tabs.filter({ hasText: name }).first().click();
    await page.waitForLoadState("networkidle");
    const words = await pageWords(page);
    expect(prelaunchHits(words, NOT_YET_WORDS), `Settings › ${name}`).toEqual([]);
    expect(prelaunchHits(words, THIRD_PARTY_NAMES), `Settings › ${name}: non-Meta tool names`).toEqual([]);
  }
}

test.describe("submission mode: no pre-launch wording", () => {
  test.skip(process.env.NEXT_PUBLIC_SUBMISSION_MODE === "0", "pre-launch build");
  // One test reads every page in turn (about 1.5 s each, waiting for the network to settle): the budget grows with the list.
  test.describe.configure({ timeout: Math.max(90_000, PAGES.length * 4_000) });

  test("every page, signed out", async ({ page }) => {
    for (const route of APP_PAGES) await sweep(page, route);
  });

  test("the public menu at phone width, opened", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto("/");
    await page.getByRole("button", { name: "Menu" }).click();
    await expect(page.getByRole("navigation", { name: "Site menu" })).toBeVisible();
    const words = await pageWords(page);
    expect(prelaunchHits(words, NOT_YET_WORDS)).toEqual([]);
    expect(prelaunchHits(words, THIRD_PARTY_NAMES)).toEqual([]);
  });

  test("every page, signed in, with each Settings tab and the account menu open", async ({ page }) => {
    await signIn(page);
    for (const route of APP_PAGES) await sweep(page, route);
    await sweepSettingsTabs(page);
    await page.goto("/");
    await page.getByRole("button", { name: /^Account: / }).click();
    const menuWords = await pageWords(page);
    expect(prelaunchHits(menuWords, NOT_YET_WORDS), "account menu").toEqual([]);
    expect(prelaunchHits(menuWords, THIRD_PARTY_NAMES), "account menu: non-Meta tool names").toEqual([]);
  });

  test("every page in the demo sandbox", async ({ page }) => {
    test.setTimeout(Math.max(240_000, APP_PAGES.length * 5_000));
    await page.goto("/judges");
    await page.getByRole("button", { name: "Start the demo" }).click();
    await expect(page).toHaveURL(/\/review$/, { timeout: 120_000 });
    for (const route of APP_PAGES) await sweep(page, route);
    await sweepSettingsTabs(page);
  });
});
