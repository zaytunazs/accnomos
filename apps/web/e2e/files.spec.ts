import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("Files lists the books folder from (fake) OneDrive", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // filed into 01 Receipts/2026-08, with a ledger event under _System

  await page.goto("/files");
  const tree = page.getByRole("list").filter({ hasText: "00 Inbox" }).first();
  const names = ["00 Inbox", "01 Receipts", "02 Needs a look", "03 Sales", "04 Bank statements", "05 Payroll", "06 VAT returns", "07 Reports"];
  for (const name of [...names, "README.txt"]) {
    await expect(tree.getByText(name, { exact: true })).toBeVisible();
  }
  const shown = await tree.locator(":scope > li").allInnerTexts();
  const order = names.map((n) => shown.findIndex((t) => t.startsWith(n)));
  expect(order).toEqual([...order].sort((a, b) => a - b)); // in the canonical order
  await expect(tree.getByText("› 2026-08")).toBeVisible();
  await expect(page.getByText(/Sample folder\.|showing the sample instead/)).toHaveCount(0); // live, not the sample tree
  await expect(page.getByText("Old and new folders side by side")).toHaveCount(0);

  await tree.getByText("rules, audit log, ledger events · show").click();
  await expect(tree.getByText("Ledger", { exact: true })).toBeVisible();
  expect(await runtime.files()).toContain("README.txt");
});

test("Files: old-named folders are renamed once; old and new side by side get a warning", async ({ page, runtime }) => {
  // Books as the previous version left them, before the user signs in again.
  await runtime.putFile("03 Bank statements/2026-09-30_starling.csv", "Date,Amount\n"); // old name
  await runtime.putFile("05 VAT returns/2026-Q2/return.json", "{}"); // old name, and the new one exists too:
  await runtime.putFile("06 VAT returns/2026-Q3/return.json", "{}");

  await signIn(page);
  await page.goto("/files");
  await expect(page.getByText("Old and new folders side by side")).toBeVisible();
  await expect(page.getByText("05 VAT returns → 06 VAT returns: move its files into the new folder.")).toBeVisible(); // old name

  const files = await runtime.files();
  expect(files).toContain("04 Bank statements/2026-09-30_starling.csv");
  expect(files.filter((f) => f.startsWith("03 Bank statements"))).toEqual([]); // old name: moved, not copied
  expect(files).toContain("05 VAT returns/2026-Q2/return.json"); // old name: left alone
  const tree = page.getByRole("list").filter({ hasText: "04 Bank statements" }).first();
  await expect(tree.getByText("04 Bank statements", { exact: true })).toBeVisible();
});
