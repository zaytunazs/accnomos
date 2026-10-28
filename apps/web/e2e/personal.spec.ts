import AxeBuilder from "@axe-core/playwright";
import { createBooksFolder, expect, settingsTab, signIn, test } from "./fixtures";

// SAMPLE — FICTIONAL ACCOUNT: four Netflix payments, rent, a supermarket shop and a payment no rule knows.
const STATEMENT = `Date,Description,Amount,Balance
03/07/2026,NETFLIX.COM 11111 ON 03 JUL,-10.99,0
03/08/2026,NETFLIX.COM 22222 ON 03 AUG,-10.99,0
03/09/2026,NETFLIX.COM 33333 ON 03 SEP,-10.99,0
03/10/2026,NETFLIX.COM 44444 ON 03 OCT,-10.99,0
01/10/2026,SALARY ACME LTD,2500.00,0
02/10/2026,RENT LANDLORD,-1200.00,0
05/10/2026,TESCO STORES 1234,-45.10,0
06/10/2026,MYSTERY SHOP,-9.99,0
`;

test("off by default; Settings switch adds Personal; budgets, bills and goals work from a statement", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/personal");
  await expect(page.getByText("Personal finances are off.")).toBeVisible();
  // Signed in, the main navigation is the menu bar, where Personal is a group (lib/nav.ts).
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("button", { name: "Personal" })).toHaveCount(0);

  await page.goto("/settings");
  const panel = await settingsTab(page, "Business");
  await panel.getByRole("checkbox", { name: "Show personal finances" }).check();
  const personalMenu = page.getByRole("navigation", { name: "Main" }).getByRole("button", { name: "Personal" });
  await expect(personalMenu).toBeVisible();
  await personalMenu.click();
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Personal overview" })).toBeVisible();
  await personalMenu.click();

  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles({ name: "personal.csv", mimeType: "text/csv", buffer: Buffer.from(STATEMENT) });
  await expect(page.getByRole("status").filter({ hasText: "personal.csv" })).toContainText("8 new lines");

  await page.goto("/personal");
  const summary = page.getByRole("region", { name: /^Summary for October 2026/ });
  await expect(summary.getByText("£2500.00")).toBeVisible();
  await expect(summary).toContainText("did not match a rule"); // nothing sorted yet: all 5 payments are under Other

  // rules: common merchants, then one of our own
  await page.getByRole("button", { name: "Add common UK merchants" }).click();
  await expect(page.getByRole("status").filter({ hasText: "common UK merchants" })).toBeVisible();
  const sorting = page.getByRole("region", { name: "Sorting payments" });
  await sorting.getByLabel("When the payment contains").fill("rent landlord");
  await sorting.getByLabel("Put it in").selectOption({ label: "Housing" });
  await sorting.getByRole("button", { name: "Add rule" }).click();
  await expect(sorting.getByText("rent landlord")).toBeVisible();

  // budgets: Groceries £80, spent £45.10 -> 56%
  const budgets = page.getByRole("region", { name: "Budgets" });
  await budgets.getByLabel("Groceries monthly budget in pounds").fill("80");
  await budgets.getByLabel("Housing monthly budget in pounds").fill("1000");
  await budgets.getByRole("button", { name: "Save budgets" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Budgets saved" })).toBeVisible();
  await expect(budgets.getByRole("progressbar", { name: "Groceries budget used" })).toHaveAttribute("aria-valuenow", "56");
  await expect(budgets).toContainText("£34.90 left (56% used)");
  await expect(budgets.getByRole("progressbar", { name: "Housing budget used" })).toHaveAttribute("aria-valuenow", "100");
  await expect(budgets).toContainText("£200.00 over budget (120%)");

  // bills: Netflix found by code, labelled an estimate
  const bills = page.getByRole("region", { name: "Bills and subscriptions" });
  await expect(bills).toContainText("£10.99 a month");
  await expect(bills).toContainText("Next due around 3 Nov 2026");
  await expect(bills).toContainText("Estimate");

  // goals: £1,200 by 27 Oct 2027 = 12 months -> £100.00 a month
  const goals = page.getByRole("region", { name: "Savings goals" });
  await goals.getByLabel("Goal name").fill("Holiday");
  await goals.getByLabel("Target £").fill("1200");
  await goals.getByLabel("Target date").fill("2027-10-27");
  await goals.getByRole("button", { name: "Add goal" }).click();
  await expect(goals).toContainText("Estimate: put aside £100.00 a month for 12 months");
  await goals.getByLabel("Holiday saved so far in pounds").fill("300");
  await goals.getByRole("button", { name: "Update Holiday" }).click();
  await expect(goals).toContainText("Estimate: put aside £75.00 a month for 12 months");
  await expect(goals.getByRole("progressbar", { name: "Holiday saved" })).toHaveAttribute("aria-valuenow", "25");
  await goals.getByRole("button", { name: "Delete goal Holiday" }).click();
  await expect(goals).toContainText("No goals yet.");
});

test.describe("360 px wide", () => {
  test.use({ viewport: { width: 360, height: 740 } });

  test("Personal has no sideways scroll and no serious axe violations", async ({ page, runtime }) => {
    await signIn(page);
    await page.addInitScript(() => window.localStorage.setItem("accnomos.personal.show", "1"));
    await createBooksFolder(page);
    await runtime.api("POST", "/personal/goals", { name: "A very long goal name to see how it wraps on a small phone", target_pence: 250000, target_date: "2027-06-01" });
    await page.goto("/bank");
    await page.locator('input[type="file"]').setInputFiles({ name: "personal.csv", mimeType: "text/csv", buffer: Buffer.from(STATEMENT) });
    await expect(page.getByRole("status").filter({ hasText: "personal.csv" })).toContainText("8 new lines");

    await page.goto("/personal");
    await expect(page.getByRole("region", { name: "Savings goals" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Bills and subscriptions" })).toContainText("NETFLIX.COM");
    const { scroll, width } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: window.innerWidth }));
    expect(scroll).toBeLessThanOrEqual(width);
    const { violations } = await new AxeBuilder({ page }).analyze();
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
});
