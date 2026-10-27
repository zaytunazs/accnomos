import { join } from "node:path";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

// SAMPLE — FICTIONAL COMPANY: six lines, three paying seeded entries exactly, one a penny out, a transfer and a fee.
const BARCLAYS = join(__dirname, "../../../evals/gold/bank/barclays.csv");

test("upload the gold Barclays CSV → confirm a match → settle the unmatched lines", async ({ page, runtime }) => {
  await runtime.reset("bank"); // Screwfix, Acme Kitchens, Toolstation and Travis Perkins in the ledger
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles(BARCLAYS);
  await expect(page.getByRole("status").filter({ hasText: "barclays.csv" })).toContainText("6 new lines");
  expect((await runtime.files()).some((f) => f.startsWith("03 Bank statements/") && f.endsWith(".csv"))).toBeTruthy();

  const lines = page.getByRole("region", { name: "Bank lines" });
  const tab = (name: string) => lines.getByRole("tab", { name: new RegExp(`^${name}`) });
  await expect(tab("Matches")).toContainText("4"); // three exact, Travis Perkins a penny out
  await expect(tab("Unmatched")).toContainText("2");
  await expect(lines.getByRole("button", { name: "Confirm all 3 exact matches" })).toBeVisible();

  await lines.getByRole("button", { name: /^Confirm match: SCREWFIX DIRECT/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "Matched" })).toHaveText("Matched SCREWFIX DIRECT ON 30 SEP CLP to Screwfix.");
  await expect(tab("Matches")).toContainText("3");

  await tab("Unmatched").click();
  const transfer = lines.getByRole("listitem").filter({ hasText: "TO SAVINGS" });
  await transfer.getByRole("button", { name: "Mark as transfer" }).click();
  await expect(page.getByRole("status").filter({ hasText: "transfer" })).toHaveText("TO SAVINGS 40-11-22 87654321 TFR marked as a transfer.");

  const fee = lines.getByRole("listitem").filter({ hasText: "BUSINESS ACCOUNT FEE" });
  await fee.getByRole("button", { name: "Create expense proposal" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Expense proposal" })).toHaveText("Expense proposal for BUSINESS ACCOUNT FEE is waiting on Review.");
  await expect(fee.getByRole("button", { name: "Proposal created" })).toBeDisabled(); // nothing posted until approved
  await expect(fee.getByRole("link", { name: "Approve it on Review" })).toBeVisible();

  await tab("Done").click();
  const done = lines.getByRole("tabpanel");
  await expect(done.getByRole("row").filter({ hasText: "SCREWFIX" })).toContainText("Matched");
  await expect(done.getByRole("row").filter({ hasText: "TO SAVINGS" })).toContainText("Transfer");
});
