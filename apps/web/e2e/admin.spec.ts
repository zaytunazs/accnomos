import { expect, signIn, test } from "./fixtures";

/** The admin area in test mode: lib/billing-fake.ts plays the runtime, and `accnomos.test.admin` makes this account an administrator. */
test("a non-administrator sees nothing of /admin", async ({ page }) => {
  await signIn(page);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Not available" })).toBeVisible();
  await page.goto("/");
  await page.getByRole("button", { name: /^Account/ }).first().click();
  await expect(page.getByRole("menuitem", { name: "Admin" })).toHaveCount(0);
});

test.describe("administrator", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
    await page.addInitScript(() => window.localStorage.setItem("accnomos.test.admin", "1"));
  });

  test("the menu shows Admin and the dashboard has the numbers and the sign-ups chart", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /^Account/ }).first().click();
    await page.getByRole("menuitem", { name: "Admin" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Admin" })).toBeVisible();
    await expect(page.locator('[data-stat="MRR"]')).toContainText("£"); // 6×10 + 11×20 + 3×50 = £430
    await expect(page.locator('[data-stat="MRR"]')).toContainText("£430");
    await expect(page.locator('[data-stat="Trialing"]')).toContainText("14");
    await expect(page.getByRole("img", { name: "Sign-ups per day" })).toBeVisible();
  });

  test("Users: search and filter, open a user, change the plan after confirming", async ({ page }) => {
    await page.goto("/admin/users");
    const rows = page.locator("[data-users-table] tbody tr");
    await expect(rows).toHaveCount(3);
    await page.getByLabel("Search by email or name").fill("raj");
    await expect(rows).toHaveCount(1);
    await page.getByLabel("Search by email or name").fill("");
    await page.getByLabel("Status").selectOption("past_due");
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("lee@harthillbakery.example");
    await page.getByLabel("Status").selectOption("");

    await page.getByRole("link", { name: "amy@bramblejoinery.example" }).click();
    await expect(page.getByRole("heading", { name: "amy@bramblejoinery.example" })).toBeVisible();
    await expect(page.getByText("Free trial", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Usage history" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Stripe" })).toBeVisible();

    await page.getByLabel("Change plan").selectOption("ultimate");
    await page.getByRole("button", { name: "Change", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Change plan" });
    await expect(dialog).toContainText("Ultimate");
    await dialog.getByRole("button", { name: "Cancel" }).click(); // nothing happens without Confirm
    await expect(page.getByText("Comprehensive").first()).toBeVisible();
    await page.getByRole("button", { name: "Change", exact: true }).click();
    await page.getByRole("dialog", { name: "Change plan" }).getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
    await expect(page.locator("dl").first()).toContainText("Ultimate");
    await expect(page.getByRole("heading", { name: "Audit" }).locator("..")).toContainText("update");

    await page.getByRole("button", { name: "Grant top-up (100 documents)" }).click();
    await page.getByRole("dialog", { name: "Grant top-up" }).getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Done." })).toBeVisible();
  });

  test("Promo codes: the 12 months free preset creates a code", async ({ page }) => {
    await page.goto("/admin/codes");
    await expect(page.locator("[data-codes-table]")).toContainText("WELCOME20");
    await page.getByRole("button", { name: "Preset: 12 months free" }).click();
    const form = page.getByRole("dialog", { name: "New promo code" });
    await expect(form.getByLabel("Code")).toHaveValue("YEARFREE");
    await form.getByLabel("Code").fill("FREEYEAR2");
    await form.getByRole("button", { name: "Review" }).click();
    const confirm = page.getByRole("dialog", { name: "Create code" });
    await expect(confirm).toContainText("12 months free");
    await confirm.getByRole("button", { name: "Create" }).click();
    await expect(page.locator("[data-codes-table]")).toContainText("FREEYEAR2");
  });

  test("Plans, Analytics, Bug reports and the Audit log render", async ({ page }) => {
    await page.goto("/admin/plans");
    await expect(page.locator('[data-plan-edit="starter"]')).toContainText("£10");
    await expect(page.getByText(/creates a new Stripe price/).first()).toBeVisible();
    await page.goto("/admin/analytics");
    await expect(page.getByRole("img", { name: "Daily active accounts" })).toBeVisible();
    await expect(page.getByText("Documents scanned")).toBeVisible();
    await expect(page.getByText("24.4% of trials")).toBeVisible();
    await expect(page.getByText("POST /books/scan")).toBeVisible();
    await page.goto("/admin/bugs");
    await expect(page.locator("[data-bugs-table] tbody tr")).toHaveCount(2);
    await page.getByRole("tab", { name: "Triaged" }).click();
    await expect(page.locator("[data-bugs-table] tbody tr")).toHaveCount(1);
    await page.getByRole("button", { name: /Receipt would not upload/ }).click();
    await page.getByRole("button", { name: "Show screenshot" }).click();
    await expect(page.getByRole("img", { name: "Screenshot sent with the report" })).toBeVisible();
    await expect.poll(async () => page.evaluate(() => (JSON.parse(window.localStorage.getItem("accnomos.test.billing.calls") ?? "[]") as { path: string }[]).some((c) => c.path === "/admin/bug-reports/b-2/screenshot"))).toBe(true);
    await page.getByRole("region", { name: /Report from/ }).getByLabel("Status").selectOption("fixed");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
    await page.goto("/admin/audit");
    await expect(page.getByText("grant_topup")).toBeVisible();
  });

  test("usable on a phone: the users table scrolls inside its card", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto("/admin/users");
    await expect(page.locator("[data-users-table] tbody tr").first()).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    expect(overflow).toBe(false);
  });
});
