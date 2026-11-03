import AxeBuilder from "@axe-core/playwright";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * Budget › Categories and rules (components/personal/HouseholdRules.tsx), the same things the Android app's Categories
 * and rules screen does: rename and add categories, add a rule and move it up (first match wins), put one bank line in a
 * category by hand and hand it back to the rules. Personal books, a statement imported first.
 */

// SAMPLE — FICTIONAL ACCOUNT
const STATEMENT = `Date,Description,Amount,Balance
01/10/2026,SALARY ACME LTD,2500.00,0
02/10/2026,RENT LANDLORD,-1200.00,0
05/10/2026,TESCO STORES 1234,-45.10,0
06/10/2026,MYSTERY SHOP,-9.99,0
`;

test("household categories, rule order and a line by hand", async ({ page, runtime }) => {
  await runtime.api("PUT", "/profile", { name: "Sam at home", kind: "personal", settings: {} });
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles({ name: "home.csv", mimeType: "text/csv", buffer: Buffer.from(STATEMENT) });
  await expect(page.getByRole("status").filter({ hasText: "home.csv" })).toContainText("4 new lines");

  await page.goto("/personal");
  const section = page.getByRole("region", { name: "Categories and rules" });
  await expect(section.getByRole("tab", { name: /Categories/ })).toHaveAttribute("aria-selected", "true");

  // Rename a category and add one.
  await section.getByRole("textbox", { name: "Name of the category Eating out" }).fill("Takeaways and cafés");
  await section.getByRole("button", { name: "Save names" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Category names saved" })).toBeVisible();
  await expect(section.getByRole("textbox", { name: "Name of the category Takeaways and cafés" })).toBeVisible();
  await section.getByLabel("New category").fill("Pets");
  await section.getByRole("button", { name: "Add category" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Added Pets" })).toBeVisible();
  // Removing asks first, inline.
  await section.getByRole("button", { name: "Remove category Pets" }).click();
  await section.getByRole("group", { name: "Remove Pets?" }).getByRole("button", { name: "Keep it" }).click();
  await expect(section.getByRole("textbox", { name: "Name of the category Pets" })).toBeVisible();

  // Rules: two, then move the second up.
  await section.getByRole("tab", { name: /Rules/ }).click();
  for (const [value, cat] of [
    ["tesco", "Groceries"],
    ["landlord", "Housing"],
  ]) {
    await section.getByLabel("When the payment contains").fill(value);
    await section.getByLabel("Put it in").selectOption({ label: cat });
    await section.getByRole("button", { name: "Add rule" }).click();
    await expect(page.getByRole("status").filter({ hasText: `"${value}"` })).toBeVisible();
  }
  const order = section.getByRole("list", { name: "Rules, first match wins" }).getByRole("listitem");
  await expect(order.first()).toContainText("tesco");
  await section.getByRole("button", { name: "Move rule landlord up" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Moved the rule for landlord up" })).toBeVisible();
  await expect(order.first()).toContainText("landlord");

  // Lines: MYSTERY SHOP has no category; put it in Health by hand, then hand it back to the rules.
  await section.getByRole("tab", { name: /Lines/ }).click();
  const lines = section.getByRole("list", { name: "Bank lines" });
  await expect(lines).toContainText("MYSTERY SHOP");
  await expect(lines).not.toContainText("TESCO");
  await section.getByLabel("Only lines with no category").uncheck();
  await lines.getByRole("combobox", { name: /Category for MYSTERY SHOP/ }).selectOption({ label: "Health" });
  await expect(page.getByRole("status").filter({ hasText: "Put MYSTERY SHOP in Health" })).toBeVisible();
  const mystery = lines.getByRole("listitem").filter({ hasText: "MYSTERY SHOP" });
  await expect(mystery).toContainText("set by you");
  await mystery.getByRole("button", { name: "Use the rules for MYSTERY SHOP" }).click();
  await expect(page.getByRole("status").filter({ hasText: "MYSTERY SHOP goes back to the rules" })).toBeVisible();
  await expect(mystery).toContainText("no category yet");

  const axe = await new AxeBuilder({ page }).include("#categories-rules").analyze();
  expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
});

test("Bank's 'Lines with no category' opens Budget on the lines", async ({ page, runtime }) => {
  await runtime.api("PUT", "/profile", { name: "Sam at home", kind: "personal", settings: {} });
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles({ name: "home.csv", mimeType: "text/csv", buffer: Buffer.from(STATEMENT) });
  await expect(page.getByRole("status").filter({ hasText: "home.csv" })).toContainText("4 new lines");
  await page.getByRole("link", { name: "Budget › Categories and rules" }).click();
  await expect(page).toHaveURL(/\/personal\/?#household-lines$/);
  const section = page.getByRole("region", { name: "Categories and rules" });
  await expect(section.getByRole("tab", { name: /Lines/ })).toHaveAttribute("aria-selected", "true");
  await expect(section.getByRole("list", { name: "Bank lines" })).toContainText("MYSTERY SHOP");
});
