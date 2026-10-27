import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("create an invoice → preview → send behind the confirmation tick; the fake sender records it", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/invoices");
  await expect(page.getByRole("heading", { name: "No invoices yet" })).toBeVisible();
  await page.getByRole("link", { name: "New invoice" }).first().click(); // the empty state repeats the link
  await expect(page).toHaveURL(/\/invoices\/new$/);

  await page.getByLabel("Name", { exact: true }).fill("Harbour Cafe Ltd");
  await page.getByLabel("Email (the invoice is sent here)").fill("accounts@harbourcafe.example");
  await page.getByLabel("Description").fill("Kitchen first fix");
  await page.getByLabel("Qty").fill("6");
  await page.getByLabel("Unit", { exact: true }).fill("hours");
  await page.getByLabel("Unit price (£, ex VAT)").fill("45.00");
  // 6 × £45.00 = £270.00 net, £54.00 VAT at 20%, £324.00 total (a preview; the runtime prices it on save)
  await expect(page.getByText("Total£324.00")).toBeVisible();

  await page.getByRole("button", { name: "Save and preview" }).click();
  const dialog = page.getByRole("dialog", { name: "Preview and send INV-0001" });
  await expect(dialog).toContainText("Harbour Cafe Ltd · £324.00");
  await expect(dialog.getByTitle("PDF of INV-0001")).toBeVisible();

  const send = dialog.getByRole("button", { name: "Send via Outlook" });
  await expect(dialog.getByRole("textbox", { name: "To", exact: true })).toHaveValue("accounts@harbourcafe.example");
  await expect(send).toBeDisabled(); // nothing goes out until the user ticks the confirmation
  expect(await runtime.sent()).toEqual([]);
  await dialog.getByRole("checkbox", { name: /I have checked this invoice/ }).check();
  await send.click();

  await expect(page).toHaveURL(/\/invoices$/);
  await expect(page.getByRole("listitem").filter({ hasText: "INV-0001 · Harbour Cafe Ltd" })).toContainText("£324.00");
  await expect(page.getByText("Awaiting payment £324.00")).toBeVisible();

  const [mail] = await runtime.sent();
  expect(mail.to).toBe("accounts@harbourcafe.example");
  expect(mail.subject).toContain("INV-0001");
  expect(mail.attachments).toEqual(["INV-0001.pdf"]);
  const files = await runtime.files();
  expect(files).toContain("03 Sales/invoices/sent/INV-0001.pdf");
  expect(files.some((f) => f.startsWith("_System/Ledger/events/2026-10/"))).toBeTruthy(); // the sale is in the books
});
