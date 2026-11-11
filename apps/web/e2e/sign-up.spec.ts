import { existsSync, readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { prelaunchHits } from "../scripts/prelaunch-words.mjs";
import { EARLY_ACCESS_FILE } from "./env.mjs";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * "Join the waiting list" (src/components/sign-up/JoinForm.tsx, POST /public/sign-up): the neutral sign-up the submission
 * build shows on the landing page (hero link, a section near the end, the pricing band, the FAQ) and on /join, the page
 * the social posts link to. Same list and file as the pre-launch form (early-access.spec.ts); its consent wording
 * names no launch. Test builds flip the mode per page through localStorage (src/lib/submission-mode.ts).
 */
const HEADING = "Join the waiting list";
const CONSENT = "Email me when my place on the Accnomos waiting list comes up. I can unsubscribe any time.";
const DONE = "Thanks — you're on the waiting list";

async function submissionMode(page: Page, mode: "0" | "1") {
  await page.addInitScript((m) => window.localStorage.setItem("accnomos.test.submission-mode", m), mode);
}

function signups(email: string): Record<string, unknown>[] {
  if (!existsSync(EARLY_ACCESS_FILE)) return [];
  return readFileSync(EARLY_ACCESS_FILE, "utf-8")
    .split("\n")
    .filter(Boolean)
    .map((l) => JSON.parse(l))
    .filter((r) => r.email === email);
}

const form = (page: Page) => page.getByRole("region", { name: HEADING, exact: true });
const address = (tag: string) => `${tag}-${test.info().workerIndex}-${Date.now()}@example.co.uk`;

async function fillAndSend(page: Page, email: string) {
  const f = form(page);
  await f.getByRole("textbox", { name: "Email" }).fill(email);
  await f.getByRole("radio", { name: "Limited company" }).check();
  await f.getByRole("checkbox", { name: CONSENT }).check();
  await f.getByRole("button", { name: HEADING }).click();
}

test.describe("submission build (the default)", () => {
  test.use({ viewport: { width: 360, height: 780 } });

  test("the home page offers the free trial, not a waiting list, and /join still has the form", async ({ page }) => {
    await page.goto("/");
    const hero = page.getByRole("region", { name: "Bookkeeping you only have to check" });
    await expect(hero.getByRole("link", { name: "Try the demo", exact: true })).toBeVisible();
    await expect(hero.getByRole("link", { name: "Start your free trial", exact: true })).toHaveAttribute("href", "/pricing");
    await expect(page.getByText(/waiting list/i)).toHaveCount(0);
    await expect(form(page)).toHaveCount(0);
    await expect(page.locator("#pricing")).toContainText("3-month free trial");
    await page.getByText("How do I start the free trial?").click();
    await expect(page.getByText(/the 3-month trial starts at once and needs no card/)).toBeVisible();
    await expect(page.getByRole("contentinfo").getByRole("link", { name: "Start your free trial" })).toBeVisible();

    await page.goto("/join");
    await expect(form(page)).toBeVisible();
    await expect(form(page).getByRole("checkbox", { name: CONSENT })).not.toBeChecked(); // never pre-ticked
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  });

  test("/join: a short page with the form, for the social posts", async ({ page }) => {
    await page.goto("/join");
    await expect(page).toHaveTitle("Join the waiting list · Accnomos");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Accnomos: bookkeeping you only have to check");
    await expect(page.getByRole("main").getByRole("link", { name: "Try the demo" })).toHaveAttribute("href", "/demo");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
    const f = form(page);
    await expect(f).toContainText("Leave your email to join the waiting list.");
    await f.getByRole("button", { name: HEADING }).click();
    await expect(f.getByRole("textbox", { name: "Email" })).toBeFocused();
    expect(prelaunchHits(await f.innerText())).toEqual([]);

    const email = address("join-page");
    await fillAndSend(page, email);
    await expect(form(page).getByRole("status")).toHaveText(DONE);
    await expect.poll(() => signups(email).length).toBe(1);
    expect(signups(email)[0]).toMatchObject({ consent_text: CONSENT, source: "/join", business_type: "company" });
  });

  test("a runtime refusal is shown, not swallowed", async ({ page }) => {
    await page.route("**/public/sign-up", (r) =>
      r.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"off"}' }),
    );
    await page.goto("/join");
    await fillAndSend(page, "someone@example.co.uk");
    await expect(form(page).getByRole("alert")).toContainText("Sign-ups aren't open on this server yet");
    await expect(form(page).getByRole("status")).toHaveCount(0);
  });

  test("the form has no serious axe violations", async ({ page }) => {
    await page.goto("/join");
    await form(page).getByRole("button", { name: HEADING }).click(); // audit the error state too
    const { violations } = await new AxeBuilder({ page }).include("section[aria-labelledby]").analyze();
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
  });

  test("the privacy policy describes the list without launch wording", async ({ page }) => {
    await page.goto("/privacy#sign-up");
    const section = page.locator("#sign-up");
    await expect(section.getByRole("heading", { name: "The waiting list" })).toBeVisible();
    await expect(section).toContainText("to email you when your place on the waiting list comes up");
    await expect(section).toContainText("by the end of November 2027");
    expect(prelaunchHits(await page.locator("main").innerText())).toEqual([]);
  });
});

test.describe("public build (submission mode 0)", () => {
  test("the landing page keeps its own form; /join shows the neutral one", async ({ page }) => {
    await submissionMode(page, "0");
    await page.goto("/");
    await expect(page.getByRole("region", { name: "Hear when Accnomos opens" })).toBeVisible();
    await expect(form(page)).toHaveCount(0); // one form per page, not two

    await page.goto("/join");
    await expect(form(page)).toBeVisible();
    await expect(form(page).getByRole("checkbox", { name: CONSENT })).toBeVisible();
  });
});

test.describe("accountants on the landing page", () => {
  test("both ways to have the books reviewed, linked to Settings › Your accountant", async ({ page }) => {
    await page.goto("/");
    const section = page.locator("#accountants");
    const ways = section.getByRole("list", { name: "Two ways to have your books reviewed" });
    await expect(ways.getByRole("heading", { level: 3 })).toHaveText([
      "Invite your own accountant",
      "Or opt in to a review by Accnomos accountants",
    ]);
    await expect(ways).toContainText("They never submit anything to HMRC for you and never move money.");
    const settings = section.getByRole("link", { name: "Settings › Your accountant" });
    await expect(settings).toHaveAttribute("href", "/settings#settings-accountant");
    const href = (await settings.getAttribute("href"))!;
    await expect(section.getByRole("link", { name: "Accountant portal" })).toHaveAttribute("href", "/accountant");
    for (const q of ["Does my accountant need an account?", "Can an accountant review my books for me?"]) {
      await expect(page.locator("#faq summary", { hasText: q })).toHaveCount(1);
    }

    // The link opens the Your accountant tab for a signed-in owner.
    await signIn(page);
    await createBooksFolder(page);
    await page.goto(href);
    await expect(page.getByRole("heading", { level: 2, name: "Your accountant", exact: true })).toBeVisible();
    await expect(page.getByRole("form", { name: "Invite your accountant" })).toBeVisible();
  });
});
