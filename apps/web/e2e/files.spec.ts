import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("Files lists the books folder from (fake) OneDrive", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // filed into 01 Receipts/2026-08, with a ledger event under _System

  await page.goto("/files");
  const tree = page.getByRole("list").filter({ hasText: "00 Inbox" }).first();
  for (const name of ["00 Inbox", "01 Receipts", "02 Sales invoices", "03 Bank statements", "04 Needs a look", "05 VAT returns", "06 Reports", "README.txt"]) {
    await expect(tree.getByText(name, { exact: true })).toBeVisible();
  }
  await expect(tree.getByText("› 2026-08")).toBeVisible();
  await expect(page.getByText(/Sample folder\.|showing the sample instead/)).toHaveCount(0); // live, not the sample tree

  await tree.getByText("rules, audit log, ledger events · show").click();
  await expect(tree.getByText("Ledger", { exact: true })).toBeVisible();
});
