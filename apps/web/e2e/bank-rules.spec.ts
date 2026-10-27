import { join } from "node:path";
import { Buffer } from "node:buffer";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

// SAMPLE — FICTIONAL COMPANY: the same gold statement as bank.spec.ts.
const BARCLAYS = join(__dirname, "../../../evals/gold/bank/barclays.csv");

// One line overlapping the gold CSV (same date, amount and description, no
// balance column on either file) plus one genuinely new line.
const OVERLAP = [
  "Number,Date,Account,Amount,Subcategory,Memo",
  ",20/10/2026,20-00-00 12345678,-45.01,PAYMENT,TRAVIS PERKINS 0099 ON 15 OCT",
  ",21/10/2026,20-00-00 12345678,-9.99,PAYMENT,COFFEE SHOP",
  "",
].join("\r\n");

test("rules: add, reorder, edit, delete with confirm; an unsafe pattern is refused", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/bank");

  const panel = page.getByRole("tabpanel");
  await page.getByRole("tab", { name: "Rules" }).click();
  await expect(panel.getByText("No rules yet.")).toBeVisible();

  async function addRule(name: string, text: string, account: string, op = "contains") {
    await panel.getByRole("button", { name: "Add a rule" }).click();
    await panel.getByLabel("Rule name").fill(name);
    await panel.getByLabel("Match type").selectOption(op);
    await panel.getByLabel("Match text").fill(text);
    await panel.getByLabel("Account").selectOption(account);
    await panel.getByRole("button", { name: "Save rule" }).click();
  }

  await addRule("Fees", "ACCOUNT FEE", "7900 Bank charges");
  await expect(panel.getByText("When the description contains ACCOUNT FEE")).toBeVisible();
  await addRule("Coffee", "COFFEE", "7999 Sundry expenses");

  // Reorder: first match wins, so moving Fees down puts Coffee first.
  await panel.getByRole("button", { name: "Move rule Fees down" }).click();
  const items = panel.getByRole("listitem");
  await expect(items.first()).toContainText("Coffee");
  await expect(items.first()).toContainText("#1 of 2");

  // Edit: rename Coffee.
  await panel.getByRole("button", { name: "Edit rule Coffee" }).click();
  await panel.getByLabel("Rule name").fill("Coffee shops");
  await panel.getByRole("button", { name: "Save rule" }).click();
  await expect(panel.getByText("Coffee shops")).toBeVisible();

  // Delete asks twice: Delete, then Confirm delete.
  await panel.getByRole("button", { name: "Delete rule Fees" }).click();
  await panel.getByRole("button", { name: "Confirm delete rule Fees" }).click();
  await expect(panel.getByText("When the description contains ACCOUNT FEE")).toHaveCount(0);
  await expect(panel.getByText("Coffee shops")).toBeVisible();

  // An unsafe pattern never saves: nested quantifiers are refused.
  await panel.getByRole("button", { name: "Add a rule" }).click();
  await panel.getByLabel("Match type").selectOption("regex");
  await panel.getByLabel("Match text").fill("(a+)+");
  await panel.getByLabel("Account").selectOption("7999 Sundry expenses");
  await panel.getByRole("button", { name: "Save rule" }).click();
  await expect(panel.getByRole("alert")).toContainText("Could not save the rule");
  await panel.getByRole("button", { name: "Cancel" }).click();
  await expect(panel.getByText("Coffee shops")).toBeVisible();
});

test("reconcile: rule coding posts, the AI suggests, create-rule pre-fills", async ({ page, runtime }) => {
  await runtime.reset("bank");
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles(BARCLAYS);
  await expect(page.getByRole("status").filter({ hasText: "barclays.csv" })).toContainText("6 new lines");

  const panel = page.getByRole("tabpanel");
  const lines = page.getByRole("region", { name: "Bank lines" });
  const tab = (name: string) => lines.getByRole("tab", { name: new RegExp(`^${name}`) });

  // A rule for the fee line, made on the Rules tab.
  await page.getByRole("tab", { name: "Rules" }).click();
  await panel.getByRole("button", { name: "Add a rule" }).click();
  await panel.getByLabel("Rule name").fill("Fees");
  await panel.getByLabel("Match text").fill("BUSINESS ACCOUNT FEE");
  await panel.getByLabel("Account").selectOption("7900 Bank charges");
  await panel.getByRole("button", { name: "Save rule" }).click();
  await expect(panel.getByText("When the description contains BUSINESS ACCOUNT FEE")).toBeVisible();

  // Reconcile shows the rule coding on the fee row.
  await page.getByRole("tab", { name: "Reconcile" }).click();
  const fee = panel.getByRole("listitem").filter({ hasText: "BUSINESS ACCOUNT FEE" });
  await expect(fee.getByText("Bank rule")).toBeVisible();
  await expect(fee.getByText("7900 Bank charges")).toBeVisible();

  // "Create rule from this" opens the Rules form pre-filled from the line.
  await fee.getByRole("button", { name: /^Create rule from this/ }).click();
  await expect(page.getByRole("tab", { name: "Rules" })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByLabel("Match text")).toHaveValue("BUSINESS ACCOUNT FEE");
  await panel.getByRole("button", { name: "Cancel" }).click();

  // The AI codes the same line when asked, labelled as its own suggestion.
  await page.getByRole("tab", { name: "Reconcile" }).click();
  const feeAgain = panel.getByRole("listitem").filter({ hasText: "BUSINESS ACCOUNT FEE" });
  await feeAgain.getByRole("button", { name: /^Suggest with AI/ }).click();
  await expect(feeAgain.getByText("suggested by AI")).toBeVisible();
  await feeAgain.getByRole("button", { name: /^Approve AI suggestion/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "Posted" })).toContainText("through Review approval");

  // Approving settles the line: it is matched to the entry it made, with no separate confirm step.
  await tab("Done").click();
  await expect(lines.getByRole("tabpanel").getByRole("row").filter({ hasText: "BUSINESS ACCOUNT FEE" })).toContainText("Matched");
});

test("an overlapping re-export adds only its new lines; the penny-out match stays out of bulk confirm", async ({
  page,
  runtime,
}) => {
  await runtime.reset("bank");
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles(BARCLAYS);
  await expect(page.getByRole("status").filter({ hasText: "barclays.csv" })).toContainText("6 new lines");

  // Same Travis Perkins line (overlap) plus one new Coffee Shop line.
  await page.locator('input[type="file"]').setInputFiles({ name: "overlap.csv", mimeType: "text/csv", buffer: Buffer.from(OVERLAP) });
  await expect(page.getByRole("status").filter({ hasText: "overlap.csv" })).toContainText("1 new line");
  // Both statements show, with 6 + 1 lines between them.
  await expect(page.getByRole("button", { name: /04 Bank statements\/.*\.csv/ })).toHaveCount(2);

  // The same file again changes nothing.
  await page.locator('input[type="file"]').setInputFiles({ name: "overlap.csv", mimeType: "text/csv", buffer: Buffer.from(OVERLAP) });
  await expect(page.getByRole("status").filter({ hasText: "overlap.csv" })).toContainText("already imported");
  await expect(page.getByRole("button", { name: /04 Bank statements\/.*\.csv/ })).toHaveCount(2);

  // The penny rule: three exact matches bulk-confirm; Travis Perkins (1p out) stays per row.
  const lines = page.getByRole("region", { name: "Bank lines" });
  const tab = (name: string) => lines.getByRole("tab", { name: new RegExp(`^${name}`) });
  await expect(lines.getByRole("button", { name: "Confirm all 3 exact matches" })).toBeVisible();
  await lines.getByRole("button", { name: "Confirm all 3 exact matches" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Confirmed" })).toContainText("Confirmed 3 exact matches");
  await expect(tab("Matches")).toContainText("1");
  await expect(lines.getByRole("table").getByText("1p out")).toBeVisible();
});
