import AxeBuilder from "@axe-core/playwright";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

// Goals (components/goals, GET/POST/PATCH/DELETE /books/goals). The test runtime's today is 27 Oct 2026.

test("add a savings goal, see it on Goals and Home, record money put aside, delete it", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/goals");
  await expect(page.getByRole("heading", { name: "Goals & progress", level: 1 })).toBeVisible();
  await expect(page.getByText("No goals yet")).toBeVisible();
  await page.getByRole("button", { name: "+ Add a goal" }).click();

  const form = page.getByRole("form", { name: "Add a goal" });
  await form.getByRole("radio", { name: /Save for something/ }).check();
  await form.getByLabel("Name", { exact: true }).fill("School fee");
  await form.getByLabel("Amount to save (£)").fill("1,000");
  await form.getByLabel("By", { exact: true }).fill("2027-08-31");
  await form.getByLabel("Already put aside (£, optional)").fill("100");
  // the runtime's own refusal shows under the form
  await form.getByLabel("Starting", { exact: true }).fill("2027-09-30");
  await form.getByRole("button", { name: "Add goal" }).click();
  await expect(form.getByRole("alert")).toContainText("end date is before the start date");
  await form.getByLabel("Starting", { exact: true }).fill("2026-10-27");
  await form.getByRole("button", { name: "Add goal" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Goal added: School fee." })).toBeVisible();

  const card = page.getByRole("article", { name: "School fee" });
  await expect(card).toContainText("£100");
  await expect(card).toContainText("£1,000.00 target");
  await expect(card.getByRole("progressbar", { name: "School fee: 10% of target" })).toHaveAttribute("aria-valuenow", "10");
  await expect(page.locator("[data-goals-note]")).toContainText("What your goals are telling you");

  await card.getByRole("button", { name: "View details" }).click();
  const details = page.getByRole("region", { name: "School fee details" });
  await details.getByLabel("Record money put aside (£)").fill("50");
  await details.getByRole("button", { name: "Record" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Recorded £50.00 put aside for School fee." })).toBeVisible();
  await expect(page.getByRole("article", { name: "School fee" })).toContainText("£150");

  // Home shows it in Goals & progress
  await page.goto("/");
  const home = page.locator("[data-home-goals]");
  await expect(home.getByRole("heading", { name: "Goals & progress" })).toBeVisible();
  await expect(home.getByRole("article", { name: "School fee" })).toContainText("£150");
  await home.getByRole("link", { name: /View details/ }).click();
  await expect(page).toHaveURL(/\/goals#goal-/);
  const opened = page.getByRole("region", { name: "School fee details" });
  await expect(opened).toBeVisible();

  await opened.getByRole("button", { name: "Delete" }).click();
  await opened.getByRole("button", { name: "Yes, delete" }).click();
  await expect(page.getByText("No goals yet")).toBeVisible();
});

test("signed out, Goals and the sample Home show fictional sample goals, labelled so", async ({ page }) => {
  await page.goto("/goals");
  await expect(page.getByText("Sample — fictional figures.").first()).toBeVisible();
  await expect(page.getByRole("article", { name: "October sales" })).toContainText("At risk");
  await expect(page.getByRole("button", { name: "+ Add a goal" })).toHaveCount(0);
  await page.goto("/try");
  const home = page.locator("[data-home-goals]");
  await expect(home).toContainText("Sample — fictional figures.");
  await expect(home.getByRole("article")).toHaveCount(3);
});

test.describe("390 px wide", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("Goals has no sideways scroll and no serious axe violations", async ({ page, runtime }) => {
    await signIn(page);
    await createBooksFolder(page);
    await runtime.api("POST", "/books/goals", {
      name: "Keep groceries under a very long limit name that wraps on a phone",
      kind: "spend_cap",
      start: "2026-10-01",
      end: "2026-10-31",
      target_pence: 40000,
      focus: "Groceries",
    });
    await page.goto("/goals");
    await expect(page.getByRole("article")).toHaveCount(1);
    const { scroll, width } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: window.innerWidth }));
    expect(scroll).toBeLessThanOrEqual(width);
    const { violations } = await new AxeBuilder({ page }).analyze();
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
});
