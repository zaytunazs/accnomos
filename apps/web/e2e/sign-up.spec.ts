import { existsSync, readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { prelaunchHits } from "../scripts/prelaunch-words.mjs";
import { EARLY_ACCESS_FILE } from "./env.mjs";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * "Get 3 months free" (src/components/sign-up/JoinForm.tsx, POST /public/sign-up): the neutral sign-up the submission
 * build shows on the landing page (hero link, a section near the end, the pricing band, the FAQ) and on /join, the page
 * the social posts link to. Same list and file as the pre-launch form (early-access.spec.ts); its consent wording
 * names no launch. Test builds flip the mode per page through localStorage (src/lib/submission-mode.ts).
 */
const HEADING = "Get 3 months free";
const CONSENT = "Email me to set up my 3 months free of Accnomos. I can unsubscribe any time.";
const DONE = "Thanks — we'll email you to set up your 3 months free";

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

  test("the hero's Get 3 months free leads to the form, which signs up at 360 px", async ({ page }) => {
    await page.goto("/");
    const hero = page.getByRole("region", { name: "Bookkeeping you only have to check" });
    await expect(hero.getByRole("link", { name: "Try the demo", exact: true })).toBeVisible();
    const cta = hero.getByRole("link", { name: HEADING, exact: true });
    await expect(cta).toHaveAttribute("href", "#join");
    await cta.click();
    const f = form(page);
    await expect(f).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);

    await expect(f).toContainText("Leave your email and we will set you up with 3 months free.");
    const consent = f.getByRole("checkbox", { name: CONSENT });
    await expect(consent).not.toBeChecked(); // never pre-ticked
    await expect(f.getByText(/Zaytuna Business Services Ltd keeps these details only to email you/)).toBeVisible();
    await expect(f.getByRole("link", { name: "privacy policy" })).toHaveAttribute("href", "/privacy#sign-up");
    // No launch, beta or waiting-list wording anywhere in the form, its errors included.
    await f.getByRole("button", { name: HEADING }).click();
    await expect(f.getByRole("textbox", { name: "Email" })).toBeFocused();
    await expect(f.getByText("Tick the box so we can email you")).toBeVisible();
    expect(prelaunchHits(await f.innerText())).toEqual([]);

    const email = address("join-home");
    await f.getByRole("textbox", { name: "Name (optional)" }).fill("Sam Okoro");
    await f.getByRole("textbox", { name: "How did you hear about us? (optional)" }).fill("YouTube");
    await fillAndSend(page, email);
    const done = f.getByRole("status");
    await expect(done).toHaveText(DONE);
    await expect(done).toBeFocused();

    await expect.poll(() => signups(email).length).toBe(1);
    expect(signups(email)[0]).toMatchObject({
      name: "Sam Okoro",
      business_type: "company",
      heard: "YouTube",
      consent: true,
      consent_text: CONSENT,
      source: "/",
    });
  });

  test("/join: a short page with the form, for the social posts", async ({ page }) => {
    await page.goto("/join");
    await expect(page).toHaveTitle("Get 3 months free · Accnomos");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Accnomos: bookkeeping you only have to check");
    await expect(page.getByRole("main").getByRole("link", { name: "Try the demo" })).toHaveAttribute("href", "/judges");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);

    const email = address("join-page");
    await fillAndSend(page, email);
    await expect(form(page).getByRole("status")).toHaveText(DONE);
    await expect.poll(() => signups(email).length).toBe(1);
    expect(signups(email)[0]).toMatchObject({ consent_text: CONSENT, source: "/join", business_type: "company" });
  });

  test("pricing, the FAQ and the footer point to it", async ({ page }) => {
    await page.goto("/");
    const pricing = page.locator("#pricing");
    await expect(pricing).toContainText("Leave your email and we will set you up with 3 months free.");
    await expect(pricing.getByRole("link", { name: HEADING, exact: true })).toHaveAttribute("href", "#join");
    await page.getByText("How do I get 3 months free?").click();
    await expect(page.getByText(/at accnomos\.com\/join\) and we will set you up/)).toBeVisible();
    await expect(page.getByRole("contentinfo").getByRole("link", { name: HEADING })).toHaveAttribute("href", "/join");
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
    await expect(section.getByRole("heading", { name: "The 3 months free list" })).toBeVisible();
    await expect(section).toContainText("to email you to set up your 3 months free");
    await expect(section).toContainText("by the end of November 2027");
    expect(prelaunchHits(await page.locator("main").innerText())).toEqual([]);
  });
});

test.describe("public build (submission mode 0)", () => {
  test("the landing page keeps its own form; /join shows the neutral one", async ({ page }) => {
    await submissionMode(page, "0");
    await page.goto("/");
    await expect(page.getByRole("region", { name: "Get 3 months free at launch" })).toBeVisible();
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
