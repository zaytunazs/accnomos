import AxeBuilder from "@axe-core/playwright";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * Home for a household (personal books; src/components/home/household/*): its month against last month, budgets,
 * regular bills, goals and where the money went, all from the imported statements. No business wording.
 */

// SAMPLE — FICTIONAL ACCOUNT. October (today is 27 Oct 2026) against September.
const STATEMENT = `Date,Description,Amount,Balance
03/07/2026,NETFLIX.COM 11111 ON 03 JUL,-10.99,0
03/08/2026,NETFLIX.COM 22222 ON 03 AUG,-10.99,0
01/09/2026,SALARY ACME LTD,2400.00,0
03/09/2026,NETFLIX.COM 33333 ON 03 SEP,-10.99,0
10/09/2026,TESCO STORES 1111,-60.00,0
03/10/2026,NETFLIX.COM 44444 ON 03 OCT,-10.99,0
01/10/2026,SALARY ACME LTD,2500.00,0
02/10/2026,RENT LANDLORD,-1200.00,0
05/10/2026,TESCO STORES 1234,-95.10,0
06/10/2026,MYSTERY SHOP,-9.99,0
`;

const PERSONAL = { name: "Sam at home", kind: "personal", settings: {} };

test("a household's Home: its month, budgets, bills and goals, never VAT or turnover", async ({ page, runtime }) => {
  await runtime.api("PUT", "/profile", PERSONAL);
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles({ name: "home.csv", mimeType: "text/csv", buffer: Buffer.from(STATEMENT) });
  await expect(page.getByRole("status").filter({ hasText: "home.csv" })).toContainText("10 new lines");
  await runtime.api("POST", "/personal/rules/starter");
  await runtime.api("POST", "/personal/rules", { match: { op: "contains", value: "rent landlord" }, category_id: "housing" });
  await runtime.api("PUT", "/personal/budgets", { budgets: { groceries: 8000, housing: 130000 } });

  await page.goto("/");
  const main = page.getByRole("main");
  const month = page.getByRole("region", { name: /^This month/ });
  await expect(month).toContainText("October 2026 so far");
  await expect(month.getByRole("definition").first()).toHaveText("£2,500");
  await expect(month).toContainText("£100 more than last month"); // £2,500 in against £2,400
  await expect(month).toContainText("Left over");

  const tiles = page.getByRole("region", { name: "What needs attention" });
  await expect(tiles.getByRole("link", { name: /Receipts to review/ })).toBeVisible();
  await expect(tiles.getByRole("link", { name: /Spending with no category/ })).toContainText("1");
  await expect(tiles.getByRole("link", { name: /Budgets/ })).toContainText("1 over"); // groceries £95.10 of £80
  await expect(tiles.getByRole("link", { name: /Next regular bill|Regular bills/ })).toBeVisible();

  const budgets = page.getByRole("region", { name: "Budgets this month" });
  await expect(budgets.getByRole("listitem").first()).toContainText("Groceries");
  await expect(budgets.getByRole("progressbar", { name: /Groceries/ })).toHaveAttribute("aria-valuenow", "100");
  await expect(budgets).toContainText("£15 over");

  await expect(page.getByRole("region", { name: "Bills and subscriptions due" })).toContainText("NETFLIX");
  await expect(main.getByRole("heading", { name: "Goals & progress" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Where the money went" })).toContainText("Housing");

  await expect(main.getByRole("heading", { name: "Business snapshot" })).toHaveCount(0);
  await expect(main).not.toContainText(/turnover|Overdue invoices|VAT estimate/i);
  const summary = page.getByRole("region", { name: /^Your summary/ });
  await expect(summary).not.toContainText(/VAT|turnover|invoice/i);

  const axe = await new AxeBuilder({ page }).include("main").withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
});

test("a household with no statement yet: one clear step, not a page of zeros", async ({ page, runtime }) => {
  await runtime.api("PUT", "/profile", PERSONAL);
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/");
  const month = page.getByRole("region", { name: /^This month/ });
  await expect(month.getByRole("link", { name: "Import a statement" })).toHaveAttribute("href", "/bank");
  await expect(page.getByRole("region", { name: "Budgets this month" })).toHaveCount(0);
});
