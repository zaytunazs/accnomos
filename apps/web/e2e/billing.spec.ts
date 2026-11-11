import type { Page } from "@playwright/test";
import { RUNTIME_URL } from "./env.mjs";
import { expect, settingsTab, signIn, test } from "./fixtures";

/**
 * Plans and billing in test mode: the billing endpoints answer from lib/billing-fake.ts in the browser, so none of this
 * needs the backend. Calls the page made are recorded under accnomos.test.billing.calls.
 */
const calls = (page: Page) =>
  page.evaluate(() => JSON.parse(window.localStorage.getItem("accnomos.test.billing.calls") ?? "[]") as { path: string; method: string; body?: Record<string, unknown> }[]);

test("/pricing: three plans, VAT, the toggle, the limits table and the trial call to action", async ({ page }) => {
  await page.goto("/pricing");
  await expect(page.getByRole("heading", { level: 1, name: "Pricing" })).toBeVisible();
  const cards = page.locator("[data-plan-card]");
  await expect(cards).toHaveCount(3);
  await expect(page.locator('[data-plan-card="starter"]')).toContainText("£10");
  await expect(page.locator('[data-plan-card="starter"]')).toContainText("£12 with VAT");
  await expect(page.locator('[data-plan-card="comprehensive"]')).toContainText("£20");
  await expect(page.locator('[data-plan-card="ultimate"]')).toContainText("£50");
  await expect(page.locator('[data-plan-card="ultimate"]')).toContainText("£60 with VAT");

  await page.getByRole("radio", { name: /Annual · 2 months free/ }).click();
  await expect(page.locator('[data-plan-card="starter"]')).toContainText("£100");
  await expect(page.locator('[data-plan-card="ultimate"]')).toContainText("£500");
  await expect(page.locator('[data-plan-card="ultimate"]')).toContainText("£100 saved");

  const table = page.locator("[data-limits-table]");
  const row = (name: string) => table.getByRole("row").filter({ has: page.getByRole("rowheader", { name }) });
  await expect(row("AI-read documents")).toContainText("50");
  await expect(row("AI-read documents")).toContainText("1,500");
  await expect(row("Live bank feeds")).toContainText("Unlimited");
  await expect(row("Support")).toContainText("Priority email");

  await expect(page.getByRole("link", { name: "Start your 3-month free trial — no card needed" }).first()).toHaveAttribute("href", /\/connect/);
  await expect(page.getByText(/Bring your own AI/)).toBeVisible();
  await expect(page.getByText(/100 extra AI-read documents cost £3/)).toBeVisible();
  await expect(page.locator("[data-market-line]")).toContainText("£14 to £56");
});

test("the home page and menu lead to pricing and no longer mention a waiting list", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Pricing" }).first()).toHaveAttribute("href", "/pricing");
  await expect(page.getByText(/waiting list/i)).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Start your free trial" }).first()).toBeVisible();
});

test.describe("signed in", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test("Plan & billing: plan, status, trial date, meters, checkout, portal, top-up and a code", async ({ page }) => {
    await page.goto("/settings");
    const panel = await settingsTab(page, "Plan & billing");
    await expect(panel.getByText("Comprehensive").first()).toBeVisible();
    await expect(panel.getByText("Free trial", { exact: true })).toBeVisible();
    await expect(panel.getByText("Free trial ends")).toBeVisible();
    await expect(panel.getByRole("status").filter({ hasText: "Your free trial ends" })).toHaveCount(0); // not in the last 14 days
    await expect(panel.getByRole("meter", { name: "AI-read documents" })).toHaveAttribute("aria-valuenow", "12");
    await expect(panel.locator('[data-meter-value="docs"]')).toHaveText("12 of 300");
    await expect(panel.getByText(/Bring your own AI/)).toBeVisible();

    await panel.getByRole("radio", { name: /Ultimate/ }).click();
    await panel.getByRole("radio", { name: /Yearly/ }).click();
    await panel.getByRole("button", { name: "Upgrade" }).click();
    await expect.poll(async () => (await calls(page)).find((c) => c.path === "/billing/checkout")?.body).toEqual({ plan_code: "ultimate", interval: "year" });

    await page.goto("/settings#plan-billing");
    await panel.getByRole("button", { name: "Manage card & invoices" }).click();
    await expect.poll(async () => (await calls(page)).some((c) => c.path === "/billing/portal")).toBe(true);

    await page.goto("/settings#plan-billing");
    await page.getByRole("button", { name: "Buy 100 documents" }).click();
    await expect.poll(async () => (await calls(page)).some((c) => c.path === "/billing/topup")).toBe(true);

    await page.goto("/settings#plan-billing");
    await page.getByLabel("Redeem a code").fill("nonsense");
    await page.getByRole("button", { name: "Redeem" }).click();
    await expect(page.locator("[data-plan-billing]").getByRole("alert")).toContainText("not valid");
    await page.getByLabel("Redeem a code").fill("yearfree");
    await page.getByRole("button", { name: "Redeem" }).click();
    await expect(page.getByRole("status").filter({ hasText: "12 months free applied." })).toBeVisible();
    await expect(page.getByText("Free access", { exact: true })).toBeVisible();
  });

  test("the reminder banner shows in the last 14 days of the trial", async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem("accnomos.test.billing", JSON.stringify({ account: { trial_ends_at: "2026-10-30T00:00:00Z" } })));
    await page.goto("/settings#plan-billing");
    await expect(page.getByRole("status").filter({ hasText: "Your free trial ends in 3 days" })).toBeVisible();
  });

  test("an HTTP 402 plan_limit from the runtime opens one friendly dialog with top-up and upgrade", async ({ page }) => {
    await page.route(`${RUNTIME_URL}/books/proposals*`, (route) =>
      route.fulfill({ status: 402, contentType: "application/json", body: JSON.stringify({ code: "plan_limit", limit: "docs", message: "50 of 50 used" }) }),
    );
    await page.goto("/review");
    const dialog = page.getByRole("dialog", { name: "You have reached your plan's limit" });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("AI-read documents");
    await expect(dialog).toContainText("approve, edit and export");
    await expect(dialog.getByRole("button", { name: "Buy 100 documents for £3" })).toBeVisible();
    await expect(dialog.getByRole("link", { name: "Upgrade or change plan" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  });

  test("Settings › Privacy: the analytics opt-out is kept and sent to the account; no events after it", async ({ page }) => {
    await page.goto("/settings");
    const panel = await settingsTab(page, "Privacy");
    const toggle = panel.getByRole("switch", { name: "Do not collect usage analytics" });
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await expect.poll(async () => (await calls(page)).find((c) => c.method === "PATCH" && c.path === "/account")?.body).toEqual({ analytics_opt_out: true });
    await page.reload();
    await settingsTab(page, "Privacy");
    await expect(page.getByRole("switch", { name: "Do not collect usage analytics" })).toHaveAttribute("aria-checked", "true");
    await page.evaluate(() => window.localStorage.removeItem("accnomos.test.billing.calls"));
    await page.goto("/review");
    await page.waitForTimeout(6000);
    expect((await calls(page)).filter((c) => c.path === "/events")).toEqual([]);
  });

  test("first-party page views are batched to /events", async ({ page }) => {
    await page.goto("/review");
    await expect.poll(async () => (await calls(page)).filter((c) => c.path === "/events").length, { timeout: 15_000 }).toBeGreaterThan(0);
    const events = (await calls(page)).filter((c) => c.path === "/events").flatMap((c) => (c.body as { events: { name: string; props: { page?: string }; app: string }[] }).events);
    expect(events.some((e) => e.name === "page_view" && e.props.page === "/review" && e.app === "web")).toBe(true);
  });

  test("Help › Report a problem sends the message with page, version and browser", async ({ page }) => {
    await page.goto("/help");
    await page.getByRole("main").getByRole("button", { name: "Report a problem" }).click();
    const dialog = page.getByRole("dialog", { name: "Report a problem" });
    await dialog.getByLabel("What went wrong?").fill("The VAT page shows last quarter first.");
    await dialog.getByRole("button", { name: "Send report" }).click();
    await expect(dialog).toContainText("Thank you");
    const sent = (await calls(page)).find((c) => c.path === "/bug-reports");
    expect(sent?.body).toMatchObject({ message: "The VAT page shows last quarter first.", page: "/help", app: "web" });
    expect(typeof sent?.body?.version).toBe("string");
    expect(typeof sent?.body?.ua).toBe("string");
  });

  test("the account menu shows Admin only to an administrator", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /^Account/ }).first().click();
    await expect(page.getByRole("menuitem", { name: "Plan & billing" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Admin" })).toHaveCount(0);
  });
});
