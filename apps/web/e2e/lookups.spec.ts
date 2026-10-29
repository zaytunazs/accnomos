import { createBooksFolder, expect, GOLD, signIn, test, confirmScan } from "./fixtures";

/**
 * Official look-ups against the test-mode fakes (services/runtime/app/company_lookup.py): fictional SAMPLE
 * companies for Companies House, the gold receipts' fictional suppliers for the HMRC VAT check. No network.
 */

test("contacts: look up a company, fill the edit form, save; check the VAT number", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // Novex Office Supplies Ltd, VAT number GB 882431902

  await page.goto("/contacts");
  await page.getByRole("button", { name: "Refresh from books" }).click();
  await page.getByRole("button", { name: "Novex Office Supplies Ltd" }).click();
  const panel = page.getByRole("complementary", { name: "Novex Office Supplies Ltd: statement" });
  await panel.getByRole("button", { name: "Edit" }).click();

  await panel.getByRole("button", { name: "Look up on Companies House" }).click();
  const lookup = panel.getByRole("region", { name: "Look up on Companies House" });
  await expect(lookup.getByRole("textbox", { name: "Company name or number" })).toHaveValue("Novex Office Supplies Ltd");
  await lookup.getByRole("button", { name: "Look up" }).click();
  const matches = lookup.getByRole("list", { name: "Companies House matches" });
  await expect(matches.getByRole("button")).toHaveCount(1);
  await expect(matches).toContainText("SAMPLE");
  await matches.getByRole("button", { name: /NOVEX OFFICE SUPPLIES LIMITED/ }).click();

  await expect(panel.getByRole("status").first()).toContainText("Filled from Companies House (SAMPLE)");
  await expect(panel.getByRole("textbox", { name: "Name" })).toHaveValue("NOVEX OFFICE SUPPLIES LIMITED");
  await expect(panel.getByRole("textbox", { name: "Company number" })).toHaveValue("ZZ000001");
  await panel.getByRole("button", { name: "Save" }).click(); // the user saves; the look-up saved nothing

  const saved = page.getByRole("complementary", { name: "NOVEX OFFICE SUPPLIES LIMITED: statement" });
  await expect(saved.getByRole("button", { name: "Edit" })).toBeVisible();
  await expect(saved).toContainText("ZZ000001");

  await saved.getByRole("button", { name: /^Check VAT number/ }).click();
  await expect(saved).toContainText("Registered to NOVEX OFFICE SUPPLIES LTD, 14 Industrial Park, Leeds, LS10 1AB (SAMPLE, test mode)");
  await expect(saved).not.toContainText("HMRC's name differs");

  await page.reload(); // the result is kept on the contact in OneDrive
  await page.getByRole("button", { name: "NOVEX OFFICE SUPPLIES LIMITED" }).click();
  await expect(page.getByRole("complementary", { name: "NOVEX OFFICE SUPPLIES LIMITED: statement" })).toContainText(
    "Registered to NOVEX OFFICE SUPPLIES LTD",
  );
});

test("review: check a supplier's VAT number on the card; approving never waits for it", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/review");
  await page.locator('input[type="file"]').first().setInputFiles({ name: `${GOLD}.png`, mimeType: "image/png", buffer: await runtime.goldPng() });
  await confirmScan(page);
  const novex = page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" });
  await expect(novex).toBeVisible();
  await expect(novex).not.toContainText("Registered to"); // nothing is checked on scan

  await novex.getByRole("button", { name: /^Check VAT number/ }).click();
  await expect(novex).toContainText("Registered to NOVEX OFFICE SUPPLIES LTD, 14 Industrial Park, Leeds, LS10 1AB (SAMPLE, test mode)");
  await novex.getByRole("button", { name: /^Approve/ }).click();
  await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText("Approved · posted to your books · U to undo");
});
