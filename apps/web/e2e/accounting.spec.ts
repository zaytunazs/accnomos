import AxeBuilder from "@axe-core/playwright";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

/** Accounting tools (services/runtime/app/routes_accounting.py and the budget / cash flow reports). */
const TOOLS = [
  "/accounting/chart",
  "/accounting/journals",
  "/accounting/assets",
  "/accounting/recode",
  "/accounting/tracking",
  "/reports/budgets",
  "/reports/cashflow",
];

const events = async (files: () => Promise<string[]>) => (await files()).filter((f) => f.startsWith("_System/Ledger/events/"));

test("signed out: every tool page says what it does and asks to sign in", async ({ page }) => {
  for (const path of TOOLS) {
    await page.goto(path);
    await expect(page.getByRole("navigation", { name: "Accounting tools" })).toBeVisible();
    await expect(page.getByRole("main").getByRole("link", { name: "Sign in to see your books" })).toBeVisible();
  }
});

test.describe("signed in", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
    await createBooksFolder(page);
  });

  test("chart of accounts: the standard chart, add an account, refusals in plain words", async ({ page }) => {
    await page.goto("/accounting/chart");
    await expect(page.getByText("This is the standard UK small-business chart.")).toBeVisible();
    const table = page.getByRole("table", { name: "Chart of accounts" });
    await expect(table.getByRole("row", { name: /0050 Computer equipment/ })).toBeVisible();
    const add = page.getByRole("region", { name: "Add an account" });
    await add.getByLabel("Code").fill("7650");
    await add.getByLabel("Name").fill("Training");
    await add.getByLabel("Type").selectOption("overhead");
    await add.getByRole("button", { name: "Add account" }).click();
    await expect(page.getByRole("status")).toHaveText("Added 7650 Training.");
    await expect(table.getByRole("row", { name: /7650 Training/ })).toBeVisible();
    await add.getByLabel("Code").fill("7651");
    await add.getByLabel("Name").fill("Grants");
    await add.getByLabel("Type").selectOption("revenue");
    await add.getByRole("button", { name: "Add account" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Revenue accounts" }).last()).toContainText("Revenue accounts use codes 4000 to 4999");
  });

  test("manual journal: balance shown, draft posts nothing, approve posts it and its reversal", async ({ page, runtime }) => {
    const before = await events(() => runtime.files());
    await page.goto("/accounting/journals");
    const form = page.getByRole("region", { name: "New journal" });
    await form.getByLabel("Narration").fill("Accrue October electricity");
    await form.getByLabel("Line 1 account").selectOption("7200 Utilities");
    await form.getByLabel("Debit £").first().fill("123.45");
    await form.getByLabel("Line 2 account").selectOption("2400 Accruals");
    await form.getByLabel("Credit £").nth(1).fill("123.40");
    await expect(form.getByText(/£0.05 apart: they must be equal/)).toBeVisible();
    await form.getByLabel("Credit £").nth(1).fill("123.45");
    await expect(form.getByText(/balanced/)).toBeVisible();
    await form.getByLabel("Reverse on (optional)").fill("2026-11-01");
    await form.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByRole("status")).toContainText("Saved MJ-0001 as a draft. Nothing is posted until you approve it.");
    expect(await events(() => runtime.files())).toEqual(before);

    await page.getByRole("button", { name: "Approve MJ-0001" }).click();
    await expect(page.getByRole("status")).toContainText("MJ-0001 approved and posted, with its reversal on 1 Nov 2026.");
    expect((await events(() => runtime.files())).length).toBe(before.length + 2);
    await page.getByLabel("Status").selectOption("posted");
    await expect(page.getByRole("heading", { name: /MJ-0001/ })).toBeVisible();
  });

  test("fixed assets: register, run depreciation, approve, schedule", async ({ page }) => {
    await page.goto("/accounting/assets");
    await expect(page.getByRole("note").filter({ hasText: "Capital allowances" })).toBeVisible();
    const form = page.getByRole("region", { name: "Register an asset" });
    await form.getByLabel("Name").fill("Laptop");
    await form.getByLabel("Purchase date").fill("2026-04-15");
    await form.getByLabel("Cost £ (ex VAT)").fill("1200");
    await form.getByRole("button", { name: "Register asset" }).click();
    await expect(page.getByRole("status")).toContainText("FA-0001 Laptop registered. Nothing was posted");
    await page.getByLabel("Up to the end of").fill("2026-06-30");
    await page.getByRole("button", { name: "Run depreciation" }).click();
    await expect(page.getByRole("status")).toHaveText("Journal MJ-0001 is ready for you to approve.");

    await page.goto("/accounting/journals");
    await page.getByRole("button", { name: "Approve MJ-0001" }).click();
    await expect(page.getByRole("status")).toContainText("MJ-0001 approved and posted");

    await page.goto("/accounting/assets");
    const row = page.getByRole("table", { name: "Fixed asset register" }).getByRole("row", { name: /FA-0001 Laptop/ });
    await expect(row).toContainText("£100.00"); // Apr–Jun at £1,200 over 3 years
    await expect(row).toContainText("£1,100.00");
    await page.getByRole("button", { name: "Schedule for FA-0001" }).click();
    const sched = page.getByRole("table", { name: "Depreciation schedule for FA-0001" });
    await expect(sched.getByRole("row")).toHaveCount(37);
  });

  test("find and recode: preview, then post an adjusting entry", async ({ page, runtime }) => {
    await runtime.postGold(); // Novex Office Supplies Ltd, net £43.25 + VAT
    const before = await events(() => runtime.files());
    await page.goto("/accounting/recode");
    await page.getByLabel("Contact").fill("Novex");
    await page.getByRole("main").getByRole("button", { name: "Search" }).click();
    const found = page.getByRole("table", { name: "Posted lines found" });
    await expect(found.getByText(/^1200 Bank is kept by invoices, bills, the VAT return or bank lines/)).toBeVisible();
    await found.getByRole("checkbox", { name: /Choose 7500 Office supplies £43.25/ }).check();
    await page.getByLabel("New account").selectOption("0030 Office equipment");
    await page.getByRole("button", { name: "Preview the adjusting entries" }).click();
    await expect(page.getByRole("table", { name: "Adjusting entry lines" }).getByRole("row", { name: /0030 Office equipment £43.25/ })).toBeVisible();
    expect(await events(() => runtime.files())).toEqual(before);
    await page.getByRole("button", { name: "Approve and post the recode" }).click();
    await expect(page.getByRole("status")).toContainText("Recoded 1 line with 1 adjusting entry.");
    expect((await events(() => runtime.files())).length).toBe(before.length + 1);
  });

  test("tracking: two categories at most, options, and the summary", async ({ page }) => {
    await page.goto("/accounting/tracking");
    await page.getByLabel("New category").fill("Department");
    await page.getByRole("button", { name: "Add category" }).click();
    await expect(page.getByRole("status")).toHaveText("Added the Department category.");
    await page.getByLabel("New Department option").fill("Kitchens");
    await page.getByRole("button", { name: "Add option" }).click();
    await expect(page.getByRole("status")).toHaveText("Added Kitchens to Department.");
    await page.getByRole("button", { name: "Show" }).click();
    const table = page.getByRole("table", { name: "Profit and loss by Department" });
    await expect(table.getByRole("columnheader", { name: "Kitchens" })).toBeVisible();
    await expect(table.getByRole("columnheader", { name: "Unassigned" })).toBeVisible();
  });

  test("budgets: save, then compare with actual", async ({ page, runtime }) => {
    await runtime.postGold();
    await page.goto("/reports/budgets");
    await page.getByLabel("First month").fill("2026-07");
    await page.getByLabel("7500 Office supplies, Aug 26").fill("50");
    await page.getByRole("button", { name: "Save budget" }).click();
    await expect(page.getByRole("status")).toContainText("saved (1 account). Nothing is posted.");
    await page.getByRole("button", { name: "Compare with actual" }).click();
    const v = page.getByRole("table", { name: "Actual against budget" });
    // Budget £50.00, actual £43.25: −£6.75, favourable.
    await expect(v.getByRole("row", { name: /7500 Office supplies/ })).toContainText("-£6.75 favourable");
    await page.getByRole("button", { name: "Budget summary" }).click();
    await expect(page.getByRole("table", { name: "Budget by month" })).toContainText("£50.00");
  });

  test("cash flow: bank today, 30/60/90 days and one checked sentence", async ({ page, runtime }) => {
    await runtime.postGold();
    await page.goto("/reports/cashflow");
    await expect(page.getByRole("heading", { name: /Bank today/ })).toBeVisible();
    await expect(page.getByText("In 90 days · 25 Jan 2027")).toBeVisible();
    await expect(page.getByRole("note").filter({ hasText: "Repeating invoices and bills" })).toBeVisible();
    await page.getByRole("button", { name: "Say it in a sentence" }).click();
    await expect(page.getByText(/^Your bank is -£51.90 today and -£51.90 in 90 days\./)).toBeVisible();
  });

  test.describe("at 360 px", () => {
    test.use({ viewport: { width: 360, height: 780 } });
    test("no page scrolls sideways and axe finds nothing serious", async ({ page }) => {
      test.slow(); // seven pages, an axe run on each
      for (const path of TOOLS) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await expect(page.getByRole("status").filter({ hasText: /^Loading/ })).toHaveCount(0);
        const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(wide, `${path} scrolls sideways`).toBeLessThanOrEqual(0);
        const { violations } = await new AxeBuilder({ page }).analyze();
        expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${path}: ${v.id}`)).toEqual([]);
      }
    });
  });
});
