import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("contacts: list from the books, edit one, its statement", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // Novex Office Supplies Ltd, 14 Aug 2026, £51.90 paid by card

  await page.goto("/contacts");
  await page.getByRole("button", { name: "Refresh from books" }).click();
  await expect(page.getByRole("status")).toContainText("saved to _System/Contacts/contacts.json in your OneDrive");
  await expect(page.getByText("SAMPLE — FICTIONAL COMPANY")).toHaveCount(0); // the live list, not the sample

  let statements = 0;
  await page.route("**/contacts/*/statement*", async (route) => {
    statements += 1;
    await route.continue();
  });

  await page.getByRole("button", { name: "Novex Office Supplies Ltd" }).click();
  const panel = page.getByRole("complementary", { name: "Novex Office Supplies Ltd: statement" });
  await expect(panel).toContainText("Supplier");
  await expect(panel).toContainText("VAT-registered"); // learnt from the VAT number on the approved receipt
  const statement = panel.getByRole("table");
  await expect(statement.getByRole("row").filter({ hasText: "14 Aug 2026" })).toContainText("£51.90");
  const loaded = statements;
  expect(loaded).toBeGreaterThanOrEqual(1);

  await panel.getByRole("button", { name: "Edit" }).click();
  await panel.getByRole("textbox", { name: "Phone" }).fill("0117 496 0123");
  await expect(panel.getByRole("combobox", { name: "VAT status" })).toHaveValue("registered");
  await panel.getByRole("combobox", { name: "VAT status" }).selectOption("unknown");
  await panel.getByRole("button", { name: "Save" }).click();
  await expect(panel.getByRole("button", { name: "Edit" })).toBeVisible();
  await expect(panel).toContainText("0117 496 0123");
  await expect(panel).toContainText("VAT status not known yet");
  // Saving re-fetches the statement in place: the purchase line is still there, freshly loaded
  await expect.poll(() => statements).toBeGreaterThan(loaded);
  await expect(statement.getByRole("row").filter({ hasText: "14 Aug 2026" })).toContainText("£51.90");

  await page.reload(); // kept in contacts.json in OneDrive
  await page.getByRole("button", { name: "Novex Office Supplies Ltd" }).click();
  const again = page.getByRole("complementary", { name: "Novex Office Supplies Ltd: statement" });
  await expect(again).toContainText("0117 496 0123");
  await expect(again).toContainText("VAT status not known yet");
});
