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
  expect((await runtime.files()).some((f) => f.startsWith("04 Bank statements/") && f.endsWith(".csv"))).toBeTruthy();

  // Statement view: the canonical folder path, per-line status and the running balance from the CSV.
  const statement = page.getByRole("button", { name: /04 Bank statements\/.*barclays\.csv/ });
  await expect(statement).toBeVisible();
  await statement.click();
  const statementLines = page.getByRole("region", { name: /Lines in .*barclays\.csv/ });
  await expect(statementLines.getByText("TO SAVINGS 40-11-22 87654321 TFR")).toBeVisible();
  await expect(statementLines.getByText(/^Balance /).first()).toBeVisible();
  await statementLines.getByLabel("Show").selectOption("unmatched");
  await expect(statementLines.getByText("TO SAVINGS 40-11-22 87654321 TFR")).toBeVisible();
  await expect(statementLines.getByText("SCREWFIX DIRECT ON 30 SEP CLP")).toHaveCount(0);
  await statementLines.getByLabel("Show").selectOption("all");

  const lines = page.getByRole("region", { name: "Bank lines" });
  const tab = (name: string) => lines.getByRole("tab", { name: new RegExp(`^${name}`) });
  await expect(tab("Matches")).toContainText("4"); // three exact, Travis Perkins a penny out
  await expect(tab("Unmatched")).toContainText("2");
  // The penny-out suggestion stays per row and out of the bulk confirm, with its reason shown.
  await expect(lines.getByRole("button", { name: "Confirm all 3 exact matches" })).toBeVisible();
  await expect(lines.getByText("1p out")).toBeVisible();

  await lines.getByRole("button", { name: /^Confirm match: SCREWFIX DIRECT/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "Matched" })).toHaveText("Matched SCREWFIX DIRECT ON 30 SEP CLP to Screwfix.");
  await expect(tab("Matches")).toContainText("3");

  // The reconciled tile explains what counts as decided.
  await page.getByRole("button", { name: "What counts?" }).click();
  await expect(page.getByText("Suggested matches do not count until you confirm them.")).toBeVisible();

  await tab("Unmatched").click();
  const transfer = lines.getByRole("listitem").filter({ hasText: "TO SAVINGS" });
  await transfer.getByRole("button", { name: /^Actions for TO SAVINGS/ }).click();
  await transfer.getByRole("menuitem", { name: /^Mark as transfer/ }).click();
  const transferSheet = page.getByRole("dialog");
  await expect(transferSheet).toContainText("TO SAVINGS 40-11-22 87654321 TFR will be marked as a transfer between your own accounts. Nothing will be booked.");
  await transferSheet.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "transfer" })).toHaveText("TO SAVINGS 40-11-22 87654321 TFR marked as a transfer.");
  await expect(tab("Unmatched")).toContainText("1"); // the line moved tabs without a reload

  const fee = lines.getByRole("listitem").filter({ hasText: "BUSINESS ACCOUNT FEE" });
  await fee.getByRole("button", { name: /^Actions for BUSINESS ACCOUNT FEE/ }).click();
  await fee.getByRole("menuitem", { name: "Create expense proposal" }).click();
  const feeSheet = page.getByRole("dialog");
  await expect(feeSheet).toContainText("A £6.50 expense proposal with no VAT reclaimed will wait in Review.");
  await feeSheet.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Expense proposal" })).toHaveText("Expense proposal for BUSINESS ACCOUNT FEE is waiting on Review.");
  await expect(fee.getByRole("button", { name: "Proposal created" })).toBeDisabled(); // nothing posted until approved
  await expect(fee.getByRole("link", { name: "Approve it on Review" })).toBeVisible();

  // Changes offer a rebuild of Books.xlsx.
  await expect(page.getByRole("button", { name: "Rebuild Books.xlsx" })).toBeVisible();

  await tab("Done").click();
  const done = lines.getByRole("tabpanel");
  await expect(done.getByRole("row").filter({ hasText: "SCREWFIX" })).toContainText("Matched");
  await expect(done.getByRole("row").filter({ hasText: "TO SAVINGS" })).toContainText("Transfer");
});
