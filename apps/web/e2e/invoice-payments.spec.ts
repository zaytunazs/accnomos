import { createBooksFolder, expect, signIn, test } from "./fixtures";

/** Part payment, a credit note for one line, then taking the payment back: every figure from the runtime. */
test("record a part payment and a credit note; the balance follows; removing the payment reverses it", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  // Arranged through the API (the invoice spec covers writing and sending): 6 h × £45 + 4 boxes × £10, 20% VAT
  // = £310.00 net, £62.00 VAT, £372.00 total.
  await runtime.api("POST", "/invoices", {
    customer: { name: "Harbour Cafe Ltd", email: "accounts@harbourcafe.example" },
    lines: [
      { description: "Kitchen first fix", quantity: "6", unit: "hours", unit_price_pence: 4500, vat_code: "S" },
      { description: "Fixings", quantity: "4", unit: "boxes", unit_price_pence: 1000, vat_code: "S" },
    ],
  });
  await runtime.api("POST", "/invoices/INV-0001/send", { confirm: true });

  await page.goto("/invoices");
  const row = page.getByRole("listitem").filter({ hasText: "INV-0001 · Harbour Cafe Ltd" });
  await expect(row).toContainText("£372.00");

  // Record payment: £100 of £372
  await row.getByRole("button", { name: "Record payment" }).click();
  const pay = page.getByRole("dialog", { name: "Record payment on INV-0001" });
  await expect(pay).toContainText("balance £372.00");
  await pay.getByLabel("Amount (£)").fill("100.00");
  await expect(pay).toContainText("£272.00 stays owed.");
  await pay.getByRole("button", { name: "Record payment" }).click();
  await expect(page.getByRole("status")).toContainText("Payment recorded on INV-0001: £272.00 still owed.");
  await expect(row).toContainText("Part paid");
  await expect(row).toContainText("balance £272.00");
  await expect(page.getByText("Awaiting payment £272.00")).toBeVisible();

  // Create credit note: one of the four boxes of fixings (£10.00 + £2.00 VAT)
  await row.getByRole("button", { name: "Create credit note" }).click();
  const cn = page.getByRole("dialog", { name: "Credit note for INV-0001" });
  await cn.getByRole("radio", { name: "Chosen lines" }).check();
  await cn.getByRole("checkbox", { name: /Fixings/ }).check();
  await cn.getByLabel("Qty (of 4)").fill("1");
  await cn.getByLabel("Reason").fill("One box returned unopened");
  await expect(cn).toContainText("Credit about £12.00 (net £10.00, VAT £2.00)");
  const create = cn.getByRole("button", { name: "Create credit note" });
  await expect(create).toBeDisabled(); // nothing is posted until the user ticks the confirmation
  await cn.getByRole("checkbox", { name: /Record this credit note in my books now/ }).check();
  await create.click();
  await expect(page.getByRole("status")).toContainText("Credit note CN-0001 for £12.00 recorded against INV-0001.");
  await expect(row).toContainText("balance £260.00");
  const credits = page.getByRole("region", { name: "Credit notes" });
  await expect(credits).toContainText("CN-0001 · Harbour Cafe Ltd");
  await expect(credits).toContainText("-£12.00");

  // The credit note's PDF is saved next to the invoices
  await credits.getByRole("button", { name: "View PDF" }).click();
  const view = page.getByRole("dialog", { name: "Credit note CN-0001" });
  await expect(view.getByTitle("PDF of CN-0001")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(view).toBeHidden();
  const files = await runtime.files();
  expect(files).toContain("03 Sales/credit-notes/CN-0001.json");
  expect(files).toContain("03 Sales/credit-notes/CN-0001.pdf");

  // Payments and history: remove the £100; the invoice is owed again, less the credit note
  await row.getByText("Payments and history").click();
  const panel = row.getByRole("region", { name: "Payments on INV-0001" });
  await expect(panel).toContainText("Paid£100.00");
  await expect(panel).toContainText("Credited£12.00");
  await panel.getByRole("button", { name: "Remove payment of £100.00 on INV-0001" }).click();
  await expect(page.getByRole("status")).toContainText("Payment removed from INV-0001.");
  await expect(row).toContainText("balance £360.00");

  const payments = await runtime.api<{ id: string }[]>("GET", "/payments");
  expect(payments).toEqual([]);
});
