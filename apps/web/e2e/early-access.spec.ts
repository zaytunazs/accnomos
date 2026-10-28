import { existsSync, readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { EARLY_ACCESS_FILE } from "./env.mjs";
import { expect, test } from "./fixtures";

/**
 * "Get 3 months free at launch" (src/components/early-access/EarlyAccessForm.tsx). The e2e build is a submission
 * build (NEXT_PUBLIC_SUBMISSION_MODE unset = 1); test-mode builds let a spec flip it per page through localStorage
 * (src/lib/submission-mode.ts). The runtime writes sign-ups to EARLY_ACCESS_FILE (playwright.config.ts).
 */
const HEADING = "Get 3 months free at launch";
const CONSENT = "Email me once Accnomos launches, with my 3 months free. I can unsubscribe any time.";

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

test.describe("public build (submission mode 0)", () => {
  test.use({ viewport: { width: 360, height: 780 } });

  test("signs up from the landing page at 360 px", async ({ page }) => {
    await submissionMode(page, "0");
    await page.goto("/");
    const form = page.getByRole("region", { name: HEADING });
    await expect(form).toBeVisible();
    // Fits a 360 px phone: no sideways scroll.
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);

    const consent = form.getByRole("checkbox", { name: CONSENT });
    await expect(consent).not.toBeChecked(); // never pre-ticked
    await expect(form.getByText(/Zaytuna Business Services Ltd keeps these details only/)).toBeVisible();
    await expect(form.getByRole("link", { name: "privacy policy" })).toHaveAttribute("href", "/privacy#early-access");

    // Nothing filled: each problem is named and focus goes to the first one.
    await form.getByRole("button", { name: "Join the early list" }).click();
    const email = form.getByRole("textbox", { name: "Email" });
    await expect(email).toBeFocused();
    await expect(email).toHaveAttribute("aria-invalid", "true");
    await expect(form.getByText("Enter an email address like name@example.co.uk")).toBeVisible();
    await expect(form.getByText("Choose the one that fits best")).toBeVisible();
    await expect(form.getByText("Tick the box so we can send you the launch email")).toBeVisible();

    const address = `early-${test.info().workerIndex}-${Date.now()}@example.co.uk`;
    await email.fill(address);
    await form.getByRole("textbox", { name: "Name (optional)" }).fill("Priya Shah");
    await form.getByRole("radio", { name: "Sole trader" }).check();
    await form.getByRole("textbox", { name: "How did you hear about us? (optional)" }).fill("A friend");
    // The consent box is still required.
    await form.getByRole("button", { name: "Join the early list" }).click();
    await expect(consent).toBeFocused();
    expect(signups(address)).toEqual([]);

    await consent.check();
    await form.getByRole("button", { name: "Join the early list" }).click();
    const done = form.getByRole("status");
    await expect(done).toHaveText("You're on the list — we'll email you once at launch");
    await expect(done).toBeFocused();

    await expect.poll(() => signups(address).length).toBe(1);
    const [rec] = signups(address);
    expect(rec).toMatchObject({
      name: "Priya Shah",
      business_type: "sole_trader",
      heard: "A friend",
      consent: true,
      consent_text: CONSENT,
      source: "/",
    });
  });

  test("the form has no serious axe violations", async ({ page }) => {
    await submissionMode(page, "0");
    await page.goto("/");
    await expect(page.getByRole("region", { name: HEADING })).toBeVisible();
    await page.getByRole("button", { name: "Join the early list" }).click(); // audit the error state too
    const { violations } = await new AxeBuilder({ page }).include("section[aria-labelledby]").analyze();
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
  });

  test("a runtime refusal is shown, not swallowed", async ({ page }) => {
    await submissionMode(page, "0");
    await page.route("**/public/early-access", (r) =>
      r.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"off"}' }),
    );
    await page.goto("/");
    const form = page.getByRole("region", { name: HEADING });
    await form.getByRole("textbox", { name: "Email" }).fill("someone@example.co.uk");
    await form.getByRole("radio", { name: "Limited company" }).check();
    await form.getByRole("checkbox", { name: CONSENT }).check();
    await form.getByRole("button", { name: "Join the early list" }).click();
    await expect(form.getByRole("alert")).toContainText("Sign-ups aren't open on this server yet");
    await expect(form.getByRole("status")).toHaveCount(0);
  });
});

test.describe("submission build (the default)", () => {
  test("renders nothing on the landing page", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("AI proposes.You approve.Code calculates.");
    await expect(page.getByRole("heading", { name: HEADING })).toHaveCount(0);
    await expect(page.getByText(CONSENT)).toHaveCount(0);
  });

  test("renders nothing when the mode is set to 1 explicitly", async ({ page }) => {
    await submissionMode(page, "1");
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("AI proposes.You approve.Code calculates.");
    await expect(page.getByRole("heading", { name: HEADING })).toHaveCount(0);
  });
});
